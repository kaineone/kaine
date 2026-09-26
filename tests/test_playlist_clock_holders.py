# SPDX-License-Identifier: Apache-2.0
"""Tests for per-holder playlist-clock pauses and freeze-driven programme pause.

Uses an injectable monotonic clock so no real time passes. The freeze-watch
loop is driven through the real control-state file, but its default path is
monkeypatched into a temporary directory so no real operator state is touched."""


import asyncio
import time

import pytest

from kaine.cycle.__main__ import _freeze_watch_loop
from kaine.cycle.control_state import (
    pop_freeze,
    push_freeze,
)
from kaine.modules.topos.feed import PlaylistClock


class _FakeClock:
    """Manually advanced monotonic clock."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class _CountingClock:
    """Monotonic clock that counts how many times it is read."""

    def __init__(self) -> None:
        self.t = 0.0
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return self.t


async def _wait_for(condition, timeout=5.0, interval=0.01):
    """Poll ``condition`` until it returns True or ``timeout`` elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await asyncio.sleep(interval)
    raise TimeoutError(f"condition never became true within {timeout}s")


def test_overlapping_holders_keep_clock_paused_until_both_release():
    clock = PlaylistClock(3, clock=_FakeClock())
    clock.start()
    c = clock._clock
    c.t = 1.0
    assert clock.elapsed() == 1.0

    clock.pause("hypnos")
    c.t = 2.0
    assert clock.paused
    assert clock.elapsed() == 1.0

    clock.pause("freeze")
    c.t = 3.0
    assert clock.paused
    assert clock.elapsed() == 1.0

    clock.resume("hypnos")
    c.t = 4.0
    assert clock.paused
    assert clock.elapsed() == 1.0

    clock.resume("freeze")
    c.t = 5.0
    assert not clock.paused
    assert clock.elapsed() == 2.0  # 5 - origin(0) - paused_total(3: t=1..4)


def test_overlapping_holders_reverse_order():
    clock = PlaylistClock(3, clock=_FakeClock())
    clock.start()
    c = clock._clock
    c.t = 10.0

    clock.pause("freeze")
    clock.pause("hypnos")
    c.t = 20.0
    assert clock.paused
    assert clock.elapsed() == 10.0

    clock.resume("freeze")
    c.t = 30.0
    assert clock.paused
    assert clock.elapsed() == 10.0

    clock.resume("hypnos")
    c.t = 40.0
    assert not clock.paused
    assert clock.elapsed() == 20.0  # 40 - origin(0) - paused_total(20: t=10..30)


def test_elapsed_excludes_every_paused_span():
    clock = PlaylistClock(3, clock=_FakeClock())
    clock.start()
    c = clock._clock

    c.t = 5.0
    assert clock.elapsed() == 5.0

    clock.pause("a")
    c.t = 15.0
    clock.resume("a")
    assert clock.elapsed() == 5.0

    c.t = 20.0
    assert clock.elapsed() == 10.0

    clock.pause("b")
    c.t = 100.0
    clock.resume("b")
    assert clock.elapsed() == 10.0

    c.t = 110.0
    assert clock.elapsed() == 20.0


def test_no_argument_calls_use_default_holder():
    clock = PlaylistClock(1, clock=_FakeClock())
    clock.start()
    c = clock._clock

    clock.pause()
    c.t = 5.0
    assert clock.paused
    assert clock.elapsed() == 0.0

    clock.pause()  # idempotent
    clock.resume()
    assert not clock.paused
    c.t = 10.0
    assert clock.elapsed() == 5.0


def test_resume_non_held_holder_is_noop():
    clock = PlaylistClock(1, clock=_FakeClock())
    clock.start()
    c = clock._clock

    clock.pause("default")
    clock.resume("ghost")
    assert clock.paused
    c.t = 5.0
    assert clock.elapsed() == 0.0

    clock.resume("default")
    assert not clock.paused


def test_pending_pause_before_start_with_named_holder():
    clock = PlaylistClock(1, clock=_FakeClock())
    c = clock._clock
    clock.pause("hypnos")
    assert clock.paused
    assert clock.elapsed() == 0.0

    c.t = 10.0
    clock.start()
    assert clock.paused
    assert clock.elapsed() == 0.0

    c.t = 20.0
    clock.resume("hypnos")
    assert not clock.paused
    assert clock.elapsed() == 0.0


def test_elapsed_locked_reads_clock_once():
    counting = _CountingClock()
    clock = PlaylistClock(1, clock=counting)
    clock.start()
    counting.t = 1.0

    counting.calls = 0
    clock.elapsed()
    assert counting.calls == 1

    clock.pause()
    counting.calls = 0
    clock.elapsed()
    assert counting.calls == 1

    clock.resume()
    counting.calls = 0
    clock.elapsed()
    assert counting.calls == 1


class _FakeCycle:
    def __init__(self):
        self.is_paused = False
        self.pause_calls = 0
        self.resume_calls = 0

    async def pause(self):
        self.is_paused = True
        self.pause_calls += 1

    async def resume(self):
        self.is_paused = False
        self.resume_calls += 1


@pytest.fixture
def patched_control_path(monkeypatch, tmp_path):
    """Redirect the control-state file into ``tmp_path`` for the test."""
    p = tmp_path / "control.json"
    monkeypatch.setattr("kaine.cycle.control_state.CONTROL_PATH", p)
    return p


def test_freeze_watch_loop_pauses_and_resumes_playlist_clock(patched_control_path):
    async def _run():
        clock = PlaylistClock(1, clock=_FakeClock())
        clock.start()
        fake_cycle = _FakeCycle()
        stop_event = asyncio.Event()

        task = asyncio.create_task(
            _freeze_watch_loop(fake_cycle, stop_event, playlist_clock=clock)
        )

        push_freeze(reason="test freeze")
        await _wait_for(lambda: fake_cycle.pause_calls > 0 and clock.paused)
        assert "freeze" in clock._holders
        clock._clock.t += 5.0
        assert clock.elapsed() == 0.0  # still frozen at the origin

        pop_freeze()
        await _wait_for(lambda: fake_cycle.resume_calls > 0 and not clock.paused)
        assert "freeze" not in clock._holders
        assert clock.elapsed() == 0.0  # no programme time elapsed while frozen

        stop_event.set()
        await asyncio.wait_for(task, timeout=5.0)

    asyncio.run(_run())


def test_hypnos_pause_survives_freeze_thaw(patched_control_path):
    async def _run():
        clock = PlaylistClock(1, clock=_FakeClock())
        clock.start()
        clock.pause("hypnos")
        clock._clock.t = 2.0
        assert clock.elapsed() == 0.0

        fake_cycle = _FakeCycle()
        stop_event = asyncio.Event()

        task = asyncio.create_task(
            _freeze_watch_loop(fake_cycle, stop_event, playlist_clock=clock)
        )

        push_freeze(reason="test freeze")
        await _wait_for(lambda: "freeze" in clock._holders)
        assert clock.paused
        clock._clock.t = 5.0
        assert clock.elapsed() == 0.0

        pop_freeze()
        await _wait_for(lambda: "freeze" not in clock._holders)
        assert clock.paused  # hypnos still holds the clock
        assert "hypnos" in clock._holders
        assert clock.elapsed() == 0.0

        stop_event.set()
        await asyncio.wait_for(task, timeout=5.0)
        clock.resume("hypnos")
        assert not clock.paused

    asyncio.run(_run())
