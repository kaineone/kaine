# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Accelerator memory classification for KAINE host description.

Implements section 1 ("unified-memory classification") of the merged OpenSpec
change ``host-aware-accelerator-provisioning``: for one detected accelerator,
decide whether its memory is ``discrete`` (private VRAM) or ``unified``
(shared system RAM), report the matching pool figures with provenance, and
emit explicit unknown markers (a ``None`` figure plus an ``unknown_reason``)
instead of silent zeros or omitted fields.  The module is pure inspection: it
only reads files, only calls query entry points through ctypes, spawns no
subprocesses, and never raises -- every filesystem read, ctypes call and torch
attribute access is individually guarded, and a total failure degrades to
``MemoryClassification(state="unknown", pools=(), ...)``.

Detection ladder (ordered; the first positive verdict wins):

1. NVML figures.  ``nvmlDeviceGetMemoryInfo`` via ctypes on
   ``libnvidia-ml.so.1``: real total+free figures are a positive *discrete*
   verdict.  NVML is the verdict authority for this rung: it is the
   management-plane view of private VRAM, and where the figure does not exist
   it refuses to report instead of inventing numbers (Tegra drivers answer
   "Not Supported").  torch-derived figures (``torch.cuda.mem_get_info``,
   ``torch.xpu.mem_get_info``) are recorded as pool figures with their own
   provenance but are never promoted to a discreteness verdict, because
   runtime figures describe whatever pool the runtime sees -- on integrated
   parts that pool is shared system RAM, so trusting them would misclassify
   exactly the hosts this change is about.

2. CUDA integrated-device attribute.  ``CU_DEVICE_ATTRIBUTE_INTEGRATED``
   (attribute 18) read via ctypes against ``libcuda``, or
   ``cudaDeviceProp.integrated`` through torch: ``1`` is a positive *unified*
   verdict, ``0`` a positive *discrete* verdict, even when NVML figures are
   unavailable.  If libcuda is absent or the call fails, the ladder falls
   through to the next rung instead of failing.

3. Platform class.  Darwin + arm64 is *unified* (Apple Silicon).  Linux +
   aarch64 with Tegra markers is *unified*: ``/etc/nv_tegra_release`` exists,
   or ``/proc/device-tree/model`` contains "Jetson"/"Orin"/"Tegra"
   (case-insensitive), or ``/proc/device-tree/compatible`` contains
   ``nvidia,tegra``.  Device-tree properties are NUL-terminated; trailing NUL
   bytes are stripped before comparing.

4. AMD APU carve-out signature.  An AMD display-class PCI device whose amdgpu
   ``mem_info_vram_total`` is carve-out sized (<= 1 GiB; real dGPUs ship
   >= 2 GiB) is drawing its "VRAM" from a system-RAM carve-out: *unified*.
   This rung is a heuristic; when it does not match, the ladder degrades to
   ``unknown`` rather than guessing.

5. Nothing matched.  ``unknown`` with an explicit reason.

WHY ``unknown`` MUST NEVER BE PROMOTED TO ``unified``: downstream
provisioning reads ``unified`` as "accelerator capacity and host RAM are the
same pool" and budgets allocations out of system RAM.  Promoting an
``unknown`` to ``unified`` would let a discrete host whose NVML is broken
have its system RAM silently overcommitted as if it were device memory -- a
host-wide failure, and exactly the misclassification this ladder exists to
prevent.  The safe failure direction is the explicit ``unknown`` state:
figures stay ``None`` with an ``unknown_reason``, nothing is zeroed or
omitted, and callers must treat ``unknown`` as "no allocation guarantees".
"""

from __future__ import annotations

import ctypes
import os
import platform
import sys
from dataclasses import dataclass
from typing import Any, Literal

__all__ = [
    "MemoryState",
    "Pool",
    "MemoryClassification",
    "classify_accelerator_memory",
    "system_memory_pool",
    "is_tegra",
    "is_apple_silicon",
    "to_dict",
]

MemoryState = Literal["discrete", "unified", "unknown"]

# CUdevice_attribute::CU_DEVICE_ATTRIBUTE_INTEGRATED (nvml/cuda headers).
_CU_DEVICE_ATTRIBUTE_INTEGRATED = 18

# dlopen candidates for NVML; the explicit aarch64/x86_64 Debian paths cover
# drivers whose libnvidia-ml directory is not in the ldconfig cache (e.g. the
# Jetson's /usr/lib/aarch64-linux-gnu/nvidia/libnvidia-ml.so.1).
_NVML_LIBRARY_CANDIDATES: tuple[str, ...] = (
    "libnvidia-ml.so.1",
    "libnvidia-ml.so",
    "/usr/lib/aarch64-linux-gnu/nvidia/libnvidia-ml.so.1",
    "/usr/lib/x86_64-linux-gnu/nvidia/libnvidia-ml.so.1",
    "/usr/lib64/libnvidia-ml.so.1",
    "/usr/lib/libnvidia-ml.so.1",
    "nvml.dll",
)

_CUDA_LIBRARY_CANDIDATES: tuple[str, ...] = (
    "libcuda.so.1",
    "libcuda.so",
    "/usr/lib/aarch64-linux-gnu/tegra/libcuda.so.1",
    "nvcuda.dll",
)

_AMD_PCI_VENDOR_ID = "0x1002"
# An amdgpu "VRAM" window at or below this size is a BIOS carve-out from
# system RAM rather than private device memory (desktop dGPUs ship >= 2 GiB).
_AMD_CARVE_OUT_MAX_BYTES = 1 << 30

_DT_READ_LIMIT = 1 << 16


@dataclass(frozen=True)
class Pool:
    """One memory pool figure set with explicit provenance and unknown markers."""

    kind: str  # "vram" | "system"
    total_bytes: int | None
    available_bytes: int | None
    provenance: str  # names the data source, e.g. "nvml", "/proc/meminfo"
    unknown_reason: str | None  # non-None exactly when a figure is None


@dataclass(frozen=True)
class MemoryClassification:
    """Ladder verdict for one accelerator, its pools, and the deciding evidence."""

    state: MemoryState
    pools: tuple[Pool, ...]
    evidence: str  # which ladder rung decided it
    unknown_reason: str | None


@dataclass(frozen=True)
class _Probe:
    """Outcome of one internal source probe (figures, attribute value, or note)."""

    figures: tuple[int, int] | None = None  # (total_bytes, free_bytes) when read
    value: int | None = None  # integrated-attribute value when read
    provenance: str = ""
    note: str = ""
    device_seen: bool = False


@dataclass(frozen=True)
class _AmdProbe:
    """Outcome of the AMD APU carve-out signature scan."""

    found: bool = False
    integrated_signature: bool = False
    evidence: str = ""
    vram_total: int | None = None
    vram_free: int | None = None
    provenance: str = ""
    note: str = ""


class _NvmlMemory(ctypes.Structure):
    """nvmlMemory_t (nvml.h): total, free, used -- all unsigned long long."""

    _fields_ = [
        ("total", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    ]


# --------------------------------------------------------------------------- #
# Small guarded helpers
# --------------------------------------------------------------------------- #


def _as_int(value: Any) -> int | None:
    """Best-effort int coercion; ``None`` when impossible. Never raises."""
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _read_file_bytes(path: str, limit: int = _DT_READ_LIMIT) -> bytes | None:
    """Read up to ``limit`` bytes of a file; ``None`` on any failure."""
    try:
        with open(path, "rb") as handle:
            return handle.read(limit)
    except Exception:
        return None


def _dt_pieces(path: str) -> list[str] | None:
    """Decode a device-tree property into its NUL-separated string pieces.

    Device-tree properties are NUL-terminated (and ``compatible`` is a list of
    NUL-separated strings), so trailing -- and for lists, interior -- NUL
    bytes are handled here before any comparison happens.
    """
    data = _read_file_bytes(path)
    if data is None:
        return None
    pieces: list[str] = []
    for chunk in data.split(b"\x00"):
        if not chunk:
            continue
        try:
            piece = chunk.decode("utf-8", errors="replace").strip()
        except Exception:
            continue
        if piece:
            pieces.append(piece)
    return pieces


def _sysfs_text(path: str) -> str | None:
    data = _read_file_bytes(path, limit=4096)
    if data is None:
        return None
    text = data.decode("utf-8", errors="replace").strip()
    return text or None


def _sysfs_int(path: str) -> int | None:
    text = _sysfs_text(path)
    if text is None:
        return None
    try:
        return int(text.split()[0], 10)
    except Exception:
        return None


def _load_library(names: tuple[str, ...]) -> tuple[ctypes.CDLL | None, str]:
    """Try each dlopen candidate; return (library or None, note)."""
    failures: list[str] = []
    for name in names:
        try:
            return ctypes.CDLL(name), name
        except Exception as exc:
            failures.append(f"{name} ({exc.__class__.__name__})")
    if failures:
        return None, "load failed: " + "; ".join(failures)
    return None, "no library candidates"


def _bind(library: ctypes.CDLL, names: tuple[str, ...], restype: Any, argtypes: tuple[Any, ...]) -> Any:
    """Resolve the first present symbol and configure its signature."""
    for name in names:
        try:
            function = getattr(library, name)
        except Exception:
            continue
        try:
            function.restype = restype
            function.argtypes = list(argtypes)
        except Exception:
            continue
        return function
    return None


def _make_pool(kind: str, total: Any, available: Any, provenance: str, reason: str | None = None) -> Pool:
    """Build a Pool, enforcing: unknown_reason is non-None exactly when a figure is None."""
    total_bytes = _as_int(total)
    available_bytes = _as_int(available)
    if total_bytes is None or available_bytes is None:
        return Pool(
            kind=kind,
            total_bytes=total_bytes,
            available_bytes=available_bytes,
            provenance=provenance,
            unknown_reason=reason or f"{kind} figure(s) could not be determined",
        )
    return Pool(
        kind=kind,
        total_bytes=total_bytes,
        available_bytes=available_bytes,
        provenance=provenance,
        unknown_reason=None,
    )


# --------------------------------------------------------------------------- #
# Source probes
# --------------------------------------------------------------------------- #


def _nvml_probe(index: int) -> _Probe:
    """Rung-1 source: NVML device memory figures via ctypes (never raises)."""
    library, load_note = _load_library(_NVML_LIBRARY_CANDIDATES)
    if library is None:
        return _Probe(note=f"nvml: {load_note}")
    init = _bind(library, ("nvmlInit_v2", "nvmlInit"), ctypes.c_int, ())
    shutdown = _bind(library, ("nvmlShutdown",), ctypes.c_int, ())
    get_handle = _bind(
        library,
        ("nvmlDeviceGetHandleByIndex_v2", "nvmlDeviceGetHandleByIndex"),
        ctypes.c_int,
        (ctypes.c_uint, ctypes.c_void_p),
    )
    get_memory = _bind(
        library,
        ("nvmlDeviceGetMemoryInfo",),
        ctypes.c_int,
        (ctypes.c_void_p, ctypes.POINTER(_NvmlMemory)),
    )
    if init is None or get_handle is None or get_memory is None:
        return _Probe(note="nvml: library loaded but required symbols are missing")
    try:
        rc = init()
    except Exception as exc:
        return _Probe(note=f"nvml: nvmlInit raised {exc.__class__.__name__}: {exc}")
    if rc != 0:
        return _Probe(note=f"nvml: nvmlInit failed (rc={rc})")
    try:
        try:
            handle = ctypes.c_void_p()
            rc = get_handle(index, ctypes.byref(handle))
        except Exception as exc:
            return _Probe(
                note=f"nvml: nvmlDeviceGetHandleByIndex raised {exc.__class__.__name__}: {exc}",
                device_seen=True,
            )
        if rc != 0:
            return _Probe(note=f"nvml: no NVML device at index {index} (rc={rc})", device_seen=True)
        try:
            memory = _NvmlMemory()
            rc = get_memory(handle, ctypes.byref(memory))
        except Exception as exc:
            return _Probe(
                note=f"nvml: nvmlDeviceGetMemoryInfo raised {exc.__class__.__name__}: {exc}",
                device_seen=True,
            )
        if rc != 0:
            # Tegra drivers answer "Not Supported" here instead of reporting
            # figures; that is a refusal, never a zero, and never a verdict.
            return _Probe(
                note=(
                    f"nvml: nvmlDeviceGetMemoryInfo failed (rc={rc}); NVML does not report "
                    f"memory figures for this device (Tegra drivers answer 'Not Supported')"
                ),
                device_seen=True,
            )
        if memory.total <= 0:
            return _Probe(
                note=f"nvml: nvmlDeviceGetMemoryInfo returned total={int(memory.total)}; not a usable figure",
                device_seen=True,
            )
        return _Probe(
            figures=(int(memory.total), int(memory.free)),
            provenance="nvml",
            note=(
                f"nvmlDeviceGetMemoryInfo(device {index}) reported "
                f"total={int(memory.total)} free={int(memory.free)}"
            ),
            device_seen=True,
        )
    finally:
        if shutdown is not None:
            try:
                shutdown()
            except Exception:
                pass


def _cuda_integrated_probe(index: int) -> _Probe:
    """Rung-2 source: CU_DEVICE_ATTRIBUTE_INTEGRATED via ctypes on libcuda."""
    library, load_note = _load_library(_CUDA_LIBRARY_CANDIDATES)
    if library is None:
        return _Probe(note=f"libcuda: {load_note}")
    cu_init = _bind(library, ("cuInit",), ctypes.c_int, (ctypes.c_uint,))
    cu_device_get = _bind(
        library, ("cuDeviceGet",), ctypes.c_int, (ctypes.POINTER(ctypes.c_int), ctypes.c_int)
    )
    cu_attribute = _bind(
        library,
        ("cuDeviceGetAttribute",),
        ctypes.c_int,
        (ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_int),
    )
    if cu_init is None or cu_device_get is None or cu_attribute is None:
        return _Probe(note="libcuda: library loaded but required symbols are missing")
    try:
        rc = cu_init(0)
    except Exception as exc:
        return _Probe(note=f"libcuda: cuInit raised {exc.__class__.__name__}: {exc}")
    if rc != 0:
        return _Probe(note=f"libcuda: cuInit failed (rc={rc})")
    try:
        device = ctypes.c_int(-1)
        rc = cu_device_get(ctypes.byref(device), index)
    except Exception as exc:
        return _Probe(note=f"libcuda: cuDeviceGet raised {exc.__class__.__name__}: {exc}")
    if rc != 0:
        return _Probe(note=f"libcuda: no CUDA device at index {index} (rc={rc})")
    try:
        value = ctypes.c_int(-1)
        rc = cu_attribute(ctypes.byref(value), _CU_DEVICE_ATTRIBUTE_INTEGRATED, device)
    except Exception as exc:
        return _Probe(
            note=f"libcuda: cuDeviceGetAttribute raised {exc.__class__.__name__}: {exc}",
            device_seen=True,
        )
    if rc != 0:
        return _Probe(
            note=f"libcuda: cuDeviceGetAttribute(CU_DEVICE_ATTRIBUTE_INTEGRATED) failed (rc={rc})",
            device_seen=True,
        )
    if value.value not in (0, 1):
        return _Probe(
            note=f"libcuda: CU_DEVICE_ATTRIBUTE_INTEGRATED returned unexpected value {int(value.value)}",
            device_seen=True,
        )
    return _Probe(
        value=int(value.value),
        provenance="libcuda cuDeviceGetAttribute",
        note=(
            f"CU_DEVICE_ATTRIBUTE_INTEGRATED={int(value.value)} via libcuda "
            f"cuDeviceGetAttribute (device {index})"
        ),
        device_seen=True,
    )


def _torch_integrated_probe(index: int, torch: Any) -> _Probe:
    """Rung-2 fallback source: cudaDeviceProp.integrated through torch."""
    if torch is None:
        return _Probe(note="torch: not provided")
    try:
        cuda = getattr(torch, "cuda", None)
    except Exception as exc:
        return _Probe(note=f"torch: inspecting torch.cuda raised {exc.__class__.__name__}: {exc}")
    if cuda is None:
        return _Probe(note="torch: torch.cuda not present")
    try:
        available = bool(cuda.is_available())
    except Exception as exc:
        return _Probe(note=f"torch: torch.cuda.is_available() raised {exc.__class__.__name__}: {exc}")
    if not available:
        return _Probe(note="torch: torch.cuda.is_available() is False")
    try:
        props = cuda.get_device_properties(index)
    except Exception as exc:
        return _Probe(
            note=f"torch: get_device_properties({index}) raised {exc.__class__.__name__}: {exc}",
            device_seen=True,
        )
    for attr in ("integrated", "is_integrated"):
        try:
            raw = getattr(props, attr, None)
        except Exception:
            raw = None
        value = _as_int(raw)
        if value in (0, 1):
            return _Probe(
                value=value,
                provenance=f"torch.cuda.get_device_properties({index}).{attr}",
                note=f"torch: cudaDeviceProp.{attr}={value} (device {index})",
                device_seen=True,
            )
    return _Probe(note="torch: device properties expose no integrated attribute", device_seen=True)


def _torch_figures_probe(index: int, torch: Any) -> _Probe:
    """Figure source only: runtime memory figures (never a discreteness verdict)."""
    if torch is None:
        return _Probe(note="torch: not provided")
    notes: list[str] = []
    seen = False
    for namespace, label in (("cuda", "torch.cuda.mem_get_info"), ("xpu", "torch.xpu.mem_get_info")):
        try:
            ns = getattr(torch, namespace, None)
        except Exception as exc:
            notes.append(f"{label}: inspecting torch.{namespace} raised {exc.__class__.__name__}")
            continue
        if ns is None:
            notes.append(f"{label}: torch.{namespace} not present")
            continue
        try:
            available = bool(ns.is_available())
        except Exception as exc:
            notes.append(f"{label}: is_available() raised {exc.__class__.__name__}: {exc}")
            continue
        if not available:
            notes.append(f"{label}: is_available() is False")
            continue
        seen = True
        try:
            getter = getattr(ns, "mem_get_info", None)
        except Exception as exc:
            notes.append(f"{label}: inspecting mem_get_info raised {exc.__class__.__name__}")
            continue
        if getter is None:
            notes.append(f"{label}: not exposed by this torch build")
            continue
        try:
            free, total = getter(index)  # torch returns (free, total)
            total_i = int(total)
            free_i = int(free)
        except Exception as exc:
            notes.append(f"{label}: raised {exc.__class__.__name__}: {exc}")
            continue
        if total_i <= 0:
            notes.append(f"{label}: total={total_i} is not a usable figure")
            continue
        return _Probe(
            figures=(total_i, free_i),
            provenance=label,
            note=f"{label}(device {index}) -> total={total_i} free={free_i}",
            device_seen=True,
        )
    return _Probe(
        note="; ".join(notes) if notes else "torch: no memory figure source available",
        device_seen=seen,
    )


def _amd_probe() -> _AmdProbe:
    """Rung-4 source: AMD display devices and the amdgpu carve-out signature."""
    try:
        entries = sorted(os.listdir("/sys/bus/pci/devices"))
    except Exception as exc:
        return _AmdProbe(note=f"amd: /sys/bus/pci/devices unreadable ({exc.__class__.__name__})")
    found = False
    signature_evidence = ""
    vram_total: int | None = None
    vram_free: int | None = None
    for name in entries:
        base = os.path.join("/sys/bus/pci/devices", name)
        vendor = _sysfs_text(os.path.join(base, "vendor"))
        device_class = _sysfs_text(os.path.join(base, "class"))
        if vendor is None or device_class is None:
            continue
        if vendor.lower() != _AMD_PCI_VENDOR_ID or not device_class.lower().startswith("0x03"):
            continue
        found = True
        total = _sysfs_int(os.path.join(base, "mem_info_vram_total"))
        used = _sysfs_int(os.path.join(base, "mem_info_vram_used"))
        gtt = _sysfs_int(os.path.join(base, "mem_info_gtt_total"))
        if total is None:
            continue
        detail = f"PCI {name} vendor {vendor} class {device_class} mem_info_vram_total={total}"
        if gtt is not None:
            detail += f" mem_info_gtt_total={gtt}"
        if total <= _AMD_CARVE_OUT_MAX_BYTES:
            if not signature_evidence:
                signature_evidence = (
                    f"{detail} -- the VRAM window is carve-out sized "
                    f"(<= {_AMD_CARVE_OUT_MAX_BYTES} bytes), i.e. the display device "
                    f"draws from system RAM"
                )
        elif vram_total is None:
            vram_total = total
            vram_free = total - used if used is not None and 0 <= used <= total else None
    if not found:
        return _AmdProbe(note="amd: no AMD display-class PCI device found under /sys/bus/pci/devices")
    note = "amd: AMD display device present" + (
        " with carve-out signature" if signature_evidence else " but no carve-out signature"
    )
    return _AmdProbe(
        found=True,
        integrated_signature=bool(signature_evidence),
        evidence=signature_evidence,
        vram_total=vram_total,
        vram_free=vram_free,
        provenance="amdgpu sysfs mem_info_vram_total" if vram_total is not None else "",
        note=note,
    )


# --------------------------------------------------------------------------- #
# Platform-class markers
# --------------------------------------------------------------------------- #


def is_tegra() -> tuple[bool, str]:
    """Detect NVIDIA Tegra/Jetson platforms from read-only filesystem markers.

    Markers, in order: ``/etc/nv_tegra_release`` exists; ``/proc/device-tree/
    model`` contains "Jetson", "Orin" or "Tegra" (case-insensitive);
    ``/proc/device-tree/compatible`` contains ``nvidia,tegra``.  Device-tree
    properties are NUL-terminated and trailing NUL bytes are stripped before
    comparing.  Returns ``(verdict, provenance)`` and never raises.
    """
    try:
        release = _read_file_bytes("/etc/nv_tegra_release", limit=4096)
        if release is not None:
            lines = release.decode("utf-8", errors="replace").strip().splitlines()
            snippet = lines[0].strip() if lines and lines[0].strip() else "<empty>"
            if len(snippet) > 120:
                snippet = snippet[:120] + "..."
            return True, f"/etc/nv_tegra_release present ({snippet})"
        model_pieces = _dt_pieces("/proc/device-tree/model")
        if model_pieces:
            model = model_pieces[0]
            lowered = model.lower()
            for token in ("jetson", "orin", "tegra"):
                if token in lowered:
                    return True, f"/proc/device-tree/model {model!r} contains {token!r}"
        compatible_pieces = _dt_pieces("/proc/device-tree/compatible")
        for piece in compatible_pieces or ():
            if "nvidia,tegra" in piece.lower():
                return True, f"/proc/device-tree/compatible contains {piece!r}"
        return False, (
            "no Tegra markers found (checked /etc/nv_tegra_release, "
            "/proc/device-tree/model, /proc/device-tree/compatible)"
        )
    except Exception as exc:  # pragma: no cover - defensive backstop
        return False, f"tegra marker probe failed: {exc.__class__.__name__}: {exc}"


def is_apple_silicon() -> tuple[bool, str]:
    """Detect Darwin + arm64 (Apple Silicon, unified memory). Never raises."""
    try:
        system = platform.system()
        machine = platform.machine()
    except Exception as exc:  # pragma: no cover - defensive backstop
        return False, f"platform probe failed: {exc.__class__.__name__}: {exc}"
    if system == "Darwin" and machine.lower() in ("arm64", "aarch64"):
        return True, (
            f"platform.system()=='Darwin' and platform.machine()=='{machine}' (Apple Silicon)"
        )
    return False, (
        f"platform.system()=={system!r}, platform.machine()=={machine!r} "
        f"(Apple Silicon requires Darwin+arm64)"
    )


def _is_linux_aarch64() -> bool:
    try:
        if not sys.platform.startswith("linux"):
            return False
        return platform.machine().lower() in ("aarch64", "arm64")
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# System memory pool
# --------------------------------------------------------------------------- #


def _parse_kb(rest: str) -> int | None:
    try:
        fields = rest.split()
        if not fields:
            return None
        return int(fields[0], 10)
    except Exception:
        return None


def _meminfo_pool() -> Pool | None:
    data = _read_file_bytes("/proc/meminfo", limit=1 << 20)
    if data is None:
        return None
    text = data.decode("utf-8", errors="replace")
    total_kb: int | None = None
    available_kb: int | None = None
    for line in text.splitlines():
        key, sep, rest = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        if key == "MemTotal" and total_kb is None:
            total_kb = _parse_kb(rest)
        elif key == "MemAvailable" and available_kb is None:
            available_kb = _parse_kb(rest)
    if total_kb is None and available_kb is None:
        return None
    total = total_kb * 1024 if total_kb is not None else None
    available = available_kb * 1024 if available_kb is not None else None
    if total is None:
        return Pool(
            kind="system",
            total_bytes=None,
            available_bytes=available,
            provenance="/proc/meminfo",
            unknown_reason="MemTotal not reported by /proc/meminfo",
        )
    if available is None:
        return Pool(
            kind="system",
            total_bytes=total,
            available_bytes=None,
            provenance="/proc/meminfo",
            unknown_reason="MemAvailable not reported by /proc/meminfo",
        )
    return Pool(
        kind="system",
        total_bytes=total,
        available_bytes=available,
        provenance="/proc/meminfo",
        unknown_reason=None,
    )


def _system_memory_pool() -> Pool:
    notes: list[str] = []
    try:
        pool = _meminfo_pool()
    except Exception as exc:
        pool = None
        notes.append(f"/proc/meminfo probe raised {exc.__class__.__name__}: {exc}")
    if pool is not None:
        return pool
    psutil_module: Any = None
    try:
        import psutil  # defensive: optional KAINE dependency, imported lazily

        psutil_module = psutil
    except Exception as exc:
        notes.append(f"psutil import failed ({exc.__class__.__name__})")
    if psutil_module is not None:
        try:
            vm = psutil_module.virtual_memory()
            total = _as_int(getattr(vm, "total", None))
            available = _as_int(getattr(vm, "available", None))
        except Exception as exc:
            notes.append(f"psutil.virtual_memory failed ({exc.__class__.__name__}: {exc})")
        else:
            if total is not None and total > 0 and available is not None and available > 0:
                return Pool(
                    kind="system",
                    total_bytes=total,
                    available_bytes=available,
                    provenance="psutil.virtual_memory",
                    unknown_reason=None,
                )
            if total is None or total <= 0:
                notes.append("psutil reported no usable total figure")
            else:
                notes.append("psutil reported no usable available figure")
    detail = "; ".join(notes) if notes else "no system memory source succeeded"
    return Pool(
        kind="system",
        total_bytes=None,
        available_bytes=None,
        provenance="/proc/meminfo",
        unknown_reason=f"/proc/meminfo unavailable and the psutil fallback failed: {detail}",
    )


def system_memory_pool() -> Pool:
    """System RAM pool (total/available) from /proc/meminfo, psutil fallback.

    Never raises; a figure that cannot be determined is ``None`` with an
    ``unknown_reason`` (never a silent zero).
    """
    try:
        return _system_memory_pool()
    except Exception as exc:  # pragma: no cover - defensive backstop
        return Pool(
            kind="system",
            total_bytes=None,
            available_bytes=None,
            provenance="/proc/meminfo",
            unknown_reason=f"system memory probe failed: {exc.__class__.__name__}: {exc}",
        )


# --------------------------------------------------------------------------- #
# Ladder
# --------------------------------------------------------------------------- #


def _best_vram_pool(nvml: _Probe, torch_fig: _Probe, amd: _AmdProbe | None = None) -> Pool:
    """Best-effort VRAM pool: NVML figures, then torch figures, then amdgpu sysfs."""
    if nvml.figures is not None:
        total, free = nvml.figures
        return _make_pool("vram", total, free, nvml.provenance or "nvml")
    if torch_fig.figures is not None:
        total, free = torch_fig.figures
        return _make_pool("vram", total, free, torch_fig.provenance or "torch")
    if amd is not None and amd.vram_total is not None:
        reason = (
            None
            if amd.vram_free is not None
            else "amdgpu mem_info_vram_used not readable; available figure undetermined"
        )
        return _make_pool(
            "vram",
            amd.vram_total,
            amd.vram_free,
            amd.provenance or "amdgpu sysfs mem_info_vram_total",
            reason,
        )
    notes = [nvml.note, torch_fig.note]
    if amd is not None and amd.note:
        notes.append(amd.note)
    detail = "; ".join(note for note in notes if note)
    return _make_pool(
        "vram",
        None,
        None,
        "nvml",
        f"no VRAM figure source succeeded ({detail})",
    )


def _classify(index: int, torch: Any) -> MemoryClassification:
    # -- Rung 1: NVML figures (positive discrete verdict) --------------------
    nvml = _nvml_probe(index)
    if nvml.figures is not None:
        total, free = nvml.figures
        return MemoryClassification(
            state="discrete",
            pools=(_make_pool("vram", total, free, nvml.provenance or "nvml"),),
            evidence=f"rung-1 nvml-figures: {nvml.note}",
            unknown_reason=None,
        )

    # torch-derived figures: recorded for pools, never a discreteness verdict.
    torch_fig = _torch_figures_probe(index, torch)

    # -- Rung 2: CUDA integrated-device attribute ----------------------------
    integrated = _cuda_integrated_probe(index)
    integrated_notes = [integrated.note]
    if integrated.value is None:
        via_torch = _torch_integrated_probe(index, torch)
        integrated_notes.append(via_torch.note)
        if via_torch.value is not None:
            integrated = via_torch
    if integrated.value is not None:
        if integrated.value == 1:
            return MemoryClassification(
                state="unified",
                pools=(system_memory_pool(),),
                evidence=f"rung-2 cuda-integrated-attribute: {integrated.note}",
                unknown_reason=None,
            )
        return MemoryClassification(
            state="discrete",
            pools=(_best_vram_pool(nvml, torch_fig),),
            evidence=f"rung-2 cuda-integrated-attribute: {integrated.note}",
            unknown_reason=None,
        )

    # -- Rung 3: platform class ----------------------------------------------
    apple_ok, apple_prov = is_apple_silicon()
    if apple_ok:
        return MemoryClassification(
            state="unified",
            pools=(system_memory_pool(),),
            evidence=f"rung-3 platform-class: {apple_prov}",
            unknown_reason=None,
        )
    tegra_prov = "not checked (Tegra markers require Linux aarch64)"
    if _is_linux_aarch64():
        tegra_ok, tegra_prov = is_tegra()
        if tegra_ok:
            return MemoryClassification(
                state="unified",
                pools=(system_memory_pool(),),
                evidence=f"rung-3 platform-class: Linux aarch64; {tegra_prov}",
                unknown_reason=None,
            )

    # -- Rung 4: AMD APU carve-out signature ---------------------------------
    amd = _amd_probe()
    if amd.integrated_signature:
        return MemoryClassification(
            state="unified",
            pools=(system_memory_pool(),),
            evidence=f"rung-4 amd-apu-carveout: {amd.evidence}",
            unknown_reason=None,
        )

    # -- Rung 5: explicit unknown (never promoted to unified) -----------------
    seen = nvml.device_seen or integrated.device_seen or torch_fig.device_seen or amd.found
    pools: list[Pool] = []
    if seen:
        vram_pool = _best_vram_pool(nvml, torch_fig, amd)
        if vram_pool.total_bytes is not None or vram_pool.available_bytes is not None:
            pools.append(vram_pool)
        system = system_memory_pool()
        if system.total_bytes is not None or system.available_bytes is not None:
            pools.append(system)
    notes = [nvml.note, *integrated_notes, torch_fig.note, amd.note]
    detail = "; ".join(note for note in notes if note)
    platform_note = f"platform: {apple_prov}; {tegra_prov}"
    detail = f"{detail}; {platform_note}" if detail else platform_note
    if seen:
        reason = f"accelerator detected but its memory class could not be determined ({detail})"
    else:
        reason = f"no recognizable accelerator and no unified-platform signature ({detail})"
    return MemoryClassification(
        state="unknown",
        pools=tuple(pools),
        evidence="rung-5 fallback: no ladder rung produced a verdict",
        unknown_reason=reason,
    )


def classify_accelerator_memory(index: int | None = None, *, torch: Any = None) -> MemoryClassification:
    """Classify the memory of one accelerator; never raises.

    ``index`` selects the device (default 0).  ``torch`` may be an
    already-imported torch module (or a test double); when it is ``None`` a
    defensive ``import torch`` is attempted and its failure is ignored, so the
    module works with torch absent entirely.  Every probe failure degrades
    towards the explicit ``unknown`` state -- figures become ``None`` with an
    ``unknown_reason``, never silent zeros, and ``unknown`` is never promoted
    to ``unified``.
    """
    if index is None:
        device_index = 0
    else:
        device_index = _as_int(index)
        if device_index is None:
            return MemoryClassification(
                state="unknown",
                pools=(),
                evidence="backstop: device index is not an integer",
                unknown_reason=f"device index {index!r} is not an integer",
            )
    effective_torch: Any = torch
    if effective_torch is None:
        try:
            import torch as _torch_module  # defensive: torch is optional

            effective_torch = _torch_module
        except Exception:
            effective_torch = None
    try:
        return _classify(device_index, effective_torch)
    except Exception as exc:  # pragma: no cover - absolute backstop
        return MemoryClassification(
            state="unknown",
            pools=(),
            evidence="backstop: an unexpected error aborted the ladder",
            unknown_reason=f"unexpected {exc.__class__.__name__}: {exc}",
        )


# --------------------------------------------------------------------------- #
# JSON serialization
# --------------------------------------------------------------------------- #


def _json_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def to_dict(c: MemoryClassification) -> dict:
    """Convert a classification to a JSON-serializable dict (never raises).

    The output uses only plain ints, strs, ``None``, lists and dicts, so
    ``json.loads(json.dumps(to_dict(c))) == to_dict(c)`` holds.
    """
    try:
        pools = [
            {
                "kind": str(p.kind),
                "total_bytes": _json_int(p.total_bytes),
                "available_bytes": _json_int(p.available_bytes),
                "provenance": str(p.provenance),
                "unknown_reason": None if p.unknown_reason is None else str(p.unknown_reason),
            }
            for p in (c.pools or ())
        ]
        return {
            "state": str(c.state),
            "pools": pools,
            "evidence": str(c.evidence),
            "unknown_reason": None if c.unknown_reason is None else str(c.unknown_reason),
        }
    except Exception as exc:  # pragma: no cover - defensive backstop
        return {
            "state": "unknown",
            "pools": [],
            "evidence": f"backstop: to_dict failed on the original classification ({exc.__class__.__name__})",
            "unknown_reason": "classification could not be serialized",
        }
