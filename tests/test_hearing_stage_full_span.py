# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Full-span saturation: the hearing stage is released only on full-span readings.

These run the real path the cycle wires: the affect module's audition bins,
restarted by a ``development.hearing_stage`` event, ``Affect.audition_learning_progress``
as the watch's provider, ``HearingStageWatch.check`` and ``HearingStageState``.
The band-step record (docs/records/validation/band-steps/2026-10-31-summary.json)
showed that a reading over less than the full span sits below the floor for about
an hour after any restart, so counting it released every stage 12 minutes in.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.hearing_stage_watch import HearingStageWatch
from kaine.modules.affect import Affect
from kaine.modules.affect.learning_progress import WindowedProgress
from kaine.modules.audition.hearing_band import HearingBandParams
from kaine.modules.audition.hearing_stage_state import HearingStageState

pytestmark = pytest.mark.asyncio

SPAN = 5400.0
BIN = 60.0
W = 600.0


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


def _audition(err: float) -> Event:
    return Event(
        source="audition",
        type="audition.perception",
        payload={"alert": False, "prediction_error": err},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


def _vision(err: float) -> Event:
    return Event(
        source="vision",
        type="vision.report",
        payload={"alert": False, "prediction_error": err},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


def _hearing(stage: int, previous: int | None) -> Event:
    return Event(
        source="development",
        type="development.hearing_stage",
        payload={
            "stage": stage,
            "previous_stage": previous,
            "low_hz": None,
            "high_hz": 707.1,
            "awake_seconds": 0.0,
        },
        salience=0.05,
        timestamp=datetime.now(timezone.utc),
    )


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _falling(t: float) -> float:
    """A slow fall: the full-span reading clears the 0.20 floor, the drives see progress."""
    return 1.0 / (1.0 + t / 1800.0)


async def _stepped_affect(bus, clock: _Clock) -> Affect:
    """An affect module with stage-0 audition history, then the step to stage 1 at clock.t."""
    affect = Affect(
        bus,
        clock=clock,
        publish_interval_s=1.0,
        learning_progress_span_s=SPAN,
        learning_progress_bin_s=BIN,
    )
    await affect._handle_peer_event("development.out", _hearing(0, None))
    for _ in range(600):
        clock.t += 1.0
        await affect._handle_peer_event("audition.out", _audition(1.0))
    assert affect.audition_learning_progress(0) is None  # 10 bins, not 90
    await affect._handle_peer_event("development.out", _hearing(1, 0))
    assert "audition" not in affect._lp_windows
    return affect


def _stage_one_owner(tmp_path, params: HearingBandParams) -> HearingStageState:
    path = tmp_path / "hearing_stage.json"
    path.write_text(json.dumps({"version": 1, "entity_id": None, "stage": 1, "dwell_seconds": 0.0}))
    state = HearingStageState.load(params, path=path, learning_progress_span_s=SPAN)
    assert state.stage == 1
    return state


async def _run_watch(affect, watch, clock, awake, seconds, error_at):
    """Advance one second at a time: an audition report, then the watch's check.

    Returns the awake time (seconds after the step) at which the stage advanced, or None.
    """
    step_at = awake.t
    advanced_at = None
    for _ in range(int(seconds)):
        clock.t += 1.0
        awake.t += 1.0
        await affect._handle_peer_event("audition.out", _audition(error_at(awake.t - step_at)))
        payload = watch.check()
        if payload is not None and payload["previous_stage"] is not None and advanced_at is None:
            advanced_at = awake.t - step_at
    return advanced_at


async def test_reading_is_none_until_the_window_is_full_then_equals_the_estimator(bus):
    """Affect spec: less than a full window after a step, and a full window."""
    clock = _Clock()
    affect = await _stepped_affect(bus, clock)
    replay = WindowedProgress(BIN, int(SPAN / BIN))
    step = clock.t
    seen_full = False
    for _ in range(int(SPAN) + 120):
        clock.t += 1.0
        err = _falling(clock.t - step)
        await affect._handle_peer_event("audition.out", _audition(err))
        replay.add(clock.t, err)
        await affect._tick()
        window = affect._lp_windows["audition"]
        full = window.completed_bins(clock.t) >= 90
        reading = affect.audition_learning_progress(1)
        if clock.t - step == 3000.0:
            # 3000 s after the restart: no hearing reading, yet the drives' term and
            # the state field carry the estimator's value.
            assert reading is None
            per_source, _ = affect._learning_progress_terms(clock.t)
            assert per_source["audition"] == pytest.approx(replay.value(clock.t))
            assert per_source["audition"] is not None
            await affect._maybe_publish_state()
            entries = await bus.read("affect.out", last_id="0", count=10000)
            states = [ev.payload for _, ev in entries if ev.type == "affect.state"]
            assert states[-1]["audition_learning_progress"] == pytest.approx(replay.value(clock.t))
        if full:
            seen_full = True
            assert reading == pytest.approx(replay.value(clock.t))
            assert reading is not None
        else:
            assert reading is None
    assert seen_full
    # The window fills 90 bins after the restart's first report (1 s after the step).
    assert affect._lp_windows["audition"].completed_bins(clock.t) == 90


async def test_completed_bins_counts_closed_bins_and_survives_a_restore():
    w = WindowedProgress(60.0, 4)
    assert w.completed_bins(100.0) == 0
    w.add(10.0, 1.0)
    assert w.completed_bins(69.9) == 0
    assert w.completed_bins(70.0) == 1
    assert w.completed_bins(250.0) == 4
    assert w.completed_bins(10_000.0) == 4  # capped at the window
    w2 = WindowedProgress(60.0, 4)
    w2.add(0.0, 1.0)
    w2.add(130.0, 1.0)
    restored = WindowedProgress.from_dict(w2.to_dict(130.0), bin_s=60.0, max_bins=4, t=500.0)
    assert restored is not None
    assert restored.completed_bins(500.0) == 2


async def test_partial_span_saturation_720_s_after_the_step_does_not_advance(bus, tmp_path):
    """Developmental-stimulus spec: saturation before the minimum dwell does not advance.

    Constant errors give partial readings of 0.0 (below the floor) from 121 s after the
    step, so 600 s of them have passed by 721 s. Counted, they would release the stage;
    as missing readings they do not.
    """
    clock = _Clock()
    affect = await _stepped_affect(bus, clock)
    state = _stage_one_owner(tmp_path, HearingBandParams())
    awake = _Clock()
    watch = HearingStageWatch(bus, awake, state, affect.audition_learning_progress)
    assert watch.check() is not None  # anchors and reports stage 1
    advanced = await _run_watch(affect, watch, clock, awake, 900, lambda _s: 1.0)
    window = affect._lp_windows["audition"]
    assert window.value(clock.t) == pytest.approx(0.0)  # partial readings were below the floor
    assert advanced is None
    assert state.stage == 1
    assert state.saturated_seconds == 0.0


async def test_full_span_saturation_advances_no_earlier_than_6000_s(bus, tmp_path):
    """Developmental-stimulus spec: saturation advances the stage after the minimum dwell."""
    clock = _Clock()
    affect = await _stepped_affect(bus, clock)
    state = _stage_one_owner(tmp_path, HearingBandParams())
    awake = _Clock()
    watch = HearingStageWatch(bus, awake, state, affect.audition_learning_progress)
    watch.check()
    advanced = await _run_watch(affect, watch, clock, awake, 6100, lambda _s: 1.0)
    assert advanced is not None
    assert 6000.0 <= advanced <= 6010.0
    assert state.stage == 2


async def test_retired_min_dwell_600_changes_nothing(bus, tmp_path, caplog):
    """Developmental-stimulus spec: a retired minimum dwell."""
    with caplog.at_level("WARNING"):
        params = HearingBandParams.from_section({"min_dwell_seconds": 600})
    assert "min_dwell_seconds is retired" in caplog.text
    clock = _Clock()
    affect = await _stepped_affect(bus, clock)
    state = _stage_one_owner(tmp_path, params)
    awake = _Clock()
    watch = HearingStageWatch(bus, awake, state, affect.audition_learning_progress)
    watch.check()
    advanced = await _run_watch(affect, watch, clock, awake, 6100, lambda _s: 1.0)
    assert advanced is not None and advanced >= 6000.0


async def test_a_stage_with_progress_waits_for_the_full_span_reading_to_fall(bus, tmp_path):
    """A falling error keeps the full-span reading above the floor: no release by saturation."""
    clock = _Clock()
    affect = await _stepped_affect(bus, clock)
    state = _stage_one_owner(tmp_path, HearingBandParams())
    awake = _Clock()
    watch = HearingStageWatch(bus, awake, state, affect.audition_learning_progress)
    watch.check()
    advanced = await _run_watch(affect, watch, clock, awake, 7200, _falling)
    assert affect.audition_learning_progress(1) > 0.20
    assert advanced is None
    assert state.stage == 1


async def test_the_gate_leaves_drives_state_and_the_rest_reset_unchanged(bus):
    """Reading the hearing-stage accessor has no effect on affect.

    Two modules get the same reports through the same band step; one has its
    hearing-stage reading polled every second, as the watch does, the other never.
    Their drives, their published learning-progress terms and what the rest's
    affective reset leaves are identical. The welfare indicators read these drives,
    so the change cannot move them.
    """
    clocks = (_Clock(), _Clock())
    modules = []
    for c in clocks:
        modules.append(
            Affect(bus, clock=c, publish_interval_s=1.0, learning_progress_span_s=SPAN, learning_progress_bin_s=BIN)
        )
    for m in modules:
        await m._handle_peer_event("development.out", _hearing(0, None))
    polled, quiet = modules
    for i in range(7200):
        for c in clocks:
            c.t += 1.0
        if i == 600:
            for m in modules:
                await m._handle_peer_event("development.out", _hearing(1, 0))
        for m in modules:
            await m._handle_peer_event("audition.out", _audition(_falling(float(i % 3000))))
            await m._handle_peer_event("vision.out", _vision(0.5 + 0.1 * ((i // 60) % 2)))
            await m._tick()
        polled.audition_learning_progress(1)
        polled.audition_learning_progress(0)
    assert polled._drives.to_dict() == quiet._drives.to_dict()
    assert polled._state.to_dict() == quiet._state.to_dict()
    assert polled._valence_terms() == quiet._valence_terms()
    assert polled._progress() == quiet._progress()
    for m in modules:
        await m.affective_reset()
    assert polled._drives.to_dict() == quiet._drives.to_dict()
    assert polled._state.to_dict() == quiet._state.to_dict()
    assert polled._progress() == quiet._progress()
