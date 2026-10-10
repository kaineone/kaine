# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests that host memory and the hardware snapshot have a single owner.

- System memory fallbacks live in `kaine.hostmem`.
- `kaine.hardware.total_ram_gb` delegates to that single owner.
- `run_preflight` takes exactly one `describe_host` snapshot per run.
- Service-port definitions live in one place (`kaine.net.SERVICE_PORTS` and
  the defaults module), not as aliases in preflight or as raw literals.
"""
from __future__ import annotations

import inspect
import os
import sys

import pytest

from kaine import hostmem
from kaine.cycle import preflight as pf
from kaine.cycle.preflight import GpuPreflightConfig, run_preflight
from kaine.hardware import total_ram_gb
from kaine.setup import dependencies as deps


def test_sysconf_fallback_total_bytes(monkeypatch):
    """POSIX sysconf is the final rung when /proc/meminfo and psutil fail."""
    try:
        os.sysconf("SC_PAGE_SIZE")
        os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        pytest.skip("sysconf lacks SC_PAGE_SIZE or SC_PHYS_PAGES")

    monkeypatch.setattr(hostmem, "_meminfo_pool", lambda: None)
    monkeypatch.setitem(sys.modules, "psutil", None)

    pool = hostmem.system_memory_pool()

    assert pool.provenance == "sysconf"
    assert pool.total_bytes is not None and pool.total_bytes > 0
    assert pool.available_bytes is None
    assert pool.unknown_reason is not None


def test_total_ram_gb_delegates_to_hostmem():
    pool = hostmem.system_memory_pool()
    if pool.total_bytes is None:
        pytest.skip("system memory total not available on this host")
    expected = round(pool.total_bytes / (1024**3), 2)
    assert total_ram_gb() == expected


def test_run_preflight_takes_one_host_snapshot(tmp_path, monkeypatch):
    calls: list[None] = []

    def counting_describe_host():
        calls.append(None)
        return {"cuda_devices": [], "memory": {"state": "unknown"}}

    monkeypatch.setattr("kaine.hardware.describe_host", counting_describe_host)
    monkeypatch.setattr(pf, "_gpu_consumers", lambda *_a, **_k: [])
    monkeypatch.setattr(pf, "_device_consumers", lambda *_a, **_k: [])
    monkeypatch.setattr(pf, "_kaine_services_up", lambda *_a, **_k: {})
    monkeypatch.setattr(pf, "_server_resident_models", lambda *_a, **_k: [])
    monkeypatch.setattr(pf, "shared_services", lambda *_a, **_k: [])

    run_preflight(GpuPreflightConfig(enabled=True), state_path=tmp_path / "state.json")
    assert len(calls) == 1


def test_preflight_has_no_kaine_service_ports_alias():
    assert not hasattr(pf, "KAINE_SERVICE_PORTS")


def test_dependencies_source_uses_constants_not_port_literals():
    source = inspect.getsource(deps)
    assert "6479" not in source
    assert "6533" not in source
