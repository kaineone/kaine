# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unit tests for the windowed affect learning progress estimator."""

import pytest

from kaine.modules.affect.learning_progress import WindowedProgress

BIN_S = 60.0
MAX_BINS = 90


def feed(progress, start, end, error):
    """Add error every 1.0 s from start to end, inclusive."""
    t = float(start)
    end = float(end)
    while t <= end + 1e-9:
        progress.add(t, error)
        t += 1.0


def test_started_false_initially():
    p = WindowedProgress(BIN_S, MAX_BINS)
    assert not p.started
    assert p.bin_s == BIN_S
    assert p.max_bins == MAX_BINS


def test_constructor_rejects_bad_bin_s():
    for bad in (0.0, -1.0, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            WindowedProgress(bad, MAX_BINS)


def test_constructor_rejects_bad_max_bins():
    for bad in (3, 0, True, False, 2.5):
        with pytest.raises(ValueError):
            WindowedProgress(BIN_S, bad)
    # smallest valid window
    WindowedProgress(BIN_S, 2)


def test_undefined_before_two_completed_bins():
    p = WindowedProgress(BIN_S, MAX_BINS)
    feed(p, 0.0, 59.0, 1.0)
    assert p.value(59.0) is None

    feed(p, 60.0, 119.0, 0.7)
    assert p.value(119.0) is None
    assert p.value(120.0) == pytest.approx(0.3)


def test_thirty_percent_fall():
    p = WindowedProgress(BIN_S, MAX_BINS)
    feed(p, 0.0, 59.0, 1.0)
    feed(p, 60.0, 119.0, 0.7)
    assert p.value(120.0) == pytest.approx(0.3)


def test_constant_error_gives_zero_progress():
    p = WindowedProgress(BIN_S, MAX_BINS)
    feed(p, 0.0, 299.0, 2.0)
    assert p.value(300.0) == pytest.approx(0.0)


def test_rising_error_negative_and_clipped():
    p = WindowedProgress(BIN_S, 4)
    feed(p, 0.0, 59.0, 1.0)
    feed(p, 60.0, 119.0, 1.0)
    feed(p, 120.0, 179.0, 3.0)
    feed(p, 180.0, 239.0, 3.0)
    assert p.value(240.0) == pytest.approx(-1.0)


def test_three_completed_bins_rounds_down_to_two():
    p = WindowedProgress(BIN_S, MAX_BINS)
    feed(p, 0.0, 59.0, 100.0)
    feed(p, 60.0, 119.0, 1.0)
    feed(p, 120.0, 179.0, 0.7)
    # three completed bins, but k is rounded down to 2
    assert p.value(239.0) == pytest.approx(0.3)


def test_max_bins_keeps_only_newest_completed_bins():
    p = WindowedProgress(BIN_S, 4)
    feed(p, 0.0, 119.0, 1.0)
    feed(p, 120.0, 239.0, 1.0)
    feed(p, 240.0, 359.0, 0.7)
    # newest four bins are 2, 3 (1.0) and 4, 5 (0.7)
    assert p.value(360.0) == pytest.approx(0.3)


def test_report_weighting_not_mean_of_bin_means():
    p = WindowedProgress(60.0, 4)
    p.add(0.0, 4.0)
    p.add(60.0, 0.0)
    p.add(61.0, 0.0)
    p.add(62.0, 0.0)
    p.add(120.0, 0.5)
    p.add(180.0, 0.5)
    assert p.value(240.0) == pytest.approx(0.5)
    assert p.value(240.0) != pytest.approx(0.75)


def test_zeros_ignored_before_start_counted_after():
    p = WindowedProgress(BIN_S, MAX_BINS)
    p.add(0.0, 0.0)
    p.add(1.0, 0.0)
    p.add(2.0, 0.0)

    p.add(10.0, 5.0)
    p.add(11.0, 0.0)
    p.add(12.0, 0.0)
    p.add(13.0, 0.0)
    p.add(14.0, 0.0)

    # five reports in bin 0 give a mean of 1.0
    snapshot = p.to_dict(15.0)
    assert snapshot["current"] == [5.0, 5]
    assert snapshot["elapsed_s"] == pytest.approx(5.0)

    feed(p, 70.0, 129.0, 5.0)
    # bin 0 mean 1.0, bin 1 mean 5.0
    assert p.value(130.0) == pytest.approx(-1.0)


def test_long_gap_longer_than_max_bins_is_fast_and_none():
    p = WindowedProgress(60.0, 4)
    feed(p, 0.0, 119.0, 1.0)
    feed(p, 120.0, 239.0, 0.5)
    assert p.value(240.0) == pytest.approx(0.5)

    gap_t = 240.0 + 1_000_000 * 60.0
    p.advance(gap_t)
    assert p.value(gap_t) is None

    feed(p, gap_t, gap_t + 59.0, 0.8)
    feed(p, gap_t + 60.0, gap_t + 119.0, 0.8)
    assert p.value(gap_t + 120.0) is None

    feed(p, gap_t + 120.0, gap_t + 179.0, 0.4)
    feed(p, gap_t + 180.0, gap_t + 239.0, 0.4)
    assert p.value(gap_t + 240.0) == pytest.approx(0.5)


def test_backwards_clock_does_not_raise_or_change_value():
    p = WindowedProgress(BIN_S, MAX_BINS)
    feed(p, 0.0, 59.0, 1.0)
    feed(p, 60.0, 119.0, 0.7)

    v = p.value(120.0)
    assert v == pytest.approx(0.3)

    p.advance(60.0)
    assert p.value(120.0) == pytest.approx(0.3)

    p.add(30.0, 100.0)
    assert p.value(120.0) == pytest.approx(0.3)


def test_current_partial_bin_does_not_affect_value():
    p = WindowedProgress(BIN_S, MAX_BINS)
    feed(p, 0.0, 119.0, 1.0)
    assert p.value(120.0) == pytest.approx(0.0)

    for i in range(10):
        p.add(150.0 + i * 0.01, 100.0)

    assert p.value(150.0) == pytest.approx(0.0)


def test_to_dict_requires_started():
    p = WindowedProgress(BIN_S, MAX_BINS)
    with pytest.raises(ValueError):
        p.to_dict(0.0)


def test_to_dict_from_dict_round_trip_preserves_values():
    p = WindowedProgress(BIN_S, MAX_BINS)
    feed(p, 0.0, 59.0, 1.0)
    feed(p, 60.0, 119.0, 0.7)

    save_t = 150.0
    v_before = p.value(save_t)
    d = p.to_dict(save_t)

    q = WindowedProgress.from_dict(d, bin_s=BIN_S, max_bins=MAX_BINS, t=save_t)
    assert q is not None
    assert q.value(save_t) == pytest.approx(v_before)

    feed(p, save_t, 209.0, 0.5)
    feed(q, save_t, 209.0, 0.5)
    assert p.value(240.0) == pytest.approx(q.value(240.0))


def test_from_dict_rejects_invalid_data():
    base = WindowedProgress(BIN_S, MAX_BINS)
    feed(base, 0.0, 59.0, 1.0)
    base.add(60.0, 0.7)
    d = base.to_dict(90.0)
    assert (
        WindowedProgress.from_dict(d, bin_s=BIN_S, max_bins=MAX_BINS, t=90.0)
        is not None
    )

    assert (
        WindowedProgress.from_dict([], bin_s=BIN_S, max_bins=MAX_BINS, t=90.0)
        is None
    )

    bad = dict(d)
    bad["bin_s"] = 61.0
    assert (
        WindowedProgress.from_dict(bad, bin_s=BIN_S, max_bins=MAX_BINS, t=90.0)
        is None
    )

    bad = dict(d)
    bad["bins"][0][0] = -1.0
    assert (
        WindowedProgress.from_dict(bad, bin_s=BIN_S, max_bins=MAX_BINS, t=90.0)
        is None
    )

    bad = dict(d)
    bad["bins"][0][0] = float("inf")
    assert (
        WindowedProgress.from_dict(bad, bin_s=BIN_S, max_bins=MAX_BINS, t=90.0)
        is None
    )

    bad = dict(d)
    bad["bins"][0][1] = True
    assert (
        WindowedProgress.from_dict(bad, bin_s=BIN_S, max_bins=MAX_BINS, t=90.0)
        is None
    )

    bad = dict(d)
    bad["bins"][0][1] = 3.5
    assert (
        WindowedProgress.from_dict(bad, bin_s=BIN_S, max_bins=MAX_BINS, t=90.0)
        is None
    )

    bad = dict(d)
    bad["current"] = [0.0, True]
    assert (
        WindowedProgress.from_dict(bad, bin_s=BIN_S, max_bins=MAX_BINS, t=90.0)
        is None
    )

    bad = dict(d)
    bad["current"] = [0.0]
    assert (
        WindowedProgress.from_dict(bad, bin_s=BIN_S, max_bins=MAX_BINS, t=90.0)
        is None
    )

    bad = dict(d)
    bad["elapsed_s"] = -1.0
    assert (
        WindowedProgress.from_dict(bad, bin_s=BIN_S, max_bins=MAX_BINS, t=90.0)
        is None
    )

    bad = dict(d)
    bad["elapsed_s"] = BIN_S + 1.0
    assert (
        WindowedProgress.from_dict(bad, bin_s=BIN_S, max_bins=MAX_BINS, t=90.0)
        is None
    )


def test_from_dict_accepts_whole_float_counts():
    d = {
        "bin_s": BIN_S,
        "bins": [[1.0, 3.0], [2.0, 4.0]],
        "current": [0.5, 2.0],
        "elapsed_s": 0.0,
    }
    p = WindowedProgress.from_dict(d, bin_s=BIN_S, max_bins=MAX_BINS, t=0.0)
    assert p is not None
    assert p.value(60.0) == pytest.approx(0.5)


def test_from_dict_trims_excess_bins_to_max_bins():
    bins = [[float(i), 1] for i in range(1, 7)]
    d = {"bin_s": BIN_S, "bins": bins, "current": [0.0, 0], "elapsed_s": 0.0}
    p = WindowedProgress.from_dict(d, bin_s=BIN_S, max_bins=4, t=0.0)
    assert p is not None

    snapshot = p.to_dict(0.0)
    assert len(snapshot["bins"]) == 4
    assert snapshot["bins"] == [[3.0, 1], [4.0, 1], [5.0, 1], [6.0, 1]]
    assert p.value(0.0) == pytest.approx(1.0 - 5.5 / 3.5)


def test_from_dict_rejects_positive_sum_with_zero_count():
    base = WindowedProgress(BIN_S, MAX_BINS)
    feed(base, 0.0, 59.0, 1.0)
    base.add(60.0, 0.7)
    d = base.to_dict(90.0)

    bad_bins = dict(d)
    bad_bins["bins"] = [[2.5, 0]]
    assert (
        WindowedProgress.from_dict(
            bad_bins, bin_s=BIN_S, max_bins=MAX_BINS, t=90.0
        )
        is None
    )

    bad_current = dict(d)
    bad_current["current"] = [2.5, 0]
    assert (
        WindowedProgress.from_dict(
            bad_current, bin_s=BIN_S, max_bins=MAX_BINS, t=90.0
        )
        is None
    )

    zero_sum = dict(d)
    zero_sum["bins"] = [[0.0, 0]]
    assert (
        WindowedProgress.from_dict(
            zero_sum, bin_s=BIN_S, max_bins=MAX_BINS, t=90.0
        )
        is not None
    )

    zero_current = dict(d)
    zero_current["current"] = [0.0, 0]
    assert (
        WindowedProgress.from_dict(
            zero_current, bin_s=BIN_S, max_bins=MAX_BINS, t=90.0
        )
        is not None
    )


def test_value_none_when_older_half_has_no_reports():
    p = WindowedProgress(BIN_S, 4)
    feed(p, 0.0, 59.0, 1.0)
    # bins 1, 2 and 3 are empty
    feed(p, 240.0, 359.0, 1.0)
    assert p.value(360.0) is None


def test_value_none_when_newer_half_has_no_reports():
    p = WindowedProgress(BIN_S, 4)
    feed(p, 0.0, 119.0, 1.0)
    # bins 2 and 3 are empty
    assert p.value(240.0) is None


def test_gap_of_exactly_max_bins_empty_bins_gives_none_then_recover():
    p = WindowedProgress(60.0, 4)
    feed(p, 0.0, 119.0, 1.0)
    feed(p, 120.0, 239.0, 0.5)
    p.add(240.0, 0.9)

    # advancing from bin 4 to bin 9 appends bin 4 and four empty bins,
    # so the deque ends up holding four empty bins
    assert p.value(540.0) is None

    feed(p, 540.0, 659.0, 0.8)
    assert p.value(660.0) is None

    feed(p, 660.0, 779.0, 0.4)
    assert p.value(780.0) == pytest.approx(0.5)


def test_gap_of_max_bins_minus_one_empty_bins_gives_none():
    p = WindowedProgress(60.0, 4)
    feed(p, 0.0, 119.0, 1.0)
    feed(p, 120.0, 239.0, 0.5)
    p.add(240.0, 0.9)

    # three skipped bins (bins 5, 6, 7); next report is in bin 8
    assert p.value(480.0) is None
    # bin 4 survives the gap as the oldest completed bin
    assert p.to_dict(480.0)["bins"] == [[0.9, 1], [0.0, 0], [0.0, 0], [0.0, 0]]

    feed(p, 480.0, 599.0, 0.45)
    assert p.value(600.0) is None
