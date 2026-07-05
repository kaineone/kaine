# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json
import os
import types

import pytest

from kaine.hardware import (
    describe_host,
    detect_device,
    resolve_device,
    select_device,
)

import kaine.hardware as _hw


_DEVICES = {"cuda", "xpu", "mps", "cpu"}


# ---------------------------------------------------------------------------
# Existing tests (unchanged)
# ---------------------------------------------------------------------------

def test_detect_device_returns_known_value():
    assert detect_device() in _DEVICES


def test_select_device_default_matches_detect():
    assert select_device() == detect_device()


def test_select_device_cpu_always_allowed():
    assert select_device("cpu") == "cpu"


def test_select_device_unknown_preferred_rejected():
    # Clear any forced override so the ValueError surfaces from the
    # argument validation, not from the env-var check.
    with pytest.MonkeyPatch().context() as mp:
        mp.delenv("KAINE_FORCE_DEVICE", raising=False)
        with pytest.raises(ValueError):
            select_device("vulkan")


def test_env_var_overrides_argument(monkeypatch):
    monkeypatch.setenv("KAINE_FORCE_DEVICE", "cpu")
    assert select_device("cuda") == "cpu"
    assert detect_device() == "cpu"


def test_env_var_invalid_value_raises(monkeypatch):
    monkeypatch.setenv("KAINE_FORCE_DEVICE", "vulkan")
    with pytest.raises(ValueError):
        detect_device()


def test_select_device_preferred_falls_back_when_unavailable(monkeypatch):
    monkeypatch.delenv("KAINE_FORCE_DEVICE", raising=False)
    # On a CPU-only run, asking for cuda must fall back to detect_device.
    if not _has_cuda():
        assert select_device("cuda") in _DEVICES
        assert select_device("cuda") != "cuda"


def test_describe_host_returns_documented_keys():
    info = describe_host()
    for key in (
        "device",
        "cuda_available",
        "mps_available",
        "gpu_count",
        "gpu_names",
        "torch_version",
        "torch_installed",
        "platform",
        "python_version",
    ):
        assert key in info, f"missing key {key!r}"
    assert info["device"] in _DEVICES


def test_describe_host_is_json_serializable():
    info = describe_host()
    encoded = json.dumps(info, default=str)
    assert isinstance(encoded, str)


def test_describe_host_consistency_with_detect_device():
    info = describe_host()
    if info["cuda_available"]:
        assert info["device"] in {"cuda", "cpu"}
        if os.environ.get("KAINE_FORCE_DEVICE") is None:
            assert info["device"] == "cuda"
    if info["gpu_count"] > 0:
        assert len(info["gpu_names"]) == info["gpu_count"]


def _has_cuda() -> bool:
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Fake-torch helpers
# ---------------------------------------------------------------------------

def _make_fake_torch(
    *,
    cuda_available: bool = False,
    cuda_count: int = 0,
    cuda_names: list[str] | None = None,
    xpu_available: bool = False,
    xpu_count: int = 0,
    xpu_names: list[str] | None = None,
    mps_available: bool = False,
    hip_version: str | None = None,
    torch_version: str = "2.5.0+fake",
):
    """Build a minimal fake torch namespace for monkeypatching _try_torch."""
    cuda_names = cuda_names or [f"FakeGPU-{i}" for i in range(cuda_count)]
    xpu_names = xpu_names or [f"FakeArc-{i}" for i in range(xpu_count)]

    # --- cuda sub-namespace ---
    cuda_ns = types.SimpleNamespace(
        is_available=lambda: cuda_available,
        device_count=lambda: cuda_count,
        get_device_name=lambda i: cuda_names[i] if i < len(cuda_names) else "",
        get_device_properties=lambda i: types.SimpleNamespace(total_memory=4 * 1024**3),
        mem_get_info=lambda i: (2 * 1024**3, 4 * 1024**3),
    )

    # --- xpu sub-namespace ---
    def _xpu_props(i):
        return types.SimpleNamespace(name=xpu_names[i] if i < len(xpu_names) else "")

    xpu_ns = types.SimpleNamespace(
        is_available=lambda: xpu_available,
        device_count=lambda: xpu_count,
        get_device_properties=_xpu_props,
    )

    # --- backends sub-namespace ---
    mps_ns = types.SimpleNamespace(is_available=lambda: mps_available)
    backends_ns = types.SimpleNamespace(mps=mps_ns)

    # --- version sub-namespace ---
    version_ns = types.SimpleNamespace(hip=hip_version)

    fake = types.SimpleNamespace(
        __version__=torch_version,
        cuda=cuda_ns,
        xpu=xpu_ns,
        backends=backends_ns,
        version=version_ns,
        set_num_threads=lambda n: None,
    )
    return fake


# ---------------------------------------------------------------------------
# XPU tests
# ---------------------------------------------------------------------------

class TestXpuPresent:
    """XPU available, CUDA unavailable."""

    @pytest.fixture(autouse=True)
    def patch_torch(self, monkeypatch):
        fake = _make_fake_torch(xpu_available=True, xpu_count=2)
        monkeypatch.setattr(_hw, "_try_torch", lambda: fake)
        monkeypatch.delenv("KAINE_FORCE_DEVICE", raising=False)

    def test_detect_device_is_xpu(self):
        assert detect_device() == "xpu"

    def test_select_device_xpu(self):
        assert select_device("xpu") == "xpu"

    def test_resolve_device_xpu(self):
        assert resolve_device("xpu") == "xpu:0"

    def test_select_device_xpu_indexed_valid(self):
        assert select_device("xpu:0") == "xpu:0"
        assert select_device("xpu:1") == "xpu:1"

    def test_select_device_xpu_indexed_out_of_range_raises(self):
        with pytest.raises(ValueError, match="xpu:3"):
            select_device("xpu:3")

    def test_resolve_device_xpu_indexed_out_of_range_falls_back(self):
        # Should NOT raise — falls back gracefully.
        result = resolve_device("xpu:3", fallback="cpu")
        assert result == "cpu"

    def test_describe_host_xpu_keys(self):
        info = describe_host()
        assert info["xpu_available"] is True
        assert info["xpu_count"] == 2
        assert isinstance(info["xpu_names"], list)
        assert len(info["xpu_names"]) == 2
        assert isinstance(info["xpu_devices"], list)
        assert len(info["xpu_devices"]) == 2
        # Each device entry has required fields.
        for d in info["xpu_devices"]:
            assert "index" in d
            assert "device" in d
            assert "name" in d

    def test_describe_host_backend_is_xpu(self):
        info = describe_host()
        assert info["backend"] == "xpu"
        assert info["hip_version"] is None

    def test_describe_host_json_serializable(self):
        info = describe_host()
        json.dumps(info, default=str)  # must not raise


class TestXpuNotPresent:
    """XPU module exists but is_available() returns False."""

    @pytest.fixture(autouse=True)
    def patch_torch(self, monkeypatch):
        fake = _make_fake_torch(xpu_available=False, xpu_count=0)
        monkeypatch.setattr(_hw, "_try_torch", lambda: fake)
        monkeypatch.delenv("KAINE_FORCE_DEVICE", raising=False)

    def test_detect_device_is_cpu(self):
        assert detect_device() == "cpu"

    def test_select_device_xpu_falls_back(self):
        # XPU not available; should fall back to detect_device() == "cpu".
        result = select_device("xpu")
        assert result == "cpu"

    def test_describe_host_xpu_counts_zero(self):
        info = describe_host()
        assert info["xpu_available"] is False
        assert info["xpu_count"] == 0
        assert info["xpu_names"] == []
        assert info["xpu_devices"] == []


class TestXpuRaisesGracefully:
    """xpu.is_available() raises — must never crash."""

    @pytest.fixture(autouse=True)
    def patch_torch(self, monkeypatch):
        fake = _make_fake_torch()

        def _raise():
            raise RuntimeError("simulated XPU driver error")

        fake.xpu.is_available = _raise
        monkeypatch.setattr(_hw, "_try_torch", lambda: fake)
        monkeypatch.delenv("KAINE_FORCE_DEVICE", raising=False)

    def test_xpu_device_count_is_zero(self):
        from kaine.hardware import _xpu_device_count
        assert _xpu_device_count() == 0

    def test_detect_device_does_not_crash(self):
        result = detect_device()
        assert result in _DEVICES

    def test_describe_host_does_not_crash(self):
        info = describe_host()
        assert info["xpu_available"] is False
        assert info["xpu_count"] == 0


# ---------------------------------------------------------------------------
# ROCm tests
# ---------------------------------------------------------------------------

class TestRocmPresent:
    """AMD ROCm: cuda_available True, hip_version set, device strings still 'cuda'."""

    @pytest.fixture(autouse=True)
    def patch_torch(self, monkeypatch):
        fake = _make_fake_torch(
            cuda_available=True,
            cuda_count=1,
            cuda_names=["AMD Radeon RX 7900 XTX"],
            hip_version="6.2.41134",
        )
        monkeypatch.setattr(_hw, "_try_torch", lambda: fake)
        monkeypatch.delenv("KAINE_FORCE_DEVICE", raising=False)

    def test_detect_device_is_cuda_for_rocm(self):
        # ROCm reuses the cuda device string.
        assert detect_device() == "cuda"

    def test_select_device_cuda_works(self):
        assert select_device("cuda") == "cuda"

    def test_select_device_cuda_indexed_works(self):
        assert select_device("cuda:0") == "cuda:0"

    def test_describe_host_backend_is_rocm(self):
        info = describe_host()
        assert info["backend"] == "rocm"

    def test_describe_host_hip_version_populated(self):
        info = describe_host()
        assert info["hip_version"] == "6.2.41134"

    def test_describe_host_cuda_available_true(self):
        info = describe_host()
        assert info["cuda_available"] is True

    def test_describe_host_gpu_count(self):
        info = describe_host()
        assert info["gpu_count"] == 1
        assert info["gpu_names"] == ["AMD Radeon RX 7900 XTX"]

    def test_describe_host_json_serializable(self):
        info = describe_host()
        json.dumps(info, default=str)


# ---------------------------------------------------------------------------
# describe_host() completeness & JSON tests
# ---------------------------------------------------------------------------

_OLD_REQUIRED_KEYS = {
    "device",
    "cuda_available",
    "mps_available",
    "gpu_count",
    "gpu_names",
    "cuda_devices",
    "torch_version",
    "torch_installed",
    "platform",
    "python_version",
}

_NEW_REQUIRED_KEYS = {
    "backend",
    "hip_version",
    "xpu_available",
    "xpu_count",
    "xpu_names",
    "xpu_devices",
}


class TestDescribeHostAllKeys:
    """describe_host() must include both old and new keys in every configuration."""

    @pytest.mark.parametrize(
        "fake_kwargs,expected_backend",
        [
            (dict(cuda_available=True, cuda_count=1, hip_version=None), "cuda"),
            (dict(cuda_available=True, cuda_count=1, hip_version="6.1"), "rocm"),
            (dict(xpu_available=True, xpu_count=1), "xpu"),
            (dict(mps_available=True), "mps"),
            (dict(), "cpu"),
        ],
    )
    def test_all_keys_present_and_json_serializable(
        self, monkeypatch, fake_kwargs, expected_backend
    ):
        fake = _make_fake_torch(**fake_kwargs)
        monkeypatch.setattr(_hw, "_try_torch", lambda: fake)
        monkeypatch.delenv("KAINE_FORCE_DEVICE", raising=False)

        info = describe_host()

        missing_old = _OLD_REQUIRED_KEYS - set(info)
        assert not missing_old, f"missing old keys: {missing_old}"

        missing_new = _NEW_REQUIRED_KEYS - set(info)
        assert not missing_new, f"missing new keys: {missing_new}"

        assert info["backend"] == expected_backend

        # Must remain JSON-serializable.
        json.dumps(info, default=str)

    def test_no_torch_still_has_all_keys(self, monkeypatch):
        monkeypatch.setattr(_hw, "_try_torch", lambda: None)
        monkeypatch.delenv("KAINE_FORCE_DEVICE", raising=False)

        info = describe_host()

        for key in _OLD_REQUIRED_KEYS | _NEW_REQUIRED_KEYS:
            assert key in info, f"missing key {key!r} when torch absent"

        assert info["backend"] == "cpu"
        assert info["hip_version"] is None
        assert info["xpu_available"] is False
        assert info["xpu_count"] == 0
        json.dumps(info, default=str)


# ---------------------------------------------------------------------------
# available_xpu_devices helper
# ---------------------------------------------------------------------------

def test_available_xpu_devices_empty_when_no_xpu(monkeypatch):
    from kaine.hardware import available_xpu_devices
    fake = _make_fake_torch(xpu_available=False, xpu_count=0)
    monkeypatch.setattr(_hw, "_try_torch", lambda: fake)
    assert available_xpu_devices() == []


def test_available_xpu_devices_returns_indexed_strings(monkeypatch):
    from kaine.hardware import available_xpu_devices
    fake = _make_fake_torch(xpu_available=True, xpu_count=3)
    monkeypatch.setattr(_hw, "_try_torch", lambda: fake)
    assert available_xpu_devices() == ["xpu:0", "xpu:1", "xpu:2"]
