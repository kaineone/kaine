# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The welfare log's affect_welfare record: negative-valence share, crossing ends by the credit rule and deprivation shares (paper 6.2)."""

from datetime import datetime, timedelta, timezone

import pytest

from kaine.bus.schema import Event
from kaine.cycle import control_state
from kaine.cycle.unfrozen_clock import UnfrozenClock
from kaine.evaluation.config import WelfareConfig
from kaine.evaluation.observers.welfare_observer import (
    AffectWelfareTally,
    WelfareObserver,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
_DRIVES = ("curiosity", "boredom", "social_drive", "restlessness")


@pytest.fixture(autouse=True)
def _control_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(control_state, "CONTROL_PATH", tmp_path / "control.json")


class _Mono:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class FakeBus:
    def __init__(self) -> None:
        self.published: list[Event] = []

    async def read_entries(self, stream, *, last_id, count, block_ms):
        return [], None

    async def latest(self, stream: str):
        return None

    async def publish(self, event: Event) -> None:
        self.published.append(event)


class FakeSink:
    def __init__(self):
        self.rows: list[dict] = []

    async def write(self, row: dict) -> None:
        self.rows.append(row)


def _event(source: str, type_: str, payload: dict, at_s: float) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=0.5,
        timestamp=T0 + timedelta(seconds=at_s),
    )


def _observer(u: _Mono, **kw):
    bus, sink = FakeBus(), FakeSink()
    obs = WelfareObserver(
        bus,
        sink,
        unfrozen_clock=UnfrozenClock(
            control_state.read_frozen_state, unknown_counts_as="unfrozen", monotonic=u
        ),
        **kw,
    )
    return obs, bus, sink


def _ends(**counts):
    return {
        drive: {
            "own": counts.get(drive, (0, 0))[0],
            "other": counts.get(drive, (0, 0))[1],
        }
        for drive in _DRIVES
    }


def _above(**flags):
    return {drive: flags.get(drive, False) for drive in _DRIVES}


def test_tally_synthetic_run():
    tally = AffectWelfareTally(negative_valence_bar=0.5, max_gap_s=5.0)
    tally.sleep_started(100.0)
    tally.sleep_completed(150.0)
    for t in range(151):
        if 10 <= t <= 34 or t >= 100:
            v = -0.6
        else:
            v = 0.1
        tally.observe_state(float(t), v)
    snap = tally.snapshot()
    assert snap["awake_seconds"] == pytest.approx(100.0)
    assert snap["negative_valence_share"] == pytest.approx(0.25)
    assert snap["negative_valence_bar"] == pytest.approx(0.5)


def test_tally_bar_strict_and_configurable():
    tally1 = AffectWelfareTally(negative_valence_bar=0.5, max_gap_s=5.0)
    tally1.observe_state(0.0, -0.5)
    tally1.observe_state(1.0, -0.5)
    assert tally1.snapshot()["negative_valence_share"] == pytest.approx(0.0)

    tally2 = AffectWelfareTally(negative_valence_bar=0.2, max_gap_s=5.0)
    tally2.observe_state(0.0, -0.3)
    tally2.observe_state(1.0, 0.0)
    tally2.observe_state(2.0, 0.0)
    assert tally2.snapshot()["negative_valence_share"] == pytest.approx(0.5)


def test_tally_gap_cap():
    tally = AffectWelfareTally(negative_valence_bar=0.5, max_gap_s=5.0)
    tally.observe_state(0.0, 0.0)
    tally.observe_state(100.0, 0.0)
    assert tally.snapshot()["awake_seconds"] == pytest.approx(5.0)


def test_tally_ignores_out_of_order_and_non_finite():
    tally = AffectWelfareTally(negative_valence_bar=0.5, max_gap_s=5.0)
    tally.observe_state(0.0, -0.6)
    tally.observe_state(1.0, -0.6)
    tally.observe_state(0.5, -0.6)  # older, ignored
    tally.observe_state(2.0, float("nan"))  # non-finite, ignored
    snap = tally.snapshot()
    assert snap["awake_seconds"] == pytest.approx(1.0)
    assert snap["negative_valence_share"] == pytest.approx(1.0)


def test_tally_crossing_ends_from_counts():
    tally = AffectWelfareTally(negative_valence_bar=0.5, max_gap_s=5.0)
    for t in range(101):
        ends = (
            _ends(boredom=(5, 7))
            if t < 50
            else _ends(boredom=(6, 10))
        )
        tally.observe_state(float(t), 0.0, drive_ends=ends)
    snap = tally.snapshot()
    assert snap["boredom_uncontrolled_share"] == pytest.approx(0.75)
    assert snap["boredom_uncontrolled_per_awake_hour"] == pytest.approx(108.0)
    assert snap["curiosity_uncontrolled_share"] is None


def test_tally_first_sample_is_baseline():
    tally = AffectWelfareTally(negative_valence_bar=0.5, max_gap_s=5.0)
    tally.observe_state(0.0, 0.0, drive_ends=_ends(curiosity=(4, 2)))
    snap = tally.snapshot()
    for drive in _DRIVES:
        assert snap[f"{drive}_uncontrolled_share"] is None
    assert tally.changed is False


def test_tally_count_fall_rebaselines():
    tally = AffectWelfareTally(negative_valence_bar=0.5, max_gap_s=5.0)
    tally.observe_state(0.0, 0.0, drive_ends=_ends(curiosity=(3, 3)))
    tally.observe_state(1.0, 0.0, drive_ends=_ends(curiosity=(0, 0)))
    tally.observe_state(2.0, 0.0, drive_ends=_ends(curiosity=(1, 0)))
    snap = tally.snapshot()
    assert snap["curiosity_uncontrolled_share"] == pytest.approx(0.0)
    assert snap["curiosity_uncontrolled_per_awake_hour"] == pytest.approx(0.0)


def test_tally_partial_count_fall_rebaselines():
    # A restored entity whose counts are lower than the last ones read: the
    # counts at the fall are a new baseline, and only later increases count.
    tally = AffectWelfareTally(negative_valence_bar=0.5, max_gap_s=5.0)
    tally.observe_state(0.0, 0.0, drive_ends=_ends(curiosity=(5, 5)))
    tally.observe_state(1.0, 0.0, drive_ends=_ends(curiosity=(2, 6)))
    tally.observe_state(2.0, 0.0, drive_ends=_ends(curiosity=(3, 6)))
    snap = tally.snapshot()
    assert snap["curiosity_uncontrolled_share"] == pytest.approx(0.0)
    assert snap["curiosity_uncontrolled_per_awake_hour"] == pytest.approx(0.0)


def test_tally_invalid_ends_ignored():
    tally = AffectWelfareTally(negative_valence_bar=0.5, max_gap_s=5.0)
    tally.observe_state(0.0, 0.0, drive_ends=_ends(curiosity=(1, 1)))
    bad_bool = {"curiosity": {"own": True, "other": 1}}
    bad_neg = {"curiosity": {"own": -1, "other": 0}}
    bad_float = {"curiosity": {"own": 1.0, "other": 0}}
    bad_missing = {"curiosity": {"own": 1}}
    bad_non_dict = {"curiosity": "x"}
    bad_drive_ends = "not a dict"
    bad_unknown = {"secret thoughts": {"own": 9, "other": 9}}
    for inv in [
        bad_bool,
        bad_neg,
        bad_float,
        bad_missing,
        bad_non_dict,
        bad_drive_ends,
        bad_unknown,
    ]:
        tally.observe_state(1.0, 0.0, drive_ends=inv)
    snap = tally.snapshot()
    for drive in _DRIVES:
        assert snap[f"{drive}_uncontrolled_share"] is None
    assert "secret_thoughts_uncontrolled_share" not in snap
    assert "secret" not in str(snap).lower()


def test_tally_deprivation_share():
    tally = AffectWelfareTally(negative_valence_bar=0.5, max_gap_s=5.0)
    for t in range(101):
        above = _above(curiosity=(t < 60))
        tally.observe_state(float(t), 0.0, drive_above=above)
    snap = tally.snapshot()
    assert snap["curiosity_deprivation_share"] == pytest.approx(0.6)
    assert snap["boredom_deprivation_share"] == pytest.approx(0.0)


def test_tally_deprivation_excludes_sleep_and_missing_flags():
    # A: sleep removes 10 s of above curiosity time.
    tally = AffectWelfareTally(negative_valence_bar=0.5, max_gap_s=5.0)
    tally.sleep_started(20.0)
    tally.sleep_completed(30.0)
    for t in range(101):
        tally.observe_state(float(t), 0.0, drive_above=_above(curiosity=True))
    snap = tally.snapshot()
    assert snap["awake_seconds"] == pytest.approx(90.0)
    assert snap["curiosity_deprivation_share"] == pytest.approx(1.0)

    # B: no drive_above for the first 50 s means those intervals count in neither part.
    tally2 = AffectWelfareTally(negative_valence_bar=0.5, max_gap_s=5.0)
    for t in range(101):
        above = None if t < 50 else _above(curiosity=True)
        tally2.observe_state(float(t), 0.0, drive_above=above)
    snap2 = tally2.snapshot()
    assert snap2["awake_seconds"] == pytest.approx(100.0)
    assert snap2["curiosity_deprivation_share"] == pytest.approx(1.0)

    # C: an int 1 value for a drive flag is treated as missing.
    tally3 = AffectWelfareTally(negative_valence_bar=0.5, max_gap_s=5.0)
    tally3.observe_state(0.0, 0.0, drive_above=_above(curiosity=True))
    tally3.observe_state(1.0, 0.0, drive_above={"curiosity": 1})
    tally3.observe_state(2.0, 0.0, drive_above=_above(curiosity=False))
    snap3 = tally3.snapshot()
    assert snap3["curiosity_deprivation_share"] == pytest.approx(1.0)


def _run_drive_history(history: str, with_sleep: bool):
    tally = AffectWelfareTally(negative_valence_bar=0.5, max_gap_s=5.0)
    if with_sleep:
        for k in range(1, 8):
            tally.sleep_started(k * 1500.0)
            tally.sleep_completed(k * 1500.0 + 10.0)
    own = 0
    learning_ends = {1500, 4000, 6500, 9000, 10800}
    for t in range(10801):
        if history == "frozen":
            above_flag = True
        else:
            period_pos = t % 2500
            above_flag = period_pos < 1500
            if with_sleep:
                for k in range(1, 8):
                    start = k * 1500 + 10
                    end = k * 1500 + 37
                    if start <= t < end:
                        above_flag = False
                        break
            if history == "learning" and t in learning_ends:
                own += 1
        ends = _ends(curiosity=(own, 0)) if history == "learning" else _ends()
        tally.observe_state(
            float(t),
            0.0,
            drive_above=_above(curiosity=above_flag),
            drive_ends=ends,
        )
    return tally.snapshot()


def test_frozen_control_ranks_worst_at_any_sleep_cadence():
    frozen_no = _run_drive_history("frozen", False)
    frozen_sleep = _run_drive_history("frozen", True)
    learning_no = _run_drive_history("learning", False)
    learning_sleep = _run_drive_history("learning", True)

    assert frozen_no["curiosity_deprivation_share"] > learning_no["curiosity_deprivation_share"]
    assert frozen_sleep["curiosity_deprivation_share"] > learning_sleep["curiosity_deprivation_share"]
    assert abs(frozen_no["curiosity_deprivation_share"] - frozen_sleep["curiosity_deprivation_share"]) < 0.05
    assert abs(learning_no["curiosity_deprivation_share"] - learning_sleep["curiosity_deprivation_share"]) < 0.05

    assert frozen_no["curiosity_uncontrolled_share"] is None
    assert frozen_sleep["curiosity_uncontrolled_share"] is None
    assert learning_no["curiosity_uncontrolled_share"] == pytest.approx(0.0)
    assert learning_sleep["curiosity_uncontrolled_share"] == pytest.approx(0.0)


def test_tally_initially_empty():
    tally = AffectWelfareTally(negative_valence_bar=0.5, max_gap_s=5.0)
    snap = tally.snapshot()
    assert snap["awake_seconds"] == pytest.approx(0.0)
    assert snap["negative_valence_share"] is None
    for drive in _DRIVES:
        assert snap[f"{drive}_uncontrolled_share"] is None
        assert snap[f"{drive}_uncontrolled_per_awake_hour"] is None
        assert snap[f"{drive}_deprivation_share"] is None


def test_tally_content_free_and_fixed_keys():
    tally = AffectWelfareTally(negative_valence_bar=0.5, max_gap_s=5.0)
    tally.observe_state(
        0.0,
        0.0,
        drive_above={"secret thoughts": True, "curiosity": True, "text": "private"},
        drive_ends={
            "secret thoughts": {"own": 9, "other": 9},
            "text": "private",
        },
    )
    tally.observe_state(1.0, 0.0, drive_above=_above(), drive_ends=_ends())
    snap = tally.snapshot()
    fixed = {"awake_seconds", "negative_valence_bar", "negative_valence_share"}
    for drive in _DRIVES:
        fixed.add(f"{drive}_uncontrolled_share")
        fixed.add(f"{drive}_uncontrolled_per_awake_hour")
        fixed.add(f"{drive}_deprivation_share")
    assert set(snap.keys()) == fixed
    for k, v in snap.items():
        assert not isinstance(v, bool)
        assert isinstance(v, (int, float)) or v is None
    serialized = str(snap).lower()
    assert "secret" not in serialized
    assert "private" not in serialized


@pytest.mark.asyncio
async def test_observer_stalled_goal_leaves_crossing_open():
    u = _Mono(0.0)
    obs, bus, sink = _observer(u, affect_summary_interval_s=300.0)
    await obs._tick()  # starts the summary interval at u = 0

    for t in range(101):
        await obs.handle(
            "affect.out",
            "1-0",
            _event(
                "affect",
                "affect.state",
                {
                    "state": {"valence": 0.0, "arousal": 0.3, "dominance": 0.0},
                    "drive_above": _above(curiosity=True),
                    "drive_ends": _ends(),
                },
                float(t),
            ),
        )

    await obs.handle(
        "affect.out",
        "1-0",
        _event(
            "affect",
            "affect.goal",
            {"action": "abandoned", "drive": "curiosity", "reason": "stalled"},
            100.0,
        ),
    )

    for t in range(101, 201):
        await obs.handle(
            "affect.out",
            "1-0",
            _event(
                "affect",
                "affect.state",
                {
                    "state": {"valence": 0.0, "arousal": 0.3, "dominance": 0.0},
                    "drive_above": _above(curiosity=False),
                    "drive_ends": _ends(curiosity=(1, 0)),
                },
                float(t),
            ),
        )

    u.value = 300.0
    await obs._tick()
    affect_rows = [r for r in sink.rows if r.get("record") == "affect_welfare"]
    assert len(affect_rows) == 1
    row = affect_rows[0]
    assert row["curiosity_uncontrolled_share"] == pytest.approx(0.0)
    assert row["curiosity_uncontrolled_per_awake_hour"] == pytest.approx(0.0)
    assert row["curiosity_deprivation_share"] == pytest.approx(0.5, abs=0.01)
    assert len(bus.published) == 0


@pytest.mark.asyncio
async def test_observer_end_to_end():
    u = _Mono(0.0)
    obs, bus, sink = _observer(u, affect_summary_interval_s=300.0)
    await obs._tick()  # starts the summary interval at u = 0

    await obs.handle(
        "sleep.out",
        "1-0",
        _event("sleep", "sleep.sleep.started", {}, 20.0),
    )
    await obs.handle(
        "sleep.out",
        "1-0",
        _event("sleep", "sleep.sleep.completed", {}, 30.0),
    )

    for t in range(101):
        v = -0.6 if t < 50 else 0.0
        ends = _ends() if t < 60 else _ends(boredom=(0, 1))
        await obs.handle(
            "affect.out",
            "1-0",
            _event(
                "affect",
                "affect.state",
                {
                    "state": {"valence": v, "arousal": 0.3, "dominance": 0.0},
                    "drive_ends": ends,
                },
                float(t),
            ),
        )

    u.value = 299.0
    await obs._tick()
    assert len([r for r in sink.rows if r.get("record") == "affect_welfare"]) == 0

    u.value = 300.0
    await obs._tick()
    affect_rows = [r for r in sink.rows if r.get("record") == "affect_welfare"]
    assert len(affect_rows) == 1
    row = affect_rows[0]
    assert row["awake_seconds"] == pytest.approx(90.0)
    assert row["negative_valence_share"] == pytest.approx(40.0 / 90.0)
    assert row["boredom_uncontrolled_share"] == pytest.approx(1.0)
    assert len(bus.published) == 0

    u.value = 600.0
    await obs._tick()
    assert len([r for r in sink.rows if r.get("record") == "affect_welfare"]) == 1

    await obs.handle(
        "affect.out",
        "1-0",
        _event(
            "affect",
            "affect.state",
            {
                "state": {"valence": 0.0, "arousal": 0.3, "dominance": 0.0},
                "drive_ends": _ends(boredom=(0, 1)),
            },
            101.0,
        ),
    )
    await obs._cleanup()
    assert len([r for r in sink.rows if r.get("record") == "affect_welfare"]) == 2


@pytest.mark.asyncio
async def test_cleanup_writes_nothing_when_unchanged():
    u = _Mono(0.0)
    obs, _bus, sink = _observer(u, affect_summary_interval_s=300.0)
    await obs._tick()

    await obs.handle(
        "affect.out",
        "1-0",
        _event(
            "affect",
            "affect.state",
            {"state": {"valence": 0.0, "arousal": 0.3, "dominance": 0.0}},
            0.0,
        ),
    )
    await obs.handle(
        "affect.out",
        "1-0",
        _event(
            "affect",
            "affect.state",
            {"state": {"valence": 0.0, "arousal": 0.3, "dominance": 0.0}},
            1.0,
        ),
    )

    u.value = 300.0
    await obs._tick()
    assert len([r for r in sink.rows if r.get("record") == "affect_welfare"]) == 1

    u.value = 600.0
    await obs._tick()
    await obs._cleanup()
    assert len([r for r in sink.rows if r.get("record") == "affect_welfare"]) == 1


@pytest.mark.asyncio
async def test_observer_row_types():
    u = _Mono(0.0)
    obs, _bus, sink = _observer(u, affect_summary_interval_s=300.0)
    await obs._tick()  # starts the summary interval at u = 0
    await obs.handle(
        "affect.out",
        "1-0",
        _event(
            "affect",
            "affect.state",
            {"state": {"valence": -0.6, "arousal": 0.3, "dominance": 0.0}},
            0.0,
        ),
    )
    await obs.handle(
        "affect.out",
        "1-0",
        _event(
            "affect",
            "affect.state",
            {"state": {"valence": 0.0, "arousal": 0.3, "dominance": 0.0}},
            1.0,
        ),
    )
    u.value = 300.0
    await obs._tick()
    row = [r for r in sink.rows if r.get("record") == "affect_welfare"][0]
    assert row["record"] == "affect_welfare"
    assert isinstance(row["ts"], str)
    for k, v in row.items():
        if k in ("ts", "record"):
            assert isinstance(v, str)
        else:
            assert isinstance(v, (int, float)) or v is None
    assert not any(isinstance(v, bool) for v in row.values())


class _FailingSink:
    def __init__(self) -> None:
        self.calls = 0

    async def write(self, row: dict) -> None:
        self.calls += 1
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_failing_sink_does_not_break_tick():
    u = _Mono(0.0)
    bus = FakeBus()
    sink = _FailingSink()
    obs = WelfareObserver(
        bus,
        sink,
        unfrozen_clock=UnfrozenClock(
            control_state.read_frozen_state, unknown_counts_as="unfrozen", monotonic=u
        ),
        affect_summary_interval_s=300.0,
    )
    await obs._tick()  # starts the summary interval at u = 0
    await obs.handle(
        "affect.out",
        "1-0",
        _event(
            "affect",
            "affect.state",
            {"state": {"valence": -0.6, "arousal": 0.3, "dominance": 0.0}},
            0.0,
        ),
    )
    await obs.handle(
        "affect.out",
        "1-0",
        _event(
            "affect",
            "affect.state",
            {"state": {"valence": 0.0, "arousal": 0.3, "dominance": 0.0}},
            1.0,
        ),
    )
    u.value = 300.0
    await obs._tick()
    assert sink.calls == 1


def test_welfare_config_affect_fields():
    cfg = WelfareConfig()
    assert cfg.negative_valence_bar == pytest.approx(0.5)
    assert cfg.affect_summary_interval_s == pytest.approx(300.0)

    cfg2 = WelfareConfig.from_mapping(
        {"negative_valence_bar": 0.3, "affect_summary_interval_s": 60}
    )
    assert cfg2.negative_valence_bar == pytest.approx(0.3)
    assert cfg2.affect_summary_interval_s == pytest.approx(60.0)

    with pytest.raises(ValueError):
        WelfareConfig(negative_valence_bar=-0.1)
    with pytest.raises(ValueError):
        WelfareConfig(negative_valence_bar=1.5)
    with pytest.raises(ValueError):
        WelfareConfig(negative_valence_bar=float("nan"))
    with pytest.raises(ValueError):
        WelfareConfig(affect_summary_interval_s=0.0)
    with pytest.raises(ValueError):
        WelfareConfig(affect_summary_interval_s=float("inf"))
