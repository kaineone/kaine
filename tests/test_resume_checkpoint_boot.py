# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for wiring the rolling resume checkpoint into boot and shutdown."""

import asyncio
import inspect
import types

import pytest

import kaine.cycle.__main__ as cyc
from kaine.cycle.boot_context import BootContext
from kaine.cycle.revive_boot import REVIVE_REFUSED_EXIT
from kaine.lifecycle import resume_checkpoint as rc
from kaine.lifecycle.identity import mint_identity
from kaine.modules.registry import ModuleRegistry


class FakeModule:
    def __init__(self, name, state=None):
        self.name = name
        self.state = dict(state or {})
        self.deserialized = []
        self.initialized = False
        self.shutdown_called = False

    async def initialize(self):
        self.initialized = True

    async def shutdown(self):
        self.shutdown_called = True

    def serialize(self):
        return dict(self.state)

    def deserialize(self, state):
        self.deserialized.append(dict(state))
        self.state = dict(state)


def _make_ctx(identity, registry, monkeypatch, *, revive=None):
    ctx = BootContext(kaine_config={})
    ctx.bus = None
    ctx.plugins = None
    ctx.staging_enabled = False
    ctx.stage_state = None
    ctx.identity = identity
    ctx.revive = revive
    ctx.welfare_producer = None
    monkeypatch.setattr(cyc, "build_registry", lambda *a, **k: registry)
    return ctx


@pytest.mark.asyncio
async def test_plain_start_restores_checkpoint(monkeypatch) -> None:
    ident = mint_identity()
    reg_old = ModuleRegistry()
    reg_old.register(FakeModule("vocal", {"v": 1}))
    assert await rc.save_checkpoint(reg_old, ident, reason="periodic")

    reg = ModuleRegistry()
    mod = FakeModule("vocal", {})
    reg.register(mod)

    ctx = _make_ctx(ident, reg, monkeypatch, revive=None)
    result = await cyc._phase_registry(ctx)
    assert result is None
    assert mod.initialized is True
    assert mod.state == {"v": 1}
    assert mod.deserialized == [{"v": 1}]


@pytest.mark.asyncio
async def test_plain_start_ignores_other_identity_checkpoint(monkeypatch) -> None:
    ident_a = mint_identity()
    ident_b = mint_identity()

    reg_old = ModuleRegistry()
    reg_old.register(FakeModule("vocal", {"v": 1}))
    await rc.save_checkpoint(reg_old, ident_a, reason="periodic")
    before = rc.checkpoint_file().read_bytes()

    reg = ModuleRegistry()
    mod = FakeModule("vocal", {})
    reg.register(mod)

    ctx = _make_ctx(ident_b, reg, monkeypatch, revive=None)
    assert await cyc._phase_registry(ctx) is None
    assert mod.state == {}
    assert mod.deserialized == []
    assert rc.checkpoint_file().read_bytes() == before


@pytest.mark.asyncio
async def test_revive_wins_over_stale_checkpoint(monkeypatch) -> None:
    ident = mint_identity()

    reg_old = ModuleRegistry()
    reg_old.register(FakeModule("vocal", {"v": 1}))
    await rc.save_checkpoint(reg_old, ident, reason="periodic")

    reg = ModuleRegistry()
    mod = FakeModule("vocal", {})
    reg.register(mod)

    async def fake_apply(revive, registry, state_root):
        registry.get("vocal").state = {"v": 2}
        return None

    monkeypatch.setattr(cyc, "_apply_revive", fake_apply)

    ctx = _make_ctx(ident, reg, monkeypatch, revive=object())
    assert await cyc._phase_registry(ctx) is None
    assert mod.deserialized == []
    snap = rc.read_checkpoint()
    assert snap is not None
    assert snap.modules["vocal"] == {"v": 2}

    # A later plain start must see the revived state, not the stale checkpoint.
    reg2 = ModuleRegistry()
    mod2 = FakeModule("vocal", {})
    reg2.register(mod2)
    ctx2 = _make_ctx(ident, reg2, monkeypatch, revive=None)
    assert await cyc._phase_registry(ctx2) is None
    assert mod2.state == {"v": 2}


@pytest.mark.asyncio
async def test_revive_wins_even_when_replace_fails(monkeypatch) -> None:
    ident = mint_identity()

    reg_old = ModuleRegistry()
    reg_old.register(FakeModule("vocal", {"v": 1}))
    await rc.save_checkpoint(reg_old, ident, reason="periodic")

    def boom(snap, directory=None):
        raise OSError("disk")

    monkeypatch.setattr(rc, "write_checkpoint", boom)

    reg = ModuleRegistry()
    mod = FakeModule("vocal", {})
    reg.register(mod)

    async def fake_apply(revive, registry, state_root):
        registry.get("vocal").state = {"v": 2}
        return None

    monkeypatch.setattr(cyc, "_apply_revive", fake_apply)

    ctx = _make_ctx(ident, reg, monkeypatch, revive=object())
    assert await cyc._phase_registry(ctx) is None
    assert not rc.checkpoint_file().exists()


@pytest.mark.asyncio
async def test_revive_refuses_when_checkpoint_cannot_be_replaced_or_removed(monkeypatch) -> None:
    ident = mint_identity()

    reg_old = ModuleRegistry()
    reg_old.register(FakeModule("vocal", {"v": 1}))
    await rc.save_checkpoint(reg_old, ident, reason="periodic")

    def boom(snap, directory=None):
        raise OSError("disk")

    monkeypatch.setattr(rc, "write_checkpoint", boom)
    monkeypatch.setattr(rc, "discard_checkpoint", lambda directory=None: False)

    reg = ModuleRegistry()
    mod = FakeModule("vocal", {})
    reg.register(mod)

    async def fake_apply(revive, registry, state_root):
        registry.get("vocal").state = {"v": 2}
        return None

    monkeypatch.setattr(cyc, "_apply_revive", fake_apply)

    stopped = []
    async def noop_welfare(w):
        stopped.append(w)

    monkeypatch.setattr(cyc, "_stop_welfare_producer", noop_welfare)

    ctx = _make_ctx(ident, reg, monkeypatch, revive=object())
    ctx.welfare_producer = object()

    class FakeBus:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    ctx.bus = FakeBus()

    result = await cyc._phase_registry(ctx)
    assert result == REVIVE_REFUSED_EXIT
    assert mod.shutdown_called is True
    assert ctx.bus.closed is True
    assert stopped == [ctx.welfare_producer]


@pytest.mark.asyncio
async def test_revive_refused_when_set_aside_fails(monkeypatch) -> None:
    ident = mint_identity()

    reg_old = ModuleRegistry()
    reg_old.register(FakeModule("vocal", {"v": 1}))
    await rc.save_checkpoint(reg_old, ident, reason="periodic")

    apply_called = [False]
    async def fake_apply(revive, registry, state_root):
        apply_called[0] = True
        return None

    monkeypatch.setattr(cyc, "_apply_revive", fake_apply)
    monkeypatch.setattr(rc, "set_aside_for_revive", lambda *args, **kwargs: False)

    stopped = []
    async def noop_welfare(w):
        stopped.append(w)

    monkeypatch.setattr(cyc, "_stop_welfare_producer", noop_welfare)

    reg = ModuleRegistry()
    mod = FakeModule("vocal", {})
    reg.register(mod)

    ctx = _make_ctx(ident, reg, monkeypatch, revive=object())
    ctx.welfare_producer = object()

    class FakeBus:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    ctx.bus = FakeBus()

    result = await cyc._phase_registry(ctx)
    assert result == REVIVE_REFUSED_EXIT
    assert apply_called[0] is False
    assert mod.shutdown_called is True
    assert ctx.bus.closed is True
    assert stopped == [ctx.welfare_producer]


@pytest.mark.asyncio
async def test_refused_revive_sets_the_checkpoint_aside(monkeypatch) -> None:
    ident = mint_identity()

    reg_old = ModuleRegistry()
    reg_old.register(FakeModule("vocal", {"v": 1}))
    await rc.save_checkpoint(reg_old, ident, reason="periodic")
    before = rc.checkpoint_file().read_bytes()

    async def partial_then_refuse(revive, registry, state_root):
        registry.get("vocal").state = {"v": 2}
        return 7

    async def noop_welfare(w):
        return None

    monkeypatch.setattr(cyc, "_apply_revive", partial_then_refuse)
    monkeypatch.setattr(cyc, "_stop_welfare_producer", noop_welfare)

    reg = ModuleRegistry()
    reg.register(FakeModule("vocal", {}))
    ctx = _make_ctx(ident, reg, monkeypatch, revive=object())
    ctx.welfare_producer = object()

    async def close_bus():
        return None

    ctx.bus = types.SimpleNamespace(close=close_bus)

    result = await cyc._phase_registry(ctx)
    assert result == 7
    assert not rc.checkpoint_file().exists()
    aside = rc.checkpoint_file().with_name(rc.ASIDE_FILENAME)
    assert aside.exists()
    assert aside.read_bytes() == before

    # A later plain start must not lay the set-aside stale checkpoint over fresh modules.
    reg2 = ModuleRegistry()
    mod2 = FakeModule("vocal", {})
    reg2.register(mod2)
    ctx2 = _make_ctx(ident, reg2, monkeypatch, revive=None)
    assert await cyc._phase_registry(ctx2) is None
    assert mod2.state == {}
    assert mod2.deserialized == []


@pytest.mark.asyncio
async def test_revive_record_guards_a_stale_checkpoint(monkeypatch) -> None:
    ident = mint_identity()

    reg_old = ModuleRegistry()
    reg_old.register(FakeModule("vocal", {"v": 1}))
    await rc.save_checkpoint(reg_old, ident, reason="periodic")

    async def fake_apply(revive, registry, state_root):
        registry.get("vocal").state = {"v": 2}
        return None

    monkeypatch.setattr(cyc, "_apply_revive", fake_apply)

    reg = ModuleRegistry()
    mod = FakeModule("vocal", {})
    reg.register(mod)

    ctx = _make_ctx(ident, reg, monkeypatch, revive=object())
    assert await cyc._phase_registry(ctx) is None
    assert mod.state == {"v": 2}

    stale_bytes = rc.checkpoint_file().with_name(rc.ASIDE_FILENAME).read_bytes()
    rc.checkpoint_file().write_bytes(stale_bytes)

    reg2 = ModuleRegistry()
    mod2 = FakeModule("vocal", {})
    reg2.register(mod2)
    ctx2 = _make_ctx(ident, reg2, monkeypatch, revive=None)
    assert await cyc._phase_registry(ctx2) is None
    assert mod2.state == {}
    assert mod2.deserialized == []


@pytest.mark.asyncio
async def test_phase_checkpoint_starts_rolling_task() -> None:
    ident = mint_identity()
    reg = ModuleRegistry()
    reg.register(FakeModule("vocal", {}))

    clock = {"now": 100.0, "unawake": 0.0}
    fake_cycle = types.SimpleNamespace(
        entity_clock=types.SimpleNamespace(now=lambda: clock["now"]),
        unawake_subjective_seconds=lambda: clock["unawake"],
        is_paused=False,
        is_asleep=False,
    )

    ctx = BootContext(kaine_config={})
    ctx.cycle = fake_cycle
    ctx.registry = reg
    ctx.identity = ident

    result = await cyc._phase_checkpoint(ctx)
    assert result is None
    assert isinstance(ctx.checkpointer, rc.ResumeCheckpointer)
    assert isinstance(ctx.checkpoint_task, asyncio.Task)

    await ctx.checkpointer.stop()
    assert ctx.checkpoint_task.done()


@pytest.mark.asyncio
async def test_final_checkpoint_writes_once_when_awake(caplog) -> None:
    ident = mint_identity()
    reg = ModuleRegistry()
    reg.register(FakeModule("vocal", {"x": 1}))
    cycle = types.SimpleNamespace(is_paused=False)

    cp = rc.ResumeCheckpointer(reg, ident, awake_seconds=lambda: 5.0, can_write=lambda: True)
    cp.start()
    await cyc._final_checkpoint(cp, reg, cycle, cycle_crashed=False)

    snap = rc.read_checkpoint()
    assert snap is not None
    assert snap.metadata["reason"] == "shutdown"

    # When paused nothing is written.
    rc.discard_checkpoint()
    cp2 = rc.ResumeCheckpointer(reg, ident, awake_seconds=lambda: 5.0, can_write=lambda: True)
    cp2.start()
    paused_cycle = types.SimpleNamespace(is_paused=True)
    await cyc._final_checkpoint(cp2, reg, paused_cycle, cycle_crashed=False)
    assert not rc.checkpoint_file().exists()

    # When asleep the final checkpoint is skipped.
    rc.discard_checkpoint()

    class SleepyModule(FakeModule):
        is_sleeping = True

    reg_sleep = ModuleRegistry()
    reg_sleep.register(SleepyModule("sleep"))
    cp3 = rc.ResumeCheckpointer(
        reg_sleep, ident, awake_seconds=lambda: 5.0, can_write=lambda: True
    )
    cp3.start()
    await cyc._final_checkpoint(cp3, reg_sleep, cycle, cycle_crashed=False)
    assert not rc.checkpoint_file().exists()

    # When the cycle crashed nothing is written; a warning is logged and the periodic task is stopped.
    rc.discard_checkpoint()
    cp4 = rc.ResumeCheckpointer(reg, ident, awake_seconds=lambda: 5.0, can_write=lambda: True)
    cp4.start()
    with caplog.at_level("WARNING"):
        await cyc._final_checkpoint(cp4, reg, cycle, cycle_crashed=True)
    assert not rc.checkpoint_file().exists()
    task = getattr(cp4, "task", getattr(cp4, "_task", None))
    assert task is not None
    assert task.done()
    assert "ended with an error" in caplog.text

    # No checkpointer is a no-op.
    await cyc._final_checkpoint(None, reg, cycle, cycle_crashed=False)


@pytest.mark.asyncio
async def test_cycle_crashed() -> None:
    async def boom():
        raise RuntimeError("cycle error")

    t_err = asyncio.create_task(boom())
    try:
        await t_err
    except Exception:
        # The task's error is what this case inspects.
        pass
    assert cyc._cycle_crashed(t_err) is True

    async def ok():
        return 42

    t_ok = asyncio.create_task(ok())
    assert await t_ok == 42
    assert cyc._cycle_crashed(t_ok) is False

    t_cancel = asyncio.create_task(ok())
    t_cancel.cancel()
    try:
        await t_cancel
    except asyncio.CancelledError:
        # The cancellation is the point of this case.
        pass
    assert cyc._cycle_crashed(t_cancel) is False

    assert cyc._cycle_crashed(None) is False


def test_shutdown_order_and_failed_boot_no_checkpoint() -> None:
    shutdown_src = inspect.getsource(cyc._shutdown)
    idx_final = shutdown_src.index("_final_checkpoint(")
    assert idx_final > shutdown_src.index("ctx.cycle.shutdown()")
    assert idx_final > shutdown_src.index("await ctx.cycle_task")
    assert idx_final < shutdown_src.index("_shutdown_modules(")
    assert "_cycle_crashed(ctx.cycle_task)" in shutdown_src
    assert "checkpoint_task" not in shutdown_src

    failed_src = inspect.getsource(cyc._release_after_failed_boot)
    assert "_final_checkpoint" not in failed_src
    assert "save_checkpoint" not in failed_src


@pytest.mark.asyncio
async def test_real_modules_boot_initialize_then_restore(monkeypatch, tmp_path, fake_async_bus) -> None:
    from kaine.modules.affect.module import Affect
    from kaine.modules.self_model import SelfModel

    ident = mint_identity()

    affect1 = Affect(fake_async_bus, publish_interval_s=999.0)
    self_model1 = SelfModel(fake_async_bus, persistence_path=tmp_path / "sm.json", save_interval_s=60)

    reg1 = ModuleRegistry()
    reg1.register(affect1)
    reg1.register(self_model1)

    ctx = _make_ctx(ident, reg1, monkeypatch, revive=None)
    ctx.bus = fake_async_bus

    # The real initialize() of both modules runs on the fakeredis bus.
    result = await cyc._phase_registry(ctx)
    assert result is None
    assert self_model1._drift_count == 0

    affect1._drives.curiosity.value = 0.77
    affect1._goals.add("explore", drive="curiosity")
    self_model1._drift_count = 3

    await rc.save_checkpoint(reg1, ident, reason="shutdown")

    await affect1.shutdown()
    await self_model1.shutdown()

    affect2 = Affect(fake_async_bus, publish_interval_s=999.0)
    self_model2 = SelfModel(fake_async_bus, persistence_path=tmp_path / "sm.json", save_interval_s=60)

    reg2 = ModuleRegistry()
    reg2.register(affect2)
    reg2.register(self_model2)

    ctx2 = _make_ctx(ident, reg2, monkeypatch, revive=None)
    ctx2.bus = fake_async_bus

    result = await cyc._phase_registry(ctx2)
    assert result is None

    assert affect2._drives.curiosity.value == 0.77
    assert affect2._goals.to_dict() == affect1._goals.to_dict()
    assert self_model2._drift_count == 3

    await affect2.shutdown()
    await self_model2.shutdown()


@pytest.mark.asyncio
async def test_real_module_restart_through_resume() -> None:
    pytest.importorskip("snntorch")
    from kaine.boot import make_interoception
    from kaine.modules.affect.module import Affect

    ident = mint_identity()
    reg1 = ModuleRegistry()
    inter1 = make_interoception(types.SimpleNamespace(), {"self_rhythm_enabled": True})
    affect1 = Affect(types.SimpleNamespace(), publish_interval_s=999.0)
    reg1.register(inter1)
    reg1.register(affect1)

    await rc.save_checkpoint(reg1, ident, reason="periodic")
    # Stay inside [ln tau_min, ln tau_max]; deserialize clamps to it.
    inter1._self_rhythm._ln_tau -= 0.2
    affect1._drives.curiosity.value = 0.77
    affect1._goals.add("explore", drive="curiosity")
    await rc.save_checkpoint(reg1, ident, reason="periodic")

    reg2 = ModuleRegistry()
    inter2 = make_interoception(types.SimpleNamespace(), {"self_rhythm_enabled": True})
    affect2 = Affect(types.SimpleNamespace(), publish_interval_s=999.0)
    reg2.register(inter2)
    reg2.register(affect2)

    cyc._resume_from_checkpoint(reg2, ident)

    assert inter2._self_rhythm._ln_tau == inter1._self_rhythm._ln_tau
    assert affect2._drives.curiosity.value == affect1._drives.curiosity.value
    assert affect2._goals.to_dict() == affect1._goals.to_dict()
    assert affect2.serialize() == affect1.serialize()
