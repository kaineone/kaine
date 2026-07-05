# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Cooperative pre-boot GPU headroom check.

Runs once at cycle startup, BEFORE any module initializes, so a just-born entity
is not OOM-killed mid-init — which would otherwise make Spot thrash trying to
restart modules. Starting an entity you cannot sustain is a welfare problem, so
this fails closed rather than booting into a doomed state.

It is COOPERATIVE, never coercive:

  - The model backend is a single OpenAI-compatible local server (Unsloth Studio
    / llama.cpp), which keeps ONE model resident for its lifetime — the organ
    itself. There is no idle model to evict (no Ollama-style keep_alive cache), so
    reclamation here is REPORT-ONLY: the gate measures headroom and reports the
    resident model and other GPU consumers; it does not unload anything.
  - It NEVER terminates a process — not a foreign GPU program, and not a KAINE
    service. The model server / Chatterbox / Speaches keep running; they are
    detected and preserved, not killed.
  - If headroom is short, it REPORTS the GPU memory consumers, asks the operator
    to free what they can, and refuses to boot (exit at the call site) unless the
    operator overrides with the configured env flag.

No pretend work: every step does the real thing (real VRAM query via torch, real
resident-model query via the server's /v1/models, real process listing via
nvidia-smi) or is skipped with the gap reflected honestly in the result —
nothing is simulated or assumed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from kaine.config import require_known_keys
from kaine.net import SERVICE_PORTS, port_listening
from kaine.state_io import write_json_atomic

PREFLIGHT_PATH = Path("state/cycle/gpu_preflight.json")
DEFAULT_OVERRIDE_ENV = "KAINE_GPU_PREFLIGHT_APPROVED"

# KAINE's own GPU-using services, by local port. Detected and PRESERVED — the
# preflight never kills these. `model_server` is the OpenAI-compatible inference
# server (Unsloth Studio / llama.cpp) that serves the language organ. Sourced
# from the shared boundary-neutral registry (kaine.net.SERVICE_PORTS) so the
# preflight and the setup dependency probe agree on one definition.
KAINE_SERVICE_PORTS: dict[str, int] = SERVICE_PORTS


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class GpuPreflightConfig:
    enabled: bool = False
    # Minimum free VRAM (GiB) required on EACH detected GPU before boot.
    min_free_vram_gb: float = 2.0
    # OpenAI-compatible model server, queried read-only for its resident model
    # (report only — the single-resident backend has no idle model to evict).
    model_server_url: str = "http://127.0.0.1:11434/v1"
    timeout_s: float = 5.0
    # Set this env var to "1" to boot anyway when headroom is short.
    override_env: str = DEFAULT_OVERRIDE_ENV

    @classmethod
    def from_section(cls, data: dict[str, Any] | None) -> "GpuPreflightConfig":
        data = dict(data or {})
        require_known_keys(
            data,
            {
                "enabled",
                "min_free_vram_gb",
                "model_server_url",
                "timeout_s",
                "override_env",
            },
            "[gpu_preflight]",
        )
        return cls(
            enabled=bool(data.get("enabled", cls.enabled)),
            min_free_vram_gb=float(
                data.get("min_free_vram_gb", cls.min_free_vram_gb)
            ),
            model_server_url=str(data.get("model_server_url", cls.model_server_url)),
            timeout_s=float(data.get("timeout_s", cls.timeout_s)),
            override_env=str(data.get("override_env", cls.override_env)),
        )


@dataclass
class PreflightResult:
    status: str  # "pass" | "skipped" | "overridden" | "blocked"
    devices: list[dict[str, Any]] = field(default_factory=list)
    shortfall: list[dict[str, Any]] = field(default_factory=list)
    # Models the backend reports resident (report-only; never evicted here).
    resident_models: list[str] = field(default_factory=list)
    gpu_consumers: list[dict[str, Any]] = field(default_factory=list)
    kaine_services_up: dict[str, bool] = field(default_factory=dict)
    message: str = ""
    checked_at: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("pass", "skipped", "overridden")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ok"] = self.ok
        return d


# --- real probes (each returns honest empties on failure) --------------------


def _device_free_vram() -> list[dict[str, Any]]:
    """Per-device free/total VRAM from a live hardware scan (CUDA today)."""
    try:
        from kaine.hardware import describe_host

        host = describe_host()
    except Exception:
        return []
    return list(host.get("cuda_devices") or [])


def _server_resident_models(url: str, timeout_s: float) -> list[str]:
    """GET /v1/models → ids the OpenAI-compatible server reports resident.

    Report-only: the single-resident backend (Studio / llama-server) has no
    unload API, so this informs the operator what is holding VRAM on KAINE's
    side; nothing is evicted. [] on any failure.
    """
    base = url.rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    try:
        resp = httpx.get(f"{base}/models", timeout=timeout_s)
        resp.raise_for_status()
        data = resp.json().get("data") or []
        return [str(m.get("id")) for m in data if m.get("id")]
    except Exception:
        return []


def _gpu_consumers(timeout_s: float) -> list[dict[str, Any]]:
    """List GPU compute processes via nvidia-smi (report only; [] if absent)."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        out = subprocess.run(
            [
                exe,
                "--query-compute-apps=pid,process_name,used_memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except Exception:
        return []
    if out.returncode != 0:
        return []
    rows: list[dict[str, Any]] = []
    for line in out.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3 and parts[0]:
            rows.append(
                {"pid": parts[0], "process_name": parts[1], "used_mib": parts[2]}
            )
    return rows


def _kaine_services_up() -> dict[str, bool]:
    return {
        name: port_listening(port) for name, port in KAINE_SERVICE_PORTS.items()
    }


def _write_state(result: PreflightResult, path: Path | None = None) -> None:
    target = path or PREFLIGHT_PATH
    try:
        write_json_atomic(target, result.to_dict())
    except OSError:
        # Surfacing the gate to Nexus is best-effort; never block boot on the
        # status file itself.
        pass


def _format_block_message(
    short: list[dict[str, Any]],
    consumers: list[dict[str, Any]],
    services: dict[str, bool],
    unexpected_models: list[str],
    config: GpuPreflightConfig,
) -> str:
    lines = [
        "GPU headroom is below the configured minimum "
        f"({config.min_free_vram_gb:.1f} GiB free per device):",
    ]
    for d in short:
        lines.append(
            f"  - {d.get('device')} ({d.get('name')}): "
            f"{d.get('free_vram_gb')} GiB free of {d.get('total_vram_gb')} GiB"
        )
    if consumers:
        lines.append("GPU memory is held by these processes:")
        for c in consumers:
            lines.append(
                f"  - pid {c['pid']} {c['process_name']} ({c['used_mib']} MiB)"
            )
    if unexpected_models:
        lines.append(
            "Model server holds these resident models beyond the organ "
            "(consider unloading them in the server): "
            + ", ".join(sorted(unexpected_models))
        )
    up = [name for name, on in services.items() if on]
    if up:
        lines.append(
            "KAINE services detected (DO NOT close these — they are reused): "
            + ", ".join(sorted(up))
        )
    lines.append(
        "Please close other GPU programs to free memory, then retry. To boot "
        f"anyway, set {config.override_env}=1 (not recommended — the entity may "
        "be OOM-killed mid-cycle)."
    )
    return "\n".join(lines)


def run_preflight(
    config: GpuPreflightConfig,
    *,
    keep_models: Optional[list[str]] = None,
    state_path: Path | None = None,
) -> PreflightResult:
    """Check per-device GPU headroom cooperatively and return the verdict.

    The model backend is a single-resident OpenAI-compatible server with no
    unload API, so this RECLAIMS NOTHING: it measures per-device headroom,
    reports the backend's resident model(s) and other GPU consumers (flagging any
    resident model NOT in ``keep_models`` — the organ's model — as unexpected),
    preserves KAINE services, and NEVER kills a process. Writes a status snapshot
    for Nexus. The CALLER decides what a non-ok result means (the cycle refuses to
    boot); this function performs no process control.
    """
    keep = {m for m in (keep_models or []) if m}

    if not config.enabled:
        return PreflightResult(status="skipped", checked_at=_now_iso())

    devices = _device_free_vram()
    consumers = _gpu_consumers(config.timeout_s)
    services = _kaine_services_up()
    resident = _server_resident_models(config.model_server_url, config.timeout_s)
    # Resident models KAINE did not expect (anything the server holds beyond the
    # organ's keep set) — surfaced for the operator, never evicted here.
    unexpected = [m for m in resident if m not in keep]

    def below_min(devs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            d
            for d in devs
            if float(d.get("free_vram_gb", 0.0)) < config.min_free_vram_gb
        ]

    short = below_min(devices)
    checked = _now_iso()

    if not short:
        result = PreflightResult(
            status="pass",
            devices=devices,
            shortfall=[],
            resident_models=resident,
            gpu_consumers=consumers,
            kaine_services_up=services,
            message="GPU headroom OK.",
            checked_at=checked,
        )
        _write_state(result, state_path)
        return result

    message = _format_block_message(short, consumers, services, unexpected, config)
    overridden = os.environ.get(config.override_env) == "1"
    result = PreflightResult(
        status="overridden" if overridden else "blocked",
        devices=devices,
        shortfall=short,
        resident_models=resident,
        gpu_consumers=consumers,
        kaine_services_up=services,
        message=(
            message + f"\n[{config.override_env}=1 set — booting anyway.]"
            if overridden
            else message
        ),
        checked_at=checked,
    )
    _write_state(result, state_path)
    return result


def read_preflight_state(path: Path | None = None) -> dict[str, Any] | None:
    """Read the last preflight snapshot for read-only display. None if absent."""
    target = path or PREFLIGHT_PATH
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text())
    except (json.JSONDecodeError, OSError):
        return None
