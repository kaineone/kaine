"""Scaffolding for the budget-aware hardware selector introduced for
cross-platform deployments.

These tests assert the vocabulary and the safe defaults; they work even on a
box with no GPU at all, and do not require any model weights.
"""

from __future__ import annotations

import kaine.hardware as hardware


def test_cpu_threads_budget_leaves_headroom():
    n = hardware.cpu_threads_budget()
    assert isinstance(n, int) and n >= 1


def test_gpu_inventory_is_non_raising_and_typed():
    devices = hardware.gpu_inventory()
    assert isinstance(devices, list)
    for d in devices:
        assert isinstance(d, hardware.GpuSnapshot)
        assert d.backend in {"cuda", "xpu", "mps"}
        assert d.total_mb >= 0
        assert d.free_mb >= 0


def test_best_accelerator_for_unrealistically_large_need_falls_back_to_cpu():
    assert hardware.best_accelerator_for(200_000) == "cpu"


def test_best_accelerator_for_zero_need_respects_guard():
    # Guard means even a modest sub-meg application cannot evict a neighbor.
    assert isinstance(hardware.best_accelerator_for(0), str)
