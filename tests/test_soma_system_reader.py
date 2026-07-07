# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Verifies the real SystemMetricsReader against psutil and a mock pynvml.

Skips the psutil portion if psutil is not importable. The pynvml init
failure path is exercised by monkeypatching the import so the test runs
on hosts with or without NVIDIA hardware.
"""
import sys
import types

import pytest

from kaine.modules.soma.reader import SystemMetricsReader


@pytest.mark.asyncio
async def test_init_tolerates_pynvml_missing(monkeypatch):
    fake_pynvml = types.ModuleType("pynvml")

    def _raise(*args, **kwargs):
        raise RuntimeError("simulated NVML not available")

    fake_pynvml.nvmlInit = _raise  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pynvml", fake_pynvml)
    reader = SystemMetricsReader()
    await reader.initialize()
    assert reader._gpu_available is False
    metrics = await reader.read_metrics()
    assert all(not k.startswith("gpu_") for k in metrics)
    await reader.shutdown()


@pytest.mark.asyncio
async def test_init_uses_mocked_pynvml(monkeypatch):
    fake_pynvml = types.ModuleType("pynvml")

    state = {"init": False, "shutdown": False}

    def _init():
        state["init"] = True

    def _shutdown():
        state["shutdown"] = True

    class _Mem:
        def __init__(self):
            self.total = 8 * 1024**3
            self.used = 1 * 1024**3

    fake_pynvml.nvmlInit = _init  # type: ignore[attr-defined]
    fake_pynvml.nvmlShutdown = _shutdown  # type: ignore[attr-defined]
    fake_pynvml.nvmlDeviceGetCount = lambda: 1  # type: ignore[attr-defined]
    fake_pynvml.nvmlDeviceGetHandleByIndex = lambda i: i  # type: ignore[attr-defined]
    fake_pynvml.nvmlDeviceGetTemperature = lambda h, kind: 42.0  # type: ignore[attr-defined]
    fake_pynvml.nvmlDeviceGetMemoryInfo = lambda h: _Mem()  # type: ignore[attr-defined]
    fake_pynvml.NVML_TEMPERATURE_GPU = 0  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "pynvml", fake_pynvml)
    reader = SystemMetricsReader()
    await reader.initialize()
    assert reader._gpu_available is True
    assert state["init"] is True
    metrics = await reader.read_metrics()
    assert metrics["gpu_0_temp_c"] == 42.0
    assert metrics["gpu_0_vram_percent"] == pytest.approx(12.5)
    await reader.shutdown()
    assert state["shutdown"] is True


@pytest.mark.asyncio
async def test_cycle_latency_window_averages():
    reader = SystemMetricsReader(cycle_latency_window=4)
    for ms in (1.0, 2.0, 3.0, 4.0, 5.0):
        reader.update_cycle_latency_sample(ms)
    await reader.initialize()
    metrics = await reader.read_metrics()
    assert metrics["cycle_latency_avg_ms"] == pytest.approx(3.5)
    await reader.shutdown()


@pytest.mark.asyncio
async def test_invalid_window_rejected():
    with pytest.raises(ValueError):
        SystemMetricsReader(cycle_latency_window=0)


@pytest.mark.asyncio
async def test_cpu_and_ram_metrics_present():
    pytest.importorskip("psutil")
    reader = SystemMetricsReader()
    await reader.initialize()
    try:
        metrics = await reader.read_metrics()
        assert "cpu_percent" in metrics
        assert "ram_percent" in metrics
        assert 0.0 <= metrics["ram_percent"] <= 100.0
    finally:
        await reader.shutdown()
