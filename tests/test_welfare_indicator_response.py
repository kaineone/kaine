# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The welfare monitor's response to the A.4 indicators (welfare-indicator-response).

Every test drives the real WelfareProtectiveMonitor poll over a real bus
(fakeredis), with real affect.state and sleep events, the real evaluator, the
real freeze in a tmp control file and real incident records:

* a first crossing requests a rest (no preservation, no freeze), flags it for
  review and sends the welfare_indicator_rest notice;
* the rest's completion restarts every span and resets every crossing state;
  a crossing over the fresh span preserves and pauses with reason
  indicator_<name>;
* every way the rest stage could hang escalates with indicator_rest_failed;
* a silent affect stream is reported, then escalated after 660 s;
* the latch is shared with the distress arm; a named override re-arms.
"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import validate_event
from kaine.cycle import control_state
from kaine.cycle.incident_log import IncidentLog
from kaine.cycle.preservation_monitor import (
    WELFARE_REST_REQUEST_TYPE,
    WelfareIndicatorConfig,
    WelfareProtectiveMonitor,
    WelfareResponseConfig,
)
from kaine.cycle.unfrozen_clock import UnfrozenClock
from kaine.lifecycle.preservation import PreservationResult
from kaine.lifecycle.welfare_indicators import (
    INDICATOR_NAMES,
    REST_FAILURES,
    STAGE3_REASONS,
    IndicatorParams,
)
from kaine.modules.base import BaseModule
from kaine.modules.registry import ModuleRegistry

pytestmark = pytest.mark.asyncio

T0 = 1_800_000_000.0


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


@pytest.fixture(autouse=True)
def _control_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(control_state, "CONTROL_PATH", tmp_path / "control.json")
    monkeypatch.setattr(control_state, "OVERRIDE_AUDIT_PATH", tmp_path / "audit.jsonl")


class _Clock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class _StubFM:
    """Records preservations; the real preservation path has its own tests."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def preserve_live(self, registry, *, reason, label, out_root, entity_name, require_encryption):
        self.calls.append({"reason": reason, "label": label})
        return PreservationResult(
            ok=True,
            preservation_id=f"pid{len(self.calls)}",
            snapshot_id=f"snap{len(self.calls)}",
            reason=reason,
            label=label,
            run_id="indicator000001",
            world_model_captured=False,
        )


class _SleepStandIn(BaseModule):
    """A sleep module that listens for welfare rest requests; the test plays its events."""

    name = "sleep"

    def __init__(self, bus, *, ready: bool = True, developmental_rest_s: float = 1410.0) -> None:
        super().__init__(bus)
        self.ready = ready
        self.developmental_rest_s = developmental_rest_s

    async def initialize(self) -> None:
        pass

    def serialize(self) -> dict:
        return {}

    def welfare_rest_ready(self) -> bool:
        return self.ready


def _cfg(**overrides) -> WelfareResponseConfig:
    indicators = overrides.pop("indicators", WelfareIndicatorConfig())
    values = dict(
        enabled=True,
        action="pause",
        distress_threshold=0.5,
        distress_duration_s=30.0,
        repeat_window_s=1000.0,
        repeat_threshold=99,
        warmup_s=0.0,
        warmup_ceiling_s=0.0,
        indicators=indicators,
    )
    values.update(overrides)
    return WelfareResponseConfig(**values)


class Harness:
    def __init__(
        self,
        bus: AsyncBus,
        tmp_path: Path,
        *,
        cfg: WelfareResponseConfig | None = None,
        sleep: BaseModule | None | str = "standin",
        developing: bool = False,
        awake_scale: float | None = None,
        params: IndicatorParams | None = None,
    ) -> None:
        self.bus = bus
        self.u = _Clock(0.0)
        self.w = _Clock(T0)
        self.registry = ModuleRegistry()
        if sleep == "standin":
            sleep = _SleepStandIn(bus)
        self.sleep = sleep
        if sleep is not None:
            self.registry.register(sleep)
        self.fm = _StubFM()
        self.notices: list[tuple[str, tuple[str, ...]]] = []
        self.responses: list[str] = []
        self.records: list[dict[str, Any]] = []
        self.developing = developing
        awake_clock = None
        if awake_scale is not None:
            # A dilated entity clock: awake entity time runs at awake_scale x wall.
            awake_clock = lambda: self.u.value * awake_scale  # noqa: E731
        self.mon = WelfareProtectiveMonitor(
            registry=self.registry,
            fork_manager=self.fm,
            config=cfg or _cfg(),
            bus=bus,
            incident_log=IncidentLog(enabled=True, path=str(tmp_path / "incidents"), name="welfare"),
            clock=self.u,
            on_response=self.responses.append,
            unfrozen_clock=UnfrozenClock(
                control_state.read_frozen_state, unknown_counts_as="unfrozen", monotonic=self.u
            ),
            indicator_params=params or IndicatorParams(),
            awake_clock=awake_clock,
            entity_scale=(lambda: awake_scale) if awake_scale is not None else None,
            is_developing=lambda: self.developing,
            on_notice=lambda kind, names: self.notices.append((kind, tuple(names))),
            wall_time=self.w,
        )
        original = self.mon._record

        async def _capture(record: dict[str, Any], *, event_type: str) -> None:
            self.records.append(dict(record))
            await original(record, event_type=event_type)

        self.mon._record = _capture
        self.stop = asyncio.Event()

    def _ts(self) -> datetime:
        return datetime.fromtimestamp(self.w.value, timezone.utc)

    async def poll(self) -> None:
        await self.mon._poll_once(self.stop)

    async def affect(self, *, boredom: bool = False, valence: float = 0.0) -> None:
        await self.bus.publish(
            validate_event(
                source="affect",
                type="affect.state",
                payload={
                    "state": {"valence": valence, "arousal": 0.3},
                    "drive_above": {
                        "curiosity": False,
                        "boredom": boredom,
                        "social_drive": False,
                        "restlessness": False,
                    },
                    "drive_ends": {
                        "boredom": {"own": 0, "other": 0},
                        "social_drive": {"own": 0, "other": 0},
                        "restlessness": {"own": 0, "other": 0},
                    },
                },
                salience=0.1,
                timestamp=self._ts(),
            )
        )

    async def sleep_event(self, type_: str, **payload: Any) -> None:
        await self.bus.publish(
            validate_event(
                source="sleep", type=type_, payload=payload, salience=0.1, timestamp=self._ts()
            )
        )

    async def distress(self, error: float = 0.9) -> None:
        await self.bus.publish(
            validate_event(
                source="interoception",
                type="interoception.report",
                payload={"prediction_error": error, "warmup_active": False},
                salience=0.5,
                timestamp=self._ts(),
            )
        )

    async def awake(
        self,
        seconds: float,
        *,
        every: float = 2.0,
        chunk: int = 15,
        until_requests: int | None = None,
        **state: Any,
    ) -> None:
        """Awake time: one affect.state each ``every`` seconds, a poll each ``chunk`` samples.

        Stops early once the monitor has acted, or once ``until_requests`` rest
        requests have been published.
        """
        remaining = seconds
        while remaining > 0:
            for _ in range(chunk):
                if remaining <= 0:
                    break
                await self.affect(**state)
                step = min(every, remaining)
                self.w.value += step
                self.u.value += step
                remaining -= step
            await self.poll()
            if self.mon._acted:
                return
            if until_requests is not None and len(await self.rest_requests()) >= until_requests:
                return

    async def silent(self, seconds: float, *, step: float = 1.0) -> None:
        """Time passes with no affect.state."""
        remaining = seconds
        while remaining > 0:
            d = min(step, remaining)
            self.w.value += d
            self.u.value += d
            remaining -= d
            await self.poll()

    def transitions(self) -> list[str]:
        return [r.get("transition") for r in self.records]

    async def rest_requests(self) -> list[dict]:
        entries = await self.bus.read("preservation.out", last_id="0", count=1000)
        return [e.payload for _, e in entries if e.type == WELFARE_REST_REQUEST_TYPE]


def _welfare_frozen() -> bool:
    holders = control_state.read_holder_sources()
    return holders is not None and "welfare" in holders


async def _first_crossing(h: Harness) -> dict:
    await h.poll()  # seeds the stream cursors
    await h.awake(610, boredom=True)
    requests = await h.rest_requests()
    assert len(requests) == 1
    return requests[0]


async def _complete_rest(h: Harness, request: dict, *, trigger: str = "welfare_rest") -> None:
    await h.sleep_event("sleep.sleep.started", trigger=trigger)
    await h.sleep_event(
        "sleep.rest_request", accepted=True, reason="accepted", origin="welfare",
        proposal_id=request["request_id"],
    )
    await h.poll()
    await h.sleep_event("sleep.sleep.completed", trigger=trigger)
    await h.poll()


# --- stage 1 -------------------------------------------------------------------


async def test_a_first_crossing_requests_a_rest_and_preserves_nothing(bus, tmp_path):
    h = Harness(bus, tmp_path)
    request = await _first_crossing(h)
    assert request["indicators"] == ["boredom_deprived"]
    assert h.fm.calls == []
    assert not _welfare_frozen()
    assert h.mon._acted is False
    assert h.transitions().count("indicator_rest_requested") == 1
    assert h.notices == [("welfare_indicator_rest", ("boredom_deprived",))]
    rec = next(r for r in h.records if r["transition"] == "indicator_rest_requested")
    assert rec["indicators"] == ["boredom_deprived"]
    assert rec["indicator_values"]["boredom_deprived"] >= 0.5
    assert rec["indicator_bars"]["boredom_deprived"] == 0.5
    assert rec["span_awake_s"] >= 600.0


async def test_the_request_is_not_a_workspace_candidate(bus, tmp_path):
    h = Harness(bus, tmp_path)
    await _first_crossing(h)
    entries = await bus.read("preservation.out", last_id="0", count=1000)
    request = [e for _, e in entries if e.type == WELFARE_REST_REQUEST_TYPE]
    assert request and request[0].source == "preservation"
    # The cycle reads only registered module streams; the monitor's is not one.
    assert "preservation.out" not in h.registry.active_streams()


# --- stage 2 and 3 ---------------------------------------------------------------


async def test_rest_completion_restarts_the_spans_then_a_fresh_crossing_preserves_and_pauses(bus, tmp_path):
    h = Harness(bus, tmp_path)
    request = await _first_crossing(h)
    await _complete_rest(h, request)
    assert h.mon._ind_stage == "fresh"
    assert "indicator_rest_started" in h.transitions()
    assert "indicator_rest_completed" in h.transitions()

    # The fresh span holds only the time after the rest: no freeze before 600 s.
    await h.awake(500, boredom=True)
    assert h.fm.calls == []
    assert not _welfare_frozen()

    await h.awake(200, boredom=True)
    assert len(h.fm.calls) == 1
    assert _welfare_frozen()
    final = [r for r in h.records if r["transition"] == "protective_action"]
    assert final and final[-1]["reason"] == "indicator_boredom_deprived"
    assert final[-1]["indicators"] == ["boredom_deprived"]
    assert ("welfare_response", ("boredom_deprived",)) in h.notices


async def test_a_spent_stimulus_never_falls_below_its_bar_and_still_freezes(bus, tmp_path):
    """Boredom stays over its bar through the rest: the fresh span's first evaluation crosses."""
    h = Harness(bus, tmp_path, developing=True)
    request = await _first_crossing(h)
    await _complete_rest(h, request)
    await h.awake(620, boredom=True)
    assert len(h.fm.calls) == 1
    assert _welfare_frozen()
    reason = [r for r in h.records if r["transition"] == "protective_action"][-1]["reason"]
    assert reason == "indicator_boredom_deprived"
    # In the developmental phase the notice says the stimulus is spent.
    assert ("welfare_stimulus_spent", ("boredom_deprived",)) in h.notices


async def test_a_busy_answer_lets_the_running_sleep_stand_as_the_rest(bus, tmp_path):
    h = Harness(bus, tmp_path)
    request = await _first_crossing(h)
    await h.sleep_event(
        "sleep.rest_request", accepted=False, reason="busy", origin="welfare",
        proposal_id=request["request_id"],
    )
    await h.poll()
    await h.silent(40)  # past the start timeout: the running sleep stands
    assert h.fm.calls == []
    await h.sleep_event("sleep.sleep.completed", trigger="fatigue")
    await h.poll()
    assert h.mon._ind_stage == "fresh"
    started = [r for r in h.records if r["transition"] == "indicator_rest_started"]
    assert started and started[0]["standing"] is True


async def test_a_full_fresh_span_without_a_crossing_re_arms_the_rest_stage(bus, tmp_path):
    h = Harness(bus, tmp_path)
    request = await _first_crossing(h)
    await _complete_rest(h, request)
    await h.awake(5420, boredom=False, chunk=60)
    assert h.mon._ind_stage == "armed"
    assert "indicator_rearmed" in h.transitions()
    # The next crossing requests a rest before any freeze.
    await h.awake(5420, boredom=True, chunk=60, until_requests=2)
    assert h.fm.calls == []
    assert len(await h.rest_requests()) == 2
    assert h.mon._ind_stage == "resting"


# --- the rest stage cannot hang ----------------------------------------------------


def _failures(h: Harness) -> list[str]:
    return [r.get("failure") for r in h.records if r.get("transition") == "indicator_rest_failed"]


async def _assert_escalated(h: Harness, failure: str) -> None:
    assert _failures(h) == [failure]
    assert len(h.fm.calls) == 1
    assert _welfare_frozen()
    final = [r for r in h.records if r["transition"] == "protective_action"]
    assert final[-1]["reason"] == "indicator_rest_failed"


async def test_an_unsent_request_escalates(bus, tmp_path, monkeypatch):
    h = Harness(bus, tmp_path)
    real_publish = bus.publish

    async def failing(event):
        if event.type == WELFARE_REST_REQUEST_TYPE:
            raise ConnectionError("bus down")
        return await real_publish(event)

    monkeypatch.setattr(bus, "publish", failing)
    await h.poll()
    await h.awake(610, boredom=True)
    await _assert_escalated(h, "request_not_sent")


@pytest.mark.parametrize("reason", ["failed", "too_soon"])
async def test_a_refusal_other_than_busy_escalates(bus, tmp_path, reason):
    h = Harness(bus, tmp_path)
    request = await _first_crossing(h)
    await h.sleep_event(
        "sleep.rest_request", accepted=False, reason=reason, origin="welfare",
        proposal_id=request["request_id"],
    )
    await h.poll()
    await _assert_escalated(h, "refused")


async def test_an_aborted_rest_escalates(bus, tmp_path):
    h = Harness(bus, tmp_path)
    request = await _first_crossing(h)
    await h.sleep_event("sleep.sleep.started", trigger="welfare_rest")
    await h.poll()
    await h.sleep_event("sleep.sleep.completed", trigger="welfare_rest", aborted=True, reason="RuntimeError")
    await h.poll()
    await _assert_escalated(h, "aborted")
    assert request["request_id"]


async def test_a_rest_that_does_not_start_in_30_s_escalates(bus, tmp_path):
    h = Harness(bus, tmp_path)
    await _first_crossing(h)
    await h.silent(25)
    assert h.fm.calls == []
    await h.silent(6)
    await _assert_escalated(h, "start_timeout")


async def test_no_sleep_module_escalates_at_once(bus, tmp_path):
    h = Harness(bus, tmp_path, sleep=None)
    await h.poll()
    await h.awake(610, boredom=True)
    await _assert_escalated(h, "sleep_module_not_running")
    assert await h.rest_requests() == []


async def test_a_stopped_sleep_module_escalates_at_once(bus, tmp_path):
    h = Harness(bus, tmp_path, sleep=_SleepStandIn(None, ready=False))
    await h.poll()
    await h.awake(610, boredom=True)
    await _assert_escalated(h, "sleep_module_not_running")


@pytest.mark.parametrize(("developing", "bound"), [(True, 1410.0 + 300.0), (False, 3600.0)])
async def test_a_rest_that_never_completes_escalates(bus, tmp_path, developing, bound):
    h = Harness(bus, tmp_path, developing=developing)
    await _first_crossing(h)
    await h.sleep_event("sleep.sleep.started", trigger="welfare_rest")
    await h.poll()
    await h.silent(bound - 20.0, step=20.0)
    assert h.fm.calls == []
    await h.silent(40.0, step=10.0)
    await _assert_escalated(h, "complete_timeout")


async def test_the_completion_bound_counts_unfrozen_time_only(bus, tmp_path):
    h = Harness(bus, tmp_path)
    await _first_crossing(h)
    await h.sleep_event("sleep.sleep.started", trigger="welfare_rest")
    await h.poll()
    await h.silent(3000, step=50.0)
    control_state.freeze(reason="operator check", source="operator")
    await h.silent(2000, step=50.0)  # frozen: does not count
    control_state.stand_down(source="operator")
    await h.silent(500, step=50.0)
    assert h.fm.calls == []
    await h.silent(150, step=50.0)
    await _assert_escalated(h, "complete_timeout")


# --- silence of the affect stream --------------------------------------------------


async def test_a_short_affect_silence_is_reported_once_and_freezes_nothing(bus, tmp_path):
    h = Harness(bus, tmp_path)
    await h.poll()
    await h.awake(60)
    await h.silent(5)
    await h.awake(60)
    unavailable = [r for r in h.records if r["transition"] == "indicators_unavailable"]
    assert len(unavailable) == 1
    assert h.notices == [("welfare_indicators_unavailable", ())]
    assert h.fm.calls == []
    assert not _welfare_frozen()
    assert h.mon._ind_eval.available


async def test_a_long_affect_silence_escalates(bus, tmp_path):
    """The affect module heartbeats but publishes no affect.state for 660 awake seconds."""
    h = Harness(bus, tmp_path)
    await h.poll()
    await h.awake(60)
    await h.silent(600, step=20.0)
    assert h.fm.calls == []
    await h.silent(80, step=20.0)
    assert len(h.fm.calls) == 1
    assert _welfare_frozen()
    final = [r for r in h.records if r["transition"] == "protective_action"]
    assert final[-1]["reason"] == "indicators_unavailable"
    assert h.notices.count(("welfare_indicators_unavailable", ())) == 1


# --- latch, re-arm, warm-up ----------------------------------------------------------


async def test_a_distress_pause_first_leaves_no_indicator_response(bus, tmp_path):
    h = Harness(bus, tmp_path)
    await h.poll()
    # Boredom builds toward its crossing; distress begins.
    await h.awake(560, boredom=True)
    await h.distress()
    await h.poll()
    for _ in range(25):
        await h.affect(boredom=True)
        h.u.value += 2.0
        h.w.value += 2.0
    # In this poll the sustained distress fires and boredom's span reaches its
    # crossing: the distress arm acts first and the shared latch holds.
    await h.poll()
    assert len(h.fm.calls) == 1
    distress = [r for r in h.records if r["transition"] == "protective_action"]
    assert distress[-1]["reason"] in ("sustained_distress", "repeated_distress")
    assert await h.rest_requests() == []
    # While latched, boredom keeps crossing without a response.
    for _ in range(5):
        await h.affect(boredom=True)
        h.u.value += 100.0
        h.w.value += 100.0
        await h.poll()
    assert len(h.fm.calls) == 1
    assert "indicator_rest_requested" not in h.transitions()


async def test_re_arm_after_the_operator_lifts_the_freeze_restarts_the_spans(bus, tmp_path):
    h = Harness(bus, tmp_path)
    request = await _first_crossing(h)
    await _complete_rest(h, request)
    await h.awake(620, boredom=True)
    assert len(h.fm.calls) == 1 and _welfare_frozen()

    control_state.override(["welfare"])
    await h.poll()
    assert h.mon._acted is False
    assert h.mon._ind_stage == "armed"
    # The spans restarted: the next crossing needs a fresh 600 s and requests a rest.
    await h.awake(500, boredom=True)
    assert len(await h.rest_requests()) == 1
    await h.awake(150, boredom=True)
    assert len(await h.rest_requests()) == 2
    assert len(h.fm.calls) == 1


async def test_warm_up_accrues_the_spans_and_fires_nothing(bus, tmp_path):
    h = Harness(bus, tmp_path, cfg=_cfg(warmup_s=700.0, warmup_ceiling_s=700.0))
    await h.poll()
    await h.awake(650, boredom=True)
    assert await h.rest_requests() == []
    assert h.mon._ind_eval.span_awake_s >= 600.0
    await h.awake(80, boredom=True)
    # Warm-up over: the span that accrued during it crosses at once.
    assert len(await h.rest_requests()) == 1


# --- errors are retried or escalated, never swallowed -----------------------------------


async def test_an_evaluator_that_raises_once_is_retried_next_poll(bus, tmp_path, monkeypatch):
    h = Harness(bus, tmp_path)
    await h.poll()
    await h.awake(560, boredom=True)
    real = h.mon._ind_eval.evaluate
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("evaluator fault")
        return real()

    monkeypatch.setattr(h.mon._ind_eval, "evaluate", flaky)
    await h.awake(60, boredom=True)
    assert calls["n"] >= 2
    assert len(await h.rest_requests()) == 1


async def test_an_indicator_arm_that_keeps_failing_escalates(bus, tmp_path, monkeypatch):
    h = Harness(bus, tmp_path)
    await h.poll()

    def broken():
        raise RuntimeError("evaluator fault")

    monkeypatch.setattr(h.mon._ind_eval, "evaluate", broken)
    await h.awake(600, boredom=False, chunk=30)
    assert h.fm.calls == []
    await h.awake(120, boredom=False, chunk=30)
    assert len(h.fm.calls) == 1
    final = [r for r in h.records if r["transition"] == "protective_action"]
    assert final[-1]["reason"] == "indicators_unavailable"


# --- clocks ------------------------------------------------------------------------------


async def test_a_dilated_entity_clock_counts_entity_seconds(bus, tmp_path):
    """At time scale 2 the span reaches 600 entity seconds after 300 wall seconds."""
    h = Harness(bus, tmp_path, awake_scale=2.0)
    await h.poll()
    # The affect module publishes once per entity second: twice per wall second.
    await h.awake(280, every=0.5, chunk=30, boredom=True)
    assert await h.rest_requests() == []
    assert h.mon._ind_eval.span_awake_s == pytest.approx(560.0, abs=10.0)
    await h.awake(40, every=0.5, chunk=20, boredom=True)
    assert len(await h.rest_requests()) == 1


# --- content -----------------------------------------------------------------------------


def _content_free(value: Any) -> bool:
    if value is None or isinstance(value, (bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, str):
        return True
    if isinstance(value, list):
        return all(_content_free(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _content_free(v) for k, v in value.items())
    return False


async def test_every_indicator_record_is_content_free(bus, tmp_path):
    h = Harness(bus, tmp_path)
    request = await _first_crossing(h)
    await _complete_rest(h, request)
    await h.awake(620, boredom=True)
    labels = set(INDICATOR_NAMES) | set(STAGE3_REASONS) | set(REST_FAILURES)
    for record in h.records:
        assert _content_free(record)
        for name in record.get("indicators", []):
            assert name in INDICATOR_NAMES
        for key in ("indicator_values", "indicator_bars"):
            if key in record:
                assert set(record[key]) == set(INDICATOR_NAMES)
        if str(record.get("reason", "")).startswith("indicator"):
            assert record["reason"] in labels
