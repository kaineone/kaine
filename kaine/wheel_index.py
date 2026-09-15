# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Host-aware CUDA wheel-index resolution -- the single source of truth for
which pip ``--index-url`` provides the NVIDIA wheels on this host.

Section 2 of the merged OpenSpec change ``host-aware-accelerator-provisioning``.
``scripts/install.sh`` used to hardcode the cu128 index whenever ``nvidia-smi``
existed, blind to CPU architecture, the driver's CUDA version and the GPU's
compute capability.  On aarch64 that could install SBSA wheels that import
cleanly and then die at the first kernel launch with "no kernel image is
available for execution on the device" -- the worst failure mode, because
install and configuration both appeared to succeed.  This module replaces that
guesswork with probed, explainable decisions.

Responsibilities are strictly split:

* :func:`collect_probes` performs every fallible discovery (platform,
  ``nvidia-smi``, NVML through ``ctypes``, optional torch,
  ``kaine.hostmem``).  Every probe is fail-soft: a probe that cannot run
  yields ``None``/empty plus a provenance note in ``Probes.notes``, never an
  exception.
* :func:`resolve_index` is a pure function of its ``Probes`` argument: no I/O,
  no subprocesses, no probing.  Purity is what makes the decision table
  unit-testable.

The fallback ladder (normative; ``DECISION_TABLE`` is its declarative
companion):

1. Candidates: every ``cuX.Y`` index with ``X.Y <=`` driver CUDA, newest
   first.  A newer driver may run an older index (driver backward
   compatibility); the reverse is never attempted.
2. Architecture filter: drop candidates whose ``INDEX_ARCH_MAP`` entry lacks
   the host architecture.  ``INDEX_ARCH_MAP`` carries x86_64 and aarch64
   (SBSA) lines only; any other architecture yields an empty candidate list.
3. Compute-capability filter: keep a candidate only if EVERY probed NVIDIA
   device is covered -- an exact ``sm_XY`` entry, or a ``compute_ZW`` PTX
   entry with ``(Z, W) >= (X, Y)``.  PTX counts as coverage and such a
   selection is annotated as JIT-from-PTX in ``selected_reason``.
4. Unified-memory exclusion: if host memory is POSITIVELY classified
   ``unified``, every candidate is dropped, because upstream wheels carry no
   Tegra SASS.  An ``unknown`` classification NEVER excludes.  This is
   deliberate: ``unknown`` means the classifier could not gather evidence
   (broken NVML, restricted sysfs, a probe crash), not that the memory is
   unified.  Treating ``unknown`` as ``unified`` would convert a recoverable
   probe failure into a host that receives no wheel at all; a discrete host
   with broken NVML must still receive its wheel.  Only positive evidence
   excludes; absence of evidence never does.
5. First survivor wins; if it is older than the newest candidate that passed
   the driver and architecture filters, a downgrade note naming both index
   versions is emitted.
6. Exhaustion falls back to ``CPU_INDEX`` with a warning stating the probed
   architecture, driver CUDA, per-device compute capability, memory
   classification, the terminal rejection reason, and the ``--index-url``
   remediation (for Tegra, the JetPack-provided index).

Every rejected candidate is reported in ``rejected`` with the reason it was
dropped, so an operator can see why a wheel they expected was not chosen.

An operator-supplied ``--index-url`` override wins over the table whenever a
CUDA index would be used and is recorded in ``selected_reason`` as
operator-provided.  When the ladder would have selected the CPU index (no
CUDA index would be used) the override is not applied and a warning says so.

``resolve_index`` returns exactly ``{"variant", "index_url", "probes",
"selected_reason", "rejected", "warnings"}``; the result is JSON-serializable
and stable, nothing raises out of ``collect_probes`` or ``resolve_index``, and
torch may be absent entirely (stdlib only).
"""

from __future__ import annotations

import ctypes
import json
import platform
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "CPU_INDEX",
    "DECISION_TABLE",
    "INDEX_ARCH_MAP",
    "Probes",
    "collect_probes",
    "main",
    "resolve_index",
]

# ---------------------------------------------------------------------------
# Authoritative data
# ---------------------------------------------------------------------------

CPU_INDEX = "https://download.pytorch.org/whl/cpu"

_CU130 = "https://download.pytorch.org/whl/cu130"
_CU128 = "https://download.pytorch.org/whl/cu128"
_CU126 = "https://download.pytorch.org/whl/cu126"
_CU121 = "https://download.pytorch.org/whl/cu121"
_CU118 = "https://download.pytorch.org/whl/cu118"

# Authoritative index -> {arch -> supported SM entries}.  Entry semantics:
#   "sm_XY"       -- SASS for compute capability X.Y is embedded in the wheels
#   "compute_ZW"  -- PTX for compute_ZW is embedded (the JIT path)
#   "sm_XY+PTX"   -- both of the above (accepted by the parser for completeness)
# Per the binding ladder rule, a compute_ZW entry covers a device of compute
# capability (X, Y) when (Z, W) >= (X, Y).
INDEX_ARCH_MAP: dict = {
    _CU130: {
        "x86_64": ("sm_75", "sm_80", "sm_86", "sm_89", "sm_90", "sm_100", "sm_120"),
        "aarch64": ("sm_90", "sm_100", "compute_100"),
    },
    _CU128: {
        "x86_64": (
            "sm_70", "sm_75", "sm_80", "sm_86", "sm_89", "sm_90", "sm_100", "sm_120",
        ),
        "aarch64": ("sm_90", "sm_100", "compute_100"),
    },
    _CU126: {
        "x86_64": (
            "sm_50", "sm_60", "sm_70", "sm_75", "sm_80", "sm_86", "sm_89", "sm_90",
        ),
        "aarch64": ("sm_90", "compute_90"),
    },
    _CU121: {
        "x86_64": (
            "sm_50", "sm_60", "sm_70", "sm_75", "sm_80", "sm_86", "sm_89", "sm_90",
        ),
        "aarch64": ("sm_80", "sm_86", "sm_90"),
    },
    _CU118: {
        "x86_64": (
            "sm_37", "sm_50", "sm_60", "sm_70", "sm_75", "sm_80", "sm_86", "sm_89",
            "sm_90",
        ),
        "aarch64": ("sm_80", "sm_86", "sm_90"),
    },
}

# The ordered rows of the design's decision table, as data.  ``driver_min`` /
# ``driver_max`` are inclusive ``(major, minor)`` bounds (``None`` = unbounded),
# ``driver_unknown_ok`` says whether an undetermined driver CUDA matches the
# row, ``unified`` is "no" | "yes" | "any", and ``cc_guard`` names the
# INDEX_ARCH_MAP index whose entry must cover every probed device (``None`` =
# no guard).
DECISION_TABLE: tuple = (
    {
        "row": 1, "arch": "x86_64",
        "driver_min": (13, 0), "driver_max": None, "driver_unknown_ok": False,
        "unified": "no", "cc_guard": _CU130,
        "cc_guard_note": "cc covered by cu130 map (SASS or PTX)",
        "index_url": _CU130, "warning": False, "note": None,
    },
    {
        "row": 2, "arch": "x86_64",
        "driver_min": (12, 8), "driver_max": (12, 9), "driver_unknown_ok": False,
        "unified": "no", "cc_guard": _CU128,
        "cc_guard_note": "cc covered by cu128 map",
        "index_url": _CU128, "warning": False, "note": None,
    },
    {
        "row": 3, "arch": "x86_64",
        "driver_min": (12, 5), "driver_max": (12, 7), "driver_unknown_ok": False,
        "unified": "no", "cc_guard": _CU126,
        "cc_guard_note": "cc covered by cu126 map",
        "index_url": _CU126, "warning": False, "note": None,
    },
    {
        "row": 4, "arch": "x86_64",
        "driver_min": (12, 1), "driver_max": (12, 4), "driver_unknown_ok": False,
        "unified": "no", "cc_guard": _CU121,
        "cc_guard_note": "cc covered by cu121 map",
        "index_url": _CU121, "warning": False, "note": None,
    },
    {
        "row": 5, "arch": "x86_64",
        "driver_min": (11, 8), "driver_max": (12, 0), "driver_unknown_ok": False,
        "unified": "no", "cc_guard": _CU118,
        "cc_guard_note": "cc covered by cu118 map",
        "index_url": _CU118, "warning": False, "note": None,
    },
    {
        "row": 6, "arch": "x86_64",
        "driver_min": None, "driver_max": (11, 7), "driver_unknown_ok": True,
        "unified": "any", "cc_guard": None, "cc_guard_note": None,
        "index_url": CPU_INDEX, "warning": True,
        "note": "CPU index + warning (driver CUDA < 11.8 or unknown)",
    },
    {
        "row": 7, "arch": "aarch64",
        "driver_min": (13, 0), "driver_max": None, "driver_unknown_ok": False,
        "unified": "no", "cc_guard": _CU130,
        "cc_guard_note": "sm_90 / sm_100 or PTX (per map)",
        "index_url": _CU130, "warning": False, "note": None,
    },
    {
        "row": 8, "arch": "aarch64",
        "driver_min": (12, 8), "driver_max": (12, 9), "driver_unknown_ok": False,
        "unified": "no", "cc_guard": _CU128,
        "cc_guard_note": "sm_90 / sm_100 or PTX (per map)",
        "index_url": _CU128, "warning": False, "note": None,
    },
    {
        "row": 9, "arch": "aarch64",
        "driver_min": (12, 5), "driver_max": (12, 7), "driver_unknown_ok": False,
        "unified": "no", "cc_guard": _CU126,
        "cc_guard_note": "sm_90 or PTX (per map)",
        "index_url": _CU126, "warning": False, "note": None,
    },
    {
        "row": 10, "arch": "aarch64",
        "driver_min": None, "driver_max": None, "driver_unknown_ok": True,
        "unified": "yes", "cc_guard": None, "cc_guard_note": None,
        "index_url": CPU_INDEX, "warning": True,
        "note": (
            "CPU index + warning (JetPack pointer); Tegra sm_72/sm_87 served by "
            "no upstream index"
        ),
    },
    {
        "row": 11, "arch": "aarch64",
        "driver_min": None, "driver_max": (12, 4), "driver_unknown_ok": True,
        "unified": "any", "cc_guard": None, "cc_guard_note": None,
        "index_url": CPU_INDEX, "warning": True,
        "note": "CPU index + warning (aarch64 driver CUDA < 12.5 or unknown)",
    },
    {
        "row": 12, "arch": "other",
        "driver_min": None, "driver_max": None, "driver_unknown_ok": True,
        "unified": "any", "cc_guard": None, "cc_guard_note": None,
        "index_url": CPU_INDEX, "warning": True,
        "note": "CPU index + warning (unsupported CPU architecture)",
    },
)


# ---------------------------------------------------------------------------
# Probe snapshot
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Probes:
    """Immutable probe snapshot; the sole input of :func:`resolve_index`."""

    arch: str
    driver_cuda: tuple[int, int] | None
    compute_caps: tuple[tuple[int, int], ...]
    memory_state: str
    notes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Stable, JSON-serializable representation of the probes."""
        driver = None
        if self.driver_cuda is not None:
            driver = [int(self.driver_cuda[0]), int(self.driver_cuda[1])]
        return {
            "arch": str(self.arch),
            "driver_cuda": driver,
            "compute_caps": [
                [int(major), int(minor)] for major, minor in self.compute_caps
            ],
            "memory_state": str(self.memory_state),
            "notes": {
                str(key): str(value)
                for key, value in sorted(
                    self.notes.items(), key=lambda kv: str(kv[0])
                )
            },
        }


# ---------------------------------------------------------------------------
# Fail-soft probing helpers
# ---------------------------------------------------------------------------

_SUBPROC_TIMEOUT_S = 5.0
_NOTE_MAX_CHARS = 300
_NVML_LIB_NAME = "libnvidia-ml.so.1"

_CUDA_VERSION_RE = re.compile(r"CUDA Version:\s*(\d+)\.(\d+)")
_COMPUTE_CAP_LINE_RE = re.compile(r"^\s*(\d+)\.(\d)\s*$")
_INDEX_VERSION_RE = re.compile(r"cu(\d+)/?$")


def _shorten(text) -> str:
    """One-line, bounded rendering of arbitrary probe output."""
    line = " ".join(str(text).split())
    if len(line) > _NOTE_MAX_CHARS:
        return line[: _NOTE_MAX_CHARS - 3] + "..."
    return line


def _fmt_version(version: tuple[int, int]) -> str:
    return f"{version[0]}.{version[1]}"


def _fmt_cu(version: tuple[int, int]) -> str:
    return f"cu{version[0]}{version[1]}"


def _fmt_caps(caps) -> str:
    caps = list(caps)
    if not caps:
        return "none probed"
    return ", ".join(f"{major}.{minor}" for major, minor in caps)


def _run(cmd: list[str]) -> tuple[Any | None, str]:
    """Run a subprocess fail-soft; return (CompletedProcess | None, note)."""
    display = " ".join(cmd)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=_SUBPROC_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError:
        return None, f"{display}: executable not found"
    except subprocess.TimeoutExpired:
        return None, f"{display}: timed out after {_SUBPROC_TIMEOUT_S:g}s"
    except Exception as exc:
        return None, f"{display}: {_shorten(exc)}"
    return proc, f"{display}: rc={proc.returncode}"


def _nvml_load() -> tuple[Any | None, str]:
    """Load and initialize NVML via ctypes; return (lib | None, note)."""
    try:
        lib = ctypes.CDLL(_NVML_LIB_NAME)
    except Exception as exc:
        return None, f"NVML unavailable ({_NVML_LIB_NAME}): {_shorten(exc)}"
    try:
        lib.nvmlInit_v2.restype = ctypes.c_int
        lib.nvmlInit_v2.argtypes = []
        lib.nvmlShutdown.restype = ctypes.c_int
        lib.nvmlShutdown.argtypes = []
        lib.nvmlSystemGetCudaDriverVersion_v2.restype = ctypes.c_int
        lib.nvmlSystemGetCudaDriverVersion_v2.argtypes = [ctypes.POINTER(ctypes.c_int)]
        lib.nvmlDeviceGetCount_v2.restype = ctypes.c_int
        lib.nvmlDeviceGetCount_v2.argtypes = [ctypes.POINTER(ctypes.c_uint)]
        lib.nvmlDeviceGetHandleByIndex_v2.restype = ctypes.c_int
        lib.nvmlDeviceGetHandleByIndex_v2.argtypes = [
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        lib.nvmlDeviceGetCudaComputeCapability.restype = ctypes.c_int
        lib.nvmlDeviceGetCudaComputeCapability.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]
    except Exception as exc:
        return None, f"NVML symbol binding failed: {_shorten(exc)}"
    try:
        rc = lib.nvmlInit_v2()
    except Exception as exc:
        return None, f"NVML nvmlInit_v2 raised: {_shorten(exc)}"
    if rc != 0:
        return None, f"NVML nvmlInit_v2 failed (rc={rc})"
    return lib, "NVML initialized"


def _nvml_shutdown(lib) -> None:
    try:
        lib.nvmlShutdown()
    except Exception:
        pass


def _nvml_driver_cuda() -> tuple[tuple[int, int] | None, str]:
    """Driver CUDA via NVML ``nvmlSystemGetCudaDriverVersion_v2()``."""
    lib, note = _nvml_load()
    if lib is None:
        return None, note
    try:
        raw = ctypes.c_int(0)
        rc = lib.nvmlSystemGetCudaDriverVersion_v2(ctypes.byref(raw))
        if rc != 0:
            return None, f"NVML nvmlSystemGetCudaDriverVersion_v2 failed (rc={rc})"
        value = int(raw.value)
        major, minor = value // 1000, (value % 1000) // 10
        return (
            (major, minor),
            f"NVML nvmlSystemGetCudaDriverVersion_v2()={value} -> {major}.{minor}",
        )
    except Exception as exc:
        return None, f"NVML driver-version query failed: {_shorten(exc)}"
    finally:
        _nvml_shutdown(lib)


def _nvml_compute_caps() -> tuple[tuple[tuple[int, int], ...], str]:
    """Per-device compute capability via NVML; all devices must report."""
    lib, note = _nvml_load()
    if lib is None:
        return (), note
    try:
        count = ctypes.c_uint(0)
        rc = lib.nvmlDeviceGetCount_v2(ctypes.byref(count))
        if rc != 0:
            return (), f"NVML nvmlDeviceGetCount_v2 failed (rc={rc})"
        total = int(count.value)
        if total <= 0:
            return (), "NVML reports 0 NVIDIA devices"
        caps: list[tuple[int, int]] = []
        for idx in range(total):
            handle = ctypes.c_void_p()
            rc = lib.nvmlDeviceGetHandleByIndex_v2(
                ctypes.c_uint(idx), ctypes.byref(handle)
            )
            if rc != 0:
                return (), (
                    f"NVML nvmlDeviceGetHandleByIndex_v2({idx}) failed (rc={rc})"
                )
            major = ctypes.c_int(0)
            minor = ctypes.c_int(0)
            rc = lib.nvmlDeviceGetCudaComputeCapability(
                handle, ctypes.byref(major), ctypes.byref(minor)
            )
            if rc != 0:
                return (), (
                    f"NVML nvmlDeviceGetCudaComputeCapability(device {idx}) failed "
                    f"(rc={rc})"
                )
            pair = (int(major.value), int(minor.value))
            if pair == (0, 0):
                return (), f"NVML reported compute capability 0.0 for device {idx}"
            caps.append(pair)
        return tuple(caps), (
            f"NVML nvmlDeviceGetCudaComputeCapability: {_fmt_caps(caps)}"
        )
    except Exception as exc:
        return (), f"NVML compute-capability query failed: {_shorten(exc)}"
    finally:
        _nvml_shutdown(lib)


def _normalize_arch(raw) -> str:
    value = str(raw or "").strip().lower()
    if value in ("x86_64", "amd64", "x64"):
        return "x86_64"
    if value in ("aarch64", "arm64"):
        return "aarch64"
    return "other"


def _probe_arch() -> tuple[str, str]:
    try:
        raw = platform.machine() or ""
    except Exception as exc:
        return "other", f"platform.machine() failed: {_shorten(exc)}"
    arch = _normalize_arch(raw)
    return arch, f"platform.machine()={raw!r} -> {arch}"


def _probe_driver_cuda() -> tuple[tuple[int, int] | None, str]:
    """Driver CUDA: nvidia-smi header first, NVML fallback."""
    proc, run_note = _run(["nvidia-smi"])
    if proc is not None:
        header = proc.stdout or ""
        match = _CUDA_VERSION_RE.search(header)
        if match is not None:
            major, minor = int(match.group(1)), int(match.group(2))
            return (
                (major, minor),
                f"nvidia-smi header: 'CUDA Version: {major}.{minor}'",
            )
        smi_note = (
            f"nvidia-smi ran (rc={proc.returncode}) but printed no 'CUDA Version' "
            f"field; output: {_shorten(header)!r}"
        )
    else:
        smi_note = run_note
    version, nvml_note = _nvml_driver_cuda()
    if version is not None:
        return version, nvml_note
    return None, f"{smi_note}; {nvml_note}"


def _parse_compute_cap_csv(stdout: str) -> tuple[tuple[int, int], ...]:
    caps: list[tuple[int, int]] = []
    for line in str(stdout or "").splitlines():
        match = _COMPUTE_CAP_LINE_RE.match(line)
        if match is not None:
            caps.append((int(match.group(1)), int(match.group(2))))
    return tuple(caps)


def _import_torch() -> tuple[Any | None, str]:
    try:
        import importlib

        return importlib.import_module("torch"), "torch imported"
    except Exception as exc:
        return None, f"torch unavailable: {_shorten(exc)}"


def _torch_compute_caps(*, torch=None) -> tuple[tuple[tuple[int, int], ...], str]:
    if torch is None:
        torch, note = _import_torch()
        if torch is None:
            return (), note
    try:
        count = int(torch.cuda.device_count())
    except Exception as exc:
        return (), f"torch.cuda.device_count() failed: {_shorten(exc)}"
    if count <= 0:
        return (), "torch.cuda reports 0 devices"
    caps: list[tuple[int, int]] = []
    for idx in range(count):
        try:
            props = torch.cuda.get_device_properties(idx)
            caps.append((int(props.major), int(props.minor)))
        except Exception as exc:
            return (), (
                f"torch.cuda.get_device_properties({idx}) failed: {_shorten(exc)}"
            )
    return tuple(caps), f"torch.cuda.get_device_properties: {_fmt_caps(caps)}"


def _probe_compute_caps(*, torch=None) -> tuple[tuple[tuple[int, int], ...], str]:
    """Compute capability per NVIDIA device: NVML, then nvidia-smi, then torch."""
    notes: list[str] = []
    caps, nvml_note = _nvml_compute_caps()
    if caps:
        return caps, nvml_note
    notes.append(nvml_note)
    proc, run_note = _run(
        ["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"]
    )
    if proc is not None:
        caps = _parse_compute_cap_csv(proc.stdout or "")
        if caps:
            return caps, f"nvidia-smi --query-gpu=compute_cap: {_fmt_caps(caps)}"
        notes.append(
            f"nvidia-smi --query-gpu=compute_cap unusable (rc={proc.returncode}, "
            f"output: {_shorten(proc.stdout or '')!r})"
        )
    else:
        notes.append(run_note)
    caps, torch_note = _torch_compute_caps(torch=torch)
    if caps:
        return caps, torch_note
    notes.append(torch_note)
    return (), "; ".join(notes)


def _probe_memory_state(*, torch=None) -> tuple[str, str]:
    """Memory classification from kaine.hostmem, lazily imported and guarded.

    On any failure the state is "unknown" -- never "unified".
    """
    try:
        import importlib

        hostmem = importlib.import_module("kaine.hostmem")
    except Exception as exc:
        return "unknown", f"kaine.hostmem unavailable: {_shorten(exc)}"
    try:
        classification = hostmem.classify_accelerator_memory(torch=torch)
    except Exception as exc:
        return "unknown", f"classify_accelerator_memory failed: {_shorten(exc)}"
    state = getattr(classification, "state", None)
    if state not in ("discrete", "unified", "unknown"):
        return "unknown", (
            "classify_accelerator_memory returned unrecognized state "
            f"{state!r}; treating as unknown"
        )
    note = f"kaine.hostmem.classify_accelerator_memory -> {state}"
    if state == "unknown":
        reason = getattr(classification, "unknown_reason", None)
        if reason:
            note += f" (unknown_reason: {_shorten(reason)})"
    evidence = getattr(classification, "evidence", None)
    try:
        if evidence:
            note += f"; {len(evidence)} evidence item(s)"
    except Exception:
        pass
    return state, note


def collect_probes(*, torch=None) -> Probes:
    """Probe the host fail-soft and return the snapshot.  Never raises."""
    notes: dict[str, str] = {}
    try:
        arch, arch_note = _probe_arch()
    except Exception as exc:  # pragma: no cover - probes are internally guarded
        arch, arch_note = "other", f"arch probe failed: {_shorten(exc)}"
    notes["arch"] = arch_note
    try:
        driver_cuda, driver_note = _probe_driver_cuda()
    except Exception as exc:  # pragma: no cover
        driver_cuda, driver_note = None, f"driver CUDA probe failed: {_shorten(exc)}"
    notes["driver_cuda"] = driver_note
    try:
        compute_caps, caps_note = _probe_compute_caps(torch=torch)
    except Exception as exc:  # pragma: no cover
        compute_caps, caps_note = (), (
            f"compute-capability probe failed: {_shorten(exc)}"
        )
    notes["compute_caps"] = caps_note
    try:
        memory_state, memory_note = _probe_memory_state(torch=torch)
    except Exception as exc:  # pragma: no cover
        memory_state, memory_note = "unknown", f"memory probe failed: {_shorten(exc)}"
    notes["memory_state"] = memory_note
    return Probes(
        arch=arch,
        driver_cuda=driver_cuda,
        compute_caps=compute_caps,
        memory_state=memory_state,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Pure resolution (the ladder)
# ---------------------------------------------------------------------------

def _index_version(index_url: str) -> tuple[int, int] | None:
    """Parse (major, minor) from a ``.../cuXY`` index URL, e.g. cu128 -> (12, 8)."""
    match = _INDEX_VERSION_RE.search(str(index_url or ""))
    if match is None:
        return None
    digits = match.group(1)
    if len(digits) < 2:
        return None
    return (int(digits[:-1]), int(digits[-1]))


def _parse_sm_digits(digits) -> tuple[int, int] | None:
    """\"87\" -> (8, 7); \"100\" -> (10, 0); \"120\" -> (12, 0)."""
    text = str(digits or "")
    if len(text) < 2 or not text.isdigit():
        return None
    return (int(text[:-1]), int(text[-1]))


def _entry_semantics(token) -> tuple[str | None, tuple[int, int] | None]:
    """Map an INDEX_ARCH_MAP entry to (exact SASS name, PTX version).

    "sm_XY"       -> ("sm_XY", None)
    "sm_XY+PTX"   -> ("sm_XY", (X, Y))
    "compute_ZW"  -> (None, (Z, W))
    """
    text = str(token or "").strip().lower()
    if not text:
        return None, None
    base, ptx_base = text, False
    if "+" in text:
        base, suffix = text.split("+", 1)
        base = base.strip()
        ptx_base = suffix.strip() == "ptx"
    if base.startswith("compute_"):
        return (None, _parse_sm_digits(base[len("compute_"):]))
    if base.startswith("sm_"):
        version = _parse_sm_digits(base[len("sm_"):])
        if version is None:
            return (None, None)
        exact = f"sm_{version[0]}{version[1]}"
        return (exact, version if ptx_base else None)
    return (None, None)


def _device_coverage(cc, entries):
    """Coverage of one device cc by an index's arch entry list.

    Returns ("exact", None), ("ptx", (Z, W)) or None when uncovered.  Per the
    binding ladder rule, a compute_ZW PTX entry covers device cc (X, Y) when
    (Z, W) >= (X, Y).
    """
    pair = (int(cc[0]), int(cc[1]))
    want = f"sm_{pair[0]}{pair[1]}"
    best_ptx: tuple[int, int] | None = None
    for token in entries:
        exact, ptx = _entry_semantics(token)
        if exact is not None and exact == want:
            return ("exact", None)
        if ptx is not None and ptx >= pair:
            if best_ptx is None or ptx < best_ptx:
                best_ptx = ptx
    if best_ptx is not None:
        return ("ptx", best_ptx)
    return None


def _first_uncovered(compute_caps, entries):
    """First (device index, cc) not covered by ``entries``, or None."""
    for idx, cc in enumerate(compute_caps):
        pair = (int(cc[0]), int(cc[1]))
        if _device_coverage(pair, entries) is None:
            return idx, pair
    return None


def _oldest_index_version() -> tuple[int, int]:
    versions = [
        version
        for version in (_index_version(url) for url in INDEX_ARCH_MAP)
        if version is not None
    ]
    return min(versions) if versions else (0, 0)


def _cuda_selected_reason(probes: Probes, version: tuple[int, int], coverages) -> str:
    if not coverages:
        coverage_desc = (
            "no per-device compute capability probed, so the filter is vacuously "
            "satisfied"
        )
    else:
        exact_count = sum(1 for kind, _payload in coverages if kind == "exact")
        ptx_versions = sorted({
            payload
            for kind, payload in coverages
            if kind == "ptx" and payload is not None
        })
        if exact_count == len(coverages):
            coverage_desc = "exact SASS coverage for every probed device"
        elif exact_count == 0:
            names = ", ".join(f"compute_{v[0]}{v[1]}" for v in ptx_versions)
            coverage_desc = f"JIT-from-PTX coverage for every probed device via {names}"
        else:
            names = ", ".join(f"compute_{v[0]}{v[1]}" for v in ptx_versions)
            coverage_desc = (
                "mixed exact-SASS and JIT-from-PTX coverage across probed devices "
                f"({names})"
            )
    driver_str = (
        _fmt_version(probes.driver_cuda)
        if probes.driver_cuda is not None
        else "unknown"
    )
    return (
        f"newest candidate {_fmt_cu(version)} <= driver CUDA {driver_str} passing the "
        f"architecture filter ({probes.arch}) and the compute-capability filter "
        f"({coverage_desc})"
    )


def _match_table_row(probes: Probes, selected_url: str) -> dict | None:
    """First DECISION_TABLE row consistent with the outcome (cosmetic only)."""
    for row in DECISION_TABLE:
        if row["arch"] != probes.arch:
            continue
        driver = probes.driver_cuda
        if driver is None:
            if not row["driver_unknown_ok"]:
                continue
        else:
            if row["driver_min"] is not None and driver < row["driver_min"]:
                continue
            if row["driver_max"] is not None and driver > row["driver_max"]:
                continue
        unified = row["unified"]
        if unified == "no" and probes.memory_state == "unified":
            continue
        if unified == "yes" and probes.memory_state != "unified":
            continue
        if row["index_url"] != selected_url:
            continue
        guard = row["cc_guard"]
        if guard is not None and guard != selected_url:
            continue
        return row
    return None


def _exhaustion_warning(probes: Probes, terminal: str) -> str:
    driver_str = (
        _fmt_version(probes.driver_cuda)
        if probes.driver_cuda is not None
        else "unknown"
    )
    if probes.memory_state == "unified" and probes.arch == "aarch64":
        remediation = (
            "remediation: pass --index-url pointing at the JetPack-provided CUDA "
            "wheel index (NVIDIA distributes Tegra wheels with JetPack, not on "
            "download.pytorch.org)"
        )
    else:
        remediation = (
            "remediation: pass --index-url pointing at a CUDA wheel index matching "
            "this driver and GPU (the available cuXXX indexes are listed at "
            "https://download.pytorch.org/whl)"
        )
    return (
        f"no CUDA wheel index could be selected for this host: arch={probes.arch}, "
        f"driver CUDA={driver_str}, "
        f"compute capability=[{_fmt_caps(probes.compute_caps)}], "
        f"memory classification={probes.memory_state}; "
        f"terminal reason: {terminal}; {remediation}"
    )


def _ladder(probes: Probes) -> dict:
    """The binding fallback ladder.  Pure; returns the pre-override decision."""
    rejected: list[dict[str, str]] = []
    warnings: list[str] = []
    driver = probes.driver_cuda

    # Ladder step 1 -- candidates: every cuX.Y index with X.Y <= driver CUDA,
    # newest first.  An index newer than the driver is never a candidate.
    candidates: list[tuple[tuple[int, int], str]] = []
    if driver is not None:
        for url in INDEX_ARCH_MAP:
            version = _index_version(url)
            if version is not None and version <= driver:
                candidates.append((version, url))
        candidates.sort(key=lambda item: (-item[0][0], -item[0][1], item[1]))

    # Ladder step 2 -- architecture filter.
    arch_valid: list[tuple[tuple[int, int], str, tuple[str, ...]]] = []
    for version, url in candidates:
        entry = INDEX_ARCH_MAP.get(url, {}).get(probes.arch)
        if not entry:
            rejected.append({
                "index": url,
                "reason": (
                    f"no {probes.arch} build listed for this index in INDEX_ARCH_MAP"
                ),
            })
        else:
            arch_valid.append((version, url, tuple(entry)))
    newest_arch_valid = arch_valid[0] if arch_valid else None

    # Ladder step 3 -- compute-capability filter: every probed device covered.
    survivors: list[tuple[tuple[int, int], str, tuple[str, ...]]] = []
    for version, url, entries in arch_valid:
        uncovered = _first_uncovered(probes.compute_caps, entries)
        if uncovered is None:
            survivors.append((version, url, entries))
            continue
        device_idx, (major, minor) = uncovered
        rejected.append({
            "index": url,
            "reason": (
                f"compute capability {major}.{minor} of device {device_idx} not "
                f"covered by the {probes.arch} build list (no exact sm_{major}{minor} "
                f"entry; no compute_ZW PTX entry with (Z, W) >= ({major}, {minor}))"
            ),
        })

    # Ladder step 4 -- unified-memory exclusion (positive classification only;
    # an "unknown" classification never excludes).
    pre_unified_count = len(survivors)
    if probes.memory_state == "unified":
        for _version, url, _entries in survivors:
            rejected.append({
                "index": url,
                "reason": (
                    "host memory positively classified unified (Tegra); upstream "
                    "CUDA wheels carry no Tegra SASS"
                ),
            })
        survivors = []

    # Ladder step 5 -- first survivor wins.
    if survivors:
        version, url, entries = survivors[0]
        if newest_arch_valid is not None and version < newest_arch_valid[0]:
            warnings.append(
                f"downgrade: selected {url} ({_fmt_cu(version)}); the newest candidate "
                f"passing the driver and architecture filters was "
                f"{newest_arch_valid[1]} ({_fmt_cu(newest_arch_valid[0])}), rejected "
                f"by the compute-capability filter"
            )
        coverages = [
            _device_coverage((int(cc[0]), int(cc[1])), entries)
            for cc in probes.compute_caps
        ]
        reason = _cuda_selected_reason(probes, version, coverages)
        row = _match_table_row(probes, url)
        if row is not None:
            reason = f"{reason}; matches decision table row {row['row']}"
        return {
            "variant": "cuda",
            "index_url": url,
            "selected_reason": reason,
            "rejected": rejected,
            "warnings": warnings,
        }

    # Ladder step 6 -- exhaustion: CPU index with a detailed warning.
    if driver is None:
        terminal = (
            "driver CUDA version could not be determined, so no candidate index "
            "satisfies 'index version <= driver CUDA'"
        )
    elif not candidates:
        terminal = (
            f"driver CUDA {_fmt_version(driver)} predates the oldest packaged index "
            f"({_fmt_cu(_oldest_index_version())})"
        )
    elif not arch_valid:
        terminal = (
            f"no packaged CUDA index provides {probes.arch} builds in INDEX_ARCH_MAP"
        )
    elif pre_unified_count == 0:
        terminal = (
            "every architecture-compatible candidate was rejected by the "
            "compute-capability filter"
        )
    else:
        terminal = (
            "every surviving candidate was excluded because host memory is "
            "positively classified unified (Tegra); upstream CUDA wheels carry "
            "no Tegra SASS"
        )
    warnings.append(_exhaustion_warning(probes, terminal))
    reason = f"candidate ladder exhausted; using CPU index: {terminal}"
    row = _match_table_row(probes, CPU_INDEX)
    if row is not None:
        reason = f"{reason}; matches decision table row {row['row']}"
    return {
        "variant": "cpu",
        "index_url": CPU_INDEX,
        "selected_reason": reason,
        "rejected": rejected,
        "warnings": warnings,
    }


def _coerce_version(value) -> tuple[int, int] | None:
    if value is None:
        return None
    try:
        parts = tuple(value)
    except Exception:
        return None
    if len(parts) != 2:
        return None
    try:
        return (int(parts[0]), int(parts[1]))
    except Exception:
        return None


def _coerce_caps(value) -> tuple[tuple[int, int], ...]:
    if not value:
        return ()
    caps: list[tuple[int, int]] = []
    for item in value:
        try:
            parts = tuple(item)
        except Exception:
            continue
        if len(parts) != 2:
            continue
        try:
            caps.append((int(parts[0]), int(parts[1])))
        except Exception:
            continue
    return tuple(caps)


def _coerce_memory_state(value) -> str:
    state = "unknown" if value is None else str(value)
    return state if state in ("discrete", "unified", "unknown") else "unknown"


def _as_probes(probes) -> Probes:
    """Defensive normalization of arbitrary probe-like input; never raises.

    Normalization never invents "unified": unrecognized memory states become
    "unknown", which the ladder treats as non-excluding.
    """
    if probes is None:
        return Probes(
            arch="other", driver_cuda=None, compute_caps=(),
            memory_state="unknown", notes={},
        )
    if isinstance(probes, dict):
        def getter(name, default=None):
            return probes.get(name, default)
    else:
        def getter(name, default=None):
            return getattr(probes, name, default)
    try:
        notes = {
            str(key): str(value)
            for key, value in dict(getter("notes") or {}).items()
        }
    except Exception:
        notes = {}
    return Probes(
        arch=_normalize_arch(getter("arch")),
        driver_cuda=_coerce_version(getter("driver_cuda")),
        compute_caps=_coerce_caps(getter("compute_caps")),
        memory_state=_coerce_memory_state(getter("memory_state")),
        notes=notes,
    )


def _apply_override(result: dict, override) -> dict:
    """Apply the operator's --index-url when a CUDA index would be used."""
    if override is None:
        return result
    candidate = str(override).strip()
    if not candidate:
        return result
    if result["index_url"] == CPU_INDEX:
        # The ladder would not use a CUDA index at all, so the override does not
        # win over the table; say so instead of silently dropping it.
        result["warnings"].append(
            f"operator --index-url override {candidate!r} was not applied: the "
            f"ladder exhausted to the CPU index, i.e. no CUDA index would be used"
        )
        return result
    replaced = result["index_url"]
    result["index_url"] = candidate
    result["variant"] = "cpu" if candidate == CPU_INDEX else "cuda"
    result["selected_reason"] = (
        f"operator-provided --index-url override (replaces ladder selection {replaced})"
    )
    return result


def _resolve_index_ladder(probes: Probes, *, override: str | None = None) -> dict:
    """Pure decision: resolve the wheel index from ``probes`` alone.

    Returns exactly ``{"variant", "index_url", "probes", "selected_reason",
    "rejected", "warnings"}``.  Performs no I/O and never raises.
    """
    try:
        normalized = _as_probes(probes)
        probes_dict = normalized.to_dict()
        base = _ladder(normalized)
        result = {
            "variant": base["variant"],
            "index_url": base["index_url"],
            "probes": probes_dict,
            "selected_reason": base["selected_reason"],
            "rejected": base["rejected"],
            "warnings": base["warnings"],
        }
        return _apply_override(result, override)
    except Exception as exc:  # pragma: no cover - absolute last resort
        return {
            "variant": "cpu",
            "index_url": CPU_INDEX,
            "probes": {},
            "selected_reason": (
                f"internal resolution fallback after error: {_shorten(exc)}"
            ),
            "rejected": [],
            "warnings": [
                f"wheel-index resolution failed; using CPU index: {_shorten(exc)}"
            ],
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_USAGE = (
    "usage: python -m kaine.wheel_index [--index-url URL]\n"
    "\n"
    "Resolve the CUDA wheel index for this host and print the decision as JSON\n"
    "(exit code 0).  --index-url records an operator override, which wins\n"
    "whenever a CUDA index would be used."
)
_USAGE += "\n  --override URL, --override=URL    synonyms of --index-url / --index-url=URL (all four set the same override)"  # wheel-index-usage-doc-v1


def main(argv=None) -> int:
    """CLI: print the resolution as JSON; always exit 0."""
    # >>> wheel-index-cli-flag-synonyms-patch-v1 <<<
    import sys as _wi_sys
    _wi_default = argv is None
    if _wi_default:
        argv = list(_wi_sys.argv[1:])
    argv = list(argv)
    _wi_norm = []
    _wi_i = 0
    while _wi_i < len(argv):
        _wi_tok = argv[_wi_i]
        if _wi_tok == '--override':
            _wi_norm.append('--index-url')
            if _wi_i + 1 < len(argv):
                _wi_i += 1
                _wi_norm.append(argv[_wi_i])
        elif _wi_tok.startswith('--override='):
            _wi_norm.append('--index-url')
            _wi_norm.append(_wi_tok.split('=', 1)[1])
        elif _wi_tok.startswith('--index-url='):
            _wi_norm.append('--index-url')
            _wi_norm.append(_wi_tok.split('=', 1)[1])
        else:
            _wi_norm.append(_wi_tok)
        _wi_i += 1
    argv = _wi_norm
    if _wi_default:
        _wi_sys.argv[1:] = argv
    # <<< wheel-index-cli-flag-synonyms-patch-v1 end <<<
    if argv is None:
        argv = sys.argv[1:]
    override: str | None = None
    ignored: list[str] = []
    args = [str(arg) for arg in argv]
    idx = 0
    while idx < len(args):
        arg = args[idx]
        if arg == "--index-url":
            idx += 1
            if idx < len(args):
                override = args[idx]
        elif arg.startswith("--index-url="):
            override = arg.split("=", 1)[1]
        elif arg in ("-h", "--help"):
            print(_USAGE)
            return 0
        else:
            ignored.append(arg)
        idx += 1
    try:
        probes = collect_probes()
        result = resolve_index(probes, override=override)
    except Exception as exc:  # pragma: no cover - both calls never raise
        result = {
            "variant": "cpu",
            "index_url": CPU_INDEX,
            "probes": {},
            "selected_reason": f"probe or resolution failure: {_shorten(exc)}",
            "rejected": [],
            "warnings": [
                f"wheel-index probing failed; using CPU index: {_shorten(exc)}"
            ],
        }
    if ignored:
        result["warnings"].append(
            "unrecognized CLI arguments ignored: " + " ".join(ignored)
        )
    print(json.dumps(result, sort_keys=True, default=str))
    return 0


# _kaine_operator_override_patch_ : operator --index-url overrides are
# AUTHORITATIVE for the cuda flavor.  The ladder (decision table) is advisory:
# an operator can point at indexes the table cannot know about -- the
# JetPack-provided CUDA wheel index for Tegra (NVIDIA distributes Tegra wheels
# with JetPack, not on download.pytorch.org), an internal mirror, or a
# nightly.  The previous behaviour honoured an override only when the ladder
# had already found a CUDA index and silently discarded it when the ladder
# exhausted to the CPU index -- exactly the case the override exists for,
# which left Tegra hosts permanently CPU-only.
#
# The ladder implementation above (now _resolve_index_ladder) is untouched and
# is always invoked with override=None, so the no-override behaviour -- the
# full `rejected` list, any exhaustion detail, every warning -- is exactly
# what it was before this patch.  The public resolve_index then applies the
# operator override on top of the ladder's result:
#   * index_url is the operator-supplied URL whether the ladder found a
#     candidate or exhausted;
#   * variant is 'cuda' (the operator is supplying a CUDA index);
#   * selected_reason records the URL as operator-provided AND states what
#     the ladder would have chosen without the override, so the decision
#     stays auditable;
#   * the exhaustion warning that claimed no CUDA index would be used is
#     downgraded to a note that the ladder found nothing and the operator
#     override is being used instead;
#   * the old "override was not applied" refusal warning is rewritten in
#     place above and can no longer fire: the override is never routed
#     through the ladder path that emitted it.

def _apply_operator_override(result, override):
    """Apply an authoritative operator --index-url override to a ladder result."""
    ladder_url = result.get('index_url')
    ladder_variant = result.get('variant')
    out = dict(result)
    out['index_url'] = override
    out['variant'] = 'cuda'
    out['selected_reason'] = (
        'operator-provided --index-url ' + str(override)
        + '; ladder would have chosen ' + str(ladder_variant)
        + ' index ' + str(ladder_url)
    )
    # Downgrade the warnings: drop the refusal and the exhaustion claim (the
    # "no CUDA index will/would be used" line) because the operator supplied
    # an index; keep every other ladder finding visible (remediation hints,
    # exhaustion detail, anything else the ladder reported).
    warn_key = None
    for key in ('warnings', 'warning', 'messages', 'diagnostics'):
        value = result.get(key)
        if isinstance(value, (list, tuple)):
            warn_key = key
            break
    if warn_key is not None:
        kept = []
        for entry in result.get(warn_key) or ():
            if isinstance(entry, str) and (
                'was not applied' in entry or 'no CUDA index' in entry
            ):
                continue
            kept.append(entry)
        if ladder_variant != 'cuda':
            kept.append(
                'ladder found no CUDA index; using operator-provided '
                '--index-url override instead'
            )
        out[warn_key] = kept
    return out


def resolve_index(probes, override=None, **kwargs):
    """Resolve the pip wheel index for *probes*.

    Same resolution as the ladder, except that an operator ``override``
    (--index-url) is authoritative for the cuda flavor: it is returned as
    ``index_url`` whether the ladder found a CUDA index or exhausted to the
    CPU index, with ``variant`` set to 'cuda' and a ``selected_reason`` that
    records both the operator-provided URL and the ladder's own would-be
    choice.  With no override the behaviour is unchanged.  Pure: no I/O,
    never raises.
    """
    result = _resolve_index_ladder(probes, override=None, **kwargs)
    if override is None:
        return result
    try:
        return _apply_operator_override(result, override)
    except Exception:
        return result


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
