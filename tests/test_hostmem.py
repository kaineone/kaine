# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Tests for kaine.hostmem, the accelerator memory classifier.

The classifier must turn messy, host-specific probe results into a total and
honest answer: every detected accelerator is classified ``discrete``,
``unified`` or ``unknown``; every reported figure carries provenance; every
figure that cannot be determined is an explicit unknown marker (a ``None``
figure plus an ``unknown_reason``) instead of a silent zero or an omitted
field; the result is fully JSON-serializable; and no probe failure may ever
raise.

Every test injects its own platform signals (system/machine, /proc and /etc
content, NVML availability, torch) so the suite is host-independent: it must
pass unchanged on x86_64 CI runners and on the aarch64 Jetson Orin Nano target
alike.  A test that only passes on a Jetson is a broken test.
"""

import builtins
import collections
import ctypes
import ctypes.util
import errno
import fnmatch
import glob
import io
import json
import os
import pathlib
import platform
import subprocess
import sys

import pytest

from kaine import hostmem

# ---------------------------------------------------------------------------
# Verified Jetson Orin Nano Super facts, replayed through the fake filesystem.
# ---------------------------------------------------------------------------

JETSON_DEVICE_TREE_MODEL = (
    b"NVIDIA Jetson Orin Nano Engineering Reference Developer Kit Super\x00"
)
JETSON_TEGRA_RELEASE = b"# R39 (release), REVISION: 2.1\n"
JETSON_DEVICE_TREE_COMPATIBLE = (
    b"nvidia,p3768-0000+p3767-0001-super\x00"
    b"nvidia,p3767-0001\x00"
    b"nvidia,tegra234\x00"
    b"nvidia,tegra\x00"
)

# /proc/meminfo reports kB; the module must multiply by 1024 to reach bytes.
MEMINFO = (
    b"MemTotal:       7619468 kB\n"
    b"MemFree:        1023456 kB\n"
    b"MemAvailable:   3012456 kB\n"
    b"Buffers:         204800 kB\n"
    b"Cached:         3012456 kB\n"
    b"SwapTotal:             0 kB\n"
    b"SwapFree:              0 kB\n"
)
MEMINFO_TOTAL_BYTES = 7619468 * 1024
MEMINFO_AVAILABLE_BYTES = 3012456 * 1024

FAKE_VRAM_TOTAL_BYTES = 8_000_000_000
FAKE_VRAM_FREE_BYTES = 3_000_000_000

VALID_STATES = frozenset({"discrete", "unified", "unknown"})
DICT_KEYS = frozenset({"state", "pools", "evidence", "unknown_reason"})


# ---------------------------------------------------------------------------
# Torch stand-ins.
# ---------------------------------------------------------------------------


class _ExplodingTorch:
    """A torch stand-in whose every attribute access raises AttributeError.

    AttributeError, honouring the __getattr__ contract: this covers the
    missing-attribute path, where a probe's attribute lookups fail cleanly
    because the attribute does not exist.  The module must survive that
    without raising.  The unexpected-exception path — an attribute that
    exists but blows up mid-probe with RuntimeError — is covered separately
    by _HostileTorch.
    """

    def __getattr__(self, name):
        raise AttributeError(f"simulated torch failure on attribute {name!r}")


class _HostileTorch:
    """A torch stand-in whose existing attributes raise RuntimeError.

    Unlike _ExplodingTorch, nothing here relies on __getattr__: ``cuda``,
    ``version`` and ``__version__`` are explicitly defined properties that
    raise RuntimeError when accessed, simulating a probe that blows up
    mid-flight on an attribute that does exist.  The module must survive
    that without raising.
    """

    @property
    def cuda(self):
        raise RuntimeError("simulated torch failure on attribute 'cuda'")

    @property
    def version(self):
        raise RuntimeError("simulated torch failure on attribute 'version'")

    @property
    def __version__(self):
        raise RuntimeError("simulated torch failure on attribute '__version__'")


class _FakeDeviceProps:
    """Stand-in for the object returned by torch.cuda.get_device_properties."""

    def __init__(self, integrated, total_memory):
        self.name = "Fake Accelerator"
        self.major = 8
        self.minor = 0
        self.multi_processor_count = 12
        # Both spellings are provided; the module may read either one.
        self.integrated = integrated
        self.is_integrated = integrated
        if total_memory is not None:
            self.total_memory = total_memory


class _FakeCuda:
    """Stand-in for torch.cuda with controllable figures and verdicts."""

    def __init__(self, integrated, with_figures, device_count=1):
        self._integrated = integrated
        self._with_figures = with_figures
        self._device_count = device_count

    @staticmethod
    def is_available():
        return True

    @staticmethod
    def is_initialized():
        return True

    def init(self):
        return None

    def device_count(self):
        return self._device_count

    def current_device(self):
        return 0

    @staticmethod
    def _arg_index(args, kwargs):
        if args:
            return args[0]
        return kwargs.get("device")

    def _resolve(self, index):
        if index is None:
            return 0
        if isinstance(index, bool) or not isinstance(index, int):
            raise RuntimeError(f"simulated CUDA: invalid device index {index!r}")
        if not 0 <= index < self._device_count:
            raise RuntimeError(f"simulated CUDA: invalid device index {index!r}")
        return index

    def mem_get_info(self, *args, **kwargs):
        self._resolve(self._arg_index(args, kwargs))
        if not self._with_figures:
            # What NVML does on Tegra: the call exists, the figures do not.
            raise RuntimeError("simulated NVML: Not Supported")
        return (FAKE_VRAM_FREE_BYTES, FAKE_VRAM_TOTAL_BYTES)

    def get_device_properties(self, *args, **kwargs):
        self._resolve(self._arg_index(args, kwargs))
        total = FAKE_VRAM_TOTAL_BYTES if self._with_figures else None
        return _FakeDeviceProps(self._integrated, total)

    def get_device_name(self, *args, **kwargs):
        self._resolve(self._arg_index(args, kwargs))
        return "Fake Accelerator"


class _FakeTorch:
    """Stand-in for the torch module, injected through the ``torch`` keyword."""

    def __init__(self, integrated, with_figures, device_count=1):
        self.__version__ = "2.4.0"
        self.version = collections.namedtuple("Version", "cuda hip")(
            cuda="12.4", hip=None
        )
        self.cuda = _FakeCuda(integrated, with_figures, device_count)


# ---------------------------------------------------------------------------
# Platform injection.
# ---------------------------------------------------------------------------


class _FakeUname(
    collections.namedtuple("_FakeUnameBase", "sysname nodename release version machine")
):
    """os/platform uname result, including the .system/.node aliases."""

    @property
    def system(self):
        return self.sysname

    @property
    def node(self):
        return self.nodename


def _patch_platform(monkeypatch, *, system, machine):
    """Force every platform signal the classifier might consult.

    platform.system()/machine() are patched directly because platform.uname()
    caches its result, and sys.platform/os.uname are patched too in case the
    module prefers those spellings.
    """
    release = "23.0.0" if system == "Darwin" else "5.15.0-kaine"
    fake = _FakeUname(system, "kaine-test-host", release, "#1 SMP kaine", machine)
    monkeypatch.setattr(platform, "system", lambda: system)
    monkeypatch.setattr(platform, "machine", lambda: machine)
    monkeypatch.setattr(platform, "release", lambda: fake.release)
    monkeypatch.setattr(platform, "version", lambda: fake.version)
    monkeypatch.setattr(platform, "uname", lambda: fake)
    monkeypatch.setattr(
        platform, "platform", lambda *a, **k: f"{system}-{fake.release}-{machine}"
    )
    monkeypatch.setattr(os, "uname", lambda: fake, raising=False)
    monkeypatch.setattr(
        sys,
        "platform",
        {"Darwin": "darwin", "Linux": "linux"}.get(system, sys.platform),
    )
    return fake


def _patch_linux_x86_64(monkeypatch):
    """The 'nothing matches here' platform: kills ladder steps 3 and 4."""
    _patch_platform(monkeypatch, system="Linux", machine="x86_64")


def _patch_linux_aarch64(monkeypatch):
    _patch_platform(monkeypatch, system="Linux", machine="aarch64")


def _patch_darwin_arm64(monkeypatch):
    _patch_platform(monkeypatch, system="Darwin", machine="arm64")


def _break_external_probes(monkeypatch):
    """Make every non-filesystem probe backend fail deterministically.

    ctypes.CDLL raises (NVML absent or broken), find_library finds nothing,
    the ctypes.cdll shortcut is retargeted, a module-level ``from ctypes
    import CDLL`` capture is covered, an optional pynvml attribute is
    neutralised, and any attempt to shell out (nvidia-smi, rocm-smi, ...) is
    refused: the classifier must inspect, not execute.
    """

    def refuse(*args, **kwargs):
        raise OSError(errno.ENOENT, "simulated: probe backend unavailable")

    monkeypatch.setattr(ctypes, "CDLL", refuse)
    monkeypatch.setattr(
        ctypes.util, "find_library", lambda *a, **k: None, raising=False
    )
    monkeypatch.setattr(ctypes.cdll, "_dlltype", refuse, raising=False)
    monkeypatch.setattr(hostmem, "CDLL", refuse, raising=False)
    monkeypatch.setattr(hostmem, "pynvml", _ExplodingTorch(), raising=False)
    for name in (
        "Popen",
        "run",
        "check_output",
        "check_call",
        "call",
        "getoutput",
        "getstatusoutput",
    ):
        monkeypatch.setattr(subprocess, name, refuse, raising=False)


def _block_torch_import(monkeypatch):
    """Make ``import torch`` raise ImportError even when torch is installed."""
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setitem(sys.modules, "pynvml", None)


# ---------------------------------------------------------------------------
# Filesystem virtualisation.
# ---------------------------------------------------------------------------


class _FakeProcFS:
    """Redirect table from virtual /proc, /sys and /etc paths to staged files."""

    def __init__(self, tmp_path, real_open):
        self._tmp_path = tmp_path
        self._real_open = real_open
        self.mapping = {}

    def stage(self, virtual_path, data):
        """Serve exactly ``data`` for reads of ``virtual_path``."""
        virtual_path = os.fspath(virtual_path)
        safe = virtual_path.strip("/").replace("/", "_")
        target = self._tmp_path / safe
        with self._real_open(str(target), "wb") as handle:
            handle.write(data)
        self.mapping[virtual_path] = str(target)

    def lookup(self, path):
        return self.mapping.get(os.fspath(path))


@pytest.fixture
def fake_fs(tmp_path, monkeypatch):
    """Virtualise every filesystem probe the classifier might make.

    Staged virtual paths are served from real files under tmp_path (so text
    and binary read semantics stay genuine); anything else reads as
    nonexistent: exists()/isfile() return False and reads raise
    FileNotFoundError.  No test ever touches the real /proc, /sys or /etc,
    which is what makes every scenario identical on every host.
    """
    real_open = builtins.open
    real_stat = os.stat
    fs = _FakeProcFS(tmp_path, real_open)

    def fake_open(file, mode="r", *args, **kwargs):
        target = fs.lookup(file)
        if target is None:
            raise FileNotFoundError(
                errno.ENOENT, os.strerror(errno.ENOENT), os.fspath(file)
            )
        return real_open(target, mode, *args, **kwargs)

    def fake_path_open(path_self, mode="r", *args, **kwargs):
        return fake_open(os.fspath(path_self), mode, *args, **kwargs)

    def fake_stat(path, *args, **kwargs):
        target = fs.lookup(path)
        if target is None:
            raise FileNotFoundError(
                errno.ENOENT, os.strerror(errno.ENOENT), os.fspath(path)
            )
        return real_stat(target, *args, **kwargs)

    def fake_listdir(path):
        virtual = os.fspath(path).rstrip("/") or "/"
        prefix = virtual.rstrip("/") + "/"
        names = [os.path.basename(k) for k in fs.mapping if k.startswith(prefix)]
        if not names:
            raise FileNotFoundError(
                errno.ENOENT, os.strerror(errno.ENOENT), virtual
            )
        return names

    def fake_scandir(path, *args, **kwargs):
        raise FileNotFoundError(
            errno.ENOENT, os.strerror(errno.ENOENT), os.fspath(path)
        )

    def fake_access(path, mode, *args, **kwargs):
        return fs.lookup(path) is not None

    def fake_glob(pattern, *args, **kwargs):
        return sorted(p for p in fs.mapping if fnmatch.fnmatch(p, pattern))

    monkeypatch.setattr(builtins, "open", fake_open)
    monkeypatch.setattr(io, "open", fake_open)
    monkeypatch.setattr(pathlib.Path, "open", fake_path_open, raising=False)
    monkeypatch.setattr(os, "stat", fake_stat)
    monkeypatch.setattr(os, "listdir", fake_listdir)
    monkeypatch.setattr(os, "scandir", fake_scandir)
    monkeypatch.setattr(os, "access", fake_access)
    monkeypatch.setattr(os.path, "exists", lambda p: fs.lookup(p) is not None)
    monkeypatch.setattr(os.path, "isfile", lambda p: fs.lookup(p) is not None)
    monkeypatch.setattr(
        os.path,
        "isdir",
        lambda p: any(
            k.startswith(os.fspath(p).rstrip("/") + "/") for k in fs.mapping
        ),
    )
    monkeypatch.setattr(glob, "glob", fake_glob)
    return fs


# ---------------------------------------------------------------------------
# Shared assertions.
# ---------------------------------------------------------------------------


def _round_trip(classification):
    """Assert to_dict output is JSON-serializable, stable and well-shaped."""
    payload = hostmem.to_dict(classification)
    assert frozenset(payload) == DICT_KEYS
    assert json.loads(json.dumps(payload)) == payload
    assert payload["state"] in VALID_STATES
    assert isinstance(payload["pools"], list)
    assert all(isinstance(pool, dict) for pool in payload["pools"])
    assert len(payload["pools"]) == len(list(classification.pools))
    assert isinstance(payload["evidence"], str)
    assert payload["unknown_reason"] is None or isinstance(
        payload["unknown_reason"], str
    )
    return payload


def _assert_no_silent_zeros(classification):
    """Assert the no-silent-zeros invariant over every reported pool.

    A figure that cannot be determined must be None accompanied by a
    non-None unknown_reason; a zero total is always a lie.
    """
    for pool in classification.pools:
        assert pool.total_bytes != 0, (
            f"pool {pool.kind!r} reports total_bytes == 0: a silent zero; "
            "an undeterminable figure must be None plus unknown_reason"
        )
        assert pool.available_bytes != 0, (
            f"pool {pool.kind!r} reports available_bytes == 0: a silent zero"
        )
        if pool.total_bytes is None:
            assert isinstance(pool.unknown_reason, str) and pool.unknown_reason, (
                f"pool {pool.kind!r} has no total figure but no unknown_reason"
            )
        if pool.available_bytes is None:
            assert isinstance(pool.unknown_reason, str) and pool.unknown_reason, (
                f"pool {pool.kind!r} has no available figure but no unknown_reason"
            )


# ---------------------------------------------------------------------------
# Scenario builders: each pins the platform so the verdict is host-independent.
# ---------------------------------------------------------------------------


def _scenario_all_probes_broken(fake_fs, monkeypatch):
    """Every detection path fails: no files, no NVML, no torch, x86_64 Linux."""
    _patch_linux_x86_64(monkeypatch)
    _break_external_probes(monkeypatch)
    _block_torch_import(monkeypatch)
    return hostmem.classify_accelerator_memory(0, torch=_ExplodingTorch())


def _scenario_linux_aarch64_non_tegra(fake_fs, monkeypatch):
    """aarch64 Linux with no Tegra marker: the arch alone proves nothing."""
    _patch_linux_aarch64(monkeypatch)
    _break_external_probes(monkeypatch)
    return hostmem.classify_accelerator_memory(0, torch=_ExplodingTorch())


def _scenario_tegra_release_marker(fake_fs, monkeypatch):
    """Tegra via /etc/nv_tegra_release, with a readable /proc/meminfo."""
    _patch_linux_aarch64(monkeypatch)
    _break_external_probes(monkeypatch)
    fake_fs.stage("/etc/nv_tegra_release", JETSON_TEGRA_RELEASE)
    fake_fs.stage("/proc/meminfo", MEMINFO)
    return hostmem.classify_accelerator_memory(0, torch=_ExplodingTorch())


def _scenario_tegra_model_marker(fake_fs, monkeypatch):
    """Tegra via the NUL-terminated device-tree model."""
    _patch_linux_aarch64(monkeypatch)
    _break_external_probes(monkeypatch)
    fake_fs.stage("/proc/device-tree/model", JETSON_DEVICE_TREE_MODEL)
    fake_fs.stage("/proc/meminfo", MEMINFO)
    return hostmem.classify_accelerator_memory(0, torch=_ExplodingTorch())


def _scenario_tegra_compatible_marker(fake_fs, monkeypatch):
    """Tegra via the device-tree compatible property."""
    _patch_linux_aarch64(monkeypatch)
    _break_external_probes(monkeypatch)
    fake_fs.stage("/proc/device-tree/compatible", JETSON_DEVICE_TREE_COMPATIBLE)
    fake_fs.stage("/proc/meminfo", MEMINFO)
    return hostmem.classify_accelerator_memory(0, torch=_ExplodingTorch())


def _scenario_darwin_arm64(fake_fs, monkeypatch):
    """Apple Silicon platform class, with every probe failing."""
    _patch_darwin_arm64(monkeypatch)
    _break_external_probes(monkeypatch)
    return hostmem.classify_accelerator_memory(None, torch=_ExplodingTorch())


def _scenario_nvml_figures(fake_fs, monkeypatch):
    """Ladder step 1: NVML/torch figures answer before anything else."""
    _patch_linux_x86_64(monkeypatch)
    _break_external_probes(monkeypatch)
    torch = _FakeTorch(integrated=0, with_figures=True)
    return hostmem.classify_accelerator_memory(0, torch=torch)


def _scenario_integrated_unified(fake_fs, monkeypatch):
    """Ladder step 2 with integrated=1, on a platform that cannot decide."""
    _patch_linux_x86_64(monkeypatch)
    _break_external_probes(monkeypatch)
    fake_fs.stage("/proc/meminfo", MEMINFO)
    torch = _FakeTorch(integrated=1, with_figures=False)
    return hostmem.classify_accelerator_memory(0, torch=torch)


def _scenario_integrated_discrete(fake_fs, monkeypatch):
    """Ladder step 2 with integrated=0 and no figures anywhere."""
    _patch_linux_x86_64(monkeypatch)
    _break_external_probes(monkeypatch)
    torch = _FakeTorch(integrated=0, with_figures=False)
    return hostmem.classify_accelerator_memory(0, torch=torch)


_SCENARIOS = {
    "all-probes-broken": _scenario_all_probes_broken,
    "linux-aarch64-non-tegra": _scenario_linux_aarch64_non_tegra,
    "tegra-nv_tegra_release": _scenario_tegra_release_marker,
    "tegra-device-tree-model": _scenario_tegra_model_marker,
    "tegra-device-tree-compatible": _scenario_tegra_compatible_marker,
    "darwin-arm64": _scenario_darwin_arm64,
    "nvml-figures": _scenario_nvml_figures,
    "integrated-attribute-unified": _scenario_integrated_unified,
    "integrated-attribute-discrete": _scenario_integrated_discrete,
}


# ---------------------------------------------------------------------------
# Invariant 1: `unknown` is never promoted to `unified`.
# ---------------------------------------------------------------------------


def test_unknown_is_never_promoted_to_unified(fake_fs, monkeypatch):
    """Invariant: with every detection path broken the state is `unknown`,
    with a reason and no pools — never a fabricated `unified`.

    Why it matters: an `unknown` verdict that gets promoted to `unified`
    mis-sizes the memory budget on a discrete host.  Here file reads raise,
    ctypes.CDLL raises, platform.machine() reports x86_64 and torch is
    unusable, so no rung of the ladder may fire.
    """
    classification = _scenario_all_probes_broken(fake_fs, monkeypatch)
    assert classification.state == "unknown"
    assert isinstance(classification.unknown_reason, str)
    assert classification.unknown_reason
    assert not classification.pools
    payload = _round_trip(classification)
    assert payload["state"] == "unknown"
    assert payload["pools"] == []


def test_linux_aarch64_without_tegra_markers_is_unknown(fake_fs, monkeypatch):
    """Invariant: aarch64 alone is not evidence — without Tegra markers the
    classification is `unknown`, never a guessed `unified`.

    Why it matters: aarch64 SBCs with discrete GPUs exist; promoting the
    architecture to a unified verdict would mis-size their memory budget.
    """
    classification = _scenario_linux_aarch64_non_tegra(fake_fs, monkeypatch)
    assert classification.state == "unknown"
    assert isinstance(classification.unknown_reason, str)
    assert classification.unknown_reason
    assert not classification.pools
    _round_trip(classification)


# ---------------------------------------------------------------------------
# Invariant 2: never raises, under any fault injection.
# ---------------------------------------------------------------------------


def test_never_raises_when_every_open_raises_oserror(fake_fs, monkeypatch):
    """Invariant: classify_accelerator_memory returns normally when every
    open() raises OSError.

    Why it matters: probe failures are data, not exceptions — a host with a
    broken /proc must still receive a total, honest answer instead of an
    exception.
    """
    _patch_linux_x86_64(monkeypatch)
    _break_external_probes(monkeypatch)

    def always_fail(*args, **kwargs):
        raise OSError(errno.EIO, "simulated: every open() fails")

    monkeypatch.setattr(builtins, "open", always_fail)
    monkeypatch.setattr(io, "open", always_fail)
    monkeypatch.setattr(pathlib.Path, "open", always_fail, raising=False)
    monkeypatch.setattr(pathlib.Path, "read_text", always_fail, raising=False)
    monkeypatch.setattr(pathlib.Path, "read_bytes", always_fail, raising=False)

    classification = hostmem.classify_accelerator_memory(0, torch=_ExplodingTorch())
    assert classification.state == "unknown"
    assert classification.unknown_reason
    assert not classification.pools
    _round_trip(classification)


def test_never_raises_when_nvml_library_cannot_be_loaded(fake_fs, monkeypatch):
    """Invariant: ctypes.CDLL raising must not unwind out of the classifier.

    Why it matters: NVML is present-but-useless on Tegra and absent on many
    hosts; the failure must be recorded and the ladder continued, not the
    call aborted.
    """
    _patch_linux_x86_64(monkeypatch)
    _break_external_probes(monkeypatch)
    _block_torch_import(monkeypatch)
    classification = hostmem.classify_accelerator_memory(0, torch=_ExplodingTorch())
    assert classification.state == "unknown"
    assert classification.unknown_reason
    _round_trip(classification)


@pytest.mark.parametrize(
    "torch_standin",
    [_ExplodingTorch, _HostileTorch],
    ids=["attribute-error-path", "runtime-error-path"],
)
def test_never_raises_when_torch_probes_explode(fake_fs, monkeypatch, torch_standin):
    """Invariant: torch stand-ins whose attribute access fails must degrade
    to `unknown`, not crash and not guess — on both failure paths:
    _ExplodingTorch raises AttributeError from __getattr__ (the
    missing-attribute contract), while _HostileTorch raises RuntimeError
    from explicitly defined properties (an unexpected exception mid-probe).

    Why it matters: half-broken torch installs are the norm on mixed hosts;
    a failing probe is one more failed rung, never a fatal error.
    """
    _patch_linux_x86_64(monkeypatch)
    _break_external_probes(monkeypatch)
    classification = hostmem.classify_accelerator_memory(0, torch=torch_standin())
    assert classification.state == "unknown"
    assert classification.unknown_reason
    assert not classification.pools
    _round_trip(classification)


@pytest.mark.parametrize("index", [9999, -1, None])
def test_absurd_device_indices_never_raise(fake_fs, monkeypatch, index):
    """Invariant: absurd device indices (9999, -1, None) return normally.

    Why it matters: index handling is host- and driver-dependent; an
    unusable index is one more failed probe and must never become an
    exception or a fabricated verdict.
    """
    _patch_linux_x86_64(monkeypatch)
    _break_external_probes(monkeypatch)
    classification = hostmem.classify_accelerator_memory(
        index, torch=_ExplodingTorch()
    )
    assert classification.state == "unknown"
    assert classification.unknown_reason
    assert not classification.pools
    _round_trip(classification)


@pytest.mark.parametrize("index", [9999, -1, None])
def test_absurd_indices_with_working_torch_stay_well_formed(fake_fs, monkeypatch, index):
    """Invariant: even with a working torch stand-in, out-of-range indices
    produce a well-formed answer without fabricated figures.

    Why it matters: `None` means "probe the default device" and must reach
    device 0, while 9999 and -1 must fail the probe cleanly; either way the
    result must be well-formed and free of silent zeros.
    """
    _patch_linux_x86_64(monkeypatch)
    _break_external_probes(monkeypatch)
    torch = _FakeTorch(integrated=0, with_figures=True)
    classification = hostmem.classify_accelerator_memory(index, torch=torch)
    assert classification.state in VALID_STATES
    _assert_no_silent_zeros(classification)
    _round_trip(classification)


# ---------------------------------------------------------------------------
# Invariant 3: no silent zeros.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(_SCENARIOS))
def test_no_silent_zeros_in_any_reported_pool(name, fake_fs, monkeypatch):
    """Invariant: no pool ever reports a 0 figure, and every None figure
    carries a non-None unknown_reason.

    Why it matters: a silent zero is a lie that mis-sizes budgets; the spec
    demands explicit unknown markers (None + reason) instead.
    """
    classification = _SCENARIOS[name](fake_fs, monkeypatch)
    _assert_no_silent_zeros(classification)


# ---------------------------------------------------------------------------
# Invariant 4: JSON round-trip for every scenario exercised.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(_SCENARIOS))
def test_to_dict_json_round_trip(name, fake_fs, monkeypatch):
    """Invariant: to_dict output is fully JSON-serializable and survives a
    round-trip unchanged, for every scenario the suite exercises.

    Why it matters: describe_host() results cross process boundaries as
    JSON; any non-serializable value or key drift breaks downstream consumers.
    """
    classification = _SCENARIOS[name](fake_fs, monkeypatch)
    _round_trip(classification)


# ---------------------------------------------------------------------------
# Invariant 5: Tegra detection is driven by the markers.
# ---------------------------------------------------------------------------


def test_tegra_detected_via_nv_tegra_release_marker(fake_fs, monkeypatch):
    """Invariant: /etc/nv_tegra_release alone is sufficient for a Tegra
    verdict.

    Why it matters: on the Jetson target nvidia-smi runs but reports no
    memory figures, so the file marker must carry detection on its own.
    """
    _patch_linux_aarch64(monkeypatch)
    fake_fs.stage("/etc/nv_tegra_release", JETSON_TEGRA_RELEASE)
    verdict, detail = hostmem.is_tegra()
    assert verdict is True
    assert isinstance(detail, str)


def test_tegra_model_marker_matched_with_trailing_nul_stripped(fake_fs, monkeypatch):
    """Invariant: a NUL-terminated device-tree model containing "Orin" is
    detected as Tegra and the trailing NUL never reaches the evidence.

    Why it matters: device-tree properties are NUL-terminated; the marker
    must still match, and the raw NUL bytes must be stripped rather than
    leaked into reports.
    """
    _patch_linux_aarch64(monkeypatch)
    fake_fs.stage("/proc/device-tree/model", JETSON_DEVICE_TREE_MODEL)
    verdict, detail = hostmem.is_tegra()
    assert verdict is True
    assert "Orin" in detail
    assert "\x00" not in detail


def test_tegra_detected_via_compatible_marker(fake_fs, monkeypatch):
    """Invariant: a `compatible` property containing "nvidia,tegra" is
    sufficient for a Tegra verdict.

    Why it matters: the release file and model string are reworded between
    boards and releases; the compatible root is the stable identifier.
    """
    _patch_linux_aarch64(monkeypatch)
    fake_fs.stage("/proc/device-tree/compatible", JETSON_DEVICE_TREE_COMPATIBLE)
    verdict, detail = hostmem.is_tegra()
    assert verdict is True
    assert isinstance(detail, str)


def test_non_tegra_linux_aarch64_is_not_reported_as_tegra(fake_fs, monkeypatch):
    """Invariant: a non-Tegra Linux aarch64 host is NOT reported as Tegra.

    Why it matters: the architecture alone must never produce a Tegra
    verdict, otherwise every aarch64 SBC would be misread as Tegra
    unified-memory hardware.
    """
    _patch_linux_aarch64(monkeypatch)
    # fake_fs stages nothing: none of the three markers exists, on any host.
    verdict, detail = hostmem.is_tegra()
    assert verdict is False
    assert isinstance(detail, str)


# ---------------------------------------------------------------------------
# Invariant 6: Apple Silicon requires Darwin AND arm64.
# ---------------------------------------------------------------------------


def test_darwin_arm64_is_apple_silicon(fake_fs, monkeypatch):
    """Invariant: Darwin + arm64 satisfies the Apple Silicon platform class.

    Why it matters: Apple Silicon is unified memory by construction; missing
    this rung would leave locked-down Macs classified `unknown`.
    """
    _patch_darwin_arm64(monkeypatch)
    verdict, detail = hostmem.is_apple_silicon()
    assert verdict is True
    assert isinstance(detail, str)


def test_darwin_x86_64_is_not_apple_silicon(fake_fs, monkeypatch):
    """Invariant: Apple Silicon requires Darwin AND arm64 — an Intel Mac is
    not Apple Silicon.

    Why it matters: Intel Macs carry discrete GPUs; conflating Darwin with
    Apple Silicon would fabricate a `unified` verdict on a discrete host.
    """
    _patch_platform(monkeypatch, system="Darwin", machine="x86_64")
    verdict, detail = hostmem.is_apple_silicon()
    assert verdict is False
    assert isinstance(detail, str)


def test_linux_aarch64_is_not_apple_silicon(fake_fs, monkeypatch):
    """Invariant: Linux + aarch64 is NOT classified as Apple Silicon.

    Why it matters: arm64 says nothing about the vendor; only the Darwin AND
    arm64 pair may claim the Apple Silicon rung.
    """
    _patch_linux_aarch64(monkeypatch)
    verdict, detail = hostmem.is_apple_silicon()
    assert verdict is False
    assert isinstance(detail, str)


# ---------------------------------------------------------------------------
# Detection ladder, end to end.
# ---------------------------------------------------------------------------


def test_classify_tegra_platform_class_is_unified_with_system_pool(fake_fs, monkeypatch):
    """Invariant (ladder step 3): Linux + aarch64 + a Tegra marker classifies
    `unified`, with a system-RAM pool parsed from /proc/meminfo.

    Why it matters: this is the Jetson target's path — NVML is present but
    reports no figures, so the platform class must carry the verdict and the
    system pool must carry real, provenance-backed figures.
    """
    classification = _scenario_tegra_release_marker(fake_fs, monkeypatch)
    assert classification.state == "unified"
    assert classification.unknown_reason is None
    assert classification.evidence
    _assert_no_silent_zeros(classification)
    assert any(
        pool.total_bytes == MEMINFO_TOTAL_BYTES for pool in classification.pools
    )
    assert any(
        pool.available_bytes == MEMINFO_AVAILABLE_BYTES
        for pool in classification.pools
    )
    _round_trip(classification)


def test_classify_darwin_arm64_is_unified_without_any_probe(fake_fs, monkeypatch):
    """Invariant (ladder step 3): Darwin + arm64 classifies `unified` even
    when NVML, torch and every file probe fail.

    Why it matters: the platform class is the only evidence on a locked-down
    Mac; the verdict must not depend on probe success.
    """
    classification = _scenario_darwin_arm64(fake_fs, monkeypatch)
    assert classification.state == "unified"
    assert classification.unknown_reason is None
    _assert_no_silent_zeros(classification)
    _round_trip(classification)


def test_nvml_figures_classify_discrete_with_provenance(fake_fs, monkeypatch):
    """Invariant (ladder step 1): real total+free figures from NVML/torch
    are a POSITIVE `discrete` verdict whose provenance names the source.

    Why it matters: figures without provenance cannot be audited, and the
    first positive rung must win the ladder.
    """
    classification = _scenario_nvml_figures(fake_fs, monkeypatch)
    assert classification.state == "discrete"
    assert classification.unknown_reason is None
    _assert_no_silent_zeros(classification)
    assert any(
        pool.total_bytes == FAKE_VRAM_TOTAL_BYTES for pool in classification.pools
    )
    assert any(
        pool.available_bytes == FAKE_VRAM_FREE_BYTES for pool in classification.pools
    )
    assert any(
        isinstance(pool.provenance, str)
        and pool.provenance
        and any(
            tag in pool.provenance.lower()
            for tag in ("nvml", "nvidia", "torch", "cuda")
        )
        for pool in classification.pools
    )
    _round_trip(classification)


def test_cuda_integrated_attribute_one_is_unified_without_figures(fake_fs, monkeypatch):
    """Invariant (ladder step 2): cudaDeviceProp.integrated == 1 is a
    POSITIVE `unified` verdict even when no memory figures exist anywhere.

    Why it matters: on Tegra the integrated attribute is often the only
    authoritative signal; the platform class is patched away here (x86_64),
    so the attribute alone must carry the verdict.
    """
    classification = _scenario_integrated_unified(fake_fs, monkeypatch)
    assert classification.state == "unified"
    assert classification.unknown_reason is None
    _assert_no_silent_zeros(classification)
    assert any(
        pool.total_bytes == MEMINFO_TOTAL_BYTES for pool in classification.pools
    )
    _round_trip(classification)


def test_cuda_integrated_attribute_zero_is_discrete_with_unknown_markers(
    fake_fs, monkeypatch
):
    """Invariant (ladder step 2): integrated == 0 is a POSITIVE `discrete`
    verdict even when NVML figures are unavailable — and the missing VRAM
    figures must be explicit unknown markers (None + unknown_reason), never
    silent zeros and never an omitted pool.

    Why it matters: a discrete host whose NVML is broken must still be
    described as best it can, with honest holes instead of zeros.
    """
    classification = _scenario_integrated_discrete(fake_fs, monkeypatch)
    assert classification.state == "discrete"
    assert classification.unknown_reason is None
    assert classification.pools
    assert any(
        pool.total_bytes is None and pool.unknown_reason
        for pool in classification.pools
    )
    _assert_no_silent_zeros(classification)
    _round_trip(classification)


# ---------------------------------------------------------------------------
# Invariant 7: system_memory_pool parses /proc/meminfo correctly.
# ---------------------------------------------------------------------------


def test_system_memory_pool_parses_proc_meminfo_into_bytes(fake_fs):
    """Invariant: MemTotal/MemAvailable are parsed from /proc/meminfo into
    BYTES — meminfo reports kB, so the factor is 1024.

    Why it matters: a kB/bytes mix-up mis-sizes the unified memory budget by
    three orders of magnitude in either direction.
    """
    fake_fs.stage("/proc/meminfo", MEMINFO)
    pool = hostmem.system_memory_pool()
    assert pool.total_bytes == MEMINFO_TOTAL_BYTES
    assert pool.available_bytes == MEMINFO_AVAILABLE_BYTES
    assert pool.unknown_reason is None
    assert isinstance(pool.kind, str) and pool.kind
    assert isinstance(pool.provenance, str)
    assert "meminfo" in pool.provenance.lower()


def test_system_memory_pool_unreadable_reports_none_with_reason(fake_fs):
    """Invariant: an unreadable /proc/meminfo yields None figures plus an
    unknown_reason — never 0, never a raise.

    Why it matters: 0 bytes of system RAM is a silent lie; the spec demands
    an explicit unknown marker instead.
    """
    # fake_fs stages nothing, so /proc/meminfo is unreadable on every host.
    pool = hostmem.system_memory_pool()
    assert pool.total_bytes is None
    assert pool.available_bytes is None
    assert pool.total_bytes != 0
    assert isinstance(pool.unknown_reason, str) and pool.unknown_reason
    assert pool.provenance is None or isinstance(pool.provenance, str)
