# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json

from kaine import hostmem
from kaine.residency.budget import (
    MemoryDomain,
    ResidencyBudget,
    cgroup_available_bytes,
    compute_budget,
    default_reserve_bytes,
)


def test_default_reserve_bytes():
    assert default_reserve_bytes(None) == 1 << 30
    assert default_reserve_bytes(10 << 30) == 1 << 30
    assert default_reserve_bytes(20 << 30) == 2 << 30
    assert default_reserve_bytes(0) == 1 << 30


def test_cgroup_v2_limit(tmp_path):
    cgroup = tmp_path / "cgroup"
    cgroup.mkdir()
    (cgroup / "memory.max").write_text("5000000000\n")
    (cgroup / "memory.current").write_text("1000000000\n")
    available, provenance = cgroup_available_bytes(cgroup)
    assert available == 4000000000
    assert provenance == "cgroup v2"


def test_cgroup_v2_nested_limit_at_intermediate(tmp_path):
    cgroup = tmp_path / "cgroup"
    leaf = cgroup / "user.slice" / "user-1000.slice" / "session.scope"
    leaf.mkdir(parents=True)
    (leaf / "memory.max").write_text("max\n")
    (leaf / "memory.current").write_text("1000000000\n")

    intermediate = cgroup / "user.slice"
    (intermediate / "memory.max").write_text("5000000000\n")
    (intermediate / "memory.current").write_text("1000000000\n")

    self_cgroup = tmp_path / "self_cgroup"
    self_cgroup.write_text("0::/user.slice/user-1000.slice/session.scope\n")

    available, provenance = cgroup_available_bytes(cgroup, self_cgroup=self_cgroup)
    assert available == 4000000000
    assert provenance == "cgroup v2 limit at /user.slice"


def test_cgroup_v2_max_all_levels(tmp_path):
    cgroup = tmp_path / "cgroup"
    for directory in (cgroup, cgroup / "user.slice"):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "memory.max").write_text("max\n")
        (directory / "memory.current").write_text("0\n")

    self_cgroup = tmp_path / "self_cgroup"
    self_cgroup.write_text("0::/user.slice\n")

    available, provenance = cgroup_available_bytes(cgroup, self_cgroup=self_cgroup)
    assert available is None
    assert provenance == "cgroup v2: no limit"


def test_cgroup_v2_current_above_max_clamped_to_zero(tmp_path):
    cgroup = tmp_path / "cgroup"
    cgroup.mkdir()
    (cgroup / "memory.max").write_text("1000000000\n")
    (cgroup / "memory.current").write_text("2000000000\n")
    available, provenance = cgroup_available_bytes(cgroup)
    assert available == 0
    assert provenance == "cgroup v2"


def test_cgroup_v1(tmp_path):
    cgroup = tmp_path / "cgroup"
    (cgroup / "memory").mkdir(parents=True)
    (cgroup / "memory" / "memory.limit_in_bytes").write_text("4000000000\n")
    (cgroup / "memory" / "memory.usage_in_bytes").write_text("1000000000\n")
    available, provenance = cgroup_available_bytes(cgroup)
    assert available == 3000000000
    assert provenance == "cgroup v1"


def test_cgroup_v1_memory_controller_comma_list(tmp_path):
    cgroup = tmp_path / "cgroup"
    mem = cgroup / "memory" / "user.slice"
    mem.mkdir(parents=True)
    (mem / "memory.limit_in_bytes").write_text("4000000000\n")
    (mem / "memory.usage_in_bytes").write_text("1000000000\n")

    self_cgroup = tmp_path / "self_cgroup"
    self_cgroup.write_text("7:cpu,memory:/user.slice\n")

    available, provenance = cgroup_available_bytes(cgroup, self_cgroup=self_cgroup)
    assert available == 3000000000
    assert provenance == "cgroup v1 limit at /user.slice"


def test_cgroup_v1_no_limit(tmp_path):
    cgroup = tmp_path / "cgroup"
    (cgroup / "memory").mkdir(parents=True)
    (cgroup / "memory" / "memory.limit_in_bytes").write_text(f"{1 << 60}\n")
    (cgroup / "memory" / "memory.usage_in_bytes").write_text("0\n")
    available, provenance = cgroup_available_bytes(cgroup)
    assert available is None
    assert provenance == "cgroup v1: no limit"


def test_cgroup_self_cgroup_missing_falls_back_to_root(tmp_path):
    cgroup = tmp_path / "cgroup"
    cgroup.mkdir()
    (cgroup / "memory.max").write_text("3000000000\n")
    (cgroup / "memory.current").write_text("1000000000\n")

    missing = tmp_path / "missing_self_cgroup"

    available, provenance = cgroup_available_bytes(cgroup, self_cgroup=missing)
    assert available == 2000000000
    assert provenance == "cgroup v2"


def test_compute_budget_clamp():
    system_pool = hostmem.Pool(
        kind="system",
        total_bytes=16 << 30,
        available_bytes=8 << 30,
        provenance="/proc/meminfo",
        unknown_reason=None,
    )
    budget = compute_budget(
        system_pool=system_pool,
        accelerators=(),
        cgroup_available=3 << 30,
    )
    reserve = default_reserve_bytes(16 << 30)
    assert budget.system.available_bytes == 3 << 30
    assert budget.system.provenance == "/proc/meminfo + cgroup clamp"
    assert budget.system.budget_bytes == (3 << 30) - reserve


def test_compute_budget_unified_ignores_device_pools():
    vram_pool = hostmem.Pool(
        kind="vram",
        total_bytes=8 << 30,
        available_bytes=4 << 30,
        provenance="torch",
        unknown_reason=None,
    )
    accel = hostmem.MemoryClassification(
        state="unified",
        pools=(vram_pool,),
        evidence="cuda integrated",
        unknown_reason=None,
    )
    system_pool = hostmem.Pool(
        kind="system",
        total_bytes=16 << 30,
        available_bytes=8 << 30,
        provenance="/proc/meminfo",
        unknown_reason=None,
    )
    budget = compute_budget(system_pool=system_pool, accelerators=(accel,))
    assert budget.topology == "unified"
    assert budget.devices == ()
    assert any("shared" in note for note in budget.notes)


def test_compute_budget_discrete_device_domain():
    vram_pool = hostmem.Pool(
        kind="vram",
        total_bytes=16 << 30,
        available_bytes=8 << 30,
        provenance="nvml",
        unknown_reason=None,
    )
    accel = hostmem.MemoryClassification(
        state="discrete",
        pools=(vram_pool,),
        evidence="nvml",
        unknown_reason=None,
    )
    system_pool = hostmem.Pool(
        kind="system",
        total_bytes=32 << 30,
        available_bytes=16 << 30,
        provenance="/proc/meminfo",
        unknown_reason=None,
    )
    budget = compute_budget(system_pool=system_pool, accelerators=(accel,))
    assert budget.topology == "discrete"
    assert len(budget.devices) == 1
    device = budget.devices[0]
    assert device.name == "device:0"
    expected_reserve = max(256 << 20, int((16 << 30) * 0.05))
    assert device.reserve_bytes == expected_reserve
    assert device.budget_bytes == (8 << 30) - expected_reserve


def test_compute_budget_unknown_never_promoted():
    vram_pool = hostmem.Pool(
        kind="vram",
        total_bytes=8 << 30,
        available_bytes=4 << 30,
        provenance="torch",
        unknown_reason=None,
    )
    accel = hostmem.MemoryClassification(
        state="unknown",
        pools=(vram_pool,),
        evidence="none",
        unknown_reason="NVML unavailable",
    )
    system_pool = hostmem.Pool(
        kind="system",
        total_bytes=16 << 30,
        available_bytes=8 << 30,
        provenance="/proc/meminfo",
        unknown_reason=None,
    )
    budget = compute_budget(system_pool=system_pool, accelerators=(accel,))
    assert budget.topology == "unknown"
    assert budget.devices == ()
    assert any("no device-memory guarantees" in note for note in budget.notes)


def test_compute_budget_cpu_only():
    system_pool = hostmem.Pool(
        kind="system",
        total_bytes=16 << 30,
        available_bytes=8 << 30,
        provenance="/proc/meminfo",
        unknown_reason=None,
    )
    budget = compute_budget(system_pool=system_pool, accelerators=())
    assert budget.topology == "cpu_only"
    assert budget.devices == ()


def test_compute_budget_unknown_system_available():
    system_pool = hostmem.Pool(
        kind="system",
        total_bytes=16 << 30,
        available_bytes=None,
        provenance="/proc/meminfo",
        unknown_reason="meminfo unreadable",
    )
    budget = compute_budget(system_pool=system_pool, accelerators=())
    assert budget.system.budget_bytes is None
    assert budget.system.unknown_reason == "meminfo unreadable"


def test_residency_budget_to_dict_round_trip():
    domain = MemoryDomain(
        name="system",
        total_bytes=16 << 30,
        available_bytes=8 << 30,
        reserve_bytes=1 << 30,
        provenance="/proc/meminfo",
        unknown_reason=None,
    )
    budget = ResidencyBudget(
        topology="cpu_only",
        system=domain,
        devices=(),
        notes=("note one", "note two"),
    )
    dumped = json.dumps(budget.to_dict())
    loaded = json.loads(dumped)
    assert loaded["topology"] == "cpu_only"
    assert loaded["system"]["budget_bytes"] == (8 << 30) - (1 << 30)
    assert loaded["notes"] == ["note one", "note two"]
