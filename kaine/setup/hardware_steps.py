# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Declarative setup steps for hardware inventory, consent, and device fit."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from kaine.hardware import total_ram_gb
from kaine.setup.steps import Field, Step, StepContext
from kaine.storage import resolve

COMPONENT_OF_ADDRESS = {
    "hypnos.voice_alignment.training_device": "voice_alignment",
    "topos.device": "topos",
    "phantasia.training_device": "phantasia",
    "embedding.device": "embedding",
    "audition.emotion_device": "emotion",
}


def _fmt_gb(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.2f}"
    return "unknown"


def device_inventory(
    host: dict[str, Any], consumers: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Return one row per recognised accelerator plus the CPU."""
    rows: list[dict[str, Any]] = []

    cuda_backend = "rocm" if host.get("backend") == "rocm" else "cuda"
    for dev in host.get("cuda_devices") or []:
        rows.append(
            {
                "device": dev.get("device"),
                "backend": cuda_backend,
                "name": dev.get("name") or "unknown",
                "total_gb": dev.get("total_vram_gb"),
                "free_gb": dev.get("free_vram_gb"),
            }
        )

    for dev in host.get("xpu_devices") or []:
        rows.append(
            {
                "device": dev.get("device"),
                "backend": "xpu",
                "name": dev.get("name") or "unknown",
                "total_gb": dev.get("total_memory_gb") or dev.get("total_vram_gb"),
                "free_gb": dev.get("free_memory_gb") or dev.get("free_vram_gb"),
            }
        )

    if host.get("mps_available"):
        rows.append(
            {
                "device": "mps",
                "backend": "mps",
                "name": "Apple MPS",
                "total_gb": None,
                "free_gb": None,
            }
        )

    rows.append(
        {
            "device": "cpu",
            "backend": "cpu",
            "name": "CPU",
            "total_gb": None,
            "free_gb": None,
        }
    )

    if consumers:
        for row in rows:
            matched = [
                consumer for consumer in consumers if consumer.get("device") == row["device"]
            ]
            if matched:
                row["consumers"] = matched
                row["consumers_note"] = matched[0].get(
                    "consumers_note"
                ) or matched[0].get("note")

    return rows


def _processes_for_row(row: dict[str, Any]) -> list[dict[str, Any]]:
    consumers = row.get("consumers") or []
    processes: list[dict[str, Any]] = []
    for consumer in consumers:
        if isinstance(consumer.get("processes"), list):
            processes.extend(consumer["processes"])
        else:
            processes.append(consumer)
    return processes


def _inventory_explanation(ctx: StepContext) -> list[str]:
    host = ctx.host
    rows = device_inventory(host, ctx.extra.get("consumers"))
    lines: list[str] = []

    accelerators = [row for row in rows if row["backend"] != "cpu"]
    if not accelerators:
        lines.append("  no accelerator found — KAINE will run on the CPU")

    for row in rows:
        lines.append(
            f"  {row['device']} ({row['backend']}) {row['name']}: "
            f"{_fmt_gb(row['total_gb'])} GB total, {_fmt_gb(row['free_gb'])} GB free"
        )
        for process in _processes_for_row(row):
            pid = process.get("pid", "?")
            name = process.get("name") or process.get("process_name") or "unknown"
            used = process.get("used_mib") or process.get("used_memory") or "?"
            lines.append(f"      pid {pid} {name} — {used} MiB")
        note = row.get("consumers_note")
        if note:
            lines.append(f"      {note}")

    memory = host.get("memory") or {}
    if memory.get("state") == "unified":
        lines.append("  unified memory: accelerators share system memory")

    lines.append(f"  CPU cores: {host.get('cpu_count') or 'unknown'}")

    ram = total_ram_gb()
    lines.append(
        f"  system memory: {_fmt_gb(ram)} GB" if ram is not None else "  system memory: unknown GB"
    )

    return lines


inventory_step = Step(
    id="hardware-inventory",
    title="Hardware on this host",
    explanation=_inventory_explanation,
    fields=lambda _ctx: (),
    applies=lambda _ctx: True,
    apply=lambda _ctx, _answers: None,
)


def _consent_explanation(_ctx: StepContext) -> list[str]:
    return [
        "A device you leave out stays free for other work; "
        "KAINE will never place a module on it."
    ]


def _consent_fields(ctx: StepContext) -> tuple[Field, ...]:
    cores = ctx.host.get("cpu_count") or 1
    rows = device_inventory(ctx.host, ctx.extra.get("consumers"))
    choices = tuple(row["device"] for row in rows)
    accelerator_defaults = tuple(row["device"] for row in rows if row["backend"] != "cpu")
    default = accelerator_defaults + ("cpu",)

    return (
        Field(
            "allowed_devices",
            "Devices KAINE may use (comma-separated)",
            "multichoice",
            default=default,
            choices=choices,
        ),
        Field(
            "cpu_threads",
            "CPU threads KAINE may use",
            "int",
            default=max(1, cores // 2),
            validate=lambda v: (
                None
                if isinstance(v, int) and 1 <= v <= cores
                else f"must be between 1 and {cores}"
            ),
        ),
    )


def _consent_apply(ctx: StepContext, answers: dict[str, Any]) -> None:
    ctx.config["hardware"] = {
        "allowed_devices": list(answers["allowed_devices"]),
        "cpu_threads": int(answers["cpu_threads"]),
    }


consent_step = Step(
    id="hardware-consent",
    title="What KAINE may use",
    explanation=_consent_explanation,
    fields=_consent_fields,
    applies=lambda _ctx: True,
    apply=_consent_apply,
)


def load_footprint_catalogue(path: Path | None = None) -> dict[str, int]:
    """Load the best-known component footprint catalogue, never raising.

    Returns a mapping ``component -> bytes``.  If the catalogue is missing or
    malformed, an empty mapping is returned.
    """
    if path is None:
        path = Path(resolve("state/residency/footprints.json"))
    else:
        path = Path(path)

    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        result: dict[str, int] = {}
        for entry in data:
            component = entry.get("component")
            bytes_ = entry.get("bytes")
            if isinstance(component, str) and isinstance(bytes_, (int, float)):
                result[component] = max(result.get(component, 0), int(bytes_))
        return result
    except Exception:
        return {}


def fit_check(
    assignments: dict[str, str],
    inventory: list[dict[str, Any]],
    catalogue: dict[str, int],
    floor_gb: float,
) -> list[dict[str, Any]]:
    """Return a list of VRAM-fit issues for accelerator-only assignments."""
    used: dict[str, list[str]] = {}
    for address, device in assignments.items():
        if device == "cpu":
            continue
        used.setdefault(device, []).append(address)

    issues: list[dict[str, Any]] = []
    for device, addresses in used.items():
        row = next((r for r in inventory if r["device"] == device), None)
        free_gb = row["free_gb"] if row else None

        components = [COMPONENT_OF_ADDRESS[address] for address in addresses]
        if all(component in catalogue for component in components):
            need_gb = sum(catalogue[component] for component in components) / (1024**3)
            basis = "measured footprints"
        else:
            need_gb = floor_gb
            basis = "pre-flight floor (no measured footprint)"

        if free_gb is None or free_gb < need_gb:
            issues.append(
                {
                    "device": device,
                    "free_gb": free_gb,
                    "need_gb": need_gb,
                    "basis": basis,
                    "addresses": addresses,
                }
            )

    return issues


def _apply_address(cfg: dict[str, Any], address: str, value: Any) -> None:
    parts = address.split(".")
    if len(parts) == 2:
        cfg.setdefault(parts[0], {})[parts[1]] = value
    elif len(parts) == 3:
        cfg.setdefault(parts[0], {}).setdefault(parts[1], {})[parts[2]] = value
    else:  # pragma: no cover - defensive
        raise ValueError(f"unsupported device address: {address}")


def device_step(
    propose: Callable[[dict[str, Any], list[str] | None], dict[str, str]],
) -> Step:
    """Return the device-assignment step using ``propose`` for the initial map."""

    def _proposal(ctx: StepContext) -> dict[str, str]:
        allowed = ctx.config.get("hardware", {}).get("allowed_devices", [])
        return propose(ctx.host, allowed)

    def _issues(ctx: StepContext) -> list[dict[str, Any]]:
        proposal = _proposal(ctx)
        inventory = device_inventory(ctx.host, ctx.extra.get("consumers"))
        catalogue = ctx.extra.get("catalogue", {})
        floor = ctx.extra.get("floor_gb", 2.0)
        return fit_check(proposal, inventory, catalogue, floor)

    def explanation(ctx: StepContext) -> list[str]:
        proposal = _proposal(ctx)
        issues = _issues(ctx)
        lines: list[str] = []
        for address, dev in proposal.items():
            lines.append(f"  {address} = {dev}")
        lines.append(
            "  You can edit the assignments in the operator config after setup if you need to."
        )
        if issues:
            lines.append(
                "  Alternatives for a workload that does not fit: "
                "another allowed device, a lighter backend rung, or CPU."
            )
        for issue in issues:
            lines.append(
                f"  {issue['device']} does not fit: "
                f"{_fmt_gb(issue['free_gb'])} GB free, "
                f"needs {issue['need_gb']:.2f} GB ({issue['basis']})"
            )
        return lines

    def fields(ctx: StepContext) -> tuple[Field, ...]:
        issues = _issues(ctx)
        allowed = ctx.config.get("hardware", {}).get("allowed_devices", [])
        failing_devices = {issue["device"] for issue in issues}
        allowed_accels = [dev for dev in allowed if dev != "cpu"]
        other_accels = [
            dev for dev in allowed_accels if dev not in failing_devices
        ]

        result: list[Field] = [
            Field(
                "accept",
                "Accept these device assignments?",
                "bool",
                default=True,
            )
        ]
        for issue in issues:
            for address in issue["addresses"]:
                choices = tuple(other_accels) + ("cpu",)
                result.append(
                    Field(
                        address,
                        f"  device for {address}",
                        "choice",
                        default="cpu",
                        choices=choices,
                    )
                )
        return tuple(result)

    def apply(ctx: StepContext, answers: dict[str, Any]) -> None:
        proposal = _proposal(ctx)
        final = dict(proposal)
        for address in proposal:
            if address in answers:
                final[address] = answers[address]
        for address, dev in final.items():
            _apply_address(ctx.config, address, dev)

        hardware = ctx.config.setdefault("hardware", {})
        hardware["devices"] = {
            "organ": final["hypnos.voice_alignment.training_device"],
            "vision": final["topos.device"],
        }

    return Step(
        id="device-assignments",
        title="Device assignments",
        explanation=explanation,
        fields=fields,
        applies=lambda _ctx: True,
        apply=apply,
    )


def shared_services_step() -> Step:
    """Return the shared-services confirmation step."""

    def _detected(ctx: StepContext) -> list[str]:
        services_up = ctx.extra.get("services_up") or {}
        return sorted(name for name, listening in services_up.items() if listening)

    def explanation(ctx: StepContext) -> list[str]:
        lines = [f"  {name}" for name in _detected(ctx)]
        lines.append(
            "  KAINE never stops, restarts, or evicts a shared service."
        )
        return lines

    def fields(ctx: StepContext) -> tuple[Field, ...]:
        return tuple(
            Field(
                name,
                f"Is {name} shared with other applications on this machine?",
                "bool",
                default=False,
            )
            for name in _detected(ctx)
        )

    def apply(ctx: StepContext, answers: dict[str, Any]) -> None:
        services = ctx.config.setdefault("services", {})
        for name in _detected(ctx):
            answer = answers.get(name)
            if answer is not None:
                services[name] = {"shared": bool(answer)}

    return Step(
        id="shared-services",
        title="Services shared with other applications",
        explanation=explanation,
        fields=fields,
        applies=lambda ctx: bool(_detected(ctx)),
        apply=apply,
    )
