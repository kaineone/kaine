# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for operator revive boot helpers."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio

from kaine.cycle.research_gate import _NullBus
from kaine.cycle.revive_boot import (
    ReviveRefused,
    prepare_revive,
    revive_into,
)
from kaine.lifecycle.manager import ForkManager
from kaine.modules.eidolon import Eidolon, SelfModel
from kaine.modules.registry import ModuleRegistry


class _ExtraModule:
    name = "extra"

    def __init__(self):
        self.counter = 0

    def serialize(self):
        return {"counter": self.counter}

    def deserialize(self, state):
        self.counter = state["counter"]


@pytest_asyncio.fixture
async def bus():
    yield _NullBus()


@pytest_asyncio.fixture
async def eidolon(tmp_path, bus):
    eid = Eidolon(bus, persistence_path=tmp_path / "sm.json", save_interval_s=60)
    await eid.initialize()
    eid._model = SelfModel(name="revive-boot-test", values=["continuity"])
    yield eid
    try:
        await eid.shutdown()
    except Exception:
        pass


@pytest.mark.asyncio
async def test_prepare_revive_refuses_missing_directory(tmp_path):
    with pytest.raises(ReviveRefused):
        prepare_revive(tmp_path / "no-such-bundle")


@pytest.mark.asyncio
async def test_prepare_revive_refuses_directory_without_snapshot(tmp_path):
    bad = tmp_path / "bad-bundle"
    bad.mkdir()
    with pytest.raises(ReviveRefused):
        prepare_revive(bad)


@pytest.mark.asyncio
async def test_prepare_revive_reads_preservation_id(tmp_path, eidolon):
    bundle = await _make_bundle(tmp_path, eidolon)
    plan = prepare_revive(bundle)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert plan.preservation_id == manifest["preservation_id"]
    assert plan.bundle == bundle






@pytest.mark.asyncio
async def test_revive_into_restores_eidolon_and_reports_new_faculty(
    tmp_path, bus, eidolon
):
    bundle = await _make_bundle(tmp_path, eidolon)

    reg2 = ModuleRegistry()
    eid2 = Eidolon(bus, persistence_path=tmp_path / "sm2.json", save_interval_s=60)
    await eid2.initialize()
    reg2.register(eid2)
    reg2.register(_ExtraModule())

    plan = prepare_revive(bundle)
    new = await revive_into(plan, reg2)
    assert new == ["extra"]
    assert eid2.model.name == "revive-boot-test"
    assert eid2.model.values == ["continuity"]


@pytest.mark.asyncio
async def test_revive_into_refuses_missing_captured_module(tmp_path, bus, eidolon):
    reg = ModuleRegistry()
    reg.register(eidolon)
    reg.register(_ExtraModule())
    bundle = await _make_bundle(tmp_path, eidolon, registry=reg)

    reg2 = ModuleRegistry()
    eid2 = Eidolon(bus, persistence_path=tmp_path / "sm2.json", save_interval_s=60)
    await eid2.initialize()
    reg2.register(eid2)

    plan = prepare_revive(bundle)
    with pytest.raises(ReviveRefused):
        await revive_into(plan, reg2)


async def _make_bundle(
    tmp_path, eidolon, *, registry: ModuleRegistry | None = None
) -> Path:
    reg = registry or ModuleRegistry()
    if registry is None:
        reg.register(eidolon)
    fork_root = tmp_path / "forks"
    out_root = tmp_path / "backups"
    fm = ForkManager(fork_root)
    result = await fm.preserve_live(
        reg,
        reason="revive-boot-test",
        label="boot",
        out_root=out_root,
        entity_name="boot-entity",
    )
    assert result.ok
    return out_root / f"preservation_{result.preservation_id}_boot-entity"


def _replace_stage(plan, stage):
    from dataclasses import replace
    return replace(plan, stage=stage)
