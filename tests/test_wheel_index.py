# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Tests for ``kaine/wheel_index.py`` — host-aware CUDA wheel-index resolution.

Two families of tests live here.

* ``resolve_index`` is pure, so every decision-table row and fallback-ladder
  rule is pinned with hand-built :class:`Probes`: no hardware, no network, no
  subprocess.  The suite behaves identically on the x86_64 CI runners and on
  the aarch64 Jetson host.
* ``collect_probes`` is exercised only through injection: the nvidia-smi
  subprocess layer, ``platform.machine`` and every NVML entry point are
  monkeypatched, so no assertion depends on the real machine.

The one introspective test (JIT-from-PTX) reads ``INDEX_ARCH_MAP`` — the
authoritative arch→sm constant — to locate a PTX-only coverage scenario, and
skips honestly if the map exposes none.

Each test docstring names the invariant it pins and the cost its violation
would cause in ``scripts/install.sh``.
"""

import ctypes
import ctypes.util
import io
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys

import pytest

from kaine.wheel_index import (
    CPU_INDEX,
    DECISION_TABLE,
    INDEX_ARCH_MAP,
    Probes,
    collect_probes,
    resolve_index,
)

try:  # section-1 modules; imported only so hermetic tests can re-bind helpers
    import kaine.hardware  # noqa: F401
    import kaine.hostmem  # noqa: F401

    _ = kaine.hardware, kaine.hostmem  # referenced to satisfy CodeQL py/unused-import
except Exception:  # pragma: no cover - optional hedges, never a hard dependency
    pass  # optional modules; loaded so hermetic tests can monkeypatch.setattr helpers


# Binding index URLs from decision-table rows 1-5 / 7-9, and the CPU fallback.
CU130 = "https://download.pytorch.org/whl/cu130"
CU128 = "https://download.pytorch.org/whl/cu128"
CU126 = "https://download.pytorch.org/whl/cu126"
CU121 = "https://download.pytorch.org/whl/cu121"
CU118 = "https://download.pytorch.org/whl/cu118"

_KAINE_MODULES = ("kaine.wheel_index", "kaine.hostmem", "kaine.hardware")


# ---------------------------------------------------------------------------
# Probe construction (pure; never touches hardware)
# ---------------------------------------------------------------------------


def _probes(arch="x86_64", driver=(12, 8), caps=((9, 0),), memory="discrete", notes=()):
    """Build a Probes instance with the contract's field names and types."""
    return Probes(
        arch=arch,
        driver_cuda=driver,
        compute_caps=caps,
        memory_state=memory,
        notes=list(notes),
    )


def _probe_snapshot(probes):
    """Value snapshot of a Probes instance, independent of its internals."""
    return {
        "arch": probes.arch,
        "driver_cuda": (None if probes.driver_cuda is None else tuple(probes.driver_cuda)),
        "compute_caps": tuple(tuple(cap) for cap in probes.compute_caps),
        "memory_state": probes.memory_state,
        "notes": list(getattr(probes, "notes", ()) or ()),
    }


# ---------------------------------------------------------------------------
# INDEX_ARCH_MAP introspection for the JIT-from-PTX rule (test 8)
# ---------------------------------------------------------------------------

_SM_RE = re.compile(r"^sm_(\d{2,3})(\+ptx)?$", re.IGNORECASE)
_COMPUTE_RE = re.compile(r"^compute_(\d{2,3})(\+ptx)?$", re.IGNORECASE)
_CU_RE = re.compile(r"cu_?(\d{2,3})", re.IGNORECASE)
_TABLE_INDEX_TOKENS = ("cu130", "cu128", "cu126", "cu121", "cu118")


def _sm_level(digits):
    """sm_90 -> (9, 0); sm_100 -> (10, 0); sm_87 -> (8, 7)."""
    if len(digits) <= 2:
        return (int(digits[0]), int(digits[1]))
    return (int(digits[0]), int(digits[1:]))


def _cu_version(digits):
    """cu130 -> (13, 0); cu118 -> (11, 8); cu90 -> (9, 0)."""
    if len(digits) >= 3:
        return (int(digits[:2]), int(digits[2:]))
    return (int(digits[0]), int(digits[1]))


def _parse_sm_entries(tokens):
    """Split map entries into exact-SASS levels and PTX levels.

    ``sm_ZW``      -> exact (Z, W)
    ``sm_ZW+PTX``  -> exact (Z, W) plus a PTX entry at (Z, W)
    ``compute_ZW`` -> PTX entry at (Z, W)
    """
    exact, ptx = set(), set()
    for token in tokens:
        if isinstance(token, int) and not isinstance(token, bool):
            if 30 <= token <= 199:
                exact.add(_sm_level(str(token)))
            continue
        if not isinstance(token, str):
            continue
        token = token.strip()
        if not token:
            continue
        match = _SM_RE.match(token)
        if match:
            level = _sm_level(match.group(1))
            exact.add(level)
            if match.group(2):
                ptx.add(level)
            continue
        match = _COMPUTE_RE.match(token)
        if match:
            ptx.add(_sm_level(match.group(1)))
    return exact, ptx


def _walk_arch_map(node, arch, index, out):
    """Collect (arch, index-name, exact-levels, ptx-levels) from any nesting."""
    if isinstance(node, dict):
        for key, value in node.items():
            next_arch, next_index = arch, index
            if isinstance(key, str):
                if key in ("x86_64", "aarch64"):
                    next_arch = key
                elif _CU_RE.search(key):
                    next_index = key
            _walk_arch_map(value, next_arch, next_index, out)
    elif isinstance(node, (list, tuple, set, frozenset)):
        exact, ptx = _parse_sm_entries(node)
        if arch is not None and index is not None and (exact or ptx):
            out.append((arch, index, frozenset(exact), frozenset(ptx)))
    elif isinstance(node, str):
        exact, ptx = _parse_sm_entries(re.split(r"[\s,;]+", node))
        if arch is not None and index is not None and (exact or ptx):
            out.append((arch, index, frozenset(exact), frozenset(ptx)))


def _ptx_scenarios():
    """Derive (arch, driver, caps, url-token) triples covered only via PTX.

    A device (X, Y) is PTX-covered (never exact-SASS) when some compute_ZW
    entry has (Z, W) >= (X, Y) while no exact sm_XY entry exists.  The driver
    is pinned to the index's own version so no newer candidate can shadow it.
    """
    try:
        mapping = INDEX_ARCH_MAP if isinstance(INDEX_ARCH_MAP, dict) else dict(INDEX_ARCH_MAP)
    except Exception:
        return []
    found = []
    _walk_arch_map(mapping, None, None, found)
    scenarios = []
    for arch, index_name, exact, ptx in found:
        if not ptx:
            continue
        match = _CU_RE.search(index_name)
        if not match:
            continue
        version = _cu_version(match.group(1))
        max_ptx = max(ptx)
        device = None
        for major in range(max_ptx[0], 1, -1):
            candidate = (major, 0)
            if candidate <= max_ptx and candidate not in exact:
                device = candidate
                break
        if device is None:
            grid = [
                (major, minor)
                for major in range(2, max_ptx[0] + 1)
                for minor in range(0, 10)
                if (major, minor) <= max_ptx and (major, minor) not in exact
            ]
            device = max(grid) if grid else None
        if device is None:
            continue
        token = "cu" + match.group(1)
        scenarios.append((arch, version, (device,), token, index_name))
    scenarios.sort(key=lambda item: (item[0], -item[1][0], -item[1][1]))
    scenarios.sort(
        key=lambda item: 0 if any(token in item[4].lower() for token in _TABLE_INDEX_TOKENS) else 1
    )
    deduped, seen = [], set()
    for item in scenarios:
        key = (item[0], item[1])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return [(item[0], item[1], item[2], item[3]) for item in deduped]


def _pick_ptx_scenario():
    scenarios = _ptx_scenarios()
    return scenarios[0] if scenarios else None


def _scenario_results():
    """Every resolve_index scenario exercised above, for cross-cutting checks."""
    scenarios = [
        ("ws-default", _probes(), None),
        ("cuda13-driver", _probes(driver=(13, 2)), None),
        ("driver-bounds-12-9", _probes(driver=(12, 9), caps=((8, 0),)), None),
        ("driver-bounds-12-6", _probes(driver=(12, 6), caps=((8, 0),)), None),
        ("driver-bounds-12-4", _probes(driver=(12, 4), caps=((8, 0),)), None),
        ("driver-bounds-12-0", _probes(driver=(12, 0), caps=((8, 0),)), None),
        (
            "jetson-trap",
            _probes(arch="aarch64", driver=(13, 2), caps=((8, 7),), memory="unified"),
            None,
        ),
        ("sbsa", _probes(arch="aarch64", driver=(12, 8), caps=((9, 0),)), None),
        ("memory-discrete", _probes(memory="discrete"), None),
        ("memory-unknown", _probes(memory="unknown"), None),
        ("memory-nonsense", _probes(memory="nonsense"), None),
        ("dual-identical-devices", _probes(caps=((9, 0), (9, 0))), None),
        (
            "aarch64-two-covered-devices",
            _probes(arch="aarch64", driver=(12, 9), caps=((10, 0), (9, 0))),
            None,
        ),
        (
            "aarch64-second-device-uncovered",
            _probes(arch="aarch64", driver=(12, 6), caps=((9, 0), (10, 0))),
            None,
        ),
        ("aarch64-cc-exhaustion", _probes(arch="aarch64", driver=(12, 6), caps=((10, 0),)), None),
        (
            "rows-10-11-overlap",
            _probes(arch="aarch64", driver=(12, 0), caps=((8, 7),), memory="unified"),
            None,
        ),
        ("no-driver-probe", _probes(driver=None), None),
        ("no-devices-probed", _probes(caps=()), None),
        ("other-arch", _probes(arch="other"), None),
        ("driver-below-all-indexes", _probes(driver=(11, 5), caps=((8, 0),)), None),
        ("operator-override", _probes(), "https://download.pytorch.org/whl/cu129"),
    ]
    results = [
        (name, resolve_index(probes, override=override)) for name, probes, override in scenarios
    ]
    scenario = _pick_ptx_scenario()
    if scenario is not None:
        arch, driver, caps, _token = scenario
        results.append(
            ("jit-from-ptx", resolve_index(_probes(arch=arch, driver=driver, caps=caps)))
        )
    return results


# ---------------------------------------------------------------------------
# Hermetic injection helpers for collect_probes
# ---------------------------------------------------------------------------

_NVIDIA_SMI_HEADER = (
    "NVIDIA-SMI 550.54.15               Driver Version: 550.54.15   "
    "CUDA Version: 13.2     |\n"
    "-----------------------------------------+------------------------+"
    "----------------------+\n"
)


def _smi_payload(kwargs, text):
    """Render the fake header in the flavour the caller asked for."""
    texty = kwargs.get("text") or kwargs.get("encoding") or kwargs.get("universal_newlines")
    if texty:
        return text
    return text.encode("utf-8")


class _FakePopen:
    """Minimal Popen stand-in covering the common read patterns."""

    pid = 0

    def __init__(self, payload, returncode=0):
        self._payload = payload
        self.returncode = returncode
        if isinstance(payload, str):
            self.stdout = io.StringIO(payload)
            self.stderr = io.StringIO("")
        else:
            self.stdout = io.BytesIO(payload)
            self.stderr = io.BytesIO(b"")

    def communicate(self, *args, **kwargs):
        blank = "" if isinstance(self._payload, str) else b""
        return self._payload, blank

    def wait(self, *args, **kwargs):
        return self.returncode

    def poll(self):
        return self.returncode

    def read(self, *args, **kwargs):
        return self._payload

    def readline(self):
        return self._payload

    def readlines(self):
        return self._payload.splitlines(keepends=True)

    def kill(self):
        pass

    terminate = kill

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _make_smi_fakes(mode):
    if mode in ("timeout", "missing", "rc1"):
        if mode == "timeout":
            error = subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=5)
        elif mode == "missing":
            error = FileNotFoundError(2, "No such file or directory", "nvidia-smi")
        else:
            error = subprocess.CalledProcessError(returncode=1, cmd="nvidia-smi")

        def raise_error(*args, **kwargs):
            raise error

        fakes = {
            "run": raise_error,
            "check_output": raise_error,
            "check_call": raise_error,
            "call": raise_error,
            "getoutput": raise_error,
            "getstatusoutput": raise_error,
            "Popen": raise_error,
        }
        if mode == "rc1":
            # Exercise the "binary ran but failed" path for the common calls.
            def run(*args, **kwargs):
                return subprocess.CompletedProcess(
                    args=args[0] if args else "nvidia-smi",
                    returncode=1,
                    stdout=_smi_payload(kwargs, ""),
                    stderr="nvidia-smi: exited non-zero",
                )

            def call(*args, **kwargs):
                return 1

            def getstatusoutput(*args, **kwargs):
                return (1, "")

            fakes["run"] = run
            fakes["call"] = call
            fakes["getstatusoutput"] = getstatusoutput
        return fakes

    text = _NVIDIA_SMI_HEADER if mode == "ok" else ""

    def run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0] if args else "nvidia-smi",
            returncode=0,
            stdout=_smi_payload(kwargs, text),
            stderr="",
        )

    def check_output(*args, **kwargs):
        return _smi_payload(kwargs, text)

    def check_call(*args, **kwargs):
        return 0

    def call(*args, **kwargs):
        return 0

    def getoutput(*args, **kwargs):
        return text

    def getstatusoutput(*args, **kwargs):
        return (0, text)

    def popen(*args, **kwargs):
        return _FakePopen(_smi_payload(kwargs, text), returncode=0)

    return {
        "run": run,
        "check_output": check_output,
        "check_call": check_call,
        "call": call,
        "getoutput": getoutput,
        "getstatusoutput": getstatusoutput,
        "Popen": popen,
    }


def _rebind_kaine_attrs(monkeypatch, fakes, originals):
    """Also patch ``from x import y`` style bindings inside kaine modules."""
    for module_name in _KAINE_MODULES:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        for attr, fake in fakes.items():
            if getattr(module, attr, None) is originals[attr]:
                monkeypatch.setattr(module, attr, fake, raising=False)


def _install_smi_fake(monkeypatch, mode="ok"):
    """Replace every subprocess entry point; the real nvidia-smi never runs."""
    fakes = _make_smi_fakes(mode)
    originals = {name: getattr(subprocess, name) for name in fakes}
    for name, fake in fakes.items():
        monkeypatch.setattr(subprocess, name, fake, raising=True)
    _rebind_kaine_attrs(monkeypatch, fakes, originals)

    real_which = shutil.which

    def fake_which(cmd, *args, **kwargs):
        try:
            if isinstance(cmd, str) and "nvidia-smi" in cmd:
                return sys.executable
        except Exception:
            pass  # str() or comparison may fail; fall through to real
        return real_which(cmd, *args, **kwargs)

    monkeypatch.setattr(shutil, "which", fake_which, raising=True)
    _rebind_kaine_attrs(monkeypatch, {"which": fake_which}, {"which": real_which})

    real_exists = os.path.exists

    def fake_exists(path, *args, **kwargs):
        try:
            if "nvidia-smi" in str(path):
                return True
        except Exception:
            pass  # str() or comparison may fail; fall through to real
        return real_exists(path)

    monkeypatch.setattr(os.path, "exists", fake_exists, raising=True)
    _rebind_kaine_attrs(monkeypatch, {"exists": fake_exists}, {"exists": real_exists})

    real_path_exists = pathlib.Path.exists

    def fake_path_exists(self, *args, **kwargs):
        try:
            if "nvidia-smi" in str(self):
                return True
        except Exception:
            pass  # str() or comparison may fail; fall through to real
        return real_path_exists(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "exists", fake_path_exists, raising=True)


def _block_nvml(monkeypatch):
    """Make every NVML entry point fail, so probes stay machine-independent."""
    original_cdll = ctypes.CDLL
    original_find_library = ctypes.util.find_library

    def refuse(*args, **kwargs):
        raise OSError("NVML is blocked for hermetic wheel-index tests")

    def no_find_library(name, *args, **kwargs):
        return None

    monkeypatch.setattr(ctypes, "CDLL", refuse, raising=True)
    monkeypatch.setattr(ctypes.LibraryLoader, "LoadLibrary", refuse, raising=True)
    monkeypatch.setattr(ctypes.LibraryLoader, "__getitem__", refuse, raising=False)
    monkeypatch.setattr(ctypes.util, "find_library", no_find_library, raising=True)
    for name in ("pynvml", "nvml", "py3nvml"):
        monkeypatch.setitem(sys.modules, name, None)
    for module_name in _KAINE_MODULES:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        if getattr(module, "CDLL", None) is original_cdll:
            monkeypatch.setattr(module, "CDLL", refuse, raising=False)
        if getattr(module, "find_library", None) is original_find_library:
            monkeypatch.setattr(module, "find_library", no_find_library, raising=False)


def _patch_machine(monkeypatch, value):
    original = platform.machine

    def fake_machine():
        return value

    monkeypatch.setattr(platform, "machine", fake_machine, raising=True)
    _rebind_kaine_attrs(monkeypatch, {"machine": fake_machine}, {"machine": original})


# ---------------------------------------------------------------------------
# Decision table / fallback ladder (pure resolve_index)
# ---------------------------------------------------------------------------


def test_binding_constants_are_public():
    """Invariant: the decision table, the authoritative arch→sm map and the
    CPU index are importable public names.

    Cost prevented: install.sh reaching into private names that can drift
    without notice.
    """
    assert DECISION_TABLE
    assert INDEX_ARCH_MAP
    assert CPU_INDEX == "https://download.pytorch.org/whl/cpu"


def test_x86_64_workstation_default_resolves_cu128():
    """Invariant: the dual-GPU x86_64 workstation (driver CUDA 12.8, one sm_90
    device, discrete memory) still resolves to the cu128 index.

    Cost prevented: regressing the machine KAINE was developed on — the change
    must be invisible to the existing default install path.
    """
    result = resolve_index(_probes())
    assert result["index_url"] == CU128
    assert result["index_url"] != CPU_INDEX


@pytest.mark.parametrize("driver", [(13, 0), (13, 2)], ids=["cuda-13-0-driver", "cuda-13-2-driver"])
def test_cuda_13_driver_never_receives_cu128(driver):
    """Invariant: a CUDA 13.x driver is served a CUDA-13-compatible index and
    never the cu128 one.

    Cost prevented: the original hardcoded-index defect — cu128 wheels handed
    to a CUDA 13 driver.
    """
    result = resolve_index(_probes(driver=driver))
    assert result["index_url"] == CU130
    assert "cu128" not in result["index_url"]


def test_driver_cuda_bounds_the_selected_index():
    """Invariant: the selected index's CUDA version never exceeds the probed
    driver CUDA — the ladder only builds candidates with X.Y <= driver CUDA.

    Cost prevented: handing a driver wheels it cannot load (the reverse of the
    explicitly allowed older-index downgrade).
    """
    cases = {
        (12, 9): CU128,
        (12, 6): CU126,
        (12, 4): CU121,
        (12, 0): CU118,
    }
    for driver, expected in cases.items():
        result = resolve_index(_probes(driver=driver, caps=((8, 0),)))
        assert result["index_url"] == expected, driver


def test_jetson_unified_host_gets_cpu_index_with_jetpack_remediation():
    """Invariant: aarch64 + positively-unified memory (Tegra, sm_87) resolves
    to the CPU index — upstream wheels carry no Tegra SASS — and the rejection
    is explained with the --index-url / JetPack remediation.

    Cost prevented: the worst failure mode — an install that 'succeeds' and
    then dies at the first kernel launch with 'no kernel image is available
    for execution on the device'.
    """
    probes = _probes(arch="aarch64", driver=(13, 2), caps=((8, 7),), memory="unified")
    result = resolve_index(probes)
    assert result["index_url"] == CPU_INDEX
    assert result["rejected"], "rejection list must explain the exclusion"
    for entry in result["rejected"]:
        assert isinstance(entry.get("reason"), str) and entry["reason"].strip()
    joined = " ".join(result["warnings"]).lower()
    assert "unified" in joined, "warning must state the memory classification"
    assert "--index-url" in joined, "warning must carry the remediation"
    assert "jetpack" in joined, "Tegra remediation must point at JetPack"


def test_aarch64_sbsa_host_still_gets_cuda_index():
    """Invariant: aarch64 SBSA hosts (discrete memory, sm_90 devices) still
    resolve to the SBSA CUDA index, not the CPU index.

    Cost prevented: over-correcting the Tegra fix into CPU-only installs on
    GH200-class SBSA hardware.
    """
    result = resolve_index(_probes(arch="aarch64", driver=(12, 8), caps=((9, 0),)))
    assert result["index_url"] == CU128
    assert result["index_url"] != CPU_INDEX


def test_unknown_memory_never_excludes():
    """Invariant: only a POSITIVE unified verdict excludes CUDA candidates; an
    `unknown` classification resolves exactly like `discrete`.

    Cost prevented: a discrete host with broken NVML losing its wheel because
    a failed probe was read as 'integrated'.
    """
    discrete = resolve_index(_probes(memory="discrete"))
    unknown = resolve_index(_probes(memory="unknown"))
    assert discrete["index_url"] == CU128
    assert discrete["index_url"] == unknown["index_url"]
    assert discrete["variant"] == unknown["variant"]


def test_every_device_must_be_covered():
    """Invariant: a candidate survives only if EVERY probed NVIDIA device is
    covered; one uncovered device rejects the whole candidate.

    Cost prevented: multi-GPU hosts receiving a wheel that one of the cards
    cannot execute (first-device-only coverage checks).
    """
    identical = resolve_index(_probes(caps=((9, 0), (9, 0))))
    assert identical["index_url"] == CU128

    both_covered = resolve_index(_probes(arch="aarch64", driver=(12, 9), caps=((10, 0), (9, 0))))
    assert both_covered["index_url"] == CU128

    # cu126's aarch64 line serves sm_90 but not sm_100, so the second device
    # rejects the only candidate and the ladder exhausts to the CPU index.
    second_uncovered = resolve_index(
        _probes(arch="aarch64", driver=(12, 6), caps=((9, 0), (10, 0)))
    )
    assert second_uncovered["index_url"] == CPU_INDEX
    assert any("126" in str(entry.get("index", "")) for entry in second_uncovered["rejected"])


def test_ptx_counts_as_coverage_and_is_annotated():
    """Invariant: a device with no exact SASS entry is still covered when the
    index map carries a compute_ZW PTX entry with (Z, W) >= the device
    capability, and the selection is annotated as JIT-from-PTX.

    Cost prevented: refusing a workable JIT'd wheel — or JIT'ing silently.
    """
    scenario = _pick_ptx_scenario()
    if scenario is None:
        pytest.skip("INDEX_ARCH_MAP exposes no PTX-only coverage scenario")
    arch, driver, caps, token = scenario
    result = resolve_index(_probes(arch=arch, driver=driver, caps=caps))
    assert result["index_url"] != CPU_INDEX
    assert token in result["index_url"]
    annotation = " ".join([result["selected_reason"], *result["warnings"]]).lower()
    assert "ptx" in annotation


def test_override_wins_and_is_recorded_as_operator_provided():
    """Invariant: an operator-provided override beats the decision table
    whenever a CUDA index would be used, and selected_reason records the
    provenance.

    Cost prevented: silently ignoring an explicit operator --index-url.
    """
    override = "https://download.pytorch.org/whl/cu129"
    result = resolve_index(_probes(), override=override)
    assert result["index_url"] == override
    assert "operator" in result["selected_reason"].lower()


def test_exhaustion_warning_names_probes_and_rejection_reasons():
    """Invariant: when the ladder exhausts, the CPU-index warning names the
    probed arch, driver CUDA, per-device capability and memory classification,
    and every rejected candidate carries a reason string.

    Cost prevented: an unexplained CPU fallback an operator cannot debug.
    """
    result = resolve_index(
        _probes(arch="aarch64", driver=(12, 6), caps=((10, 0),), memory="discrete")
    )
    assert result["index_url"] == CPU_INDEX
    joined = " ".join(result["warnings"])
    assert "aarch64" in joined
    assert "12.6" in joined
    assert "10.0" in joined or "sm_100" in joined
    assert "discrete" in joined.lower()
    assert result["rejected"]
    for entry in result["rejected"]:
        assert isinstance(entry.get("reason"), str) and entry["reason"].strip()


def test_earlier_table_row_shadows_overlapping_later_row():
    """Invariant: first-match-wins — when a probe satisfies more than one
    table row, the earlier row's outcome prevails.

    Cost prevented: later, more generic rows (CPU fallback) swallowing
    earlier, more specific ones (CUDA indexes / the JetPack pointer).
    """
    # Rows 10 and 11 both hold for aarch64 + unified + driver < 12.5; the
    # earlier row 10 carries the JetPack remediation and must win.
    overlap = resolve_index(
        _probes(arch="aarch64", driver=(12, 0), caps=((8, 7),), memory="unified")
    )
    assert overlap["index_url"] == CPU_INDEX
    joined = " ".join(overlap["warnings"]).lower()
    assert "--index-url" in joined and "jetpack" in joined

    # A CUDA 13.x driver makes the cu130 (row 1) and cu128 (row 2) indexes
    # both driver-eligible; the earlier row (cu130) must shadow the later.
    shadowed = resolve_index(_probes(driver=(13, 2)))
    assert shadowed["index_url"] == CU130
    assert "cu128" not in shadowed["index_url"]


def test_resolve_index_is_pure():
    """Invariant: resolve_index is pure — equal inputs give equal results and
    the Probes instance is left untouched.

    Cost prevented: probe state leaking between retries of the installer.
    """
    probes = _probes(notes=("pre-existing note",))
    before = _probe_snapshot(probes)
    first = resolve_index(probes)
    second = resolve_index(probes)
    assert first == second
    assert _probe_snapshot(probes) == before


def test_degenerate_probes_return_normally():
    """Invariant: resolve_index never raises on degenerate probes (no devices,
    unknown driver, unrecognized arch, garbage memory classification) and
    falls back to the CPU index wherever no CUDA candidate can apply.

    Cost prevented: a crashed installer on half-probed hardware.
    """
    degenerate = [
        _probes(driver=None),
        _probes(caps=()),
        _probes(arch="other"),
        _probes(memory="nonsense"),
        _probes(arch="other", driver=None, caps=(), memory="nonsense"),
        _probes(driver=(11, 5), caps=((8, 0),)),
    ]
    for probes in degenerate:
        result = resolve_index(probes)
        assert isinstance(result, dict)
    assert resolve_index(_probes(driver=None))["index_url"] == CPU_INDEX
    assert resolve_index(_probes(arch="other"))["index_url"] == CPU_INDEX
    assert resolve_index(_probes(driver=(11, 5), caps=((8, 0),)))["index_url"] == CPU_INDEX
    # Garbage is not a positive unified verdict, so it must not exclude.
    assert resolve_index(_probes(memory="nonsense"))["index_url"] == CU128


def test_results_are_json_round_trippable():
    """Invariant: every emitted dict survives json.dumps -> json.loads
    verbatim and carries the full emission contract.

    Cost prevented: a broken hand-off between Python and install.sh, which
    logs the JSON verbatim.
    """
    for name, result in _scenario_results():
        assert json.loads(json.dumps(result)) == result, name
        assert {
            "variant",
            "index_url",
            "probes",
            "selected_reason",
            "rejected",
            "warnings",
        } <= set(result), name
        assert isinstance(result["variant"], str) and result["variant"], name
        assert isinstance(result["index_url"], str) and result["index_url"], name
        assert isinstance(result["selected_reason"], str), name
        assert result["selected_reason"], name
        assert isinstance(result["rejected"], list), name
        assert isinstance(result["warnings"], list), name
        assert all(isinstance(warning, str) for warning in result["warnings"]), name
        for entry in result["rejected"]:
            assert isinstance(entry, dict), name
            assert "index" in entry and "reason" in entry, name
            assert isinstance(entry["reason"], str), name
            assert entry["reason"].strip(), name


# ---------------------------------------------------------------------------
# collect_probes — injection only; the real nvidia-smi never runs
# ---------------------------------------------------------------------------


def test_collect_probes_reads_driver_cuda_from_nvidia_smi(monkeypatch):
    """Invariant: the driver-CUDA probe parses the `CUDA Version` field of
    nvidia-smi output and needs neither torch nor real hardware.

    Cost prevented: probing logic that only works on the developer's
    workstation.
    """
    _install_smi_fake(monkeypatch, "ok")
    _block_nvml(monkeypatch)
    probes = collect_probes()
    assert isinstance(probes, Probes)
    assert probes.driver_cuda == (13, 2)


@pytest.mark.parametrize("mode", ["timeout", "missing", "rc1", "empty"])
def test_collect_probes_survives_nvidia_smi_failure(monkeypatch, mode):
    """Invariant: a failing, missing, erroring, empty or timed-out nvidia-smi
    probe yields driver_cuda=None plus a note — never an exception.

    Cost prevented: a crashed install on machines where nvidia-smi is absent,
    hung, erroring, or silent.
    """
    _install_smi_fake(monkeypatch, mode)
    _block_nvml(monkeypatch)
    probes = collect_probes()
    assert probes.driver_cuda is None
    assert probes.notes


@pytest.mark.parametrize(
    ("machine_value", "expected"),
    [("x86_64", "x86_64"), ("aarch64", "aarch64"), ("ppc64le", "other")],
    ids=["x86_64", "aarch64", "other"],
)
def test_collect_probes_normalizes_platform_machine(monkeypatch, machine_value, expected):
    """Invariant: platform.machine() is normalized to x86_64 / aarch64 / other
    before it reaches the decision table.

    Cost prevented: an unnormalized arch silently emptying the candidate list
    (decision-table row 12) on exotic hosts.
    """
    _install_smi_fake(monkeypatch, "ok")
    _block_nvml(monkeypatch)
    _patch_machine(monkeypatch, machine_value)
    probes = collect_probes()
    assert probes.arch == expected


# _kaine_operator_override_patch_tests_ : regression tests for the
# authoritative operator --index-url override.  The override must win on an
# EXHAUSTED ladder (Jetson/Tegra -- the exact case the override exists for,
# since no upstream index ships Tegra SASS) and on a succeeding ladder alike;
# the ladder's own reasoning (the `rejected` list) must stay visible in both
# cases; and the old "override was not applied" refusal must never fire when
# an override is given.

from kaine.wheel_index import (  # noqa: E402,I001 — section-local imports kept adjacent to the override patch tests
    Probes as _OverridePatchProbes,
    resolve_index as _OverridePatchResolveIndex,
)


def _override_patch_jetson_probes():
    return _OverridePatchProbes(
        arch="aarch64",
        driver_cuda=(13, 2),
        compute_caps=((8, 7),),
        memory_state="unified",
        notes={},
    )


def _override_patch_x86_probes():
    return _OverridePatchProbes(
        arch="x86_64",
        driver_cuda=(12, 8),
        compute_caps=((9, 0),),
        memory_state="discrete",
        notes={},
    )


def _override_patch_all_strings(result):
    strings = []
    for value in result.values():
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, (list, tuple)):
            strings.extend(item for item in value if isinstance(item, str))
    return strings


def test_override_applied_on_exhausted_ladder():
    result = _OverridePatchResolveIndex(
        _override_patch_jetson_probes(),
        override="https://jetpack.example/cu132",
    )
    assert result["index_url"] == "https://jetpack.example/cu132"
    assert result["variant"] == "cuda"


def test_override_still_applied_on_succeeding_ladder():
    result = _OverridePatchResolveIndex(
        _override_patch_x86_probes(), override="https://custom.example/x"
    )
    assert result["index_url"] == "https://custom.example/x"
    assert result["variant"] == "cuda"


def test_override_preserves_ladder_audit_trail():
    """An operator override must not blind the ladder's audit trail — but
    what that trail holds depends on how the ladder actually fared.

    EXHAUSTED ladder (aarch64 / unified / sm_87 Jetson probes) + override:
    `rejected` MUST stay non-empty — the operator still needs to see why
    every upstream index was ruled out, even though their override is used.

    SUCCEEDING ladder (x86_64, driver CUDA 12.8) + override: an EMPTY
    `rejected` list is the correct, truthful output — do NOT 'fix' this
    back.  The candidate set is cu128, cu126, cu121, cu118 (every index
    <= 12.8, newest first) and cu128, the first candidate, already passes
    the architecture, compute-capability and memory filters, so it is
    selected immediately and nothing is ever rejected.  The decision stays
    auditable through `selected_reason`, which must record BOTH that the
    URL is operator-provided AND what the ladder would have chosen without
    it.

    Neither case may emit the old 'was not applied' refusal warning.
    """
    exhausted = _OverridePatchResolveIndex(
        _override_patch_jetson_probes(),
        override="https://jetpack.example/cu132",
    )
    assert isinstance(exhausted["rejected"], list)
    assert exhausted["rejected"], (
        "exhausted ladder under override must still explain every rejection"
    )
    for warning in exhausted["warnings"]:
        assert "was not applied" not in warning

    succeeding = _OverridePatchResolveIndex(
        _override_patch_x86_probes(), override="https://custom.example/x"
    )
    assert isinstance(succeeding["rejected"], list)
    # No truthiness/length assertion on `rejected` here: an empty list is
    # the truthful result when the first candidate (cu128) wins at once.
    ladder_alone = _OverridePatchResolveIndex(_override_patch_x86_probes())
    ladder_token = ladder_alone["index_url"].rstrip("/").rsplit("/", 1)[-1]
    reason = succeeding["selected_reason"].lower()
    assert "operator" in reason, "selected_reason must record that the URL is operator-provided"
    assert ladder_token in reason, (
        "selected_reason must also record the ladder choice the override replaced: " + ladder_token
    )
    for warning in succeeding["warnings"]:
        assert "was not applied" not in warning


def test_no_override_refusal_warning_when_override_given():
    cases = (
        (_override_patch_jetson_probes(), "https://jetpack.example/cu132"),
        (_override_patch_x86_probes(), "https://custom.example/x"),
    )
    for probes, url in cases:
        result = _OverridePatchResolveIndex(probes, override=url)
        for text in _override_patch_all_strings(result):
            assert "was not applied" not in text
