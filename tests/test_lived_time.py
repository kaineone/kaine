# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>


from kaine.lifecycle.lived_time import LivedTimeAccumulator, TickAccumulator


class FakeClock:
    def __init__(self, now: float = 0.0):
        self._now = now

    def now(self) -> float:
        return self._now


def test_lived_time_adds_unpaused_elapsed():
    clock = FakeClock()
    lived = LivedTimeAccumulator(clock.now, paused_seconds=lambda: 0.0)

    clock._now = 0.0
    assert lived.step() == 0.0

    clock._now = 10.0
    assert lived.step() == 10.0


def test_lived_time_subtracts_paused_seconds_exactly():
    clock = FakeClock()
    paused = {"s": 0.0}
    lived = LivedTimeAccumulator(clock.now, paused_seconds=lambda: paused["s"])

    clock._now = 0.0
    assert lived.step() == 0.0

    clock._now = 30.0
    paused["s"] = 20.0
    assert lived.step() == 10.0


def test_lived_time_raising_paused_seconds_reanchors():
    clock = FakeClock()
    calls = 0

    def paused_seconds():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("boom")
        return 0.0

    lived = LivedTimeAccumulator(clock.now, paused_seconds=paused_seconds)

    clock._now = 0.0
    assert lived.step() == 0.0
    assert lived.clock_baseline == 0.0

    clock._now = 20.0
    assert lived.step() == 0.0
    assert lived.clock_baseline is None
    assert lived.paused_baseline is None

    clock._now = 25.0
    assert lived.step() == 0.0

    clock._now = 30.0
    assert lived.step() == 5.0


def test_lived_time_raising_clock_keeps_baselines():
    clock = FakeClock()
    lived = LivedTimeAccumulator(clock.now, paused_seconds=lambda: 0.0)

    clock._now = 0.0
    lived.step()
    assert lived.clock_baseline == 0.0
    assert lived.paused_baseline == 0.0

    def raising_now():
        raise RuntimeError("clock boom")

    lived._clock_now = raising_now
    assert lived.step() == 0.0
    assert lived.clock_baseline == 0.0
    assert lived.paused_baseline == 0.0


def test_lived_time_no_clock_returns_zero():
    lived = LivedTimeAccumulator(None)
    assert lived.step() == 0.0


def test_lived_time_nonfinite_paused_reanchors():
    clock = FakeClock()
    calls = 0

    def paused_seconds():
        nonlocal calls
        calls += 1
        if calls == 2:
            return float("inf")
        return 0.0

    lived = LivedTimeAccumulator(clock.now, paused_seconds=paused_seconds)

    clock._now = 0.0
    lived.step()
    assert lived.clock_baseline == 0.0

    clock._now = 10.0
    assert lived.step() == 0.0
    assert lived.clock_baseline is None
    assert lived.paused_baseline is None

    clock._now = 15.0
    assert lived.step() == 0.0

    clock._now = 25.0
    assert lived.step() == 10.0


def test_set_paused_source_resets_paused_baseline():
    clock = FakeClock()
    lived = LivedTimeAccumulator(clock.now, paused_seconds=lambda: 0.0)

    clock._now = 0.0
    lived.step()
    assert lived.paused_baseline == 0.0

    clock._now = 10.0
    assert lived.step() == 10.0

    lived.set_paused_source(lambda: 100.0)
    assert lived.paused_baseline is None

    # As in the gate before the refactor: the new source is anchored at this
    # step, so the clock delta since the last step still counts.
    clock._now = 20.0
    assert lived.step() == 10.0
    assert lived.paused_baseline == 100.0

    clock._now = 30.0
    assert lived.step() == 10.0


def test_lived_time_negative_delta_returns_zero():
    clock = FakeClock()
    lived = LivedTimeAccumulator(clock.now)

    clock._now = 10.0
    lived.step()

    clock._now = 5.0
    assert lived.step() == 0.0


def test_tick_accumulator():
    ticks = TickAccumulator()

    assert ticks.step(0) == 0
    assert ticks.baseline == 0

    assert ticks.step(10) == 10
    assert ticks.baseline == 10

    assert ticks.step(15) == 5
    assert ticks.baseline == 15

    # restart / counter rolled over
    assert ticks.step(3) == 0
    assert ticks.baseline == 3

    assert ticks.step(7) == 4
    assert ticks.baseline == 7

    # negative index leaves state unchanged
    assert ticks.step(-1) == 0
    assert ticks.baseline == 7

    # non-int index leaves state unchanged
    assert ticks.step(9.5) == 0
    assert ticks.baseline == 7
