# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the persisted hearing stage owner."""
from __future__ import annotations

import json
import math

import pytest

from kaine.modules.audition.hearing_band import HearingBandParams
from kaine.modules.audition.hearing_stage_state import HearingStageState

PARAMS = HearingBandParams()
D_MIN = PARAMS.min_dwell_seconds
D_MAX = PARAMS.max_dwell_seconds
W = PARAMS.saturation_window_seconds
LOW = 0.05


def _run(state, start, seconds, lp, step=1.0):
    """Observe once per ``step`` awake seconds; return (end_time, last advance result)."""
    t = start
    result = None
    n = int(seconds / step)
    for _ in range(n):
        t += step
        got = state.observe(t, lp)
        if got is not None:
            result = got
    return t, result


def _anchored(state=None):
    state = state or HearingStageState(PARAMS)
    assert state.observe(0.0, None) is None
    return state


def test_first_observe_anchors_without_adding():
    state = HearingStageState(PARAMS)
    assert state.observe(1000.0, LOW) is None
    assert state.dwell_seconds == 0.0
    assert state.saturated_seconds == 0.0
    state.observe(1010.0, LOW)
    assert state.dwell_seconds == 10.0


def test_saturation_advance_after_dmin_with_window():
    state = _anchored()
    t, _ = _run(state, 0.0, D_MIN - 1, LOW, step=1.0)
    assert state.stage == 0
    assert state.saturated_seconds == D_MIN - 1
    assert state.observe(t + 1.0, LOW) == 1
    assert state.stage == 1
    assert state.dwell_seconds == 0.0
    assert state.saturated_seconds == 0.0


def test_no_advance_just_below_dmin_when_saturated():
    state = _anchored()
    t, result = _run(state, 0.0, D_MIN - 1, LOW)
    assert result is None
    assert state.stage == 0


def test_no_advance_with_599_saturated_seconds_after_dmin():
    state = _anchored()
    t, _ = _run(state, 0.0, D_MIN - 300, None)  # unsaturated, dwell builds
    t, result = _run(state, t, 599, LOW)
    assert result is None
    assert state.stage == 0
    assert state.dwell_seconds > D_MIN
    assert state.saturated_seconds == 599.0
    assert state.observe(t + 1.0, LOW) == 1


def test_dmax_cap_advances_without_saturation():
    state = _anchored()
    t, result = _run(state, 0.0, D_MAX - 10, 0.9, step=10.0)
    assert result is None
    assert state.stage == 0
    assert state.observe(t + 10.0, 0.9) == 1


def test_missing_lp_never_saturates():
    state = _anchored()
    t, result = _run(state, 0.0, D_MAX - 10, None, step=10.0)
    assert result is None
    assert state.stage == 0
    assert state.saturated_seconds == 0.0
    assert state.observe(t + 10.0, None) == 1


def test_non_finite_lp_counts_as_missing():
    state = _anchored()
    for bad in (float("nan"), float("inf"), float("-inf")):
        state.observe(state.dwell_seconds + 1.0, bad)
        assert state.saturated_seconds == 0.0


def test_lp_at_floor_resets_window():
    state = _anchored()
    t, _ = _run(state, 0.0, D_MIN, 0.9)
    t, _ = _run(state, t, 500, LOW)
    assert state.saturated_seconds == 500.0
    t += 1.0
    assert state.observe(t, 0.20) is None
    assert state.saturated_seconds == 0.0
    t, result = _run(state, t, 500, LOW)
    assert result is None
    assert state.stage == 0


def test_lp_exactly_equal_to_floor_is_not_saturated():
    state = _anchored()
    _run(state, 0.0, D_MIN + 2 * W, 0.20)
    assert state.stage == 0
    assert state.saturated_seconds == 0.0


def test_custom_lp_floor():
    state = HearingStageState(PARAMS, lp_floor=0.5)
    _anchored(state)
    _run(state, 0.0, 10, 0.4)
    assert state.saturated_seconds == 10.0
    with pytest.raises(ValueError):
        HearingStageState(PARAMS, lp_floor=1.0)
    with pytest.raises(ValueError):
        HearingStageState(PARAMS, lp_floor=float("nan"))
    with pytest.raises(ValueError):
        HearingStageState(PARAMS, lp_floor=-0.1)


def test_one_advance_per_call_and_final_stage_is_terminal():
    state = _anchored()
    t = 0.0
    for expected in (1, 2, 3, 4):
        t += 10 * D_MAX
        assert state.observe(t, LOW) == expected
        assert state.stage == expected
    assert state.complete is True
    t += 10 * D_MAX
    assert state.observe(t, LOW) is None
    assert state.stage == 4
    assert state.dwell_seconds == 0.0
    assert state.saturated_seconds == 0.0


def test_complete_false_before_final_stage():
    assert HearingStageState(PARAMS).complete is False


def test_rests_add_no_dwell_and_backwards_awake_adds_nothing():
    state = _anchored()
    for _ in range(100):
        state.observe(50.0, LOW)
    assert state.dwell_seconds == 50.0
    state.observe(40.0, LOW)
    assert state.dwell_seconds == 50.0
    # The backwards reading re-anchors, so only the rise from 40 to 60 counts.
    state.observe(60.0, LOW)
    assert state.dwell_seconds == 70.0


def test_non_finite_awake_adds_nothing():
    state = _anchored()
    state.observe(10.0, LOW)
    state.observe(float("nan"), LOW)
    state.observe(float("inf"), LOW)
    assert state.dwell_seconds == 10.0
    state.observe(15.0, LOW)
    assert state.dwell_seconds == 15.0


def test_restart_keeps_dwell_and_resets_saturation(tmp_path):
    path = tmp_path / "hearing_stage.json"
    state = HearingStageState(PARAMS, path=path)
    _anchored(state)
    t, _ = _run(state, 0.0, D_MIN + 300, None, step=10.0)
    assert state.stage == 0
    saved_dwell = state.dwell_seconds
    state.save()

    raw = json.loads(path.read_text())
    assert raw["version"] == 1
    assert raw["stage"] == 0
    assert raw["dwell_seconds"] == saved_dwell

    reloaded = HearingStageState.load(PARAMS, path=path)
    assert reloaded.stage == 0
    assert reloaded.dwell_seconds == saved_dwell
    assert reloaded.saturated_seconds == 0.0

    reloaded.observe(100000.0, LOW)  # anchor only
    t = 100000.0
    t, result = _run(reloaded, t, W - 10, LOW, step=10.0)
    assert result is None
    assert reloaded.observe(t + 10.0, LOW) == 1


def test_advance_saves_immediately(tmp_path):
    path = tmp_path / "hearing_stage.json"
    state = HearingStageState(PARAMS, path=path)
    _anchored(state)
    assert state.observe(D_MAX, None) == 1
    raw = json.loads(path.read_text())
    assert raw["stage"] == 1
    assert raw["dwell_seconds"] == 0.0
    assert HearingStageState.load(PARAMS, path=path).stage == 1


def test_autosave_every_30_dwell_seconds(tmp_path):
    path = tmp_path / "hearing_stage.json"
    state = HearingStageState(PARAMS, path=path)
    _anchored(state)
    state.observe(29.0, None)
    assert not path.exists()
    state.observe(31.0, None)
    assert json.loads(path.read_text())["dwell_seconds"] == 31.0
    state.observe(40.0, None)
    assert json.loads(path.read_text())["dwell_seconds"] == 31.0


def test_no_path_means_no_persistence(tmp_path):
    state = HearingStageState(PARAMS)
    _anchored(state)
    state.observe(100.0, None)
    state.save()
    assert list(tmp_path.iterdir()) == []
    assert HearingStageState.load(PARAMS, path=None).stage == 0


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        '"x"',
        "",
        json.dumps({"version": 1, "stage": "2", "dwell_seconds": 1.0}),
        json.dumps({"version": 1, "stage": True, "dwell_seconds": 1.0}),
        json.dumps({"version": 1, "stage": 7, "dwell_seconds": 1.0}),
        json.dumps({"version": 1, "stage": -1, "dwell_seconds": 1.0}),
        json.dumps({"version": 1, "stage": 1, "dwell_seconds": "a"}),
        json.dumps({"version": 1, "stage": 1, "dwell_seconds": -5.0}),
        json.dumps({"version": 1, "stage": 1}),
        '{"version": 1, "stage": 1, "dwell_seconds": NaN}',
    ],
)
def test_bad_file_starts_fresh_and_never_raises(tmp_path, caplog, content):
    path = tmp_path / "hearing_stage.json"
    path.write_text(content)
    with caplog.at_level("WARNING"):
        state = HearingStageState.load(PARAMS, path=path)
    assert state.stage == 0
    assert state.dwell_seconds == 0.0
    assert "unusable" in caplog.text


def test_missing_file_starts_fresh(tmp_path):
    state = HearingStageState.load(PARAMS, path=tmp_path / "absent.json")
    assert (state.stage, state.dwell_seconds) == (0, 0.0)


def test_unreadable_path_never_raises(tmp_path):
    state = HearingStageState.load(PARAMS, path=tmp_path)  # a directory
    assert state.stage == 0


def test_failed_save_logs_and_never_raises(tmp_path, caplog):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    state = HearingStageState(PARAMS, path=blocker / "hearing_stage.json")
    with caplog.at_level("WARNING"):
        state.save()
    assert "could not save hearing stage" in caplog.text


def test_loaded_state_values_are_finite(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"version": 1, "stage": 3, "dwell_seconds": 12.5}))
    state = HearingStageState.load(PARAMS, path=path)
    assert state.stage == 3
    assert math.isclose(state.dwell_seconds, 12.5)
