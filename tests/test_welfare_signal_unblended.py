# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The welfare signal is the processor's own forward-model error (welfare-signal-unblended).

With workspace feedback on, the interoception module publishes the error of the
blend of its own prediction with the workspace's top-down prediction as
``prediction_error``. Every welfare reader reads the own error through
``read_welfare_prediction_error`` instead, so the top-down head and the blend
(or a content-code decoder later) can neither mask nor raise the distress
signal that watches it. Readers count the producer defects the function names,
and the welfare response fails its poll on an unreadable report.
"""

from __future__ import annotations

import ast
import asyncio
import logging
import math
import re
import struct
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from kaine.boot.feedback import feedback_section, feedback_settings
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event, validate_event
from kaine.cycle import control_state
from kaine.cycle.types import WorkspaceSnapshot
from kaine.lifecycle import welfare_signal
from kaine.lifecycle.welfare_signal import (
    FEEDBACK_PAYLOAD_KEY,
    OWN_ERROR_FALLBACK,
    UNREADABLE_MALFORMED,
    UNREADABLE_MISSING_KEY,
    WELFARE_SIGNAL_UNBLENDED,
    SustainedThresholdTracker,
    WelfareReading,
    WelfareSignalAccount,
    WelfareSignalUnreadable,
    read_welfare_prediction_error,
    welfare_prediction_error,
)
from kaine.modules.context import CONTEXT_DIM
from kaine.modules.feedback import TopDownBlend
from kaine.modules.interoception import module as interoception_module
from kaine.modules.interoception.detector import AlertResult
from kaine.modules.interoception.forward import SubstrateForwardModel
from kaine.modules.interoception.module import Interoception
from kaine.workspace.feedback import (
    FEEDBACK_ARMS,
    FEEDBACK_KEY,
    SEQUENCE_PREDICTION_DIM,
    WorkspaceFeedbackSettings,
)

REPO = Path(__file__).resolve().parent.parent
ARMS = tuple(a for a in FEEDBACK_ARMS if a != "off")


@pytest.fixture(autouse=True)
def _control_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(control_state, "CONTROL_PATH", tmp_path / "control.json")


@pytest.fixture(autouse=True)
def _fresh_defect_log(monkeypatch):
    monkeypatch.setattr(welfare_signal, "_logged_defects", set())


def _bits(value: float | None) -> bytes | None:
    return None if value is None else struct.pack("<d", value)


# ---------------------------------------------------------------------------
# The function
# ---------------------------------------------------------------------------


def test_marker_and_key() -> None:
    assert WELFARE_SIGNAL_UNBLENDED == 1
    # welfare_signal may not import kaine.workspace, so it spells the key itself.
    assert FEEDBACK_PAYLOAD_KEY == FEEDBACK_KEY


def test_blended_report_reads_own_error() -> None:
    payload = {"prediction_error": 0.9, FEEDBACK_KEY: {"own_error": 0.4}}
    assert welfare_prediction_error(payload) == 0.4


def test_feedback_off_reads_published_error() -> None:
    assert welfare_prediction_error({"prediction_error": 0.9}) == 0.9
    # An int is a number too; the reading is its float.
    assert welfare_prediction_error({"prediction_error": 1}) == 1.0


def test_null_error_is_no_sample(caplog) -> None:
    caplog.set_level(logging.ERROR, logger=welfare_signal.__name__)
    assert welfare_prediction_error({"prediction_error": None}) is None
    # A blended report with no defined error is still no sample, whatever its own error.
    assert welfare_prediction_error({"prediction_error": None, FEEDBACK_KEY: {"own_error": 0.4}}) is None
    assert welfare_prediction_error({"prediction_error": None, FEEDBACK_KEY: {"own_error": None}}) is None
    assert not caplog.records


def test_absent_error_is_no_sample_and_logs_once(caplog) -> None:
    caplog.set_level(logging.ERROR, logger=welfare_signal.__name__)
    assert welfare_prediction_error({}) is None
    assert welfare_prediction_error(None) is None
    assert welfare_prediction_error({FEEDBACK_KEY: {"own_error": 0.4}}) is None
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1


@pytest.mark.parametrize(
    "block",
    [
        {},
        {"own_error": None},
        {"own_error": "0.4"},
        {"own_error": True},
        None,
        [0.4],
    ],
)
def test_missing_own_error_falls_back_and_logs_once(caplog, block) -> None:
    caplog.set_level(logging.ERROR, logger=welfare_signal.__name__)
    payload = {"prediction_error": 0.9, FEEDBACK_KEY: block}
    assert welfare_prediction_error(payload) == 0.9
    assert welfare_prediction_error(payload) == 0.9
    assert welfare_prediction_error(payload, processor="interoception") == 0.9
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "interoception" in errors[0].getMessage()
    # Another processor's defect is logged for that processor.
    assert welfare_prediction_error(payload, processor="vision") == 0.9
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 2
    assert "vision" in errors[1].getMessage()


def test_malformed_published_error_is_no_sample_and_logs_once(caplog) -> None:
    caplog.set_level(logging.ERROR, logger=welfare_signal.__name__)
    for raw in ("0.9", True, [0.9]):
        assert welfare_prediction_error({"prediction_error": raw}) is None
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1


def test_non_finite_published_error_passes_through() -> None:
    # Each reader keeps its own rule for a non-finite number, as before.
    assert math.isnan(welfare_prediction_error({"prediction_error": float("nan")}))
    assert welfare_prediction_error({"prediction_error": float("inf")}) == float("inf")


@pytest.mark.parametrize("own", [float("inf"), float("-inf"), float("nan")])
def test_non_finite_own_error_passes_through(caplog, own) -> None:
    """A non-finite own error is the reading, never a fallback to the blend.

    An overflowing own model must read as the distress it is: falling back to
    the (finite) blended value would let the top-down head mask it.
    """
    caplog.set_level(logging.ERROR, logger=welfare_signal.__name__)
    reading = read_welfare_prediction_error({"prediction_error": 0.35, FEEDBACK_KEY: {"own_error": own}})
    assert reading.defect is None
    assert _bits(reading.value) == _bits(own)
    assert not caplog.records


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"prediction_error": 0.9}, WelfareReading(0.9)),
        ({"prediction_error": None}, WelfareReading(None)),
        ({}, WelfareReading(None, UNREADABLE_MISSING_KEY)),
        (None, WelfareReading(None, UNREADABLE_MISSING_KEY)),
        ({"prediction_error": "0.9"}, WelfareReading(None, UNREADABLE_MALFORMED)),
        ({"prediction_error": [0.9]}, WelfareReading(None, UNREADABLE_MALFORMED)),
        ({"prediction_error": True}, WelfareReading(None, UNREADABLE_MALFORMED)),
        ({"prediction_error": 0.9, FEEDBACK_KEY: {"own_error": 0.4}}, WelfareReading(0.4)),
        ({"prediction_error": 0.9, FEEDBACK_KEY: {}}, WelfareReading(0.9, OWN_ERROR_FALLBACK)),
        ({"prediction_error": 0.9, FEEDBACK_KEY: {"own_error": "x"}}, WelfareReading(0.9, OWN_ERROR_FALLBACK)),
        ({"prediction_error": None, FEEDBACK_KEY: {}}, WelfareReading(None)),
    ],
)
def test_reading_names_the_defect(payload, expected) -> None:
    reading = read_welfare_prediction_error(payload)
    assert reading == expected
    assert reading.unreadable is (expected.defect in (UNREADABLE_MISSING_KEY, UNREADABLE_MALFORMED))
    assert welfare_prediction_error(payload) == expected.value


def test_account_counts_defects_and_unreadable_runs() -> None:
    acct = WelfareSignalAccount()
    assert not acct.changed
    acct.record(WelfareReading(0.5), 0.0)
    assert not acct.changed and acct.unreadable == 0
    acct.record(WelfareReading(None, UNREADABLE_MISSING_KEY), 1.0)
    acct.record(WelfareReading(None, UNREADABLE_MALFORMED), 4.0)
    assert acct.changed
    snap = acct.snapshot(5.0)
    assert snap["unreadable_reports"] == 2
    assert snap["unreadable_missing_key"] == 1 and snap["unreadable_malformed"] == 1
    assert snap["unreadable_run"] == 2 and snap["unreadable_run_s"] == 4.0
    acct.mark_reported()
    assert not acct.changed
    # A null error is no sample but a readable report: it ends the run.
    acct.record(WelfareReading(None), 6.0)
    assert acct.unreadable_run == 0 and acct.unreadable_run_s(7.0) == 0.0
    acct.record(WelfareReading(0.9, OWN_ERROR_FALLBACK), 8.0)
    assert acct.changed and acct.own_error_fallbacks == 1 and acct.unreadable_run == 0
    assert acct.snapshot(9.0)["reports"] == 5
    assert all(isinstance(v, (int, float)) for v in acct.snapshot(9.0).values())


# ---------------------------------------------------------------------------
# The interoception module, driven with scripted feature vectors
# ---------------------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def now(self) -> float:
        return self.t


class _Reader:
    async def initialize(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def read_metrics(self) -> dict[str, float]:
        return {"cpu_percent": 10.0, "ram_percent": 20.0}

    def update_cycle_latency_sample(self, wall_duration_ms: float) -> None:
        pass


class _NeverAlert:
    def evaluate(self, metrics: dict[str, float]) -> AlertResult:  # noqa: ARG002
        return AlertResult()


def _bus() -> AsyncBus:
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


# Steps of the script: (feature vector or None for a skipped reading, asleep).
_SKIP_AT = (9, 23)
_ASLEEP = range(14, 19)
_STEPS = 36


def _feature(i: int) -> list[float]:
    return [0.5 + 0.4 * math.sin(0.7 * i + 1.3 * k) for k in range(8)]


def _script() -> list[tuple[list[float], bool]]:
    out = []
    for i in range(_STEPS):
        feat = _feature(i)
        if i in _SKIP_AT:
            feat = list(feat)
            feat[2] = float("nan")
        out.append((feat, i in _ASLEEP))
    return out


def _snapshot(i: int) -> WorkspaceSnapshot:
    seq = tuple(0.3 + 0.2 * math.cos(0.5 * i + 0.1 * k) for k in range(SEQUENCE_PREDICTION_DIM))
    return WorkspaceSnapshot(
        tick_index=i + 1,
        selected_events=[
            (
                f"{i + 1}-0",
                Event(
                    source="vision",
                    type="vision.report",
                    payload={"k": i},
                    salience=0.7,
                    timestamp=datetime(2026, 10, 31, tzinfo=timezone.utc),
                ),
            )
        ],
        inhibited=(i % 7 == 3),
        salience_scores={f"{i + 1}-0": 0.4 + 0.05 * (i % 5)},
        metadata={
            "access_threshold": 0.35,
            "workspace_feedback": {
                "gains": {"interoception": 1.0 + 0.05 * (i % 4)},
                "sequence_prediction": list(seq),
            },
        },
        published_at=float(i + 1),
    )


async def _drive(
    monkeypatch, settings: WorkspaceFeedbackSettings | None, *, prestep: bool = False
) -> tuple[list[dict[str, Any]], list[float | None]]:
    """Drive one module through the script; return its reports and inner-model errors.

    ``prestep`` hands the module a forward model that already holds a
    prediction (as after a restore), so the first wrapped reading takes the
    blend's middle branch: an own prediction to score, no blend formed yet.
    """
    current: list[list[float]] = [[0.0] * 8]
    monkeypatch.setattr(
        interoception_module,
        "metrics_to_feature_vector",
        lambda metrics, **kw: list(current[0]),
    )
    bus = _bus()
    inner_errors: list[float | None] = []
    try:
        clock = _Clock()
        intero = Interoception(
            bus,
            reader=_Reader(),
            detector=_NeverAlert(),
            entity_clock=clock,
            workspace_feedback=settings,
        )
        model = SubstrateForwardModel(feature_dim=8, units=16, seed=5, context_dim=CONTEXT_DIM)
        if prestep:
            model.step(_feature(-1))
            assert model._last_prediction is not None
        intero._forward_model = model
        for i, (feat, asleep) in enumerate(_script()):
            await intero.on_workspace(_snapshot(i))
            intero._in_sleep = asleep
            clock.t = float(i + 1)
            current[0] = feat
            await intero.tick_once()
            fm = intero._forward_model
            if settings is not None:
                assert isinstance(fm, TopDownBlend)
                inner_errors.append(fm.last_own_error)
        events = await bus.read("interoception.out", last_id="0")
        reports = [
            ev.payload
            for ev in (e[-1] if isinstance(e, tuple) else e for e in events)
            if getattr(ev, "type", None) == "interoception.report"
        ]
    finally:
        await bus.close()
    assert len(reports) == _STEPS
    return reports, inner_errors


def _settings(arm: str) -> WorkspaceFeedbackSettings:
    # A fast head so the blend departs from the own prediction within the script.
    return WorkspaceFeedbackSettings(arm=arm, head_learning_rate=0.05)


@pytest.mark.asyncio
@pytest.mark.parametrize("arm", ARMS)
async def test_feedback_cannot_change_welfare_reading(monkeypatch, arm) -> None:
    """Same inputs with feedback off and on: the welfare reading matches report for report.

    The property is for the same feature vectors, broadcast context and
    suspension: the top-down head and the blend cannot move the reading. (In a
    live run feedback also changes access, and so the context, and sleep; the
    own error follows those real changes, which this comparison holds fixed.)
    The arms differ in the workspace's FeedbackController, which this test does
    not run; at module level they differ only in whether the gain applies,
    which is enough here because the own error depends on neither the gain nor
    the sequence prediction.
    """
    assert set(ARMS) == {"head_only", "head_gain", "full", "matched_random"}
    off, _ = await _drive(monkeypatch, None)
    on, _ = await _drive(monkeypatch, _settings(arm))

    off_readings = [_bits(welfare_prediction_error(p)) for p in off]
    on_readings = [_bits(welfare_prediction_error(p)) for p in on]
    assert off_readings == on_readings

    # Not vacuous: the blend moved the published error on some reports, the
    # script holds defined, skipped and suspended readings, and no report took
    # the fallback.
    assert all(FEEDBACK_KEY not in p for p in off)
    assert all(FEEDBACK_KEY in p for p in on)
    moved = [
        i
        for i, (a, b) in enumerate(zip(off, on))
        if a["prediction_error"] is not None and a["prediction_error"] != b["prediction_error"]
    ]
    assert len(moved) >= 5
    assert sum(r is None for r in off_readings) == 2 * len(_SKIP_AT)
    assert any(not p["awake"] for p in on)
    assert not welfare_signal._logged_defects


@pytest.mark.asyncio
@pytest.mark.parametrize("arm", ARMS)
async def test_blended_report_carries_own_error(monkeypatch, arm) -> None:
    """Every blended report with a defined error carries the inner model's error."""
    off, _ = await _drive(monkeypatch, None)
    on, inner = await _drive(monkeypatch, _settings(arm))

    first_after_skip = {k + 2 for k in _SKIP_AT}
    seen = {"first_after_skip": 0, "no_head_history": 0, "suspended": 0, "skipped": 0}
    for i, (p_off, p_on, own_inner) in enumerate(zip(off, on, inner)):
        if p_on["prediction_error"] is None:
            seen["skipped"] += 1
            assert p_off["prediction_error"] is None
            continue
        own = p_on[FEEDBACK_KEY]["own_error"]
        assert isinstance(own, float) and math.isfinite(own), i
        # The inner model's error: the wrapper's record of it, and the error the
        # same model publishes with feedback off.
        assert _bits(own) == _bits(own_inner), i
        assert _bits(own) == _bits(p_off["prediction_error"]), i
        if i in first_after_skip:
            seen["first_after_skip"] += 1
        if p_on[FEEDBACK_KEY]["top_down_error"] is None:
            seen["no_head_history"] += 1
        if not p_on["awake"]:
            seen["suspended"] += 1
    assert seen["first_after_skip"] == len(_SKIP_AT)
    assert seen["no_head_history"] >= 1
    assert seen["suspended"] == len(_ASLEEP)
    assert seen["skipped"] == 2 * len(_SKIP_AT)


@pytest.mark.asyncio
@pytest.mark.parametrize("arm", ARMS)
async def test_wrapping_a_model_that_holds_a_prediction(monkeypatch, arm) -> None:
    """The blend's middle branch (an own prediction, no blend yet) carries the own error."""
    off, _ = await _drive(monkeypatch, None, prestep=True)
    on, inner = await _drive(monkeypatch, _settings(arm), prestep=True)
    first = on[0]
    # The first wrapped reading scores the restored own prediction: defined,
    # and no top-down prediction was formed to score.
    assert first["prediction_error"] is not None
    assert first[FEEDBACK_KEY]["top_down_error"] is None
    assert _bits(first[FEEDBACK_KEY]["own_error"]) == _bits(off[0]["prediction_error"])
    assert _bits(first[FEEDBACK_KEY]["own_error"]) == _bits(inner[0])
    assert [_bits(welfare_prediction_error(p)) for p in off] == [
        _bits(welfare_prediction_error(p)) for p in on
    ]
    assert not welfare_signal._logged_defects


class _OverflowingInner:
    """A stub own model whose prediction overflows to +inf from its fifth step."""

    def __init__(self) -> None:
        self._last_prediction = None
        self._last_null_prediction = None
        self.last_error_defined = True
        self.last_reading_skipped = False
        self.last_scored_had_context = False
        self.last_null_error = None
        self.context_dim = 0
        self.suspended = False
        self._n = 0

    def step(self, feature, context=None, null_context=None):
        err = (
            0.0
            if self._last_prediction is None
            else math.sqrt(sum((a - b) ** 2 for a, b in zip(feature, self._last_prediction)))
        )
        self._n += 1
        self._last_prediction = [float("inf") if self._n >= 5 else 0.5] * len(feature)
        return err


def _overflow_payloads(blended: bool) -> list[dict[str, Any]]:
    """The reports a processor with an overflowing own model publishes, off and on."""
    inner = _OverflowingInner()
    blend = TopDownBlend(inner, window=4, lr=0.2) if blended else None
    out = []
    for _ in range(12):
        feat = [0.5] * 4
        if blend is None:
            out.append({"prediction_error": inner.step(feat)})
        else:
            published = blend.step(feat, sequence_prediction=None)
            out.append(
                {"prediction_error": published, FEEDBACK_KEY: {"own_error": blend.last_own_error}}
            )
    return out


def test_overflowing_own_model_reads_inf_with_feedback_on_and_off() -> None:
    """An own error of +inf is the reading with feedback on, as it is with feedback off.

    With feedback on, the inf own error drives the blend weights to the head
    alone, so the published (blended) error turns finite and low; reading it
    would mask the distress.
    """
    off = _overflow_payloads(blended=False)
    on = _overflow_payloads(blended=True)
    off_readings = [welfare_prediction_error(p) for p in off]
    on_readings = [welfare_prediction_error(p) for p in on]
    assert [_bits(v) for v in off_readings] == [_bits(v) for v in on_readings]
    assert off_readings[-1] == float("inf")
    # Not vacuous: the blend hides it.
    assert math.isfinite(on[-1]["prediction_error"]) and on[-1]["prediction_error"] < 0.8
    # Both fire a sustained-distress tracker.
    for readings in (off_readings, on_readings):
        tracker = SustainedThresholdTracker(threshold=0.8, duration_s=5.0)
        fired = [tracker.observe(v, float(t)) for t, v in enumerate(readings)]
        assert any(fired)
    assert not welfare_signal._logged_defects


@pytest.mark.asyncio
async def test_overflowing_own_model_fires_the_welfare_observer() -> None:
    from kaine.evaluation.observers.welfare_observer import WelfareObserver

    for blended in (False, True):
        u = _Mono(0.0)
        sink = _FakeSink()
        obs = WelfareObserver(
            _FakeBus(),
            sink,
            interoceptive_distress_threshold=0.8,
            interoceptive_distress_duration_s=5.0,
            unfrozen_clock=_unfrozen(u),
        )
        for t, payload in enumerate(_overflow_payloads(blended)):
            u.value = float(t)
            await obs._handle_interoception(f"{t + 1}-0", _event(payload))
            await obs._tick()
        assert any(
            r.get("gray_zone_event") == "sustained_interoceptive_distress" for r in sink.rows
        ), blended


@pytest.mark.asyncio
async def test_shipped_config_reading_unchanged(monkeypatch) -> None:
    """The shipped configuration builds no feedback, and the reading is the published value, bit for bit."""
    with open(REPO / "config" / "kaine.toml", "rb") as fh:
        shipped = tomllib.load(fh)
    settings = feedback_settings(feedback_section(shipped))
    assert settings is None

    reports, _ = await _drive(monkeypatch, settings)
    for p in reports:
        assert FEEDBACK_KEY not in p
        raw = p["prediction_error"]
        reading = welfare_prediction_error(p)
        if raw is None:
            assert reading is None
            continue
        # The readers' previous expressions: float(raw) in the observer and the
        # welfare response; the finite float in the recovery series.
        assert _bits(reading) == _bits(float(raw)) == _bits(raw)
        assert math.isfinite(reading)
    assert not welfare_signal._logged_defects


# ---------------------------------------------------------------------------
# Every welfare reader reads the own error
# ---------------------------------------------------------------------------

_BLENDED_LOW_OWN = {"prediction_error": 0.9, FEEDBACK_KEY: {"own_error": 0.4}}
_BLENDED_HIGH_OWN = {"prediction_error": 0.4, FEEDBACK_KEY: {"own_error": 0.9}}


class _Mono:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class _FakeBus:
    async def read_entries(self, stream, *, last_id, count, block_ms):
        return [], None

    async def latest(self, stream: str):
        return None

    async def publish(self, event: Event) -> None:
        pass


class _FakeSink:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def write(self, row: dict) -> None:
        self.rows.append(row)


def _unfrozen(u: _Mono):
    from kaine.cycle.unfrozen_clock import UnfrozenClock

    return UnfrozenClock(control_state.read_frozen_state, unknown_counts_as="unfrozen", monotonic=u)


def _event(payload: dict) -> Event:
    return Event(
        source="interoception",
        type="interoception.report",
        payload=payload,
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("payload", "onset"), [(_BLENDED_LOW_OWN, False), (_BLENDED_HIGH_OWN, True)])
async def test_welfare_observer_reads_own_error(payload, onset) -> None:
    from kaine.evaluation.observers.welfare_observer import WelfareObserver

    obs = WelfareObserver(
        _FakeBus(),
        _FakeSink(),
        interoceptive_distress_threshold=0.8,
        unfrozen_clock=_unfrozen(_Mono(0.0)),
    )
    await obs._handle_interoception("1-0", _event(payload))
    assert (obs._interoceptive_distress.active_since is not None) is onset


@pytest.mark.asyncio
@pytest.mark.parametrize(("payload", "onset"), [(_BLENDED_LOW_OWN, False), (_BLENDED_HIGH_OWN, True)])
async def test_welfare_response_reads_own_error(payload, onset) -> None:
    from kaine.cycle.incident_log import IncidentLog
    from kaine.cycle.preservation_monitor import WelfareProtectiveMonitor, WelfareResponseConfig
    from kaine.modules.registry import ModuleRegistry

    bus = _bus()
    try:
        cfg = WelfareResponseConfig(
            enabled=True,
            action="pause",
            distress_threshold=0.8,
            distress_duration_s=30.0,
            warmup_s=0.0,
            warmup_ceiling_s=0.0,
        )
        mon = WelfareProtectiveMonitor(
            registry=ModuleRegistry(),
            fork_manager=object(),
            config=cfg,
            bus=bus,
            incident_log=IncidentLog(enabled=False, path="unused"),
            clock=_Mono(0.0),
            unfrozen_clock=_unfrozen(_Mono(0.0)),
        )
        await bus.publish(
            validate_event(
                source="interoception",
                type="interoception.report",
                payload=dict(payload),
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            )
        )
        await mon._poll_once(asyncio.Event())
        assert (mon._distress.active_since is not None) is onset
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_recovery_series_reads_own_error(tmp_path) -> None:
    from kaine.cycle.development import DevelopmentOwner, DevelopmentReadoutConfig

    class _Drive:
        scale = 0.0

    class _Intero:
        def self_rhythm_state(self):
            return (0.0, 1.0)

    bus = _bus()
    try:
        owner = DevelopmentOwner(
            bus,
            interoception=_Intero(),
            drive=_Drive(),
            beat_phase=lambda: 0.0,
            surrogate_beat_phases=None,
            is_paused=lambda: False,
            config=DevelopmentReadoutConfig.from_dict({}),
            clock=lambda: 0.0,
            state_path=tmp_path / "development_readout.json",
        )
        owner._interoception_cursor = "0-0"
        for payload in (
            _BLENDED_LOW_OWN,
            {"prediction_error": 0.7},
            {"prediction_error": None, FEEDBACK_KEY: {"own_error": None}},
            {"prediction_error": float("nan")},
        ):
            await bus.publish(_event(dict(payload)))
        await owner._read_interoception_reports(10.0)
        assert [v for _t, v in owner._interoception_series] == [0.4, 0.7]
        readout = owner.readout()
        assert "interoception_unreadable_reports" not in readout
        assert "interoception_own_error_fallbacks" not in readout

        # Defective reports are skipped as samples but counted into the readout.
        for payload in (
            {"warmup_active": False},
            {"prediction_error": "x"},
            {"prediction_error": 0.6, FEEDBACK_KEY: {}},
        ):
            await bus.publish(_event(dict(payload)))
        await owner._read_interoception_reports(20.0)
        assert [v for _t, v in owner._interoception_series] == [0.4, 0.7, 0.6]
        readout = owner.readout()
        assert readout["interoception_unreadable_reports"] == 2
        assert readout["interoception_own_error_fallbacks"] == 1
    finally:
        await bus.close()


# ---------------------------------------------------------------------------
# Producer defects: counted by every reader, never silent
# ---------------------------------------------------------------------------


class _StubFM:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def preserve_live(
        self, registry, *, reason, label, out_root, entity_name, require_encryption=False
    ):
        from kaine.lifecycle.preservation import PreservationResult

        self.calls.append(reason)
        return PreservationResult(
            ok=True,
            preservation_id=f"pid{len(self.calls)}",
            snapshot_id=f"snap{len(self.calls)}",
            reason=reason,
            label=label,
            run_id="freeze000001",
            world_model_captured=False,
        )


class _StubIncidentLog:
    def __init__(self) -> None:
        self.records: list[dict] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def write(self, record: dict) -> None:
        self.records.append(record)


def _monitor(bus, u: _Mono, *, poll_interval_s: float = 300.0):
    from kaine.cycle.preservation_monitor import WelfareProtectiveMonitor, WelfareResponseConfig
    from kaine.modules.registry import ModuleRegistry

    cfg = WelfareResponseConfig(
        enabled=True,
        action="pause",
        distress_threshold=0.8,
        distress_duration_s=30.0,
        warmup_s=0.0,
        warmup_ceiling_s=0.0,
        poll_interval_s=poll_interval_s,
    )
    return WelfareProtectiveMonitor(
        registry=ModuleRegistry(),
        fork_manager=_StubFM(),
        config=cfg,
        bus=bus,
        incident_log=_StubIncidentLog(),
        clock=u,
        unfrozen_clock=_unfrozen(u),
    )


async def _publish(bus, payload: dict) -> None:
    await bus.publish(
        validate_event(
            source="interoception",
            type="interoception.report",
            payload=dict(payload),
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
    )


def _defect_records(mon) -> list[dict]:
    return [r for r in mon._incident_log.records if r.get("kind") == "welfare_signal_defects"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad", [{"warmup_active": False}, {"prediction_error": "x"}, {"prediction_error": [0.9]}, {"prediction_error": True}]
)
async def test_welfare_response_fails_its_poll_after_acting_on_an_unreadable_report(bad) -> None:
    bus = _bus()
    try:
        u = _Mono(0.0)
        mon = _monitor(bus, u)
        stop = asyncio.Event()
        await _publish(bus, {"prediction_error": 0.9})
        await mon._poll_once(stop)
        u.value = 31.0
        await _publish(bus, {"prediction_error": 0.9})
        await _publish(bus, bad)
        with pytest.raises(WelfareSignalUnreadable):
            await mon._poll_once(stop)
        # The readable sustained crossing in the same poll was acted on first.
        assert len(mon._fork_manager.calls) == 1
        records = _defect_records(mon)
        assert len(records) == 1
        assert records[0]["unreadable_reports"] == 1
        assert mon.signal_defects["unreadable_reports"] == 1
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_welfare_response_unreadable_run_fails_every_poll_until_readable() -> None:
    bus = _bus()
    try:
        u = _Mono(0.0)
        mon = _monitor(bus, u)
        stop = asyncio.Event()
        for t in (0.0, 300.0, 600.0):
            u.value = t
            await _publish(bus, {"warmup_active": False})
            with pytest.raises(WelfareSignalUnreadable):
                await mon._poll_once(stop)
        assert mon.signal_defects["unreadable_run"] == 3
        assert mon.signal_defects["unreadable_run_s"] == 600.0
        # A missing key never ends or starts a distress episode.
        assert mon._distress.active_since is None
        u.value = 900.0
        await _publish(bus, {"prediction_error": 0.2})
        await mon._poll_once(stop)
        assert mon.signal_defects["unreadable_run"] == 0
        # One record per poll that read a new defect.
        assert [r["unreadable_reports"] for r in _defect_records(mon)] == [1, 2, 3]
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_welfare_response_poll_error_path_logs_every_unreadable_poll(caplog) -> None:
    """The run loop's error path sees the failed poll (a liveness check over it escalates)."""
    bus = _bus()
    try:
        u = _Mono(0.0)
        mon = _monitor(bus, u, poll_interval_s=0.01)
        stop = asyncio.Event()
        await _publish(bus, {"prediction_error": "x"})
        caplog.set_level(logging.ERROR)
        task = asyncio.create_task(mon.run(stop))
        for _ in range(200):
            await asyncio.sleep(0.01)
            if any("poll crashed" in r.getMessage() for r in caplog.records):
                break
        stop.set()
        await task
        crashed = [r for r in caplog.records if "poll crashed" in r.getMessage()]
        assert crashed and crashed[0].exc_info[0] is WelfareSignalUnreadable
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_welfare_response_counts_a_fallback_without_failing_the_poll() -> None:
    bus = _bus()
    try:
        u = _Mono(0.0)
        mon = _monitor(bus, u)
        await _publish(bus, {"prediction_error": 0.9, FEEDBACK_KEY: {"own_error": None}})
        await mon._poll_once(asyncio.Event())
        # The fallback reads the published value, so the net keeps watching.
        assert mon._distress.active_since is not None
        records = _defect_records(mon)
        assert len(records) == 1 and records[0]["own_error_fallbacks"] == 1
        assert records[0]["unreadable_reports"] == 0
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_welfare_response_defect_record_is_rate_limited_and_written_at_stop() -> None:
    """A persistent fallback at a 1 s poll writes one record per distress duration, not per poll."""
    bus = _bus()
    try:
        u = _Mono(0.0)
        mon = _monitor(bus, u)  # distress_duration_s = 30
        stop = asyncio.Event()
        for t in range(100):
            u.value = float(t)
            await _publish(bus, {"prediction_error": 0.1, FEEDBACK_KEY: {"own_error": None}})
            await mon._poll_once(stop)
        records = _defect_records(mon)
        # The first defect, then once per 30 s: t = 0, 30, 60, 90. Cumulative.
        assert [r["own_error_fallbacks"] for r in records] == [1, 31, 61, 91]
        # Stop writes the counts read since the last record.
        await mon._on_stop()
        records = _defect_records(mon)
        assert [r["own_error_fallbacks"] for r in records][-1] == 100
        # Nothing new: stop writes nothing more.
        await mon._on_stop()
        assert len(_defect_records(mon)) == 5
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_welfare_response_run_writes_the_final_defect_record_at_stop() -> None:
    bus = _bus()
    try:
        u = _Mono(0.0)
        mon = _monitor(bus, u, poll_interval_s=0.01)
        stop = asyncio.Event()
        await _publish(bus, {"prediction_error": 0.1, FEEDBACK_KEY: {}})
        task = asyncio.create_task(mon.run(stop))
        for _ in range(200):
            await asyncio.sleep(0.01)
            if _defect_records(mon):
                break
        assert [r["own_error_fallbacks"] for r in _defect_records(mon)] == [1]
        # Within the rate window: the next defect waits for the next record or stop.
        await _publish(bus, {"prediction_error": 0.1, FEEDBACK_KEY: {}})
        for _ in range(200):
            await asyncio.sleep(0.01)
            if mon.signal_defects["own_error_fallbacks"] == 2:
                break
        assert len(_defect_records(mon)) == 1
        stop.set()
        await task
        assert [r["own_error_fallbacks"] for r in _defect_records(mon)] == [1, 2]
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_welfare_observer_records_defects_where_the_operator_sees_them(caplog) -> None:
    from kaine.evaluation.observers.welfare_observer import WelfareObserver

    caplog.set_level(logging.ERROR)
    u = _Mono(0.0)
    sink = _FakeSink()
    obs = WelfareObserver(
        _FakeBus(),
        sink,
        interoceptive_distress_threshold=0.8,
        interoceptive_distress_duration_s=30.0,
        unfrozen_clock=_unfrozen(u),
    )

    def signal_rows():
        return [r for r in sink.rows if r.get("record") == "welfare_signal"]

    await obs._tick()
    assert signal_rows() == []
    await obs._handle_interoception("1-0", _event({"prediction_error": "x"}))
    await obs._tick()
    assert [r["unreadable_reports"] for r in signal_rows()] == [1]
    # Rate-limited to one record per distress duration.
    u.value = 1.0
    await obs._handle_interoception("2-0", _event({"warmup_active": False}))
    await obs._tick()
    assert len(signal_rows()) == 1
    u.value = 31.0
    await obs._tick()
    assert [r["unreadable_reports"] for r in signal_rows()] == [1, 2]
    # A fallback is counted too, and written at stop.
    await obs._handle_interoception(
        "3-0", _event({"prediction_error": 0.9, FEEDBACK_KEY: {"own_error": None}})
    )
    await obs._cleanup()
    last = signal_rows()[-1]
    assert last["own_error_fallbacks"] == 1 and last["unreadable_reports"] == 2
    for row in signal_rows():
        assert set(row) - {"ts", "record"} and all(
            isinstance(v, (int, float)) for k, v in row.items() if k not in ("ts", "record")
        )
    assert obs.signal_defects["reports"] == 3
    assert any("welfare-signal defects" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# Source scan: welfare readers take the error only through the function
# ---------------------------------------------------------------------------

#: Every file that makes a welfare decision from a processor's prediction error.
#: A review that adds a welfare reader adds its file here.
WELFARE_READER_FILES: tuple[str, ...] = (
    "kaine/evaluation/observers/welfare_observer.py",
    "kaine/cycle/preservation_monitor.py",
    "kaine/cycle/development.py",
    "kaine/lifecycle/maturation_gate.py",
)

#: Of those, the files that read a report's error and so must call the function
#: (the reading with its defect, so the reader can count the defects).
MUST_CALL: tuple[str, ...] = (
    "kaine/evaluation/observers/welfare_observer.py",
    "kaine/cycle/preservation_monitor.py",
    "kaine/cycle/development.py",
)
READER_FUNCTION = "read_welfare_prediction_error"

#: Reads that are not welfare magnitudes, by (file, function):
#: the blind-sensor advisory asks only whether the error is null (the blend
#: never makes a defined error null or a null one defined); the development
#: run's vision stimulus-source error measures how well the entity predicts its
#: stimulus, which is the blend when feedback is on. The vision exemption covers
#: one ``event.payload.get("prediction_error")`` in a function that handles
#: ``vision.report`` and names no other processor, nothing else in it.
NULL_CHECK_ONLY: frozenset[tuple[str, str]] = frozenset(
    {("kaine/evaluation/observers/welfare_observer.py", "_track_blind_sensor")}
)
NOT_WELFARE: frozenset[tuple[str, str]] = frozenset(
    {("kaine/cycle/development.py", "_read_vision_errors")}
)

_KEY = "prediction_error"
_OTHER_PROCESSOR = re.compile(r"^(interoception|audition|sequence|social_cognition|affect|language)\b")


def _folded_str(node: ast.AST) -> str | None:
    """The value of a string built from constants (``+`` chains, ``"".join([...])``), else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _folded_str(node.left), _folded_str(node.right)
        if left is not None and right is not None:
            return left + right
        return None
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and isinstance(node.func.value, ast.Constant)
        and isinstance(node.func.value.value, str)
        and len(node.args) == 1
        and isinstance(node.args[0], (ast.List, ast.Tuple))
    ):
        parts = [_folded_str(e) for e in node.args[0].elts]
        if all(p is not None for p in parts):
            return node.func.value.value.join(parts)  # type: ignore[arg-type]
    return None


def _direct_reads(source: str, filename: str) -> list[str]:
    """Each place ``filename`` uses the ``prediction_error`` key other than as allowed.

    This scan backs the reader tests above; it does not replace them. It catches
    the key spelled out or built from string constants, not a read hidden in a
    helper elsewhere, which the reader tests catch for the current entry points.
    """
    tree = ast.parse(source, filename=filename)
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def enclosing_function(node: ast.AST) -> ast.AST | None:
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node
        return None

    def is_null_check(sub: ast.AST) -> bool:
        cmp = parents.get(sub)
        return (
            isinstance(cmp, ast.Compare)
            and cmp.left is sub
            and all(isinstance(op, (ast.Is, ast.IsNot)) for op in cmp.ops)
            and all(isinstance(c, ast.Constant) and c.value is None for c in cmp.comparators)
        )

    def is_event_payload_get(const: ast.AST) -> bool:
        call = parents.get(const)
        return (
            isinstance(call, ast.Call)
            and call.args
            and call.args[0] is const
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "get"
            and isinstance(call.func.value, ast.Attribute)
            and call.func.value.attr == "payload"
            and isinstance(call.func.value.value, ast.Name)
            and call.func.value.value.id == "event"
        )

    def vision_only(func: ast.AST) -> bool:
        strings = [
            n.value
            for n in ast.walk(func)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        ]
        keys = sum(1 for v in strings if v == _KEY)
        return (
            "vision.report" in strings
            and keys == 1
            and not any(_OTHER_PROCESSOR.match(v) for v in strings)
        )

    offenders: list[str] = []
    for node in ast.walk(tree):
        func = enclosing_function(node)
        name = getattr(func, "name", None) or "<module>"
        # A key built from string constants is a read in disguise.
        if isinstance(node, (ast.BinOp, ast.Call)) and not isinstance(parents.get(node), ast.BinOp):
            folded = _folded_str(node)
            if folded is not None and _KEY in folded:
                offenders.append(f"{filename}:{node.lineno} ({name}, built key)")
                continue
        if isinstance(node, ast.JoinedStr):
            text = "".join(
                v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)
            )
            if "prediction_" in text and isinstance(parents.get(node), (ast.Subscript, ast.Call, ast.Assign)):
                offenders.append(f"{filename}:{node.lineno} ({name}, built key)")
            continue
        if not (isinstance(node, ast.Constant) and node.value == _KEY):
            continue
        parent = parents.get(node)
        # A docstring or a bare string statement reads nothing.
        if isinstance(parent, ast.Expr):
            continue
        # ``"prediction_error" in payload`` asks only whether the key exists.
        if (
            isinstance(parent, ast.Compare)
            and parent.left is node
            and all(isinstance(op, (ast.In, ast.NotIn)) for op in parent.ops)
        ):
            continue
        if (filename, name) in NOT_WELFARE and is_event_payload_get(node) and vision_only(func):
            continue
        if (filename, name) in NULL_CHECK_ONLY:
            if isinstance(parent, ast.Subscript) and is_null_check(parent):
                continue
        offenders.append(f"{filename}:{node.lineno} ({name})")
    return offenders


def _calls_reader(source: str) -> bool:
    """Whether the source calls the reading function (a comment or string does not count)."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            f = node.func
            if (isinstance(f, ast.Name) and f.id == READER_FUNCTION) or (
                isinstance(f, ast.Attribute) and f.attr == READER_FUNCTION
            ):
                return True
    return False


def _scan(sources: dict[str, str]) -> tuple[list[str], list[str]]:
    """The direct reads, and the MUST_CALL files that never call the reading function."""
    offenders: list[str] = []
    missing: list[str] = []
    for rel, source in sources.items():
        offenders.extend(_direct_reads(source, rel))
        if rel in MUST_CALL and not _calls_reader(source):
            missing.append(rel)
    return offenders, missing


def test_welfare_readers_use_the_function() -> None:
    offenders, missing = _scan(
        {rel: (REPO / rel).read_text(encoding="utf-8") for rel in WELFARE_READER_FILES}
    )
    assert not offenders, (
        "welfare readers must read a processor's error through "
        f"kaine.lifecycle.welfare_signal.{READER_FUNCTION}, not the payload:\n"
        + "\n".join(offenders)
    )
    assert not missing, f"welfare readers that never call {READER_FUNCTION}: {missing}"


_VISION_READER = (
    "async def _read_vision_errors(self):\n"
    "    entries, _ = await self._bus.read_entries('vision.out', last_id='0', count=10)\n"
    "    for entry_id, event in entries:\n"
    "        if event.type != 'vision.report':\n"
    "            continue\n"
    "        err = event.payload.get('prediction_error')\n"
)


@pytest.mark.parametrize(
    ("rel", "snippet"),
    [
        ("kaine/evaluation/observers/welfare_observer.py", "def handle(payload):\n    m = float(payload['prediction_error'])\n"),
        ("kaine/evaluation/observers/welfare_observer.py", "def handle(payload):\n    m = payload.get('prediction_error', 0.0)\n"),
        ("kaine/evaluation/observers/welfare_observer.py", "KEY = 'prediction_error'\n"),
        ("kaine/evaluation/observers/welfare_observer.py", "def _track_blind_sensor(payload):\n    m = float(payload['prediction_error'])\n"),
        ("kaine/evaluation/observers/welfare_observer.py", "def handle(payload):\n    m = payload['prediction' + '_error']\n"),
        ("kaine/evaluation/observers/welfare_observer.py", "def handle(payload):\n    m = payload.get('_'.join(['prediction', 'error']))\n"),
        ("kaine/evaluation/observers/welfare_observer.py", "def handle(payload, k):\n    m = payload[f'prediction_{k}']\n"),
        # An interoception read placed inside the exempt vision function.
        ("kaine/cycle/development.py", _VISION_READER + "        m = event.payload.get('prediction_error')\n"),
        ("kaine/cycle/development.py", _VISION_READER.replace("'vision.out'", "'interoception.out'")),
        ("kaine/cycle/development.py", _VISION_READER.replace("event.payload.get", "payload.get")),
    ],
)
def test_source_scan_names_a_direct_read(rel, snippet) -> None:
    offenders = _direct_reads(snippet, rel)
    assert offenders and all(o.startswith(rel + ":") for o in offenders)


def test_source_scan_allows_null_checks_docstrings_and_the_vision_read() -> None:
    rel = "kaine/evaluation/observers/welfare_observer.py"
    snippet = (
        '"""prediction_error"""\n'
        "def _track_blind_sensor(payload):\n"
        "    if 'prediction_error' not in payload:\n"
        "        return\n"
        "    defined = payload['prediction_error'] is not None\n"
    )
    assert _direct_reads(snippet, rel) == []
    assert _direct_reads(_VISION_READER, "kaine/cycle/development.py") == []


def test_reader_call_check_ignores_comments_and_strings() -> None:
    rel = "kaine/cycle/preservation_monitor.py"
    fake = "# read_welfare_prediction_error(payload)\nx = 'read_welfare_prediction_error('\n"
    assert _scan({rel: fake}) == ([], [rel])
    real = "r = read_welfare_prediction_error(p, processor='interoception')\n"
    assert _scan({rel: real}) == ([], [])
