# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Host hardware detection used by both install-time and runtime code.

`scripts/install.sh` does its own probe via shell because it runs before
`torch` is installed. Once KAINE is installed, every module that needs
to pick a device asks `kaine.hardware` rather than calling
`torch.cuda.is_available()` directly. ROCm, XPU (Intel Arc), MPS
(Apple Silicon), and CUDA are all handled here with graceful fallback.

AMD ROCm note: ROCm does NOT use a separate device string. A PyTorch
build for ROCm still reports `torch.cuda.is_available() == True` and
uses `cuda` / `cuda:N` device strings. ROCm is identified by
`torch.version.hip` being non-None and surfaced via the `backend` and
`hip_version` keys in `describe_host()`. Device selection for AMD
reuses the cuda code paths unchanged.

Intel XPU: `xpu` / `xpu:N`, gated by `torch.xpu.is_available()`.

Multi-GPU support: `select_device` and `resolve_device` accept indexed
CUDA strings (`cuda:0`, `cuda:1`, ...) and indexed XPU strings
(`xpu:0`, `xpu:1`, ...). Modules pinned to `cuda:1` or `xpu:1` via
config land there when present; `resolve_device` falls back to `cuda:0`
(or `cpu`) with a warning when the requested index isn't available, so
a stale config doesn't crash the boot.
"""
from __future__ import annotations

import logging
import os
import platform
import re
from dataclasses import dataclass
from typing import Any


_BASE_DEVICES = ("cuda", "xpu", "mps", "cpu")
_ENV_OVERRIDE = "KAINE_FORCE_DEVICE"
_CUDA_INDEXED_RE = re.compile(r"^cuda:(\d+)$")
_XPU_INDEXED_RE = re.compile(r"^xpu:(\d+)$")

log = logging.getLogger(__name__)


def _try_torch():
    try:
        import torch  # type: ignore[import-untyped]
        return torch
    except Exception:
        return None


def _validate_device_string(value: str) -> None:
    """Raise ValueError if `value` is not a recognized device form."""
    if value in _BASE_DEVICES:
        return
    if _CUDA_INDEXED_RE.match(value):
        return
    if _XPU_INDEXED_RE.match(value):
        return
    raise ValueError(
        f"{value!r} is not a valid device (allowed: {_BASE_DEVICES} or 'cuda:N' or 'xpu:N')"
    )


def _cuda_device_count() -> int:
    torch = _try_torch()
    if torch is None:
        return 0
    try:
        if not torch.cuda.is_available():
            return 0
        return int(torch.cuda.device_count())
    except Exception:
        return 0


def available_cuda_devices() -> list[str]:
    """Return indexed CUDA strings for every present GPU.

    Examples: `["cuda:0", "cuda:1"]` on a two-GPU host; `[]` on a CPU
    host or when torch isn't installed.
    """
    return [f"cuda:{i}" for i in range(_cuda_device_count())]


def _xpu_device_count() -> int:
    torch = _try_torch()
    if torch is None:
        return 0
    try:
        xpu = getattr(torch, "xpu", None)
        if xpu is None:
            return 0
        if not xpu.is_available():
            return 0
        return int(xpu.device_count())
    except Exception:
        return 0


def available_xpu_devices() -> list[str]:
    """Return indexed XPU strings for every present Intel Arc / XPU device.

    Examples: `["xpu:0", "xpu:1"]` on a two-XPU host; `[]` when no XPU
    is present or torch isn't installed.
    """
    return [f"xpu:{i}" for i in range(_xpu_device_count())]


def detect_device() -> str:
    """Return the highest-priority base device available on this host.

    Order: cuda > xpu > mps > cpu. Returns the base `"cuda"` or `"xpu"`
    string (not an indexed form) so existing callers continue to work.
    AMD ROCm is covered by the cuda branch since torch.cuda.is_available()
    returns True on ROCm builds. Honors `KAINE_FORCE_DEVICE`.
    """
    forced = os.environ.get(_ENV_OVERRIDE)
    if forced:
        _validate_device_string(forced)
        return forced
    torch = _try_torch()
    if torch is None:
        return "cpu"
    try:
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        # A broken/mismatched CUDA driver can raise here instead of just
        # returning False; fall through to the next backend rather than
        # crash detection. Debug-level since this is expected on hosts
        # without a CUDA-capable driver stack.
        log.debug("torch.cuda.is_available() probe failed", exc_info=True)
    try:
        xpu = getattr(torch, "xpu", None)
        if xpu is not None and xpu.is_available():
            return "xpu"
    except Exception:
        log.debug("torch.xpu.is_available() probe failed", exc_info=True)
    try:
        backends = getattr(torch, "backends", None)
        mps = getattr(backends, "mps", None) if backends else None
        if mps is not None and mps.is_available():
            return "mps"
    except Exception:
        log.debug("torch.backends.mps.is_available() probe failed", exc_info=True)
    return "cpu"


def select_device(preferred: str | None = None) -> str:
    """Resolve a device for a single caller.

    Strict variant — raises if `preferred` names an unavailable
    indexed CUDA or XPU device. Module factories should usually call
    `resolve_device` instead, which falls back with a warning.

    Priority:
      1. `KAINE_FORCE_DEVICE` env var (operator escape hatch).
      2. `preferred` argument if valid and supported.
      3. `detect_device()` default.
    """
    forced = os.environ.get(_ENV_OVERRIDE)
    if forced:
        _validate_device_string(forced)
        return forced
    if preferred is None:
        return detect_device()
    _validate_device_string(preferred)
    torch = _try_torch()
    m = _CUDA_INDEXED_RE.match(preferred)
    if m:
        idx = int(m.group(1))
        count = _cuda_device_count()
        if idx >= count:
            raise ValueError(
                f"cuda:{idx} requested but only {count} CUDA device(s) available"
            )
        return preferred
    mx = _XPU_INDEXED_RE.match(preferred)
    if mx:
        idx = int(mx.group(1))
        count = _xpu_device_count()
        if idx >= count:
            raise ValueError(
                f"xpu:{idx} requested but only {count} XPU device(s) available"
            )
        return preferred
    if preferred == "cuda":
        if torch is not None and torch.cuda.is_available():
            return "cuda"
        return detect_device()
    if preferred == "xpu":
        xpu = getattr(torch, "xpu", None) if torch is not None else None
        if xpu is not None and xpu.is_available():
            return "xpu"
        return detect_device()
    if preferred == "mps":
        if torch is not None:
            mps = getattr(getattr(torch, "backends", None), "mps", None)
            if mps is not None and mps.is_available():
                return "mps"
        return detect_device()
    if preferred == "cpu":
        return "cpu"
    return detect_device()


def resolve_device(
    preferred: str | None = None,
    *,
    fallback: str = "cuda:0",
) -> str:
    """Operator-facing helper. Never raises on a missing CUDA or XPU index;
    falls back to `fallback` (or `cpu` if even that's unavailable) with
    a warning.

    Accepts: `None`, `"auto"`, `"cuda"`, `"cuda:N"`, `"xpu"`, `"xpu:N"`,
    `"mps"`, `"cpu"`.
    """
    forced = os.environ.get(_ENV_OVERRIDE)
    if forced:
        try:
            _validate_device_string(forced)
            return select_device(forced)
        except ValueError:
            log.warning(
                "KAINE_FORCE_DEVICE=%r is invalid; falling back to detect",
                forced,
            )
            # Probe directly so we don't re-trip detect_device()'s own
            # env-var check.
            if _cuda_device_count() > 0:
                return "cuda:0"
            return "cpu"
    if preferred is None or preferred == "auto":
        return detect_device()
    try:
        _validate_device_string(preferred)
    except ValueError as exc:
        log.warning("invalid device %r: %s; falling back to %s", preferred, exc, fallback)
        return _safe_fallback(fallback)
    m = _CUDA_INDEXED_RE.match(preferred)
    if m:
        idx = int(m.group(1))
        count = _cuda_device_count()
        if idx < count:
            return preferred
        log.warning(
            "device %s requested but only %d CUDA device(s) available; falling back to %s",
            preferred,
            count,
            fallback,
        )
        return _safe_fallback(fallback)
    mx = _XPU_INDEXED_RE.match(preferred)
    if mx:
        idx = int(mx.group(1))
        count = _xpu_device_count()
        if idx < count:
            return preferred
        log.warning(
            "device %s requested but only %d XPU device(s) available; falling back to %s",
            preferred,
            count,
            fallback,
        )
        return _safe_fallback(fallback)
    if preferred == "cuda":
        if _cuda_device_count() > 0:
            return "cuda:0"
        log.warning("cuda requested but no CUDA device available; falling back to cpu")
        return "cpu"
    if preferred == "xpu":
        if _xpu_device_count() > 0:
            return "xpu:0"
        log.warning("xpu requested but no XPU device available; falling back to cpu")
        return "cpu"
    if preferred == "mps":
        torch = _try_torch()
        mps = getattr(getattr(torch, "backends", None), "mps", None) if torch else None
        if mps is not None and mps.is_available():
            return "mps"
        log.warning("mps requested but unavailable; falling back to cpu")
        return "cpu"
    return "cpu"


def _safe_fallback(fallback: str) -> str:
    try:
        _validate_device_string(fallback)
    except ValueError:
        return "cpu"
    m = _CUDA_INDEXED_RE.match(fallback)
    if m:
        if int(m.group(1)) < _cuda_device_count():
            return fallback
        return "cpu"
    mx = _XPU_INDEXED_RE.match(fallback)
    if mx:
        if int(mx.group(1)) < _xpu_device_count():
            return fallback
        return "cpu"
    if fallback == "cuda":
        return "cuda:0" if _cuda_device_count() > 0 else "cpu"
    if fallback == "xpu":
        return "xpu:0" if _xpu_device_count() > 0 else "cpu"
    return fallback


def tune_cpu_threads(*, max_threads: int | None = None) -> int:
    """Cap torch's CPU thread pool so concurrent CPU-bound modules
    don't trash each other's pool on a many-core host.

    Default cap: `max(1, os.cpu_count() // 2)`. Returns the value
    that was actually set, or 0 if torch isn't installed.
    """
    cpu_count = os.cpu_count() or 1
    target = int(max_threads if max_threads is not None else max(1, cpu_count // 2))
    target = max(1, target)
    torch = _try_torch()
    if torch is None:
        return 0
    try:
        torch.set_num_threads(target)
    except Exception:
        log.warning("torch.set_num_threads(%d) failed", target, exc_info=True)
        return 0
    return target


def describe_host() -> dict[str, Any]:
    """Structured snapshot for diagnostics and `soma.report` payloads.

    Guaranteed keys (spec contract — never removed):
        device, cuda_available, mps_available, gpu_count, gpu_names,
        cuda_devices, torch_version, torch_installed, platform,
        python_version.

    Additional keys (added for multi-vendor GPU support):
        backend      — "rocm"|"cuda"|"xpu"|"mps"|"cpu"
        hip_version  — str|None (non-None on ROCm builds)
        xpu_available — bool
        xpu_count    — int
        xpu_names    — list[str]
        xpu_devices  — list of {index, device, name} dicts
    """
    torch = _try_torch()
    cuda_available = False
    mps_available = False
    gpu_count = 0
    gpu_names: list[str] = []
    torch_version: str | None = None
    cuda_devices: list[dict[str, Any]] = []
    hip_version: str | None = None
    xpu_available = False
    xpu_count = 0
    xpu_names: list[str] = []
    xpu_devices: list[dict[str, Any]] = []

    if torch is not None:
        torch_version = getattr(torch, "__version__", None)
        try:
            cuda_available = bool(torch.cuda.is_available())
        except Exception:
            cuda_available = False
        try:
            mps_backend = getattr(getattr(torch, "backends", None), "mps", None)
            mps_available = bool(mps_backend.is_available()) if mps_backend else False
        except Exception:
            mps_available = False
        # ROCm: torch.version.hip is set on AMD ROCm builds.
        try:
            version_mod = getattr(torch, "version", None)
            hip_version = getattr(version_mod, "hip", None)
            if hip_version is not None:
                hip_version = str(hip_version)
        except Exception:
            hip_version = None
        # Intel XPU
        try:
            xpu_mod = getattr(torch, "xpu", None)
            if xpu_mod is not None:
                xpu_available = bool(xpu_mod.is_available())
                if xpu_available:
                    xpu_count = int(xpu_mod.device_count())
        except Exception:
            xpu_available = False
            xpu_count = 0
        if xpu_available:
            for i in range(xpu_count):
                try:
                    props = getattr(torch.xpu, "get_device_properties", None)
                    name = ""
                    entry: dict[str, Any] = {"index": i, "device": f"xpu:{i}", "name": name}
                    if props is not None:
                        p = props(i)
                        name = str(getattr(p, "name", ""))
                        entry["name"] = name
                    xpu_names.append(name)
                    xpu_devices.append(entry)
                except Exception:
                    xpu_names.append("")
                    xpu_devices.append({"index": i, "device": f"xpu:{i}", "name": ""})
        if cuda_available:
            try:
                gpu_count = int(torch.cuda.device_count())
                gpu_names = [
                    str(torch.cuda.get_device_name(i)) for i in range(gpu_count)
                ]
                for i in range(gpu_count):
                    try:
                        props = torch.cuda.get_device_properties(i)
                        total = int(getattr(props, "total_memory", 0))
                        free, _ = torch.cuda.mem_get_info(i)
                    except Exception:
                        total = 0
                        free = 0
                    cuda_devices.append(
                        {
                            "index": i,
                            "device": f"cuda:{i}",
                            "name": gpu_names[i] if i < len(gpu_names) else "",
                            "total_vram_gb": round(total / (1024 ** 3), 2),
                            "free_vram_gb": round(int(free) / (1024 ** 3), 2),
                        }
                    )
            except Exception:
                gpu_count = 0
                gpu_names = []

    # Compute backend label.
    if cuda_available:
        backend = "rocm" if hip_version is not None else "cuda"
    elif xpu_available:
        backend = "xpu"
    elif mps_available:
        backend = "mps"
    else:
        backend = "cpu"

    return {
        # --- original spec-contract keys (never removed) ---
        "device": detect_device(),
        "cuda_available": cuda_available,
        "mps_available": mps_available,
        "gpu_count": gpu_count,
        "gpu_names": gpu_names,
        "cuda_devices": cuda_devices,
        "torch_version": torch_version,
        "torch_installed": torch is not None,
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        # --- new multi-vendor keys ---
        "backend": backend,
        "hip_version": hip_version,
        "xpu_available": xpu_available,
        "xpu_count": xpu_count,
        "xpu_names": xpu_names,
        "xpu_devices": xpu_devices,
    }


# ---------------------------------------------------------------------------
# Host-capability probe → recommended deployment tier (openspec host-probe).
#
# The portability thesis is that KAINE is the architecture, not the hardware:
# the same mind inhabits hardware from a retired phone to a datacenter, trading
# capability for reach rather than changing identity. The probe reports what the
# host can bear and RECOMMENDS a tier; it never applies a profile or starts the
# entity — profile selection stays an operator action, consistent with the
# operator-supervised boot.
# ---------------------------------------------------------------------------

#: RAM floor (GiB) below which the torch/transformers runtime is unrealistic and
#: the host is an edge/sensor node (Tier 0). The GGML/ONNX family still runs.
TIER1_MIN_RAM_GB = 4.0

#: 32-bit ARM (armv6/armv7) cannot realistically bear the torch stack; such a
#: host is capped at the Tier-0 symbolic-reasoning + memory + sensor role.
_ARM32_ARCHES = ("armv6", "armv7", "armv6l", "armv7l")

#: The honest capability matrix, per tier. ``present`` / ``degraded`` / ``absent``
#: name what each tier can and cannot do (openspec deployment-tiers). Rendered by
#: ``scripts/probe-host`` and mirrored in ``docs/deployment-tiers.md``.
TIER_CAPABILITIES: dict[int, dict[str, Any]] = {
    0: {
        "name": "edge / sensor node",
        "host": "~512 MB-class SBC or retired low-RAM phone",
        "summary": (
            "symbolic reasoning + episodic memory + perception satellite; "
            "no torch runtime"
        ),
        "present": ["soma", "chronos", "nous", "mnemos (sqlite-vec)", "eidolon", "thymos"],
        "degraded": ["lingua (sub-1B GGUF, slow)", "audio-in (optional whisper.cpp-tiny batch STT)"],
        "absent": ["topos vision", "vocal emotion", "expressive TTS", "≥2B LLM"],
    },
    1: {
        "name": "embodied CPU agent",
        "host": "4–8 GB-class SBC or retired 8 GB smartphone (e.g. under Termux)",
        "summary": "CPU multimodal at chat pace; periodic (not streaming) vision",
        "present": [
            "lingua (1–2B GGUF)",
            "audio-in STT (whisper.cpp/faster-whisper)",
            "audio-out TTS (Piper)",
            "mnemos embeddings (ONNX MiniLM)",
            "topos vision (ONNX/dinov2.cpp, periodic)",
        ],
        "degraded": ["vision is periodic, not streaming", "short contexts"],
        "absent": ["expressive TTS", "vocal emotion", "streaming vision"],
    },
    2: {
        "name": "workstation",
        "host": "single/dual-GPU workstation (the current default)",
        "summary": "full real-time multimodal (the untouched default)",
        "present": [
            "lingua (Gemma E2B on GPU via Ollama)",
            "topos vision (DINOv2 torch)",
            "vocal emotion (emotion2vec+)",
            "audio-in STT (faster-whisper, >realtime)",
            "audio-out TTS (Chatterbox, expressive)",
            "mnemos (Qdrant + sentence-transformers)",
        ],
        "degraded": [],
        "absent": [],
    },
    3: {
        "name": "datacenter / multi-GPU",
        "host": "multi-GPU server",
        "summary": "larger LLMs, longer contexts, concurrent instances, redundancy",
        "present": ["everything at Tier 2, with more headroom"],
        "degraded": [],
        "absent": [],
    },
}


@dataclass(frozen=True)
class TierRecommendation:
    """The probe's report: host facts + a recommended tier and why.

    ``tier`` is a *recommendation* only — nothing here applies a profile or
    starts the entity. ``capabilities`` is the matrix row for ``tier``.
    """

    tier: int
    reason: str
    total_ram_gb: float | None
    cpu_arch: str
    accelerator: str
    torch_importable: bool
    gpu_count: int

    @property
    def profile(self) -> str:
        return f"tier{self.tier}"

    @property
    def capabilities(self) -> dict[str, Any]:
        return TIER_CAPABILITIES[self.tier]

    def as_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "profile": self.profile,
            "reason": self.reason,
            "total_ram_gb": self.total_ram_gb,
            "cpu_arch": self.cpu_arch,
            "accelerator": self.accelerator,
            "torch_importable": self.torch_importable,
            "gpu_count": self.gpu_count,
            "capabilities": self.capabilities,
        }


def total_ram_gb() -> float | None:
    """Best-effort total physical RAM in GiB, or ``None`` if undetectable.

    Tries POSIX ``sysconf`` first (no third-party dependency), then
    ``/proc/meminfo``, then ``psutil`` if it happens to be installed. Returns
    ``None`` rather than guessing when none of those work.
    """
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        phys_pages = os.sysconf("SC_PHYS_PAGES")
        if page_size > 0 and phys_pages > 0:
            return round(page_size * phys_pages / (1024 ** 3), 2)
    except (ValueError, OSError, AttributeError):
        pass
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    kib = int(line.split()[1])
                    return round(kib / (1024 ** 2), 2)
    except (OSError, ValueError, IndexError):
        pass
    try:
        import psutil  # type: ignore[import-untyped]

        return round(int(psutil.virtual_memory().total) / (1024 ** 3), 2)
    except Exception:
        return None


def cpu_arch() -> str:
    """Normalized CPU architecture string, e.g. ``x86_64`` / ``aarch64`` / ``armv7l``."""
    return (platform.machine() or "unknown").lower()


def _is_arm32(arch: str) -> bool:
    a = arch.lower()
    return any(a.startswith(prefix) for prefix in _ARM32_ARCHES)


def torch_importable() -> bool:
    """True iff ``torch`` imports on this host (the torch/transformers cliff)."""
    return _try_torch() is not None


def recommend_tier(
    *,
    ram_gb: float | None = None,
    arch: str | None = None,
    torch_ok: bool | None = None,
    gpu_count: int | None = None,
    accelerator: str | None = None,
) -> TierRecommendation:
    """Map host capabilities to a recommended deployment tier.

    Recommends only — it does not apply a profile or start the entity. The
    override arguments exist for deterministic testing across host classes; when
    omitted each is probed from the live host.

    The ladder mirrors the runtime cliff (openspec design):

    * **Tier 0** — torch does not import, RAM is below the Tier-1 floor, or the
      CPU is 32-bit ARM: an edge / sensor node (GGML/ONNX only, no torch).
    * **Tier 1** — torch imports and RAM ≥ :data:`TIER1_MIN_RAM_GB` but no
      accelerator is present: an embodied CPU agent.
    * **Tier 2** — an accelerator (CUDA / ROCm / MPS / XPU) with exactly one GPU:
      the workstation default.
    * **Tier 3** — two or more GPUs: datacenter / multi-GPU.
    """
    arch_v = (arch if arch is not None else cpu_arch()).lower()
    ram_v = ram_gb if ram_gb is not None else total_ram_gb()
    torch_v = torch_ok if torch_ok is not None else torch_importable()
    if gpu_count is not None:
        gpu_v = int(gpu_count)
    else:
        gpu_v = _cuda_device_count() + _xpu_device_count()
    if accelerator is not None:
        accel_v = accelerator
    else:
        detected = detect_device()
        accel_v = detected if detected in ("cuda", "xpu", "mps") else "cpu"
    has_accelerator = accel_v in ("cuda", "xpu", "mps") or gpu_v > 0

    def _rec(tier: int, reason: str) -> TierRecommendation:
        return TierRecommendation(
            tier=tier,
            reason=reason,
            total_ram_gb=ram_v,
            cpu_arch=arch_v,
            accelerator=accel_v,
            torch_importable=bool(torch_v),
            gpu_count=gpu_v,
        )

    # 32-bit ARM cannot bear the torch stack — capped at the sensor role.
    if _is_arm32(arch_v):
        return _rec(0, f"32-bit ARM ({arch_v}); torch stack not viable")
    if not torch_v:
        return _rec(0, "torch does not import on this host")
    if ram_v is not None and ram_v < TIER1_MIN_RAM_GB:
        return _rec(
            0, f"RAM {ram_v} GB below Tier-1 floor of {TIER1_MIN_RAM_GB} GB"
        )
    if has_accelerator:
        if gpu_v >= 2:
            return _rec(3, f"{gpu_v} GPUs present (multi-GPU)")
        return _rec(2, f"accelerator present ({accel_v})")
    return _rec(1, "torch importable, adequate RAM, no accelerator (CPU agent)")

