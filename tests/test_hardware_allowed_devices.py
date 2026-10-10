# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for operator-chosen allowed_devices in kaine.hardware."""
from __future__ import annotations

import logging
import subprocess

import pytest

from kaine import hardware


@pytest.fixture(autouse=True)
def _reset_restrictions(monkeypatch):
    monkeypatch.delenv("KAINE_FORCE_DEVICE", raising=False)
    monkeypatch.setattr(hardware, "_try_torch", lambda: None)
    hardware.set_allowed_devices(None)


def _stub_cuda_devices(monkeypatch, count: int) -> None:
    monkeypatch.setattr(hardware, "_cuda_device_count", lambda: count)
    monkeypatch.setattr(hardware, "_xpu_device_count", lambda: 0)
    monkeypatch.setattr(hardware, "_mps_available", lambda: False)


def _stub_detect_device(monkeypatch, device: str) -> None:
    monkeypatch.setattr(hardware, "detect_device", lambda: device)


def test_no_restrictions_uses_unrestricted_behavior(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    _stub_cuda_devices(monkeypatch, 2)
    _stub_detect_device(monkeypatch, "cuda:0")
    assert hardware.resolve_device("cuda:1") == "cuda:1"
    assert hardware.resolve_device("auto") == "cuda:0"
    assert hardware.resolve_device("cpu") == "cpu"
    assert hardware.allowed_devices() is None


def test_request_outside_allowed_set_falls_back(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    _stub_cuda_devices(monkeypatch, 2)
    hardware.set_allowed_devices(["cuda:0"])
    assert hardware.resolve_device("cuda:1") == "cuda:0"
    assert any(
        "cuda:1" in r.message and "cuda:0" in r.message for r in caplog.records
    )


def test_cpu_only_allowed_set_redirects_accelerator(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    _stub_cuda_devices(monkeypatch, 2)
    hardware.set_allowed_devices(["cpu"])
    assert hardware.resolve_device("cuda:0") == "cpu"
    assert any("outside" in r.message for r in caplog.records)


def test_allowed_order_skips_unavailable_accelerators(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    _stub_cuda_devices(monkeypatch, 1)
    hardware.set_allowed_devices(["cuda:1", "cuda:0"])
    assert hardware.resolve_device("xpu:0") == "cuda:0"
    assert hardware.resolve_device("cuda:0") == "cuda:0"


def test_cpu_always_permitted(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    _stub_cuda_devices(monkeypatch, 2)
    hardware.set_allowed_devices(["cuda:0"])
    assert hardware.resolve_device("cpu") == "cpu"
    assert not any("outside" in r.message for r in caplog.records)


def test_normalisation_and_deduplication(monkeypatch):
    _stub_cuda_devices(monkeypatch, 1)
    hardware.set_allowed_devices(["cuda", "cuda:0", "cpu"])
    assert hardware.allowed_devices() == ("cuda:0", "cpu")
    assert hardware.resolve_device("cuda:0") == "cuda:0"


def test_resolve_auto_bare_cuda_allowed_no_warning(monkeypatch, caplog):
    _stub_cuda_devices(monkeypatch, 1)
    _stub_detect_device(monkeypatch, "cuda")
    hardware.set_allowed_devices(["cuda:0"])
    with caplog.at_level(logging.WARNING, logger="kaine.hardware"):
        assert hardware.resolve_device("auto") == "cuda"
    assert "outside the operator's allowed devices" not in caplog.text


def test_resolve_auto_bare_cuda_picks_first_allowed_indexed_gpu(monkeypatch, caplog):
    _stub_cuda_devices(monkeypatch, 2)
    _stub_detect_device(monkeypatch, "cuda")
    hardware.set_allowed_devices(["cuda:1"])
    with caplog.at_level(logging.WARNING, logger="kaine.hardware"):
        assert hardware.resolve_device("auto") == "cuda:1"
    assert "using cuda:1" in caplog.text


def test_apply_hardware_config_wraps_value_error():
    with pytest.raises(ValueError, match=r"^\[hardware\]\.allowed_devices:"):
        hardware.apply_hardware_config({"hardware": {"allowed_devices": ["gpu"]}})


def test_invalid_allowed_entry_raises():
    with pytest.raises(ValueError):
        hardware.set_allowed_devices(["gpu"])


def test_empty_allowed_devices_raises():
    with pytest.raises(ValueError, match="allowed_devices must list at least one device"):
        hardware.set_allowed_devices([])


def test_force_device_overrides_allowed_set(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    _stub_cuda_devices(monkeypatch, 2)
    monkeypatch.setenv("KAINE_FORCE_DEVICE", "cuda:1")
    hardware.set_allowed_devices(["cuda:0"])
    assert hardware.resolve_device(None) == "cuda:1"
    assert any("overrides" in r.message for r in caplog.records)


def test_apply_hardware_config_absent_section(monkeypatch):
    calls = []
    monkeypatch.setattr(
        hardware,
        "tune_cpu_threads",
        lambda *, max_threads: calls.append(max_threads) or 4,
    )
    assert hardware.apply_hardware_config({}) == 4
    assert hardware.allowed_devices() is None
    assert calls == [None]


def test_apply_hardware_config_present_section(monkeypatch):
    calls = []
    monkeypatch.setattr(
        hardware,
        "tune_cpu_threads",
        lambda *, max_threads: calls.append(max_threads) or 2,
    )
    assert (
        hardware.apply_hardware_config(
            {"hardware": {"allowed_devices": ["cuda:0"], "cpu_threads": 3}}
        )
        == 2
    )
    assert hardware.allowed_devices() == ("cuda:0",)
    assert calls == [3]


def test_device_consumers_fake_nvidia_smi(monkeypatch):
    def fake_exists(path: str) -> bool:
        return path == "/proc/123"

    monkeypatch.setattr(hardware.os.path, "exists", fake_exists)

    def fake_run(args, **kwargs):
        class Result:
            stdout = ""
            stderr = ""
            returncode = 0

        r = Result()
        if "--query-gpu=" in args[1]:
            r.stdout = (
                "0, GPU-aaa, 8192, 1024, 7168\n"
                "1, GPU-bbb, 4096, 2048, 2048\n"
                "badline\n"
            )
        elif "--query-compute-apps=" in args[1]:
            r.stdout = (
                "123, python, 512, GPU-aaa\n"
                "999999999, other, 256, GPU-bbb\n"
                "badline\n"
            )
        return r

    monkeypatch.setattr(hardware.shutil, "which", lambda _name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(hardware.subprocess, "run", fake_run)
    rows = hardware.device_consumers(timeout_s=1.0)
    assert len(rows) == 2
    by_index = {r["index"]: r for r in rows}

    assert by_index[0]["device"] == "cuda:0"
    assert by_index[0]["total_mib"] == 8192
    assert by_index[0]["used_mib"] == 1024
    assert by_index[0]["free_mib"] == 7168
    assert len(by_index[0]["processes"]) == 1
    assert by_index[0]["processes"][0]["pid"] == 123
    assert by_index[0]["processes"][0]["visible"] is True
    assert by_index[0]["unattributed_mib"] == 512
    assert by_index[0]["processes_visible"] is True
    assert by_index[0]["note"] == ""

    assert by_index[1]["processes"][0]["pid"] == 999999999
    assert by_index[1]["processes"][0]["visible"] is False
    assert by_index[1]["processes_visible"] is False
    assert "namespace" in by_index[1]["note"]


def test_device_consumers_failed_apps_query_returns_empty_processes(monkeypatch):
    def fake_run(args, **kwargs):
        class Result:
            stdout = ""
            stderr = ""
            returncode = 0

        r = Result()
        if "--query-gpu=" in args[1]:
            r.stdout = "0, GPU-ddd, 4096, 512, 3584\n"
        elif "--query-compute-apps=" in args[1]:
            r.returncode = 1
        return r

    monkeypatch.setattr(hardware.shutil, "which", lambda _name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(hardware.subprocess, "run", fake_run)
    rows = hardware.device_consumers(timeout_s=1.0)
    assert len(rows) == 1
    assert rows[0]["processes"] == []


def test_device_consumers_in_container_note(monkeypatch):
    def fake_run(args, **kwargs):
        class Result:
            stdout = ""
            stderr = ""
            returncode = 0

        r = Result()
        if "--query-gpu=" in args[1]:
            r.stdout = "0, GPU-ccc, 4096, 512, 3584\n"
        elif "--query-compute-apps=" in args[1]:
            r.stdout = "42, proc, 100, GPU-ccc\n"
        return r

    monkeypatch.setattr(hardware.shutil, "which", lambda _name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(hardware.subprocess, "run", fake_run)
    monkeypatch.setattr(hardware, "_in_container", lambda: True)
    rows = hardware.device_consumers(timeout_s=1.0)
    assert rows[0]["processes_visible"] is False
    assert "container" in rows[0]["note"]


def test_device_consumers_missing_nvidia_smi(monkeypatch):
    monkeypatch.setattr(hardware.shutil, "which", lambda _name: None)
    assert hardware.device_consumers(timeout_s=1.0) == []


def test_device_consumers_timeout_returns_empty(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired("nvidia-smi", timeout=1.0)

    monkeypatch.setattr(hardware.shutil, "which", lambda _name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(hardware.subprocess, "run", fake_run)
    assert hardware.device_consumers(timeout_s=1.0) == []
