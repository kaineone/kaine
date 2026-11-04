# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The A.4 welfare indicator evaluator (kaine.lifecycle.welfare_indicators).

Spans are the most recent T_lp of awake, unfrozen time after the last restart;
sleep and freezes are skipped and never shorten the span; an indicator is
evaluated once the span holds Delta_stall; crossings are edges and a restart
resets them.
"""
from __future__ import annotations

import subprocess
import sys
from fractions import Fraction

import pytest

from kaine.lifecycle.welfare_indicators import (
    INDICATOR_NAMES,
    STAGE3_REASONS,
    IndicatorEvaluator,
    IndicatorParams,
    indicator_reason,
    power_posterior,
)


def _state(
    *,
    boredom: bool = False,
    social: bool = False,
    restless: bool = False,
    valence: float = 0.0,
    ends: dict | None = None,
) -> dict:
    return {
        "state": {"valence": valence, "arousal": 0.3},
        "drive_above": {
            "curiosity": False,
            "boredom": boredom,
            "social_drive": social,
            "restlessness": restless,
        },
        "drive_ends": ends
        or {
            "boredom": {"own": 0, "other": 0},
            "social_drive": {"own": 0, "other": 0},
            "restlessness": {"own": 0, "other": 0},
        },
    }


def _feed(ev: IndicatorEvaluator, start: float, seconds: int, **kwargs) -> float:
    """One affect.state per second from ``start``; returns the next time."""
    t = start
    for _ in range(seconds):
        ev.observe_state(t, _state(**kwargs))
        t += 1.0
    return t


def test_sleep_and_freezes_are_not_awake_time():
    ev = IndicatorEvaluator(IndicatorParams())
    t = _feed(ev, 0.0, 301, boredom=True)
    ev.exclude_start("sleep", t)
    t = _feed(ev, t, 1410, boredom=False)
    ev.exclude_end("sleep", t)
    t = _feed(ev, t, 100, boredom=True)
    ev.exclude_start("freeze", t)
    t = _feed(ev, t, 120, boredom=False)
    ev.exclude_end("freeze", t)
    _feed(ev, t, 201, boredom=True)
    # Awake: 301 s before the rest (the last second leads into it), 100 s
    # between the rest and the freeze, 200 s after the freeze. An interval
    # that begins inside the rest or the freeze is skipped.
    reading = ev.evaluate()
    assert ev.span_awake_s == pytest.approx(601.0)
    # Neither the rest nor the freeze (boredom below threshold there) counts.
    assert reading.reading("boredom_deprived").value == pytest.approx(1.0, abs=0.01)


def test_a_rest_does_not_shorten_the_span():
    ev = IndicatorEvaluator(IndicatorParams())
    # 7000 entity seconds since the restart: 5600 awake, 1400 in a rest.
    t = _feed(ev, 0.0, 2800)
    ev.exclude_start("sleep", t)
    t = _feed(ev, t, 1400)
    ev.exclude_end("sleep", t)
    _feed(ev, t, 2801)
    assert ev.span_awake_s == pytest.approx(5400.0)


def test_a_short_span_is_not_evaluated():
    ev = IndicatorEvaluator(IndicatorParams())
    _feed(ev, 0.0, 301, boredom=True)
    reading = ev.evaluate()
    assert ev.span_awake_s == pytest.approx(300.0)
    assert not reading.evaluable
    assert reading.crossed == ()
    assert not any(r.over for r in reading.readings)


def test_a_deprived_deficit():
    ev = IndicatorEvaluator(IndicatorParams())
    t = _feed(ev, 0.0, 200, boredom=False)
    _feed(ev, t, 401, boredom=True)
    reading = ev.evaluate()
    assert ev.span_awake_s == pytest.approx(600.0)
    assert reading.reading("boredom_deprived").value == pytest.approx(400 / 600, abs=1e-9)
    assert reading.reading("boredom_deprived").over
    assert reading.crossed == ("boredom_deprived",)


def test_negative_valence_share_uses_the_regulation_set_point():
    ev = IndicatorEvaluator(IndicatorParams(valence_bar=0.5))
    t = _feed(ev, 0.0, 300, valence=-0.49)
    _feed(ev, t, 301, valence=-0.51)
    reading = ev.evaluate()
    assert reading.reading("negative_valence").value == pytest.approx(0.5)
    assert reading.reading("negative_valence").over


def _ends(own: int, other: int) -> dict:
    return {
        "boredom": {"own": own, "other": other},
        "social_drive": {"own": 0, "other": 9},
        "restlessness": {"own": 0, "other": 0},
    }


@pytest.mark.parametrize(("other", "expected", "over"), [(4, Fraction(31, 32), True), (3, Fraction(15, 16), False)])
def test_uncontrolled_boredom_from_other_ended_crossings(other, expected, over):
    ev = IndicatorEvaluator(IndicatorParams())
    t = 0.0
    ev.observe_state(t, _state(ends=_ends(0, 0)))
    for k in range(1, 601):
        t += 1.0
        ev.observe_state(t, _state(ends=_ends(0, min(other, k // 100))))
    reading = ev.evaluate()
    value = reading.reading("boredom_uncontrolled").value
    assert value == pytest.approx(float(expected))
    assert reading.reading("boredom_uncontrolled").over is over
    # The social drive has no uncontrolled indicator, however many other ends.
    assert "social_drive_uncontrolled" not in INDICATOR_NAMES


@pytest.mark.parametrize(
    ("own", "other", "value"),
    [
        (0, 0, Fraction(1, 2)),
        (0, 1, Fraction(3, 4)),
        (0, 2, Fraction(7, 8)),
        (0, 3, Fraction(15, 16)),
        (0, 4, Fraction(31, 32)),
        (0, 5, Fraction(63, 64)),
        (1, 0, Fraction(1, 4)),
        (1, 1, Fraction(1, 2)),
        # n = 6: C(6,3)+C(6,4)+C(6,5)+C(6,6) = 20+15+6+1 = 42.
        (2, 3, Fraction(42, 64)),
        # n = 6: 15+20+15+6+1 = 57.
        (1, 4, Fraction(57, 64)),
    ],
)
def test_the_posterior_against_hand_values(own, other, value):
    # n = s + f + 1 from 1 to 6: 2^-n * sum_{i=s+1}^{n} C(n, i), which is
    # P(Bin(n, 1/2) >= s + 1), the Beta(s+1, f+1) mass below one half.
    assert power_posterior(own, other) == value


def test_an_indicator_that_never_fell_below_its_bar_crosses_on_the_fresh_span():
    ev = IndicatorEvaluator(IndicatorParams())
    t = _feed(ev, 0.0, 601, boredom=True)
    assert ev.evaluate().crossed == ("boredom_deprived",)
    t = _feed(ev, t, 100, boredom=True)
    assert ev.evaluate().crossed == ()  # still over: no new edge
    # The rest (skipped) ends; the span restarts and the crossing state resets.
    ev.exclude_start("sleep", t)
    t = _feed(ev, t, 1410, boredom=False)
    ev.exclude_end("sleep", t)
    ev.restart()
    t = _feed(ev, t, 300, boredom=True)
    assert ev.evaluate().crossed == ()  # below the minimum span
    _feed(ev, t, 301, boredom=True)
    assert ev.evaluate().crossed == ("boredom_deprived",)


def test_an_indicator_re_arms_below_its_bar():
    ev = IndicatorEvaluator(IndicatorParams())
    t = _feed(ev, 0.0, 601, boredom=True)
    assert ev.evaluate().crossed == ("boredom_deprived",)
    t = _feed(ev, t, 700, boredom=False)
    assert not ev.evaluate().reading("boredom_deprived").over
    _feed(ev, t, 1000, boredom=True)
    assert ev.evaluate().crossed == ("boredom_deprived",)


def test_the_span_is_the_latest_t_lp_after_the_restart():
    ev = IndicatorEvaluator(IndicatorParams())
    t = _feed(ev, 0.0, 3000, boredom=True)
    _feed(ev, t, 5401, boredom=False)
    reading = ev.evaluate()
    assert ev.span_awake_s == pytest.approx(5400.0)
    assert reading.reading("boredom_deprived").value == pytest.approx(0.0)


def test_silence_marks_the_indicators_unavailable_and_sleep_does_not_count():
    params = IndicatorParams(publish_interval_s=1.0)
    ev = IndicatorEvaluator(params)
    t = _feed(ev, 0.0, 10)  # the last sample is at t - 1
    ev.advance(t + 1.0)
    assert ev.available  # 2 s of silence
    ev.advance(t + 2.5)
    assert not ev.available  # 3.5 s: three periods
    ev.observe_state(t + 3.0, _state())
    assert ev.available
    ev.exclude_start("sleep", t + 3.0)
    ev.advance(t + 100.0)
    assert ev.available  # asleep: no awake silence
    ev.exclude_end("sleep", t + 100.0)
    ev.advance(t + 104.0)
    assert not ev.available


def test_a_sample_behind_the_current_one_does_not_end_the_silence():
    """A clock that ran back: its samples are rejected and no sign of life."""
    params = IndicatorParams(publish_interval_s=1.0)
    ev = IndicatorEvaluator(params)
    t = _feed(ev, 1000.0, 10)  # the last sample is at t - 1
    ev.advance(t + 5.0)
    assert not ev.available
    silent = ev.silent_awake_s
    span = ev.span_awake_s
    for k in range(50):
        ev.observe_state(500.0 + k, _state())
    assert ev.silent_awake_s == silent
    assert not ev.available
    assert ev.span_awake_s == span
    # A sample on the current clock is accepted and ends the silence.
    ev.observe_state(t + 6.0, _state())
    assert ev.available


def test_peek_does_not_consume_a_crossing():
    ev = IndicatorEvaluator(IndicatorParams())
    _feed(ev, 0.0, 601, boredom=True)
    assert ev.peek().reading("boredom_deprived").over
    assert ev.evaluate().crossed == ("boredom_deprived",)


def test_the_fixed_tables():
    assert INDICATOR_NAMES == (
        "boredom_deprived",
        "social_drive_deprived",
        "restlessness_deprived",
        "negative_valence",
        "boredom_uncontrolled",
        "restlessness_uncontrolled",
    )
    assert indicator_reason("boredom_deprived") == "indicator_boredom_deprived"
    assert "indicator_rest_failed" in STAGE3_REASONS
    assert "indicators_unavailable" in STAGE3_REASONS
    with pytest.raises(ValueError):
        indicator_reason("something the entity said")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"span_s": 0.0},
        {"min_span_s": 6000.0},
        {"share_bar": 0.0},
        {"posterior_bar": 1.5},
        {"publish_interval_s": float("nan")},
    ],
)
def test_invalid_parameters_are_refused(kwargs):
    with pytest.raises(ValueError):
        IndicatorParams(**kwargs)


def test_the_evaluator_never_loads_kaine_evaluation():
    code = (
        "import sys\n"
        "import kaine.lifecycle.welfare_indicators\n"
        "bad = sorted(m for m in sys.modules if m.startswith('kaine.evaluation')"
        " or m.startswith('kaine.cycle') or m.startswith('kaine.modules'))\n"
        "print(bad)\n"
        "raise SystemExit(1 if bad else 0)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


# --- Equality with the welfare observer's cumulative tally (task 1.2) ----------


def _run_both(seconds: int, with_sleep: bool):
    from kaine.evaluation.observers.welfare_observer import AffectWelfareTally

    tally = AffectWelfareTally(negative_valence_bar=0.5, max_gap_s=5.0)
    ev = IndicatorEvaluator(IndicatorParams(valence_bar=0.5, max_gap_s=5.0))
    for t in range(seconds):
        if with_sleep and t in (1200, 2400):
            tally.sleep_started(float(t))
            ev.exclude_start("sleep", float(t))
        if with_sleep and t in (1500, 2700):
            tally.sleep_completed(float(t))
            ev.exclude_end("sleep", float(t))
        payload = _state(
            boredom=(t % 7) < 4,
            social=(t % 11) < 3,
            restless=(t % 5) == 0,
            valence=-0.6 if (t % 13) < 5 else 0.1,
        )
        # A stall now and then: gaps are capped alike.
        if t % 997 == 0 and t:
            continue
        tally.observe_state(
            float(t),
            payload["state"]["valence"],
            drive_above=payload["drive_above"],
            drive_ends=payload["drive_ends"],
        )
        ev.observe_state(float(t), payload)
    return tally.snapshot(), ev.evaluate()


@pytest.mark.parametrize("with_sleep", [False, True])
def test_shares_equal_the_tally_over_a_run_shorter_than_t_lp(with_sleep):
    snap, reading = _run_both(5000, with_sleep)
    for drive in ("boredom", "social_drive", "restlessness"):
        assert reading.reading(f"{drive}_deprived").value == pytest.approx(
            snap[f"{drive}_deprivation_share"]
        )
    assert reading.reading("negative_valence").value == pytest.approx(
        snap["negative_valence_share"]
    )
    assert reading.span_awake_s == pytest.approx(snap["awake_seconds"])


def test_uncontrolled_indicator_does_not_bleed_across_restart():
    """Drive endings during a rest must not contaminate the fresh span.

    Before the fix, restart() did not reset _last_ends, so the first
    post-restart observation computed a delta from the pre-restart baseline
    and attributed rest-period endings to the fresh span.
    """
    ev = IndicatorEvaluator(IndicatorParams())
    # Feed 601 s with 2 other-ended boredom crossings (cumulative 0 → 2).
    t = 0.0
    ev.observe_state(t, _state(ends=_ends(0, 0)))
    for k in range(1, 601):
        t += 1.0
        ev.observe_state(t, _state(ends=_ends(0, min(2, k // 200))))
    ev.evaluate()

    ev.restart()

    # Simulate 3 other-ended crossings happening during the rest (the
    # cumulative counter jumped from 2 to 5 while the evaluator was not
    # observing). Then feed 601 s where only 1 more ending happens
    # (cumulative 5 → 6). A correct fresh span counts only that 1 ending.
    for k in range(601):
        t += 1.0
        other = 5 + (1 if k >= 300 else 0)
        ev.observe_state(t, _state(ends=_ends(0, other)))
    after = ev.evaluate()

    # A fresh evaluator fed the same 1 ending over 601 s.
    fresh = IndicatorEvaluator(IndicatorParams())
    t2 = 0.0
    fresh.observe_state(t2, _state(ends=_ends(0, 0)))
    for k in range(1, 601):
        t2 += 1.0
        other = 0 + (1 if k >= 300 else 0)
        fresh.observe_state(t2, _state(ends=_ends(0, other)))
    expected = fresh.evaluate()

    assert after.reading("boredom_uncontrolled").value == expected.reading("boredom_uncontrolled").value
    # With only 1 other-ended crossing: posterior = P(p < 1/2 | s=0, f=1)
    # = 3/4 which is below the 0.95 bar.
    assert not after.reading("boredom_uncontrolled").over
