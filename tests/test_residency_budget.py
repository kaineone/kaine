# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for kaine.residency.budget."""

from __future__ import annotations

import sys

from kaine.hostmem import MemoryClassification, Pool
from kaine.residency.budget import (
    CgroupMemory,
    cgroup_memory,
    current_budgets,
    default_reserve_bytes,
    derive_budgets,
)


def test_default_reserve_bytes():
    assert default_reserve_bytes(4 * GIB) == GIB
    assert default_reserve_bytes(8 * GIB) == GIB
    assert default_reserve_bytes(64 * GIB) == 64 * GIB // 10  # 10% beats the 1 GiB floor


def test_cgroup_v2_limited(tmp_path):
    root = tmp_path / "cgroup"
    root.mkdir()
    (root / "memory.max").write_text("2147483648\n")
    (root / "memory.current").write_text("1073741824\n")
    proc = tmp_path / "proc_self_cgroup"
    proc.write_text("0::/\n")
    mem = cgroup_memory(proc_cgroup_path=str(proc), cgroup_root=str(root))
    assert mem.limit_bytes == 2 * GIB
    assert mem.usage_bytes == GIB
    assert "v2" in mem.provenance


def test_cgroup_v2_max(tmp_path):
    root = tmp_path / "cgroup"
    root.mkdir()
    (root / "memory.max").write_text("max\n")
    (root / "memory.current").write_text("100\n")
    proc = tmp_path / "proc_self_cgroup"
    proc.write_text("0::/\n")
    mem = cgroup_memory(proc_cgroup_path=str(proc), cgroup_root=str(root))
    assert mem.limit_bytes is None
    assert mem.usage_bytes == 100
    assert "limit=max" in mem.provenance


def test_cgroup_v1_limited(tmp_path):
    root = tmp_path / "cgroup"
    (root / "memory").mkdir(parents=True)
    (root / "memory" / "memory.limit_in_bytes").write_text("4294967296\n")
    (root / "memory" / "memory.usage_in_bytes").write_text("536870912\n")
    proc = tmp_path / "proc_self_cgroup"
    proc.write_text("12:memory:/\n")
    mem = cgroup_memory(proc_cgroup_path=str(proc), cgroup_root=str(root))
    assert mem.limit_bytes == 4 * GIB
    assert mem.usage_bytes == 512 * MIB
    assert "v1" in mem.provenance


def test_cgroup_v1_unlimited(tmp_path):
    root = tmp_path / "cgroup"
    (root / "memory").mkdir(parents=True)
    (root / "memory" / "memory.limit_in_bytes").write_text("9223372036854771712\n")
    (root / "memory" / "memory.usage_in_bytes").write_text("0\n")
    proc = tmp_path / "proc_self_cgroup"
    proc.write_text("12:memory:/\n")
    mem = cgroup_memory(proc_cgroup_path=str(proc), cgroup_root=str(root))
    assert mem.limit_bytes is None
    assert "huge treated as unlimited" in mem.provenance


def test_cgroup_root_path(tmp_path):
    root = tmp_path / "cgroup"
    root.mkdir()
    (root / "memory.max").write_text("1073741824\n")
    (root / "memory.current").write_text("0\n")
    proc = tmp_path / "proc_self_cgroup"
    proc.write_text("0::/\n")
    mem = cgroup_memory(proc_cgroup_path=str(proc), cgroup_root=str(root))
    assert mem.limit_bytes == GIB


def test_cgroup_missing_files(tmp_path):
    proc = tmp_path / "proc_self_cgroup"
    proc.write_text("0::/\n")
    mem = cgroup_memory(proc_cgroup_path=str(proc), cgroup_root=str(tmp_path))
    assert mem.limit_bytes is None
    assert mem.usage_bytes is None
    assert "unreadable" in mem.provenance


def test_system_budget_from_pool():
    pool = Pool(
        kind="system",
        total_bytes=8 * GIB,
        available_bytes=7 * GIB,
        provenance="meminfo",
        unknown_reason=None,
    )
    cgroup = CgroupMemory(limit_bytes=None, usage_bytes=None, provenance="none")
    domains = derive_budgets(system_pool=pool, cgroup=cgroup)
    system = domains[0]
    assert system.name == "system"
    assert system.budget_bytes == 6 * GIB
    assert "8.00" in system.derivation


def test_cgroup_clamp_lowers_available_and_total():
    pool = Pool(
        kind="system",
        total_bytes=8 * GIB,
        available_bytes=7 * GIB,
        provenance="meminfo",
        unknown_reason=None,
    )
    cgroup = CgroupMemory(limit_bytes=6 * GIB, usage_bytes=1 * GIB, provenance="v2")
    domains = derive_budgets(system_pool=pool, cgroup=cgroup)
    system = domains[0]
    assert system.total_bytes == 6 * GIB
    assert system.available_bytes == 5 * GIB  # min(7 GiB, 6-1 GiB)
    assert system.budget_bytes == 4 * GIB


def test_discrete_accelerator_adds_device_domain():
    pool = Pool(
        kind="system",
        total_bytes=64 * GIB,
        available_bytes=60 * GIB,
        provenance="meminfo",
        unknown_reason=None,
    )
    vram = Pool(
        kind="vram",
        total_bytes=24 * GIB,
        available_bytes=20 * GIB,
        provenance="cuda",
        unknown_reason=None,
    )
    classification = MemoryClassification(
        state="discrete", pools=(vram,), evidence="ladder", unknown_reason=None
    )
    domains = derive_budgets(
        system_pool=pool,
        cgroup=CgroupMemory(None, None, "none"),
        accelerators=(("cuda:0", classification),),
    )
    assert len(domains) == 2
    assert domains[1].name == "cuda:0"
    assert domains[1].budget_bytes == 20 * GIB - 24 * GIB // 10  # 20 GiB - 10% of 24 GiB


def test_unified_accelerator_no_device_domain():
    pool = Pool(
        kind="system",
        total_bytes=8 * GIB,
        available_bytes=7 * GIB,
        provenance="meminfo",
        unknown_reason=None,
    )
    vram = Pool(
        kind="vram",
        total_bytes=8 * GIB,
        available_bytes=7 * GIB,
        provenance="cuda",
        unknown_reason=None,
    )
    classification = MemoryClassification(
        state="unified", pools=(vram,), evidence="ladder", unknown_reason=None
    )
    domains = derive_budgets(
        system_pool=pool,
        cgroup=CgroupMemory(None, None, "none"),
        accelerators=(("cuda:0", classification),),
    )
    assert len(domains) == 1
    assert "shares system memory" in domains[0].derivation
    assert domains[0].budget_bytes == 6 * GIB


def test_unknown_accelerator_no_device_domain():
    pool = Pool(
        kind="system",
        total_bytes=8 * GIB,
        available_bytes=7 * GIB,
        provenance="meminfo",
        unknown_reason=None,
    )
    classification = MemoryClassification(
        state="unknown", pools=(), evidence="ladder", unknown_reason="no torch"
    )
    domains = derive_budgets(
        system_pool=pool,
        cgroup=CgroupMemory(None, None, "none"),
        accelerators=(("cuda:0", classification),),
    )
    assert len(domains) == 1
    assert "memory state unknown" in domains[0].derivation


def test_unknown_available_gives_none_budget():
    pool = Pool(
        kind="system",
        total_bytes=8 * GIB,
        available_bytes=None,
        provenance="meminfo",
        unknown_reason="no meminfo",
    )
    domains = derive_budgets(
        system_pool=pool,
        cgroup=CgroupMemory(None, None, "none"),
    )
    assert domains[0].budget_bytes is None


def test_current_budgets_without_torch(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)

    def fake_system_memory_pool():
        return Pool(
            kind="system",
            total_bytes=8 * GIB,
            available_bytes=7 * GIB,
            provenance="meminfo",
            unknown_reason=None,
        )

    monkeypatch.setattr(
        "kaine.residency.budget.system_memory_pool", fake_system_memory_pool
    )
    monkeypatch.setattr(
        "kaine.residency.budget.cgroup_memory",
        lambda: CgroupMemory(None, None, "mock"),
    )

    domains = current_budgets()
    assert len(domains) == 1
    assert domains[0].name == "system"
    assert domains[0].budget_bytes == 6 * GIB
    assert "cuda" not in domains[0].derivation


GIB = 1 << 30
MIB = 1 << 20


def test_cgroup_hybrid_prefers_v1_memory_controller(tmp_path):
    root = tmp_path / "cgroup"
    (root / "memory").mkdir(parents=True)
    (root / "memory" / "memory.limit_in_bytes").write_text("2147483648\n")
    (root / "memory" / "memory.usage_in_bytes").write_text("0\n")
    proc = tmp_path / "proc_self_cgroup"
    proc.write_text("12:memory:/\n0::/\n")
    mem = cgroup_memory(proc_cgroup_path=str(proc), cgroup_root=str(root))
    assert mem.limit_bytes == 2 * GIB
    assert "v1" in mem.provenance
