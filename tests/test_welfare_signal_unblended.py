# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The welfare signal is the processor's own forward-model error (welfare-signal-unblended).

With workspace feedback on, the interoception module publishes the error of the
blend of its own prediction with the workspace's top-down prediction as
``prediction_error``. Every welfare reader reads the own error through
``welfare_prediction_error`` instead, so the blend (or a content-code decoder
later) can neither mask nor raise the distress signal that watches it.
"""

from __future__ import annotations

import ast
import asyncio
import logging
import math
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
    WELFARE_SIGNAL_UNBLENDED,
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
    assert welfare_prediction_error(None) is None
    # A blended report with no defined error is still no sample, whatever its own error.
    assert welfare_prediction_error({"prediction_error": None, FEEDBACK_KEY: {"own_error": 0.4}}) is None
    assert welfare_prediction_error({"prediction_error": None, FEEDBACK_KEY: {"own_error": None}}) is None
    assert not caplog.records


def test_absent_error_is_no_sample_and_logs_once(caplog) -> None:
    caplog.set_level(logging.ERROR, logger=welfare_signal.__name__)
    assert welfare_prediction_error({}) is None
    assert welfare_prediction_error({FEEDBACK_KEY: {"own_error": 0.4}}) is None
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1


@pytest.mark.parametrize(
    "block",
    [
        {},
        {"own_error": None},
        {"own_error": float("nan")},
        {"own_error": float("inf")},
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
    monkeypatch, settings: WorkspaceFeedbackSettings | None
) -> tuple[list[dict[str, Any]], list[float | None]]:
    """Drive one module through the script; return its reports and inner-model errors."""
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
        intero._forward_model = SubstrateForwardModel(
            feature_dim=8, units=16, seed=5, context_dim=CONTEXT_DIM
        )
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
    """Same inputs with feedback off and on: the welfare reading matches report for report."""
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
    async def write(self, row: dict) -> None:
        pass


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
    finally:
        await bus.close()


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

#: Of those, the files that read a report's error and so must call the function.
MUST_CALL: tuple[str, ...] = (
    "kaine/evaluation/observers/welfare_observer.py",
    "kaine/cycle/preservation_monitor.py",
    "kaine/cycle/development.py",
)

#: Reads that are not welfare magnitudes, by (file, function):
#: the blind-sensor advisory asks only whether the error is null (the blend
#: never makes a defined error null or a null one defined); the development
#: run's vision stimulus-source error measures how well the entity predicts its
#: stimulus, which is the blend when feedback is on.
NULL_CHECK_ONLY: frozenset[tuple[str, str]] = frozenset(
    {("kaine/evaluation/observers/welfare_observer.py", "_track_blind_sensor")}
)
NOT_WELFARE: frozenset[tuple[str, str]] = frozenset(
    {("kaine/cycle/development.py", "_read_vision_errors")}
)

_KEY = "prediction_error"


def _direct_reads(source: str, filename: str) -> list[str]:
    """Each place ``filename`` uses the ``prediction_error`` key other than as allowed."""
    tree = ast.parse(source, filename=filename)
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def enclosing_function(node: ast.AST) -> str | None:
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node.name
        return None

    def is_null_check(sub: ast.AST) -> bool:
        cmp = parents.get(sub)
        return (
            isinstance(cmp, ast.Compare)
            and cmp.left is sub
            and all(isinstance(op, (ast.Is, ast.IsNot)) for op in cmp.ops)
            and all(isinstance(c, ast.Constant) and c.value is None for c in cmp.comparators)
        )

    offenders: list[str] = []
    for node in ast.walk(tree):
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
        func = enclosing_function(node)
        if (filename, func) in NOT_WELFARE:
            continue
        if (filename, func) in NULL_CHECK_ONLY:
            if isinstance(parent, ast.Subscript) and is_null_check(parent):
                continue
        offenders.append(f"{filename}:{node.lineno} ({func or '<module>'})")
    return offenders


def test_welfare_readers_use_the_function() -> None:
    offenders: list[str] = []
    missing: list[str] = []
    for rel in WELFARE_READER_FILES:
        source = (REPO / rel).read_text(encoding="utf-8")
        offenders.extend(_direct_reads(source, rel))
        if rel in MUST_CALL and "welfare_prediction_error(" not in source:
            missing.append(rel)
    assert not offenders, (
        "welfare readers must read a processor's error through "
        "kaine.lifecycle.welfare_signal.welfare_prediction_error, not the payload:\n"
        + "\n".join(offenders)
    )
    assert not missing, f"welfare readers that never call welfare_prediction_error: {missing}"


@pytest.mark.parametrize(
    "snippet",
    [
        "def handle(payload):\n    m = float(payload['prediction_error'])\n",
        "def handle(payload):\n    m = payload.get('prediction_error', 0.0)\n",
        "KEY = 'prediction_error'\n",
        "def _track_blind_sensor(payload):\n    m = float(payload['prediction_error'])\n",
    ],
)
def test_source_scan_names_a_direct_read(snippet) -> None:
    rel = "kaine/evaluation/observers/welfare_observer.py"
    offenders = _direct_reads(snippet, rel)
    assert offenders and all(o.startswith(rel + ":") for o in offenders)


def test_source_scan_allows_null_checks_and_docstrings() -> None:
    rel = "kaine/evaluation/observers/welfare_observer.py"
    snippet = (
        '"""prediction_error"""\n'
        "def _track_blind_sensor(payload):\n"
        "    if 'prediction_error' not in payload:\n"
        "        return\n"
        "    defined = payload['prediction_error'] is not None\n"
    )
    assert _direct_reads(snippet, rel) == []
