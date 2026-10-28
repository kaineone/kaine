# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""A state-cycle rest survives a process restart (change rest-resume-process-restart).

Module state is checkpointed only while awake, so the resume checkpoint never held the
rest. The checkpointer now updates just the sleep module's state_cycle entry in the last
awake checkpoint while a rest runs. These tests save a checkpoint, run a rest on a fake
entity clock, stop or crash, build a fresh registry and sleep module, restore from disk and
look at what the new process does. The bus is fakeredis.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from kaine.lifecycle.identity import mint_identity
from kaine.lifecycle.resume_checkpoint import (
    ResumeCheckpointer,
    checkpoint_file,
    read_checkpoint,
    restore_checkpoint,
    save_checkpoint,
    set_aside_for_revive,
    update_state_cycle_entry,
)
from kaine.security.crypto import CryptoConfig, StateEncryptor, is_encrypted, set_state_encryptor
from tests.test_developmental_state_cycle import (
    REST_S,
    T_ACT,
    Probe,
    SimClock,
    _REAL_SLEEP,
    _make,
    _record,
    _starts,
    bus,  # noqa: F401  (fixture)
)


class HoldClock(SimClock):
    """A fake entity clock that stands still while ``hold`` is set."""

    hold = False


@pytest.fixture
def sim(monkeypatch):
    """Every ``asyncio.sleep`` advances the entity clock unless it is held."""
    clock = HoldClock()

    async def fake_sleep(delay: float, result: Any = None) -> Any:
        if not clock.hold:
            clock.t += max(0.0, float(delay))
        await _REAL_SLEEP(0)
        return result

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return clock


class Other:
    """A module that is not the sleep module."""

    name = "other"

    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state

    def serialize(self) -> dict[str, Any]:
        return dict(self.state)

    def deserialize(self, state: dict[str, Any]) -> None:
        self.state = dict(state)


class Registry:
    def __init__(self, *modules: Any) -> None:
        self._modules = list(modules)

    def all_modules(self) -> list[Any]:
        return list(self._modules)


@pytest.fixture(autouse=True)
def _plain_state_tree():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


def _checkpointer(sleep: Any, ident: Any, directory: Path) -> ResumeCheckpointer:
    return ResumeCheckpointer(
        Registry(sleep),
        ident,
        awake_seconds=lambda: 0.0,
        can_write=lambda: False,
        directory=directory,
        rest_source=sleep.state_cycle_progress,
    )


async def _drive(sleep: Any, cp: ResumeCheckpointer, clock: HoldClock, until: float) -> None:
    """Poll the sleep module and the checkpointer once per entity second."""
    while clock.t < until:
        await sleep._maintenance_poll_once()
        # The clock stands still while the write runs in its thread, as the entity's does.
        was, clock.hold = clock.hold, True
        await cp._sync_rest()
        clock.hold = was
        if sleep.is_sleeping or sleep._sleep_pending:
            for _ in range(8):
                await _REAL_SLEEP(0)
        else:
            clock.t += 1.0


async def _awake_checkpoint(sleep: Any, other: Other, ident: Any, directory: Path) -> None:
    assert await save_checkpoint(Registry(sleep, other), ident, reason="periodic", directory=directory)


async def _to_mid_rest(bus: Any, tmp_path: Path, sim: SimClock, directory: Path, ident: Any, into_rest: float):
    """Run an awake stretch, take the awake checkpoint, then run ``into_rest`` s of rest."""
    sleep = _make(bus, tmp_path, sim, Probe(True))
    seen = _record(sleep, sim)
    other = Other({"v": 1, "nested": {"a": [1, 2, 3]}})
    cp = _checkpointer(sleep, ident, directory)
    await _drive(sleep, cp, sim, 1000.0)
    await _awake_checkpoint(sleep, other, ident, directory)
    other.state = {"v": 2, "nested": {"a": [9]}}  # moves on; the checkpoint must keep v 1
    await _drive(sleep, cp, sim, T_ACT + 20)
    began = _starts(seen, "state_cycle")[0][0]
    await _drive(sleep, cp, sim, began + into_rest)
    assert sleep.is_sleeping
    return sleep, cp, other, seen, began


def _fresh_process(bus: Any, tmp_path: Path, directory: Path, ident: Any, clock: HoldClock):
    clock.t = 0.0  # the new process's entity clock starts again
    clock.hold = False
    sleep = _make(bus, tmp_path, clock, Probe(True))
    other = Other({})
    result = restore_checkpoint(Registry(sleep, other), ident, directory)
    assert result is not None and "sleep" in result.restored
    return sleep, other, clock


async def _gate_count(bus: Any) -> int:
    from kaine.lifecycle.gate_runner import MaturationGateRunner
    from kaine.lifecycle.stage import DEVELOPMENT, StageState

    runner = object.__new__(MaturationGateRunner)
    runner._bus = bus
    runner._sleep_stream = "sleep.out"
    runner._stage = replace(StageState(stage=DEVELOPMENT), sleep_cursor="0-0", sleep_count=0)
    await runner._count_new_sleeps()
    return runner._stage.sleep_count


def _without_state_cycle(snap: Any) -> dict[str, Any]:
    modules = json.loads(json.dumps(snap.modules))
    modules["sleep"].pop("state_cycle")
    return modules


@pytest.mark.parametrize("encrypted", [False, True])
async def test_a_shutdown_mid_rest_resumes_the_remainder_after_a_process_restart(
    bus, tmp_path, sim, monkeypatch, encrypted
):
    if encrypted:
        monkeypatch.setenv("KAINE_STATE_KEY", base64.b64encode(os.urandom(32)).decode("ascii"))
        set_state_encryptor(StateEncryptor(CryptoConfig(enabled=True)))
    ident = mint_identity()
    d = tmp_path / "ckpt"
    sleep, cp, _other, _seen, _began = await _to_mid_rest(bus, tmp_path, sim, d, ident, 710.0)
    before = read_checkpoint(d)

    # Shutdown during the rest, in the boot's order: final checkpoint, then the modules.
    sim.hold = True
    assert await cp.write_final(can_write=lambda: False) is False
    await sleep.shutdown()

    if encrypted:
        raw = checkpoint_file(d).read_bytes()
        assert b"state_cycle" not in raw and is_encrypted(base64.b64decode(raw))

    after = read_checkpoint(d)
    entry = after.modules["sleep"]["state_cycle"]
    assert entry["phase"] == "resting" and entry["awake_s"] == 0.0
    assert entry["rest_spent_s"] == pytest.approx(710.0, abs=10.0)
    assert after.modules["other"] == {"v": 1, "nested": {"a": [1, 2, 3]}}
    assert _without_state_cycle(after) == _without_state_cycle(before)

    # A new process: fresh registry, fresh module, a clock that starts again at 0.
    sleep2, _other2, clock2 = _fresh_process(bus, tmp_path, d, ident, sim)
    seen2 = _record(sleep2, clock2)
    cp2 = _checkpointer(sleep2, ident, d)
    await _drive(sleep2, cp2, clock2, REST_S)
    resumed = _starts(seen2, "state_cycle")
    assert len(resumed) == 1
    payload = resumed[0][1]
    assert payload["resumed"] is True
    assert payload["rest_seconds"] == pytest.approx(REST_S - 710.0, abs=10.0)
    ends = [p for _, k, p in seen2 if k == "sleep.sleep.completed"]
    assert len(ends) == 1 and not ends[0].get("aborted")
    assert ends[0]["rest_seconds"] == payload["rest_seconds"]
    # The cut rest and its resumption are one sleep cycle for the maturation gate.
    assert await _gate_count(bus) == 1
    # The finished rest left the entry awake with 0 s.
    assert read_checkpoint(d).modules["sleep"]["state_cycle"] == {
        "phase": "awake",
        "awake_s": 0.0,
        "rest_spent_s": 0.0,
    }


async def test_a_crash_mid_rest_loses_at_most_one_interval_of_rest(bus, tmp_path, sim):
    ident = mint_identity()
    d = tmp_path / "ckpt"
    sleep, _cp, _other, _seen, _began = await _to_mid_rest(bus, tmp_path, sim, d, ident, 710.0)
    live = sleep._export_state_cycle()["rest_spent_s"]
    # No clean shutdown: the process just dies. Only what is on disk survives.
    stored = read_checkpoint(d).modules["sleep"]["state_cycle"]
    assert stored["phase"] == "resting"
    assert 0.0 <= live - stored["rest_spent_s"] <= 60.0 + 10.0
    assert stored["rest_spent_s"] >= 600.0

    sleep2, _other2, clock2 = _fresh_process(bus, tmp_path, d, ident, sim)
    seen2 = _record(sleep2, clock2)
    cp2 = _checkpointer(sleep2, ident, d)
    await _drive(sleep2, cp2, clock2, 10.0)
    (start,) = _starts(seen2, "state_cycle")
    assert start[1]["resumed"] is True
    assert start[1]["rest_seconds"] == pytest.approx(REST_S - stored["rest_spent_s"], abs=1.0)


async def test_the_rest_entry_is_written_when_the_rest_starts(bus, tmp_path, sim):
    ident = mint_identity()
    d = tmp_path / "ckpt"
    _sleep, _cp, _other, _seen, _began = await _to_mid_rest(bus, tmp_path, sim, d, ident, 5.0)
    entry = read_checkpoint(d).modules["sleep"]["state_cycle"]
    assert entry["phase"] == "resting"
    assert entry["rest_spent_s"] < 60.0


async def test_a_crash_right_after_the_rest_resumes_no_rest(bus, tmp_path, sim):
    ident = mint_identity()
    d = tmp_path / "ckpt"
    sleep, cp, _other, seen, began = await _to_mid_rest(bus, tmp_path, sim, d, ident, 100.0)
    await _drive(sleep, cp, sim, began + REST_S + 15)
    assert [k for _, k, _ in seen if k == "sleep.sleep.completed"]
    assert not sleep.is_sleeping
    # Crash here, with no clean shutdown and long before the next full awake write.
    stored = read_checkpoint(d).modules["sleep"]["state_cycle"]
    assert stored == {"phase": "awake", "awake_s": 0.0, "rest_spent_s": 0.0}

    sleep2, _other2, clock2 = _fresh_process(bus, tmp_path, d, ident, sim)
    seen2 = _record(sleep2, clock2)
    cp2 = _checkpointer(sleep2, ident, d)
    await _drive(sleep2, cp2, clock2, 600.0)
    assert _starts(seen2) == []  # awake time starts over; no rest of any kind resumes


async def test_other_modules_stay_byte_for_byte_through_a_whole_rest(bus, tmp_path, sim):
    ident = mint_identity()
    d = tmp_path / "ckpt"
    sleep, cp, _other, _seen, began = await _to_mid_rest(bus, tmp_path, sim, d, ident, 5.0)
    first = read_checkpoint(d)
    await _drive(sleep, cp, sim, began + REST_S + 15)
    last = read_checkpoint(d)
    assert last.modules["other"] == {"v": 1, "nested": {"a": [1, 2, 3]}}
    assert _without_state_cycle(last) == _without_state_cycle(first)
    assert last.metadata == first.metadata
    assert last.timestamp == first.timestamp


async def test_rest_progress_is_written_each_interval_not_each_poll(bus, tmp_path, sim, monkeypatch):
    ident = mint_identity()
    d = tmp_path / "ckpt"
    writes: list[float] = []
    real = update_state_cycle_entry

    def counting(identity, entry, directory=None):
        writes.append(entry["rest_spent_s"])
        return real(identity, entry, directory)

    monkeypatch.setattr("kaine.lifecycle.resume_checkpoint.update_state_cycle_entry", counting)
    sleep, cp, _other, _seen, _began = await _to_mid_rest(bus, tmp_path, sim, d, ident, 600.0)
    # One at the start, then one per 60 s of rest: about ten, not one per second.
    assert 8 <= len(writes) <= 12
    assert all(b - a >= 59.0 for a, b in zip(writes, writes[1:]))


async def test_no_checkpoint_yet_writes_nothing(bus, tmp_path, sim):
    ident = mint_identity()
    d = tmp_path / "ckpt"
    sleep = _make(bus, tmp_path, sim, Probe(True))
    entry = {"phase": "resting", "awake_s": 0.0, "rest_spent_s": 30.0}
    assert update_state_cycle_entry(ident, entry, d) is False
    assert not checkpoint_file(d).exists()


async def test_another_entitys_checkpoint_is_left_alone(bus, tmp_path, sim):
    ident, other_ident = mint_identity(), mint_identity()
    d = tmp_path / "ckpt"
    sleep = _make(bus, tmp_path, sim, Probe(True))
    await save_checkpoint(Registry(sleep), ident, reason="periodic", directory=d)
    before = checkpoint_file(d).read_bytes()
    entry = {"phase": "resting", "awake_s": 0.0, "rest_spent_s": 30.0}
    assert update_state_cycle_entry(other_ident, entry, d) is False
    assert checkpoint_file(d).read_bytes() == before


async def test_a_checkpoint_older_than_a_revive_is_left_alone(bus, tmp_path, sim):
    ident = mint_identity()
    d = tmp_path / "ckpt"
    sleep = _make(bus, tmp_path, sim, Probe(True))
    await save_checkpoint(Registry(sleep), ident, reason="periodic", directory=d)
    snap = read_checkpoint(d)
    # A revive record newer than the checkpoint, with the checkpoint still in place.
    (d / "revive.json").write_text(json.dumps({"started_at": snap.timestamp + 100.0}))
    entry = {"phase": "resting", "awake_s": 0.0, "rest_spent_s": 30.0}
    assert update_state_cycle_entry(ident, entry, d) is False
    assert read_checkpoint(d).modules["sleep"]["state_cycle"]["phase"] == "awake"
    # After a landed revive the checkpoint is set aside and there is nothing to update.
    assert set_aside_for_revive(d)
    assert update_state_cycle_entry(ident, entry, d) is False


async def test_a_non_state_cycle_sleep_writes_nothing(bus, tmp_path, sim):
    ident = mint_identity()
    d = tmp_path / "ckpt"
    sleep = _make(bus, tmp_path, sim, Probe(True))
    cp = _checkpointer(sleep, ident, d)
    await save_checkpoint(Registry(sleep), ident, reason="periodic", directory=d)
    before = checkpoint_file(d).read_bytes()
    await sleep.enter_sleep(trigger="maintenance")
    await cp._sync_rest()
    assert await cp.write_final(can_write=lambda: False) is False
    assert checkpoint_file(d).read_bytes() == before


async def test_frozen_time_adds_no_rest_time_to_the_entry(bus, tmp_path, sim):
    ident = mint_identity()
    d = tmp_path / "ckpt"
    frozen = {"t": 0.0}
    sleep = _make(bus, tmp_path, sim, Probe(True))
    sleep.set_paused_source(lambda: frozen["t"])
    seen = _record(sleep, sim)
    cp = _checkpointer(sleep, ident, d)
    await _drive(sleep, cp, sim, 100.0)
    await save_checkpoint(Registry(sleep), ident, reason="periodic", directory=d)
    await _drive(sleep, cp, sim, T_ACT + 20)
    began = _starts(seen, "state_cycle")[0][0]
    await _drive(sleep, cp, sim, began + 200)
    frozen["t"] = 150.0  # 150 s of the rest were frozen
    sim.hold = True
    await cp.write_final(can_write=lambda: False)
    spent = read_checkpoint(d).modules["sleep"]["state_cycle"]["rest_spent_s"]
    assert spent == pytest.approx(50.0, abs=10.0)
    await sleep.shutdown()
