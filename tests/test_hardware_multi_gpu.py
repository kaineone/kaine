# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the multi-GPU additions in kaine.hardware.

These tests stub `_try_torch` and `_cuda_device_count` so they pass on
any host regardless of actual GPU count.
"""
from __future__ import annotations

import os

import pytest

from kaine import hardware


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("KAINE_FORCE_DEVICE", raising=False)


def _stub_cuda_devices(monkeypatch, count: int) -> None:
    monkeypatch.setattr(hardware, "_cuda_device_count", lambda: count)


def test_validate_device_string_accepts_indexed_cuda():
    hardware._validate_device_string("cuda:0")
    hardware._validate_device_string("cuda:1")
    hardware._validate_device_string("cuda:7")
    hardware._validate_device_string("cuda")
    hardware._validate_device_string("cpu")


def test_validate_device_string_rejects_garbage():
    with pytest.raises(ValueError):
        hardware._validate_device_string("cuda:foo")
    with pytest.raises(ValueError):
        hardware._validate_device_string("gpu")
    with pytest.raises(ValueError):
        hardware._validate_device_string("cuda:-1")


def test_available_cuda_devices_enumeration(monkeypatch):
    _stub_cuda_devices(monkeypatch, 2)
    assert hardware.available_cuda_devices() == ["cuda:0", "cuda:1"]
    _stub_cuda_devices(monkeypatch, 0)
    assert hardware.available_cuda_devices() == []


def test_select_device_returns_indexed_when_present(monkeypatch):
    _stub_cuda_devices(monkeypatch, 2)
    assert hardware.select_device("cuda:1") == "cuda:1"
    assert hardware.select_device("cuda:0") == "cuda:0"


def test_select_device_raises_when_index_missing(monkeypatch):
    _stub_cuda_devices(monkeypatch, 1)
    with pytest.raises(ValueError, match="cuda:1"):
        hardware.select_device("cuda:1")


def test_resolve_device_falls_back_with_warning_on_missing_index(
    monkeypatch, caplog
):
    _stub_cuda_devices(monkeypatch, 1)
    with caplog.at_level("WARNING"):
        result = hardware.resolve_device("cuda:1", fallback="cuda:0")
    assert result == "cuda:0"
    assert any("cuda:1" in rec.message for rec in caplog.records)


def test_resolve_device_falls_back_to_cpu_when_no_cuda(monkeypatch, caplog):
    _stub_cuda_devices(monkeypatch, 0)
    with caplog.at_level("WARNING"):
        result = hardware.resolve_device("cuda:1", fallback="cuda:0")
    assert result == "cpu"


def test_resolve_device_returns_cpu_when_asked(monkeypatch):
    _stub_cuda_devices(monkeypatch, 2)
    assert hardware.resolve_device("cpu") == "cpu"


def test_resolve_device_auto_returns_detected(monkeypatch):
    _stub_cuda_devices(monkeypatch, 0)
    # No CUDA, no MPS — should be cpu.
    monkeypatch.setattr(hardware, "_try_torch", lambda: None)
    assert hardware.resolve_device("auto") == "cpu"
    assert hardware.resolve_device(None) == "cpu"


def test_resolve_device_cuda_to_cuda0_when_present(monkeypatch):
    _stub_cuda_devices(monkeypatch, 2)
    assert hardware.resolve_device("cuda") == "cuda:0"


def test_resolve_device_handles_invalid_preferred(monkeypatch, caplog):
    _stub_cuda_devices(monkeypatch, 1)
    with caplog.at_level("WARNING"):
        result = hardware.resolve_device("nonsense", fallback="cuda:0")
    assert result == "cuda:0"


def test_tune_cpu_threads_returns_value_or_zero():
    n = hardware.tune_cpu_threads(max_threads=4)
    # Returns 4 if torch is installed, 0 otherwise.
    assert n in (0, 4)


def test_tune_cpu_threads_default_caps_at_half_cpu_count(monkeypatch):
    import os as _os
    monkeypatch.setattr(_os, "cpu_count", lambda: 32)
    n = hardware.tune_cpu_threads()
    assert n == 0 or n == 16


def test_describe_host_includes_cuda_devices_key():
    out = hardware.describe_host()
    assert "cuda_devices" in out
    assert isinstance(out["cuda_devices"], list)


def test_env_override_invalid_falls_through_in_resolve(monkeypatch, caplog):
    monkeypatch.setenv("KAINE_FORCE_DEVICE", "garbage")
    _stub_cuda_devices(monkeypatch, 0)
    with caplog.at_level("WARNING"):
        result = hardware.resolve_device("auto")
    # invalid env var → warn and fall back to detect_device()
    assert result in ("cpu", "cuda", "mps")
