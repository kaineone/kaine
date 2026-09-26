# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for wiring operator revive and preserve into the cycle entrypoint."""
from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
import pytest_asyncio

from kaine.cycle.__main__ import (
    _revive_or_refuse,
    _start_preserve_watcher,
    _write_runtime_state,
)
from kaine.cycle.preserve_watch import new_request, write_request
from kaine.cycle.research_gate import _NullBus
from kaine.cycle.revive_boot import ReviveSession, prepare_revive
from kaine.lifecycle import stage
from kaine.lifecycle.manager import ForkManager
from kaine.lifecycle.preservation import bundle_dir_for
from kaine.modules.eidolon import Eidolon, SelfModel
from kaine.modules.registry import ModuleRegistry

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SHIPPED_CONFIG = _REPO_ROOT / "config" / "kaine.toml"


class _ExtraModule:
    name = "extra"

    def __init__(self):
        self.counter = 0

    def serialize(self):
        return {"counter": self.counter}

    def deserialize(self, state):
        self.counter = state["counter"]


def _hermetic_cwd(tmp_path: Path, monkeypatch) -> None:
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_SHIPPED_CONFIG, cfg_dir / "kaine.toml")
    monkeypatch.chdir(tmp_path)


@pytest_asyncio.fixture
async def bus():
    yield _NullBus()


@pytest_asyncio.fixture
async def eidolon(tmp_path, bus):
    eid = Eidolon(bus, persistence_path=tmp_path / "sm.json", save_interval_s=60)
    await eid.initialize()
    eid._model = SelfModel(name="revive-entrypoint-test", values=["continuity"])
    yield eid
    try:
        await eid.shutdown()
    except Exception:
        pass


async def _make_bundle(
    tmp_path: Path,
    eidolon: Eidolon,
    *,
    stage_state: stage.StageState | None = None,
    registry: ModuleRegistry | None = None,
) -> Path:
    reg = registry or ModuleRegistry()
    if registry is None:
        reg.register(eidolon)
    if stage_state is not None:
        stage.write_stage(stage_state)
    fork_root = tmp_path / "forks"
    out_root = tmp_path / "backups"
    fm = ForkManager(fork_root)
    result = await fm.preserve_live(
        reg,
        reason="revive-entrypoint-test",
        label="test",
        out_root=out_root,
        entity_name="entrypoint-entity",
    )
    assert result.ok
    return out_root / f"preservation_{result.preservation_id}_entrypoint-entity"


def _replace_stage(plan, stage_value):
    return replace(plan, stage=stage_value)


@pytest.mark.asyncio
async def test_revive_session_apply_writes_stage_and_rollback_restores_bytes(
    tmp_path, eidolon, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    stage_path = tmp_path / "lifecycle-stage.json"
    monkeypatch.setattr(stage, "STAGE_PATH", stage_path)

    bundle = await _make_bundle(
        tmp_path, eidolon, stage_state=stage.StageState(stage="gestation", lived_seconds=0.0)
    )
    plan = prepare_revive(bundle)

    prior = stage.StageState(stage="embodied", lived_seconds=42.0)
    stage.write_stage(prior, stage_path)
    prior_bytes = stage_path.read_bytes()

    revive = ReviveSession(plan)
    revive.apply()
    assert stage_path.read_bytes() != prior_bytes
    written = json.loads(stage_path.read_text())
    assert written["stage"] == "gestation"

    revive.rollback()
    assert stage_path.read_bytes() == prior_bytes

    # Rollback is idempotent.
    revive.rollback()
    assert stage_path.read_bytes() == prior_bytes


@pytest.mark.asyncio
async def test_revive_session_rollback_removes_file_when_no_prior_stage(
    tmp_path, eidolon, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    stage_path = tmp_path / "stage.json"
    monkeypatch.setattr(stage, "STAGE_PATH", stage_path)

    bundle = await _make_bundle(
        tmp_path, eidolon, stage_state=stage.StageState(stage="gestation", lived_seconds=0.0)
    )
    plan = prepare_revive(bundle)
    # Simulate the no-prior-stage case.
    if stage_path.exists():
        stage_path.unlink()

    revive = ReviveSession(plan)
    revive.apply()
    assert stage_path.exists()

    revive.rollback()
    assert not stage_path.exists()

    # Idempotent: still absent.
    revive.rollback()
    assert not stage_path.exists()


@pytest.mark.asyncio
async def test_revive_session_rollback_noop_after_landed(tmp_path, eidolon, bus, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stage_path = tmp_path / "stage.json"
    monkeypatch.setattr(stage, "STAGE_PATH", stage_path)

    bundle = await _make_bundle(
        tmp_path, eidolon, stage_state=stage.StageState(stage="gestation", lived_seconds=1.0)
    )
    plan = prepare_revive(bundle)

    prior = stage.StageState(stage="embodied", lived_seconds=99.0)
    stage.write_stage(prior, stage_path)
    prior_bytes = stage_path.read_bytes()

    reg = ModuleRegistry()
    eid2 = Eidolon(bus, persistence_path=tmp_path / "sm2.json", save_interval_s=60)
    await eid2.initialize()
    reg.register(eid2)

    revive = ReviveSession(plan)
    revive.apply()
    await revive.revive(reg)
    assert revive.landed

    revive.rollback()
    assert stage_path.read_bytes() != prior_bytes
    await eid2.shutdown()


def test_main_missing_revive_bundle_returns_seven_no_boot(tmp_path, monkeypatch):
    _hermetic_cwd(tmp_path, monkeypatch)
    monkeypatch.setenv("KAINE_CYCLE_OPERATOR_PRESENT", "1")

    import kaine.cycle.__main__ as cycle_main

    calls = []

    async def _fake_boot(**kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(cycle_main, "_boot_and_run", _fake_boot)

    rc = cycle_main.main(["--revive", str(tmp_path / "missing")])
    assert rc == 7
    assert calls == []
    assert not (tmp_path / "state" / "lifecycle" / "stage.json").exists()


def test_main_revive_restores_stage_on_boot_failure(tmp_path, eidolon, monkeypatch):
    _hermetic_cwd(tmp_path, monkeypatch)
    monkeypatch.setenv("KAINE_CYCLE_OPERATOR_PRESENT", "1")

    stage_path = tmp_path / "lifecycle" / "stage.json"
    monkeypatch.setattr(stage, "STAGE_PATH", stage_path)
    stage_path.parent.mkdir(parents=True, exist_ok=True)

    bundle = asyncio.run(
        _make_bundle(
            tmp_path,
            eidolon,
            stage_state=stage.StageState(stage="gestation", lived_seconds=0.0),
        )
    )

    prior = stage.StageState(stage="embodied", lived_seconds=77.0)
    stage.write_stage(prior, stage_path)
    prior_bytes = stage_path.read_bytes()

    import kaine.cycle.__main__ as cycle_main

    captured: dict[str, object] = {}

    async def _fake_boot(**kwargs):
        captured["kwargs"] = kwargs
        captured["stage_bytes"] = stage_path.read_bytes()
        raise RuntimeError("boom")

    monkeypatch.setattr(cycle_main, "_boot_and_run", _fake_boot)

    with pytest.raises(RuntimeError, match="boom"):
        cycle_main.main(["--revive", str(bundle)])

    assert isinstance(captured["kwargs"].get("revive"), ReviveSession)
    assert json.loads(captured["stage_bytes"])["stage"] == "gestation"
    assert stage_path.read_bytes() == prior_bytes


def test_main_revive_invalid_stage_returns_seven_and_leaves_stage(
    tmp_path, eidolon, monkeypatch
):
    _hermetic_cwd(tmp_path, monkeypatch)
    monkeypatch.setenv("KAINE_CYCLE_OPERATOR_PRESENT", "1")

    stage_path = tmp_path / "lifecycle" / "stage.json"
    monkeypatch.setattr(stage, "STAGE_PATH", stage_path)
    stage_path.parent.mkdir(parents=True, exist_ok=True)

    bundle = asyncio.run(
        _make_bundle(
            tmp_path,
            eidolon,
            stage_state=stage.StageState(stage="gestation", lived_seconds=0.0),
        )
    )

    prior = stage.StageState(stage="embodied", lived_seconds=55.0)
    stage.write_stage(prior, stage_path)
    prior_bytes = stage_path.read_bytes()

    import kaine.cycle.revive_boot as revive_boot

    monkeypatch.setattr(revive_boot, "read_bundle_stage", lambda _bundle: "not-a-stage")

    import kaine.cycle.__main__ as cycle_main

    calls = []

    async def _fake_boot(**kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(cycle_main, "_boot_and_run", _fake_boot)

    rc = cycle_main.main(["--revive", str(bundle)])
    assert rc == 7
    assert calls == []
    assert stage_path.read_bytes() == prior_bytes


@pytest.mark.asyncio
async def test_revive_or_refuse_exits_7_on_missing_captured_module(tmp_path, bus, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stage_path = tmp_path / "stage.json"
    monkeypatch.setattr(stage, "STAGE_PATH", stage_path)

    eid1 = Eidolon(bus, persistence_path=tmp_path / "sm1.json", save_interval_s=60)
    await eid1.initialize()
    reg1 = ModuleRegistry()
    reg1.register(eid1)
    reg1.register(_ExtraModule())

    bundle = await _make_bundle(
        tmp_path, eid1, registry=reg1, stage_state=stage.StageState(stage="embodied")
    )

    eid2 = Eidolon(bus, persistence_path=tmp_path / "sm2.json", save_interval_s=60)
    await eid2.initialize()
    reg2 = ModuleRegistry()
    reg2.register(eid2)

    plan = prepare_revive(bundle)
    revive = ReviveSession(plan)

    shutdowns = []
    original_shutdown = eid2.shutdown

    async def recorded_shutdown():
        shutdowns.append("eid2")
        return await original_shutdown()

    eid2.shutdown = recorded_shutdown

    class FakeBus:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    fake_bus = FakeBus()

    ok = await _revive_or_refuse(revive, reg2, fake_bus)
    assert ok == 7
    assert fake_bus.closed
    assert shutdowns == ["eid2"]


@pytest.mark.asyncio
async def test_revive_or_refuse_none_when_modules_match(tmp_path, eidolon, bus, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stage_path = tmp_path / "stage.json"
    monkeypatch.setattr(stage, "STAGE_PATH", stage_path)

    bundle = await _make_bundle(
        tmp_path, eidolon, stage_state=stage.StageState(stage="embodied")
    )

    eid2 = Eidolon(bus, persistence_path=tmp_path / "sm2.json", save_interval_s=60)
    await eid2.initialize()
    reg2 = ModuleRegistry()
    reg2.register(eid2)

    plan = prepare_revive(bundle)
    revive = ReviveSession(plan)

    class FakeBus:
        async def close(self):
            pass

    ok = await _revive_or_refuse(revive, reg2, FakeBus())
    assert ok is None
    assert revive.landed
    await eid2.shutdown()


@pytest.mark.asyncio
async def test_start_preserve_watcher_records_kwargs_and_bundle_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    class FakeResult:
        ok = True
        preservation_id = "pid-123"

    recorded = []

    class FakeForkManager:
        async def preserve_live(
            self, registry, *, reason, label, out_root, entity_name, require_encryption
        ):
            recorded.append(
                {
                    "reason": reason,
                    "label": label,
                    "out_root": out_root,
                    "entity_name": entity_name,
                    "require_encryption": require_encryption,
                }
            )
            return FakeResult()

    class FakeRegistry:
        pass

    class FakeCfg:
        require_encryption = True

        class divergence_monitor:
            out_root = tmp_path / "backups"
            entity_name = "test-entity"

    stop_event = asyncio.Event()
    task = _start_preserve_watcher(
        FakeRegistry(),
        FakeForkManager(),
        FakeCfg(),
        is_paused=lambda: True,
        request_stop=stop_event.set,
        stop_event=stop_event,
    )

    write_request(new_request("test-reason", stop=False))

    async def wait_for_record():
        while not recorded:
            await asyncio.sleep(0.05)

    await asyncio.wait_for(wait_for_record(), timeout=5.0)

    call = recorded[0]
    assert call["label"] == "operator"
    assert call["require_encryption"] is True
    assert call["out_root"] == FakeCfg.divergence_monitor.out_root
    assert call["entity_name"] == FakeCfg.divergence_monitor.entity_name

    expected_bundle = str(
        bundle_dir_for(
            FakeCfg.divergence_monitor.out_root,
            FakeResult.preservation_id,
            FakeCfg.divergence_monitor.entity_name,
        )
    )

    result_path = tmp_path / "state" / "cycle" / "preserve_result.json"
    assert result_path.exists()
    assert expected_bundle in result_path.read_text()

    stop_event.set()
    await asyncio.wait_for(task, timeout=5.0)


@pytest.mark.asyncio
async def test_write_runtime_state_records_revived_from(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    class FakeModule:
        name = "dummy"

        def metrics(self):
            return {}

    class FakeRegistry:
        def all_modules(self):
            return [FakeModule()]

        def metrics_summary(self):
            return {"module_count": 1}

    class FakeCycle:
        tick_index = 0
        processing_rate_hz = 1.0
        experiential_rate_hz = 1.0
        effective_experiential_rate_hz = 1.0
        access_drive = 0.0
        pacing_stats = {}
        time_scale = 1.0
        is_paused = False
        deterministic = False

        def metrics_summary(self):
            return {"ticks": 0}

    from kaine.cycle.__main__ import RUNTIME_PATH

    await _write_runtime_state(FakeCycle(), FakeRegistry(), revived_from="pid-xyz")
    data = json.loads(RUNTIME_PATH.read_text())
    assert data["revived_from"] == "pid-xyz"
