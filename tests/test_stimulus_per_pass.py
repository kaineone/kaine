# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Per-pass viewings (stimulus-control-act 5.2).

ProgrammeClock continue_mode wraps instead of ending, with pass_number
tracking. ProgrammeEndWatcher "continue" mode calls on_pass_end at pass
boundaries. StimulusTally close_pass snapshots and resets between passes.
StimulusController reset_gain returns the gain to neutral.
"""
from __future__ import annotations

import pytest

from kaine.cycle.programme_end import ProgrammeEndWatcher
from kaine.modules.effectors.stimulus.config import StimulusControlConfig
from kaine.modules.effectors.stimulus.controller import StimulusController
from kaine.modules.effectors.stimulus.programme import Programme, ProgrammeClock
from kaine.modules.effectors.stimulus.records import StimulusTally

pytestmark = pytest.mark.asyncio


class _Mono:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def _continue_clock(durations, segments=None):
    mono = _Mono()
    prog = ProgrammeClock(
        len(durations), segments=segments, clock=mono, continue_mode=True,
    )
    for i, d in enumerate(durations):
        prog.set_duration(i, d)
    prog.start()
    return mono, prog


# -- ProgrammeClock continue_mode tests ------------------------------------


def test_continue_mode_does_not_end():
    mono, prog = _continue_clock([2.0, 3.0, 1.5])
    mono.t = 100.0 + 6.5
    assert not prog.ended()
    mono.t = 100.0 + 20.0
    assert not prog.ended()
    idx, offset = prog.locate()
    assert idx < prog.item_count


def test_continue_mode_pass_number():
    mono, prog = _continue_clock([2.0, 3.0, 1.5])
    assert prog.pass_number == 0
    mono.t = 100.0 + 3.0
    assert prog.pass_number == 0
    mono.t = 100.0 + 6.5
    assert prog.pass_number == 1
    mono.t = 100.0 + 13.0
    assert prog.pass_number == 2


def test_continue_mode_wraps_position():
    mono, prog = _continue_clock([2.0, 3.0, 1.5])
    mono.t = 100.0 + 8.0
    idx, offset = prog.locate()
    mono_first = _Mono()
    prog_first = ProgrammeClock(3, clock=mono_first, continue_mode=True)
    for i, d in enumerate([2.0, 3.0, 1.5]):
        prog_first.set_duration(i, d)
    prog_first.start()
    mono_first.t = 100.0 + 1.5
    idx_first, offset_first = prog_first.locate()
    assert idx == idx_first
    assert offset == pytest.approx(offset_first)


def test_default_mode_still_ends():
    mono = _Mono()
    prog = ProgrammeClock(3, clock=mono)
    for i, d in enumerate([2.0, 3.0, 1.5]):
        prog.set_duration(i, d)
    prog.start()
    mono.t = 100.0 + 6.5
    assert prog.ended()
    assert prog.locate() == (3, 0.0)
    assert prog.pass_number == 0


# -- ProgrammeEndWatcher continue_mode tests --------------------------------


class _FakeClock:
    def __init__(self, *, started: bool = False, paused: bool = False, index: int = -1):
        self.started = started
        self.paused = paused
        self._index = index
        self._t = 0.0
        self.pass_number = 0

    def locate(self):
        return (self._index, 0.0, 1.0)

    def monotonic(self):
        return self._t

    def advance(self, dt: float) -> None:
        self._t += dt


async def test_continue_mode_calls_on_pass_end():
    clock = _FakeClock(started=True, paused=False, index=0)
    passes_completed: list[int] = []

    async def on_pass(n: int) -> None:
        passes_completed.append(n)

    watcher = ProgrammeEndWatcher(
        clock,
        3,
        mode="continue",
        on_pass_end=on_pass,
        write_request=lambda _: None,
        read_result=lambda: None,
        freeze=lambda _r, _s: None,
        sleep=lambda _dt: clock.advance(_dt),
        clock_fn=clock.monotonic,
    )

    clock.pass_number = 1
    result = await watcher.step()
    assert result is False
    assert passes_completed == [0]

    clock.pass_number = 2
    result = await watcher.step()
    assert result is False
    assert passes_completed == [0, 1]


async def test_continue_mode_never_finishes():
    clock = _FakeClock(started=True, paused=False, index=5)

    async def on_pass(n: int) -> None:
        pass

    watcher = ProgrammeEndWatcher(
        clock,
        3,
        mode="continue",
        on_pass_end=on_pass,
        write_request=lambda _: None,
        read_result=lambda: None,
        freeze=lambda _r, _s: None,
        sleep=lambda _dt: clock.advance(_dt),
        clock_fn=clock.monotonic,
    )

    for _ in range(10):
        assert await watcher.step() is False


def test_continue_mode_requires_callback():
    clock = _FakeClock()
    with pytest.raises(ValueError, match="on_pass_end"):
        ProgrammeEndWatcher(
            clock,
            3,
            mode="continue",
            on_pass_end=None,
            write_request=lambda _: None,
            read_result=lambda: None,
            freeze=lambda _r, _s: None,
            clock_fn=clock.monotonic,
        )


async def test_stop_mode_unchanged():
    clock = _FakeClock(started=True, paused=False, index=0)
    writes = []

    async def fake_sleep(dt: float) -> None:
        clock.advance(dt)

    watcher = ProgrammeEndWatcher(
        clock,
        2,
        mode="stop",
        write_request=writes.append,
        read_result=lambda: None,
        freeze=lambda _r, _s: None,
        sleep=fake_sleep,
        clock_fn=clock.monotonic,
    )

    result = await watcher.step()
    assert result is False
    assert not writes

    clock._index = 2
    clock.started = True

    def read_result():
        if writes:
            return {"request_id": writes[-1].request_id, "ok": True}
        return None

    watcher._read_result = read_result
    result = await watcher.step()
    assert result is True
    assert len(writes) == 1


# -- StimulusTally close_pass tests -----------------------------------------


def test_close_pass_returns_record_and_resets():
    config = StimulusControlConfig.from_section({"enabled": True})
    tally = StimulusTally(config)
    tally.accepted("next")
    tally.accepted("next")
    tally.accepted("louder")
    tally.account(10.0, entity_paused=False, gain_db=0.0)

    rec = tally.close_pass(0)
    assert rec["pass"] == 0
    assert rec["commands"]["next"] == 2
    assert rec["commands"]["louder"] == 1
    assert rec["awake_s"] == pytest.approx(10.0)

    fresh = tally.record()
    assert fresh["commands"]["next"] == 0
    assert fresh["commands"]["louder"] == 0
    assert fresh["awake_s"] == pytest.approx(0.0)
    assert fresh["gain_seconds"] == {}


def test_close_pass_preserves_config():
    config = StimulusControlConfig.from_section({"enabled": True})
    tally = StimulusTally(config)
    tally.accepted("next")
    tally.close_pass(0)
    tally.accepted("next")
    rec = tally.record()
    assert rec["stage"] == config.stage
    assert "next" in rec["commands"]


# -- StimulusController reset_gain test -------------------------------------


def test_reset_gain():
    mono = _Mono()
    config = StimulusControlConfig.from_section({"enabled": True})
    prog = ProgrammeClock(1, clock=mono)
    prog.set_duration(0, 100.0)
    prog.start()
    programme = Programme(
        manifest=None,
        segments=((0, 1),),
        channel_manifests=(),
    )
    controller = StimulusController(
        prog, programme, config, now=mono, tally=None,
    )
    controller.apply("louder")
    assert controller.gain_db != 0.0
    controller.reset_gain()
    assert controller.gain_db == 0.0
