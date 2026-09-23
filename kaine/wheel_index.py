# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Host-aware wheel-index resolution -- the single source of truth for
which pip ``--index-url`` provides the PyTorch wheels on this host.

This module implements tasks 1.2, 1.3 and 2.2 of the OpenSpec change
``host-fit-provisioning``.  It is stdlib-only and may run before any
dependency (including ``packaging``) is installed.

Responsibilities are strictly split:

* :func:`collect_probes` performs every fallible discovery (platform,
  ``nvidia-smi``, NVML through ``ctypes``, optional torch,
  ``kaine.hostmem``).  Every probe is fail-soft.
* :func:`resolve_index` is a pure function of its ``Probes`` argument: no
  I/O, no subprocesses, no probing.

The fallback ladder is version-aware: it consults the recorded
``PUBLISHED`` wheel lists from :mod:`kaine.wheel_data` and selects the
driver-eligible candidate with the highest in-range ``torch`` version
that is published for the host architecture and covers every probed
device.
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .wheel_data import (
    COMPANIONS,
    CUDA_ARCH,
    PUBLISHED,
    ROCM_ARCH,
)

__all__ = [
    "CPU_INDEX",
    "DECISION_TABLE",
    "INDEX_ARCH_MAP",
    "Probes",
    "collect_probes",
    "main",
    "resolve_index",
    "resolve_rocm",
]

# ---------------------------------------------------------------------------
# Version / specifier helpers (stdlib only; no packaging)
# ---------------------------------------------------------------------------


def _vtuple(version) -> tuple[int, int, int]:
    """\"2.14.0\" -> (2, 14, 0); drop any '+local' suffix; pad to 3."""
    text = str(version).split("+")[0].strip()
    parts = [int(p) for p in text.split(".") if p.isdigit()]
    parts.extend([0] * (3 - len(parts)))
    return tuple(parts[:3])


def _mm_pair(version) -> tuple[int, int]:
    """Major.minor tuple of a version string; used to detect unasserted companion pairings."""
    v = _vtuple(version)
    return (v[0], v[1])


def _strip_torch_prefix(req: str) -> str:
    req = str(req or "").strip()
    if req.lower().startswith("torch"):
        req = req[len("torch") :].strip()
    return req


def _parse_spec(spec: str):
    """\"torch>=2.9.1,<2.15\" -> [('>=', (2,9,1)), ('<', (2,15,0))]."""
    spec = _strip_torch_prefix(spec)
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        match = re.match(r"^\s*(>=|<=|>|<|==|!=)\s*([\d\.]+)", part)
        if not match:
            continue
        op, ver = match.group(1), match.group(2)
        out.append((op, _vtuple(ver)))
    return out


def _in_range(version, spec_list) -> bool:
    """Padded-tuple comparison; \"<2.15\" excludes 2.15.0."""
    v = _vtuple(version)
    for op, bound in spec_list:
        if op == ">=" and not (v >= bound):
            return False
        if op == ">" and not (v > bound):
            return False
        if op == "<=" and not (v <= bound):
            return False
        if op == "<" and not (v < bound):
            return False
        if op == "==" and not (v == bound):
            return False
        if op == "!=" and not (v != bound):
            return False
    return True


def project_torch_spec(pyproject_path=None) -> str:
    """Return the torch requirement (without the leading 'torch') from pyproject.

    Env ``KAINE_TORCH_SPEC`` wins.  Falls back to ``tomllib`` or a regex.
    Returns ``\">=\"`` (and the resolver emits a warning) when no spec is found.
    """
    env_spec = os.environ.get("KAINE_TORCH_SPEC")
    if env_spec is not None:
        return _strip_torch_prefix(env_spec)
    if pyproject_path is None:
        pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    try:
        text = Path(pyproject_path).read_text(encoding="utf-8")
    except Exception:
        return ">="
    try:
        import tomllib
    except ImportError:
        tomllib = None
    if tomllib is not None:
        try:
            data = tomllib.loads(text)
            for dep in data.get("project", {}).get("dependencies", []):
                dep = str(dep).strip()
                if dep.startswith("torch"):
                    spec = _strip_torch_prefix(dep)
                    if spec:
                        return spec
        except Exception:
            pass
    for line in text.splitlines():
        match = re.search(r'["\']torch\s*([<>=!~][^"\']*)["\']', line)
        if match:
            spec = match.group(1).strip().rstrip(",").strip()
            if spec:
                return spec
    for line in text.splitlines():
        match = re.search(r"torch\s*([<>=!~][^,\'\"\]]*)", line)
        if match:
            spec = match.group(1).strip().rstrip(",").strip()
            if spec:
                return spec
    return ">="


# ---------------------------------------------------------------------------
# Index helpers
# ---------------------------------------------------------------------------

_BASE_URL = "https://download.pytorch.org/whl/"
CPU_INDEX = _BASE_URL + "cpu"


def _index_url(name: str) -> str:
    return _BASE_URL + name


def _index_short_name(url: str) -> str | None:
    url = str(url or "").rstrip("/")
    name = url.split("/")[-1]
    if name in PUBLISHED:
        return name
    lower = name.lower()
    if lower in PUBLISHED:
        return lower
    return None


def _cuda_version_from_short(name: str) -> tuple[int, int] | None:
    match = re.match(r"^cu(\d+)$", name)
    if not match:
        return None
    digits = match.group(1)
    if len(digits) < 2:
        return None
    return (int(digits[:-1]), int(digits[-1]))


def _rocm_version_from_short(name: str) -> tuple[int, int] | None:
    match = re.match(r"^rocm(\d+)\.(\d+)$", name)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)))


def _parse_sm_digits(digits) -> tuple[int, int] | None:
    """\"87\" -> (8, 7); \"100\" -> (10, 0); \"8.6\" -> (8, 6)."""
    text = str(digits or "")
    if "." in text:
        parts = text.split(".")
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            return None
        return (int(parts[0]), int(parts[1]))
    if len(text) < 2 or not text.isdigit():
        return None
    return (int(text[:-1]), int(text[-1]))


def _token_semantics(token):
    """Map an arch-list token to (exact_sm_name, sass_version, ptx_version).

    Tokens come from CUDA_ARCH strings such as \"8.0\", \"8.0+PTX\",
    and may also appear as the sm_/compute_ entries in derived maps.
    """
    text = str(token or "").strip().lower()
    if not text:
        return None, None, None
    has_ptx = text.endswith("+ptx")
    base = text[:-4].strip() if has_ptx else text
    if base.startswith("compute_"):
        v = _parse_sm_digits(base[len("compute_") :])
        if v is None:
            return None, None, None
        return None, None, v
    if base.startswith("sm_"):
        base = base[3:]
    v = _parse_sm_digits(base)
    if v is None:
        return None, None, None
    exact = f"sm_{v[0]}{v[1]}"
    return exact, v, (v if has_ptx else None)


def _arch_list_to_entries(arch_string: str) -> tuple[str, ...]:
    """Convert a CUDA_ARCH arch-list string into INDEX_ARCH_MAP entries."""
    entries: list[str] = []
    for token in str(arch_string or "").split(";"):
        token = token.strip()
        if not token:
            continue
        sm_name, _sass, ptx = _token_semantics(token)
        if sm_name is not None:
            entries.append(sm_name)
        if ptx is not None:
            entries.append(f"compute_{ptx[0]}{ptx[1]}")
    return tuple(entries)


def _device_coverage(cc, entries):
    """Coverage of one device cc by an entry list.

    Returns ("exact", None), ("same_major", covering_sm) or
    ("ptx", ptx_version); None when uncovered.

    Same-major coverage: a cubin sm_X.Y runs on a device (X, Y2) when
    Y2 >= Y.  We therefore pick the highest cubin minor that is still
    <= the device minor.  A PTX ``compute_Z.W`` entry can be JIT-compiled
    by the driver only for devices whose compute capability (X, Y) >= (Z, W);
    we therefore pick the highest such PTX entry.  Exact SASS matches are
    preferred, same-major SASS is next, and PTX is a last-resort fallback.
    """
    cc = (int(cc[0]), int(cc[1]))
    want = f"sm_{cc[0]}{cc[1]}"
    best_same: tuple[int, str] | None = None
    best_ptx: tuple[int, int] | None = None
    for token in entries:
        sm_name, sass, ptx = _token_semantics(token)
        if sm_name is not None and sm_name == want:
            return ("exact", None)
        if sass is not None and sass[0] == cc[0] and sass[1] <= cc[1]:
            if best_same is None or sass[1] > best_same[0]:
                best_same = (sass[1], sm_name)
        if ptx is not None and ptx <= cc:
            if best_ptx is None or ptx > best_ptx:
                best_ptx = ptx
    if best_same is not None:
        return ("same_major", best_same[1])
    if best_ptx is not None:
        return ("ptx", best_ptx)
    return None


def _newest_arch_version(index_name: str, arch: str, spec_list):
    """Newest in-range torch version published for (index, arch)."""
    versions = PUBLISHED.get(index_name, {}).get(arch, ())
    for v in sorted(versions, key=_vtuple, reverse=True):
        if _in_range(v, spec_list):
            return v
    return None


def _derive_index_arch_map(spec_str: str | None = None) -> dict[str, dict[str, tuple[str, ...]]]:
    """Backward-compatible INDEX_ARCH_MAP from the newest in-range torch per (index, arch)."""
    spec_list = _parse_spec(spec_str) if spec_str else []
    if spec_str and not spec_list:
        # Unparseable or bare operator: treat as no constraint.
        spec_list = []
    derived: dict[str, dict[str, tuple[str, ...]]] = {}
    for name, arch_map in PUBLISHED.items():
        if not name.startswith("cu"):
            continue
        url = _index_url(name)
        per_arch: dict[str, tuple[str, ...]] = {}
        for arch, versions in arch_map.items():
            if arch not in ("x86_64", "aarch64"):
                continue
            chosen = None
            for v in sorted(versions, key=_vtuple, reverse=True):
                if _in_range(v, spec_list):
                    chosen = v
                    break
            if chosen is None:
                continue
            cu_data = CUDA_ARCH.get(chosen, {}).get(name, {})
            arch_string = cu_data.get(arch)
            if not arch_string:
                continue
            entries = _arch_list_to_entries(arch_string)
            if entries:
                per_arch[arch] = entries
        if per_arch:
            derived[url] = per_arch
    return derived


_DEFAULT_TORCH_SPEC = project_torch_spec()
try:
    INDEX_ARCH_MAP: dict[str, dict[str, tuple[str, ...]]] = _derive_index_arch_map(_DEFAULT_TORCH_SPEC)
    if not INDEX_ARCH_MAP:
        raise RuntimeError("derived INDEX_ARCH_MAP is empty")
except Exception:
    # Fallback to the unconstrained view over all published versions.
    INDEX_ARCH_MAP = _derive_index_arch_map(None)

# ---------------------------------------------------------------------------
# Decision table (declarative companion to the ladder)
# ---------------------------------------------------------------------------

_CU132 = _index_url("cu132")
_CU130 = _index_url("cu130")
_CU129 = _index_url("cu129")
_CU128 = _index_url("cu128")
_CU126 = _index_url("cu126")

DECISION_TABLE: tuple = (
    {
        "row": 1,
        "arch": "x86_64",
        "driver_min": (13, 2),
        "driver_max": None,
        "driver_unknown_ok": False,
        "unified": "no",
        "cc_guard": _CU132,
        "cc_guard_note": "highest in-range torch on a driver-compatible CUDA index that covers the device",
        "index_url": _CU132,
        "warning": False,
        "note": "highest in-range torch on a driver-compatible CUDA index that covers the device",
    },
    {
        "row": 2,
        "arch": "x86_64",
        "driver_min": (13, 0),
        "driver_max": (13, 1),
        "driver_unknown_ok": False,
        "unified": "no",
        "cc_guard": _CU130,
        "cc_guard_note": "highest in-range torch on a driver-compatible CUDA index that covers the device",
        "index_url": _CU130,
        "warning": False,
        "note": "highest in-range torch on a driver-compatible CUDA index that covers the device",
    },
    {
        "row": 3,
        "arch": "x86_64",
        "driver_min": (12, 9),
        "driver_max": (12, 9),
        "driver_unknown_ok": False,
        "unified": "no",
        "cc_guard": _CU129,
        "cc_guard_note": "highest in-range torch on a driver-compatible CUDA index that covers the device",
        "index_url": _CU129,
        "warning": False,
        "note": "highest in-range torch on a driver-compatible CUDA index that covers the device",
    },
    {
        "row": 4,
        "arch": "x86_64",
        "driver_min": (12, 8),
        "driver_max": (12, 8),
        "driver_unknown_ok": False,
        "unified": "no",
        "cc_guard": _CU128,
        "cc_guard_note": "highest in-range torch on a driver-compatible CUDA index that covers the device",
        "index_url": _CU128,
        "warning": False,
        "note": "highest in-range torch on a driver-compatible CUDA index that covers the device",
    },
    {
        "row": 5,
        "arch": "x86_64",
        "driver_min": (12, 6),
        "driver_max": (12, 7),
        "driver_unknown_ok": False,
        "unified": "no",
        "cc_guard": _CU126,
        "cc_guard_note": "highest in-range torch on a driver-compatible CUDA index that covers the device",
        "index_url": _CU126,
        "warning": False,
        "note": "highest in-range torch on a driver-compatible CUDA index that covers the device",
    },
    {
        "row": 6,
        "arch": "x86_64",
        "driver_min": None,
        "driver_max": (12, 5),
        "driver_unknown_ok": True,
        "unified": "any",
        "cc_guard": None,
        "cc_guard_note": None,
        "index_url": CPU_INDEX,
        "warning": True,
        "note": "CPU index + warning (no in-range wheels for cu118/cu121; driver CUDA < 12.6 or unknown)",
    },
    {
        "row": 7,
        "arch": "aarch64",
        "driver_min": (13, 2),
        "driver_max": None,
        "driver_unknown_ok": False,
        "unified": "no",
        "cc_guard": _CU132,
        "cc_guard_note": "highest in-range torch on a driver-compatible CUDA index that covers the device",
        "index_url": _CU132,
        "warning": False,
        "note": "highest in-range torch on a driver-compatible CUDA index that covers the device",
    },
    {
        "row": 8,
        "arch": "aarch64",
        "driver_min": (13, 0),
        "driver_max": (13, 1),
        "driver_unknown_ok": False,
        "unified": "no",
        "cc_guard": _CU130,
        "cc_guard_note": "highest in-range torch on a driver-compatible CUDA index that covers the device",
        "index_url": _CU130,
        "warning": False,
        "note": "highest in-range torch on a driver-compatible CUDA index that covers the device",
    },
    {
        "row": 9,
        "arch": "aarch64",
        "driver_min": (12, 9),
        "driver_max": (12, 9),
        "driver_unknown_ok": False,
        "unified": "no",
        "cc_guard": _CU129,
        "cc_guard_note": "highest in-range torch on a driver-compatible CUDA index that covers the device",
        "index_url": _CU129,
        "warning": False,
        "note": "highest in-range torch on a driver-compatible CUDA index that covers the device",
    },
    {
        "row": 10,
        "arch": "aarch64",
        "driver_min": (12, 8),
        "driver_max": (12, 8),
        "driver_unknown_ok": False,
        "unified": "no",
        "cc_guard": _CU128,
        "cc_guard_note": "highest in-range torch on a driver-compatible CUDA index that covers the device",
        "index_url": _CU128,
        "warning": False,
        "note": "highest in-range torch on a driver-compatible CUDA index that covers the device",
    },
    {
        "row": 11,
        "arch": "aarch64",
        "driver_min": (12, 6),
        "driver_max": (12, 7),
        "driver_unknown_ok": False,
        "unified": "no",
        "cc_guard": _CU126,
        "cc_guard_note": "highest in-range torch on a driver-compatible CUDA index that covers the device",
        "index_url": _CU126,
        "warning": False,
        "note": "highest in-range torch on a driver-compatible CUDA index that covers the device",
    },
    {
        "row": 12,
        "arch": "aarch64",
        "driver_min": None,
        "driver_max": (12, 5),
        "driver_unknown_ok": True,
        "unified": "any",
        "cc_guard": None,
        "cc_guard_note": None,
        "index_url": CPU_INDEX,
        "warning": True,
        "note": "CPU index + warning (aarch64 driver CUDA < 12.6 or unknown)",
    },
    {
        "row": 13,
        "arch": "aarch64",
        "driver_min": (13, 2),
        "driver_max": None,
        "driver_unknown_ok": False,
        "unified": "yes",
        "cc_guard": _CU132,
        "cc_guard_note": "aarch64 unified, driver >= 13.2 -> newest cu13x with numerical self-test",
        "index_url": _CU132,
        "warning": False,
        "note": "aarch64 unified, driver >= 13.2 -> newest cu13x with numerical self-test",
    },
    {
        "row": 14,
        "arch": "aarch64",
        "driver_min": (13, 0),
        "driver_max": (13, 1),
        "driver_unknown_ok": False,
        "unified": "yes",
        "cc_guard": _CU130,
        "cc_guard_note": "aarch64 unified, driver 13.0-13.1 -> cu130 with numerical self-test",
        "index_url": _CU130,
        "warning": False,
        "note": "aarch64 unified, driver 13.0-13.1 -> cu130 with numerical self-test",
    },
    {
        "row": 15,
        "arch": "aarch64",
        "driver_min": None,
        "driver_max": None,
        "driver_unknown_ok": True,
        "unified": "yes",
        "cc_guard": None,
        "cc_guard_note": None,
        "index_url": CPU_INDEX,
        "warning": True,
        "note": "aarch64 unified, driver < 13.0 -> CPU + JetPack 6 note (Python 3.12 required; manual --index-url)",
    },
    {
        "row": 16,
        "arch": "other",
        "driver_min": None,
        "driver_max": None,
        "driver_unknown_ok": True,
        "unified": "any",
        "cc_guard": None,
        "cc_guard_note": None,
        "index_url": CPU_INDEX,
        "warning": True,
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
    if os.environ.get("KAINE_WHEEL_PROBE_NVML") == "0":
        return None, "disabled by KAINE_WHEEL_PROBE_NVML=0"
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
    except Exception as exc:
        arch, arch_note = "other", f"arch probe failed: {_shorten(exc)}"
    notes["arch"] = arch_note
    try:
        driver_cuda, driver_note = _probe_driver_cuda()
    except Exception as exc:
        driver_cuda, driver_note = None, f"driver CUDA probe failed: {_shorten(exc)}"
    notes["driver_cuda"] = driver_note
    try:
        compute_caps, caps_note = _probe_compute_caps(torch=torch)
    except Exception as exc:
        compute_caps, caps_note = (), (
            f"compute-capability probe failed: {_shorten(exc)}"
        )
    notes["compute_caps"] = caps_note
    try:
        memory_state, memory_note = _probe_memory_state(torch=torch)
    except Exception as exc:
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


def _companion(index_name: str | None, arch: str, version: str | None, key: str):
    """Look up a companion version (torchvision / torchaudio) or None."""
    if index_name is None or version is None:
        return None
    return COMPANIONS.get(index_name, {}).get(arch, {}).get(version, {}).get(key)


def _oldest_packaged_cuda_version() -> tuple[int, int]:
    versions = [
        _cuda_version_from_short(n)
        for n in PUBLISHED
        if n.startswith("cu")
    ]
    versions = [v for v in versions if v is not None]
    return min(versions) if versions else (0, 0)


def _cuda_selected_reason(probes: Probes, cu_version: tuple[int, int], torch_version: str, coverages) -> str:
    if not coverages:
        coverage_desc = (
            "no per-device compute capability probed, so the filter is vacuously "
            "satisfied"
        )
    else:
        exact_count = sum(1 for kind, _payload in coverages if kind == "exact")
        same_major_count = sum(1 for kind, _payload in coverages if kind == "same_major")
        ptx_versions = sorted({
            payload
            for kind, payload in coverages
            if kind == "ptx" and payload is not None
        })
        if exact_count == len(coverages):
            coverage_desc = "exact SASS coverage for every probed device"
        elif same_major_count == len(coverages):
            names = ", ".join(payload for _kind, payload in coverages if payload)
            coverage_desc = f"same-major SASS coverage for every probed device via {names}"
        elif exact_count == 0 and same_major_count == 0:
            names = ", ".join(f"compute_{v[0]}{v[1]}" for v in ptx_versions)
            coverage_desc = f"JIT-from-PTX coverage for every probed device via {names}"
        else:
            parts = []
            if exact_count:
                parts.append(f"{exact_count} exact-SASS device(s)")
            if same_major_count:
                names = ", ".join(payload for kind, payload in coverages if kind == "same_major" and payload)
                parts.append(f"same-major SASS via {names}")
            if ptx_versions:
                names = ", ".join(f"compute_{v[0]}{v[1]}" for v in ptx_versions)
                parts.append(f"PTX via {names}")
            coverage_desc = "mixed coverage across probed devices: " + "; ".join(parts)
    driver_str = (
        _fmt_version(probes.driver_cuda)
        if probes.driver_cuda is not None
        else "unknown"
    )
    return (
        f"highest in-range torch {torch_version} on newest driver-compatible "
        f"index {_fmt_cu(cu_version)} <= driver CUDA {driver_str} passing the "
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


def _oldest_cuda_with_in_range_torch(arch: str, spec_list) -> tuple[int, int] | None:
    versions = [
        _cuda_version_from_short(name)
        for name in PUBLISHED
        if name.startswith("cu") and _newest_arch_version(name, arch, spec_list) is not None
    ]
    versions = [v for v in versions if v is not None]
    return min(versions) if versions else None


def _exhaustion_warning(probes: Probes, terminal: str, spec_str: str) -> str:
    driver_str = (
        _fmt_version(probes.driver_cuda)
        if probes.driver_cuda is not None
        else "unknown"
    )
    driver_too_old = (
        "predates the oldest packaged CUDA index" in terminal
        or "no packaged CUDA index provides an in-range torch" in terminal
    )
    if driver_too_old:
        spec_list = _parse_spec(spec_str)
        oldest_cu = _oldest_cuda_with_in_range_torch(probes.arch, spec_list)
        if oldest_cu is not None:
            remediation = (
                f"remediation: no CUDA wheel index carrying a torch in the tested range {spec_str} "
                f"supports driver CUDA {driver_str}; upgrade the NVIDIA driver to one supporting "
                f"CUDA {_fmt_version(oldest_cu)} or use the CPU wheels selected"
            )
        else:
            remediation = (
                f"remediation: no CUDA wheel index carrying a torch in the tested range {spec_str} "
                f"supports driver CUDA {driver_str}; use the CPU wheels selected"
            )
    elif probes.memory_state == "unified" and probes.arch == "aarch64":
        remediation = (
            "remediation: JetPack 6 hosts take the CPU route; pass --index-url "
            "pointing at the JetPack-provided CUDA wheel index "
            "(Python 3.12 required; manual --index-url)"
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
        f"memory classification={probes.memory_state}, "
        f"torch_spec={spec_str}; "
        f"terminal reason: {terminal}; {remediation}"
    )


def _ladder(probes: Probes, spec_str: str, spec_list, need_torchaudio: bool = False) -> dict:
    """The version-aware binding fallback ladder.  Pure.

    Candidates are every (index CUDA version, index short name, torch version)
    triple such that the index CUDA version is <= the probed driver CUDA, the
    torch version is in range, and the version is published for the host arch.
    Each candidate is checked against the architecture list recorded for that
    exact torch version; survivors are ranked by highest torch version, then
    newest CUDA index.
    """
    rejected: list[dict[str, str]] = []
    warnings: list[str] = []

    if spec_str == ">=":
        warnings.append(
            "torch requirement not found in pyproject.toml; using unrestricted range >=0"
        )

    if probes.memory_state == "unified" and probes.arch != "aarch64":
        warnings.append(
            f"unified-memory evidence ignored for CUDA on {probes.arch}: "
            "NVIDIA unified-memory GPUs are aarch64-only (the evidence likely comes from a "
            "non-NVIDIA integrated GPU)"
        )
        probes = replace(probes, memory_state="discrete")

    driver = probes.driver_cuda

    # Driver-eligible CUDA indices: every cuX.Y index with X.Y <= driver CUDA.
    driver_eligible_indices: list[tuple[tuple[int, int], str]] = []
    if driver is not None:
        for name in PUBLISHED:
            if not name.startswith("cu"):
                continue
            cu_version = _cuda_version_from_short(name)
            if cu_version is not None and cu_version <= driver:
                driver_eligible_indices.append((cu_version, name))
    driver_eligible_indices.sort(
        key=lambda item: (-item[0][0], -item[0][1], item[1])
    )

    # All (index, torch_version) candidates that pass the driver, arch and range filters.
    all_candidates: list[tuple[tuple[int, int], str, str]] = []
    for cu_version, name in driver_eligible_indices:
        for version in PUBLISHED.get(name, {}).get(probes.arch, ()):
            if _in_range(version, spec_list):
                all_candidates.append((cu_version, name, version))

    # Rank by highest torch version, then newest CUDA index.
    all_candidates.sort(
        key=lambda item: (
            -_vtuple(item[2])[0],
            -_vtuple(item[2])[1],
            -_vtuple(item[2])[2],
            -item[0][0],
            -item[0][1],
            item[1],
        )
    )

    newest_arch_valid = all_candidates[0] if all_candidates else None

    any_coverage = False
    any_unified = False
    any_torchaudio = False
    survivors: list[tuple[tuple[int, int], str, str, tuple[str, ...], list]] = []

    for cu_version, name, version in all_candidates:
        cu_data = CUDA_ARCH.get(version, {}).get(name, {})
        arch_list_str = cu_data.get(probes.arch)
        if arch_list_str is None:
            rejected.append({
                "index": _index_url(name),
                "reason": (
                    f"torch {version}: no recorded architecture list for {name} {probes.arch}"
                ),
            })
            continue

        entries = _arch_list_to_entries(arch_list_str)
        coverages = []
        uncovered = None
        for device_idx, cc in enumerate(probes.compute_caps):
            cov = _device_coverage(cc, entries)
            coverages.append(cov)
            if cov is None:
                uncovered = (device_idx, cc)
                break
        if uncovered is not None:
            device_idx, (major, minor) = uncovered
            rejected.append({
                "index": _index_url(name),
                "reason": (
                    f"torch {version}: compute capability {major}.{minor} of device {device_idx} "
                    f"not covered by the {probes.arch} build list for {name}"
                ),
            })
            continue
        any_coverage = True

        if probes.memory_state == "unified":
            if not (probes.arch == "aarch64" and cu_version >= (13, 0)):
                rejected.append({
                    "index": _index_url(name),
                    "reason": (
                        f"torch {version}: unified-memory host only supported on aarch64 with "
                        "CUDA 13.0+ (JetPack 6 hosts take the CPU route)"
                    ),
                })
                continue
        any_unified = True

        if need_torchaudio:
            ta = _companion(name, probes.arch, version, "torchaudio")
            if ta is None:
                rejected.append({
                    "index": _index_url(name),
                    "reason": f"torch {version}: no torchaudio published on this index",
                })
                continue
        any_torchaudio = True

        survivors.append((cu_version, name, version, entries, coverages))

    if survivors:
        cu_version, name, version, _entries, coverages = survivors[0]
        url = _index_url(name)
        if newest_arch_valid is not None:
            nv_cu, nv_name, nv_version = newest_arch_valid
            if (_vtuple(version), cu_version) < (_vtuple(nv_version), nv_cu):
                warnings.append(
                    f"downgrade: selected {url} ({_fmt_cu(cu_version)}) torch {version}; "
                    f"the newest candidate passing the driver and architecture filters was "
                    f"{_index_url(nv_name)} ({_fmt_cu(nv_cu)}) torch {nv_version}, "
                    f"rejected by a later filter"
                )
        reason = _cuda_selected_reason(probes, cu_version, version, coverages)
        row = _match_table_row(probes, url)
        if row is not None:
            reason = f"{reason}; matches decision table row {row['row']}"

        selftest = False
        selftest_warning = None
        if probes.arch == "aarch64" and cu_version >= (13, 0):
            if probes.memory_state == "unified":
                selftest = True
                selftest_warning = (
                    "unified-memory Jetson-class GPU: upstream wheels run compatible (not native) "
                    "kernels on this device and some models have produced NaNs; the installer "
                    "runs a GPU-vs-CPU numerical self-test and falls back to CPU wheels if it fails"
                )
            elif probes.memory_state == "unknown":
                selftest = True
                selftest_warning = (
                    "memory classification is unknown on this aarch64 CUDA host; the installer "
                    "runs the GPU-vs-CPU numerical self-test as a precaution"
                )
        if selftest_warning is not None:
            warnings.append(selftest_warning)

        tv = version
        ta = _companion(name, probes.arch, version, "torchaudio")
        result = {
            "variant": "cuda",
            "index_url": url,
            "selected_reason": reason,
            "rejected": rejected,
            "warnings": warnings,
            "torch_version": version,
            "torchvision_version": _companion(name, probes.arch, version, "torchvision"),
            "torchaudio_version": ta,
            "torch_spec": spec_str,
            "selftest_required": selftest,
        }
        if need_torchaudio and ta is not None and _mm_pair(ta) != _mm_pair(tv):
            warnings.append(
                f"torchaudio {ta} is paired with torch {tv} by release timing only; "
                "no published wheel metadata asserts this pairing"
            )
        return result

    # Ladder step 6 -- exhaustion: CPU index with a detailed warning.
    cpu_version = _newest_arch_version("cpu", probes.arch, spec_list)
    cpu_tv = _companion("cpu", probes.arch, cpu_version, "torchvision")
    cpu_ta = _companion("cpu", probes.arch, cpu_version, "torchaudio")
    if cpu_version is None:
        warnings.append(
            f"CPU fallback: no in-range torch published for {probes.arch} on the CPU index in range {spec_str}"
        )
    if need_torchaudio and cpu_ta is None and cpu_version is not None:
        rejected.append({
            "index": CPU_INDEX,
            "reason": f"no torchaudio published for torch {cpu_version} on this index",
        })
        warnings.append(
            f"CPU fallback rejected: no torchaudio published for torch {cpu_version} on the CPU index"
        )
    if need_torchaudio and cpu_ta is not None and cpu_version is not None and _mm_pair(cpu_ta) != _mm_pair(cpu_version):
        warnings.append(
            f"torchaudio {cpu_ta} is paired with torch {cpu_version} by release timing only; "
            "no published wheel metadata asserts this pairing"
        )
    if driver is None:
        terminal = (
            "driver CUDA version could not be determined, so no candidate index "
            "satisfies 'index CUDA version <= driver CUDA'"
        )
    elif not driver_eligible_indices:
        terminal = (
            f"driver CUDA {_fmt_version(driver)} predates the oldest packaged CUDA index "
            f"({_fmt_cu(_oldest_packaged_cuda_version())})"
        )
    elif not all_candidates:
        terminal = (
            f"no packaged CUDA index provides an in-range torch for {probes.arch} in range {spec_str}"
        )
    elif not any_coverage:
        terminal = (
            "every architecture-compatible candidate was rejected by the "
            "compute-capability filter"
        )
    elif probes.memory_state == "unified" and not any_unified:
        terminal = (
            "unified-memory host not supported on this driver/architecture "
            "(aarch64 with CUDA 13.0+ required; JetPack 6 hosts take the CPU route)"
        )
    elif need_torchaudio and not any_torchaudio:
        terminal = (
            "every architecture-compatible candidate was rejected by the need-torchaudio filter"
        )
    else:
        terminal = "candidate ladder exhausted"
    warnings.append(_exhaustion_warning(probes, terminal, spec_str))
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
        "torch_version": cpu_version,
        "torchvision_version": cpu_tv,
        "torchaudio_version": cpu_ta,
        "torch_spec": spec_str,
        "selftest_required": False,
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
    """Defensive normalization of arbitrary probe-like input; never raises."""
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


def _apply_operator_override(result: dict, override, probes: Probes, spec_str: str, spec_list, need_torchaudio: bool = False):
    """Apply an authoritative operator --index-url override to a ladder result."""
    out = dict(result)
    url = str(override).rstrip("/")
    short = _index_short_name(url)
    if short == "cpu" or url == CPU_INDEX:
        out["variant"] = "cpu"
    else:
        out["variant"] = "cuda"
    out["index_url"] = url
    ladder_url = result.get("index_url")
    ladder_variant = result.get("variant")
    out["selected_reason"] = (
        f"operator-provided --index-url {url}; ladder would have chosen "
        f"{ladder_variant} index {ladder_url}"
    )

    warnings = list(result.get("warnings", []))
    cleaned = [
        w for w in warnings
        if isinstance(w, str) and "was not applied" not in w and "no CUDA index" not in w
    ]
    if ladder_variant != "cuda":
        cleaned.append(
            "ladder found no CUDA index; using operator-provided --index-url override instead"
        )

    torch_version = None
    if short is not None:
        torch_version = _newest_arch_version(short, probes.arch, spec_list)
        if torch_version is None:
            cleaned.append(
                f"operator --index-url {url}: no in-range torch for {probes.arch} in range {spec_str}"
            )
    else:
        cleaned.append(
            f"operator --index-url {url}: index short name is not in the recorded published list; "
            "exact torch version could not be checked"
        )

    out["torch_version"] = torch_version
    out["torchvision_version"] = _companion(short, probes.arch, torch_version, "torchvision")
    out["torchaudio_version"] = _companion(short, probes.arch, torch_version, "torchaudio")

    out["torchaudio_unavailable"] = False
    if need_torchaudio:
        if out["torchaudio_version"] is None and torch_version is not None:
            out["torchaudio_unavailable"] = True
            cleaned.append(
                f"operator --index-url {url} publishes no torchaudio for torch {torch_version}; "
                "the --research install needs torchaudio"
            )
        else:
            out["torchaudio_unavailable"] = False

    tv = out["torch_version"]
    ta = out["torchaudio_version"]
    if need_torchaudio and ta is not None and tv is not None and _mm_pair(ta) != _mm_pair(tv):
        cleaned.append(
            f"torchaudio {ta} is paired with torch {tv} by release timing only; "
            "no published wheel metadata asserts this pairing"
        )

    selftest = False
    selftest_warning = None
    if probes.arch == "aarch64" and short is not None and short.startswith("cu"):
        cv = _cuda_version_from_short(short)
        if cv is not None and cv >= (13, 0):
            if probes.memory_state == "unified":
                selftest = True
                selftest_warning = (
                    "unified-memory Jetson-class GPU: upstream wheels run compatible (not native) "
                    "kernels on this device and some models have produced NaNs; the installer "
                    "runs a GPU-vs-CPU numerical self-test and falls back to CPU wheels if it fails"
                )
            elif probes.memory_state == "unknown":
                selftest = True
                selftest_warning = (
                    "memory classification is unknown on this aarch64 CUDA host; the installer "
                    "runs the GPU-vs-CPU numerical self-test as a precaution"
                )
    out["selftest_required"] = selftest
    if selftest_warning is not None:
        cleaned.append(selftest_warning)

    out["warnings"] = cleaned
    return out


def _resolve_index_ladder(probes, *, override=None, spec=None, need_torchaudio: bool = False):
    """Pure decision: resolve the wheel index from ``probes`` alone.

    Returns the full result dict including torch_version / companion versions.
    Performs no I/O (beyond reading pyproject.toml once when spec is not given)
    and never raises.
    """
    try:
        normalized = _as_probes(probes)
        probes_dict = normalized.to_dict()
        spec_str = spec if spec is not None else project_torch_spec()
        spec_list = _parse_spec(spec_str)
        base = _ladder(normalized, spec_str, spec_list, need_torchaudio=need_torchaudio)
        result = {
            "variant": base["variant"],
            "index_url": base["index_url"],
            "probes": probes_dict,
            "selected_reason": base["selected_reason"],
            "rejected": base["rejected"],
            "warnings": base["warnings"],
            "torch_version": base["torch_version"],
            "torchvision_version": base["torchvision_version"],
            "torchaudio_version": base["torchaudio_version"],
            "torch_spec": base["torch_spec"],
            "selftest_required": base["selftest_required"],
        }
        if override is not None:
            result = _apply_operator_override(
                result, override, normalized, spec_str, spec_list, need_torchaudio=need_torchaudio
            )
        return result
    except Exception as exc:
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
            "torch_version": None,
            "torchvision_version": None,
            "torchaudio_version": None,
            "torch_spec": ">=",
            "selftest_required": False,
        }


def resolve_index(probes, override=None, need_torchaudio: bool = False, **kwargs):
    """Resolve the pip wheel index for *probes*.

    With an operator ``override`` (--index-url) the supplied URL is authoritative.
    With ``need_torchaudio`` a candidate is accepted only when PyTorch publishes a
    matching torchaudio wheel for the resolved torch version.
    Pure and never raises.
    """
    return _resolve_index_ladder(probes, override=override, need_torchaudio=need_torchaudio, **kwargs)


# ---------------------------------------------------------------------------
# ROCm resolution
# ---------------------------------------------------------------------------

def _normalize_gfx(value):
    if value is None:
        return ()
    if isinstance(value, str):
        if not value.strip():
            return ()
        return tuple(x.strip() for x in value.split(",") if x.strip())
    try:
        return tuple(str(x).strip() for x in value if str(x).strip())
    except Exception:
        return ()


def _normalize_gfx_targets(value):
    """Normalize probed GFX targets: lower-case, drop gfx000/*-generic, dedup."""
    raw = _normalize_gfx(value)
    seen: list[str] = []
    for token in raw:
        token = token.lower().strip()
        if not token or token == "gfx000" or token.endswith("-generic"):
            continue
        if token not in seen:
            seen.append(token)
    return tuple(seen)


def _coerce_rocm_version(value):
    if value is None:
        return None
    if isinstance(value, str):
        match = re.match(r"^\s*(\d+)\.(\d+)", value.strip())
        if match:
            return (int(match.group(1)), int(match.group(2)))
    try:
        t = tuple(value)
        if len(t) == 2:
            return (int(t[0]), int(t[1]))
    except Exception:
        pass
    return None


def resolve_rocm(rocm_version, gfx_targets, arch, spec=None, need_torchaudio: bool = False):
    """Select a ROCm wheel index for the host.

    Returns a dict with index_url, torch_version, torchvision_version,
    torchaudio_version, selected_reason and warnings.

    Targets are normalized (lower-case, ``gfx000`` and ``*-generic`` dropped,
    de-duplicated).  When GFX targets are supplied, an index is acceptable only
    if it covers at least one requested target.  The selected index is the
    acceptable one with the highest in-range torch version, tie-breaking by
    newest ROCm version.
    """
    if spec is None:
        spec = project_torch_spec()
    spec_list = _parse_spec(spec)
    host_ver = _coerce_rocm_version(rocm_version)
    raw_gfx = _normalize_gfx(gfx_targets)
    gfx = _normalize_gfx_targets(gfx_targets)
    warnings: list[str] = []

    if not raw_gfx:
        warnings.append("no GFX targets supplied; ROCm architecture coverage check skipped")

    if host_ver is None:
        return {
            "index_url": None,
            "torch_version": None,
            "torchvision_version": None,
            "torchaudio_version": None,
            "selected_reason": "host ROCm version unknown; no ROCm index selected",
            "warnings": warnings + [
                f"host ROCm version could not be determined; cannot select a ROCm index for range {spec}"
            ],
        }

    # Host-eligible indices with an in-range torch that are recorded for this arch.
    host_eligible = []
    for name in PUBLISHED:
        ver = _rocm_version_from_short(name)
        if ver is None or ver > host_ver:
            continue
        chosen = _newest_arch_version(name, arch, spec_list)
        if chosen is None:
            continue
        rocm_info = ROCM_ARCH.get(chosen)
        if rocm_info is None or name not in rocm_info.get("indexes", ()):
            continue
        host_eligible.append((ver, name, chosen, rocm_info))

    # Oldest index that would work ignoring the host-version ceiling (remediation).
    qualifying_all = []
    for name in PUBLISHED:
        ver = _rocm_version_from_short(name)
        if ver is None:
            continue
        chosen = _newest_arch_version(name, arch, spec_list)
        if chosen is None:
            continue
        rocm_info = ROCM_ARCH.get(chosen)
        if rocm_info is None or name not in rocm_info.get("indexes", ()):
            continue
        if gfx and not any(g in rocm_info.get("gfx", ()) for g in gfx):
            continue
        qualifying_all.append((ver, name))
    qualifying_all.sort()
    oldest = qualifying_all[0] if qualifying_all else None

    if gfx:
        # An index is acceptable only when it covers at least one probed target.
        host_eligible = [
            item
            for item in host_eligible
            if any(g in item[3].get("gfx", ()) for g in gfx)
        ]
        if not host_eligible:
            host_str = _fmt_version(host_ver)
            for g in sorted(gfx):
                warnings.append(
                    f"GFX target {g} is not covered by any host-eligible ROCm index; "
                    "consider setting HIP_VISIBLE_DEVICES to restrict PyTorch to a covered GPU"
                )
            if oldest is not None:
                warn = (
                    f"no ROCm index <= host ROCm {host_str}, range {spec}, "
                    f"arch {arch} covers any GFX target in [{','.join(gfx)}]; "
                    f"the oldest ROCm index that would cover one is {_index_url(oldest[1])} "
                    f"({_fmt_version(oldest[0])})"
                )
            else:
                warn = (
                    f"no ROCm index <= host ROCm {host_str}, range {spec}, "
                    f"arch {arch} covers any GFX target in [{','.join(gfx)}]; "
                    "no recorded ROCm index would cover any of these targets"
                )
            return {
                "index_url": None,
                "torch_version": None,
                "torchvision_version": None,
                "torchaudio_version": None,
                "selected_reason": f"no ROCm index selected for host ROCm {_fmt_version(host_ver)}",
                "warnings": warnings + [warn],
            }

    if not host_eligible:
        host_str = _fmt_version(host_ver) if host_ver else "unknown"
        if oldest is not None:
            warn = (
                f"no ROCm index compatible with host ROCm {host_str}, range {spec}, "
                f"arch {arch} was found; "
                f"the oldest ROCm index that would work is {_index_url(oldest[1])} "
                f"({_fmt_version(oldest[0])})"
            )
        else:
            warn = (
                f"no ROCm index compatible with host ROCm {host_str}, range {spec}, "
                f"arch {arch} was found; "
                "no recorded ROCm index would work"
            )
        return {
            "index_url": None,
            "torch_version": None,
            "torchvision_version": None,
            "torchaudio_version": None,
            "selected_reason": f"no ROCm index selected for host ROCm {host_str}",
            "warnings": warnings + [warn],
        }

    # Select highest torch version, then newest ROCm.
    host_eligible.sort(
        key=lambda item: (
            -_vtuple(item[2])[0],
            -_vtuple(item[2])[1],
            -_vtuple(item[2])[2],
            -item[0][0],
            -item[0][1],
            item[1],
        )
    )
    ver, name, chosen, rocm_info = host_eligible[0]
    url = _index_url(name)
    index_gfx = set(rocm_info.get("gfx", ()))
    covered = [g for g in gfx if g in index_gfx]
    uncovered = [g for g in gfx if g not in index_gfx]
    for g in uncovered:
        warnings.append(
            f"GFX target {g} is not covered by {name}; "
            "consider setting HIP_VISIBLE_DEVICES to restrict PyTorch to the covered GPU(s)"
        )
    selected_reason = (
        f"newest ROCm index {name} <= host ROCm {_fmt_version(host_ver)} with "
        f"torch {chosen} in range"
    )
    if gfx:
        selected_reason += f" and covers GFX target(s) {','.join(covered)}"
    else:
        selected_reason += " (GFX check skipped)"

    ta = _companion(name, arch, chosen, "torchaudio")
    if need_torchaudio and ta is not None and _mm_pair(ta) != _mm_pair(chosen):
        warnings.append(
            f"torchaudio {ta} is paired with torch {chosen} by release timing only; "
            "no published wheel metadata asserts this pairing"
        )

    return {
        "index_url": url,
        "torch_version": chosen,
        "torchvision_version": _companion(name, arch, chosen, "torchvision"),
        "torchaudio_version": ta,
        "selected_reason": selected_reason,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Index verification
# ---------------------------------------------------------------------------

_PLATFORM_ARCH_TAGS = {
    "manylinux_2_28_x86_64": "x86_64",
    "manylinux_2_17_x86_64": "x86_64",
    "manylinux1_x86_64": "x86_64",
    "linux_x86_64": "x86_64",
    "win_amd64": "x86_64",
    "manylinux_2_28_aarch64": "aarch64",
    "manylinux_2_17_aarch64": "aarch64",
    "linux_aarch64": "aarch64",
}
_WHEEL_HREF_RE = re.compile(r'<a[^>]*href=["\']([^"\']+)["\']')
_WHEEL_FILENAME_RE = re.compile(
    r"^torch-([0-9]+(?:\.[0-9]+)*)"
    r"(?:\+[A-Za-z0-9.]+)?"
    r"-cp312-cp312-"
    r"([A-Za-z0-9_.]+)"
    r"\.whl$"
)
_FINAL_RELEASE_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*$")


def _parse_simple_index(html: str) -> dict[str, set[str]]:
    """Parse a PyTorch simple-index HTML page into {arch: {versions}}.

    URL-decodes the href, strips any fragment, matches only cp312 torch
    wheels that are final releases (no dev/rc/a/b/post suffixes), and maps
    the platform tag to x86_64/aarch64.
    """
    out: dict[str, set[str]] = {"x86_64": set(), "aarch64": set()}
    for match in _WHEEL_HREF_RE.finditer(html):
        href = match.group(1)
        href = unquote(href)
        href = href.split("#")[0]
        fname = href.split("/")[-1]
        fm = _WHEEL_FILENAME_RE.match(fname)
        if not fm:
            continue
        version = fm.group(1)
        if not _FINAL_RELEASE_RE.match(version):
            continue
        platform_tag = fm.group(2)
        arch = None
        for tag, mapped in _PLATFORM_ARCH_TAGS.items():
            if tag in platform_tag:
                arch = mapped
                break
        if arch is None:
            continue
        out[arch].add(version)
    return out


def verify_indexes(spec=None):
    """Diff in-range cp312 torch versions per (index, arch) against live indexes."""
    if spec is None:
        spec = project_torch_spec()
    spec_list = _parse_spec(spec)
    report = {}
    for name in PUBLISHED:
        url = f"{_BASE_URL}{name}/torch/"
        try:
            with urllib.request.urlopen(url, timeout=15.0) as response:
                html = response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            for arch in ("x86_64", "aarch64"):
                report[f"{name}/{arch}"] = {
                    "error": str(exc),
                    "expected": [],
                    "observed": [],
                    "added": [],
                    "missing": [],
                }
            continue
        observed = _parse_simple_index(html)
        for arch in ("x86_64", "aarch64"):
            expected = {
                v
                for v in PUBLISHED[name].get(arch, ())
                if _in_range(v, spec_list)
            }
            obs = observed.get(arch, set())
            report[f"{name}/{arch}"] = {
                "error": None,
                "expected": sorted(expected),
                "observed": sorted(obs),
                "added": sorted(obs - expected),
                "missing": sorted(expected - obs),
            }
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_USAGE = (
    "usage: python -m kaine.wheel_index [options]\n"
    "\n"
    "Resolve the CUDA wheel index for this host and print the decision as JSON\n"
    "(exit code 0).\n"
    "\n"
    "Options:\n"
    "  --index-url URL         operator override for CUDA wheel index\n"
    "  --override URL          synonym for --index-url\n"
    "  --need-torchaudio       require a matching torchaudio wheel on the selected index\n"
    "  --rocm-version X.Y      print ROCm resolution JSON instead of CUDA\n"
    "  --gfx gfxA[,gfxB]       GFX targets for --rocm-version\n"
    "  --verify-indexes        diff recorded indexes against download.pytorch.org\n"
    "  -h, --help              show this help\n"
)


def _normalize_argv(argv):
    """Accept the legacy --override synonym for --index-url."""
    if argv is None:
        return None
    out = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--override":
            out.append("--index-url")
            i += 1
            if i < len(argv):
                out.append(argv[i])
        elif tok.startswith("--override="):
            out.append("--index-url")
            out.append(tok.split("=", 1)[1])
        else:
            out.append(tok)
        i += 1
    return out


def main(argv=None) -> int:
    """CLI: print the resolution as JSON; always exit 0."""
    if argv is None:
        argv = list(sys.argv[1:])
    argv = _normalize_argv(argv)

    override = None
    need_torchaudio = False
    rocm_version = None
    gfx = None
    verify = False
    ignored: list[str] = []
    args = [str(arg) for arg in argv] if argv is not None else []
    idx = 0
    while idx < len(args):
        arg = args[idx]
        if arg == "--index-url":
            idx += 1
            if idx < len(args):
                override = args[idx]
        elif arg.startswith("--index-url="):
            override = arg.split("=", 1)[1]
        elif arg == "--need-torchaudio":
            need_torchaudio = True
        elif arg == "--rocm-version":
            idx += 1
            if idx < len(args):
                rocm_version = args[idx]
        elif arg.startswith("--rocm-version="):
            rocm_version = arg.split("=", 1)[1]
        elif arg == "--gfx":
            idx += 1
            if idx < len(args):
                gfx = args[idx]
        elif arg.startswith("--gfx="):
            gfx = arg.split("=", 1)[1]
        elif arg == "--verify-indexes":
            verify = True
        elif arg in ("-h", "--help"):
            print(_USAGE)
            return 0
        else:
            ignored.append(arg)
        idx += 1

    if verify:
        result = verify_indexes()
        print(json.dumps(result, sort_keys=True, default=str))
        return 0

    if rocm_version is not None:
        arch = _normalize_arch(platform.machine())
        result = resolve_rocm(rocm_version, gfx, arch, need_torchaudio=need_torchaudio)
        if ignored:
            result.setdefault("warnings", []).append(
                "unrecognized CLI arguments ignored: " + " ".join(ignored)
            )
        print(json.dumps(result, sort_keys=True, default=str))
        return 0

    try:
        probes = collect_probes()
        result = resolve_index(probes, override=override, need_torchaudio=need_torchaudio)
    except Exception as exc:
        result = {
            "variant": "cpu",
            "index_url": CPU_INDEX,
            "probes": {},
            "selected_reason": f"probe or resolution failure: {_shorten(exc)}",
            "rejected": [],
            "warnings": [
                f"wheel-index probing failed; using CPU index: {_shorten(exc)}"
            ],
            "torch_version": None,
            "torchvision_version": None,
            "torchaudio_version": None,
            "torch_spec": ">=",
            "selftest_required": False,
        }

    if ignored:
        result["warnings"].append(
            "unrecognized CLI arguments ignored: " + " ".join(ignored)
        )
    print(json.dumps(result, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
