# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unit tests for the hearing band schedule and filter design."""

import math

import numpy as np
import pytest

from kaine.modules.audition.hearing_band import (
    HEARING_BAND_STAGES,
    HEARING_BAND_TAPS,
    HEARING_FINAL_STAGE,
    HEARING_TOP_TONE_HZ,
    HearingBandParams,
    band_frequency_response_db,
    band_taps,
    stage_edges,
)


def test_stage_edges_follow_tone_grid():
    assert HEARING_BAND_STAGES[0] == pytest.approx((353.5534, 707.1068), abs=1e-4)
    assert HEARING_BAND_STAGES[1] == pytest.approx((158.1139, 707.1068), abs=1e-4)

    low, high = HEARING_BAND_STAGES[2]
    assert low is None
    assert high == pytest.approx(707.1068, abs=1e-4)

    low, high = HEARING_BAND_STAGES[3]
    assert low is None
    assert high == pytest.approx(1732.0508, abs=1e-4)

    assert HEARING_BAND_STAGES[4] == (None, None)
    assert HEARING_TOP_TONE_HZ == 3000.0


def test_stage_edges_per_stage_and_clamping():
    assert HEARING_FINAL_STAGE == 4
    for stage in range(5):
        assert stage_edges(stage) == HEARING_BAND_STAGES[stage]
    assert stage_edges(-3) == HEARING_BAND_STAGES[0]
    assert stage_edges(99) == HEARING_BAND_STAGES[4]
    assert stage_edges(True) == HEARING_BAND_STAGES[0]
    assert stage_edges("2") == HEARING_BAND_STAGES[0]
    assert stage_edges(2.0) == HEARING_BAND_STAGES[0]
    assert stage_edges(None) == HEARING_BAND_STAGES[0]


def test_edges_widen_with_stage():
    mapped_low = [0.0 if low is None else low for low, _ in HEARING_BAND_STAGES]
    mapped_high = [math.inf if high is None else high for _, high in HEARING_BAND_STAGES]
    for i in range(1, 5):
        assert mapped_low[i] <= mapped_low[i - 1]
        assert mapped_high[i] >= mapped_high[i - 1]


def test_from_section_defaults_and_validation():
    defaults = HearingBandParams()
    assert defaults.saturation_window_seconds == 600.0
    assert defaults.min_dwell_seconds == 5400.0
    assert defaults.max_dwell_seconds == 25200.0

    for section in (None, {}):
        parsed = HearingBandParams.from_section(section)
        assert parsed == defaults

    configured = HearingBandParams.from_section(
        {
            "enabled": False,
            "saturation_window_seconds": 60,
            "min_dwell_seconds": 120,
            "max_dwell_seconds": 600,
        }
    )
    assert configured == HearingBandParams(False, 60.0, 120.0, 600.0)

    invalid_sections = [
        {"enabled": 1},
        {"saturation_window_seconds": True},
        {"min_dwell_seconds": "x"},
        {"max_dwell_seconds": float("nan")},
        {"max_dwell_seconds": float("inf")},
        {"saturation_window_seconds": 0},
        {"saturation_window_seconds": -1.0},
        {"max_dwell_seconds": 2592001.0},
        {"saturation_window_seconds": 6000.0},
        {"min_dwell_seconds": 30000.0},
        {"min_dwell_seconds": 100.0},
        {"unknown": 1},
    ]
    for section in invalid_sections:
        with pytest.raises(ValueError):
            HearingBandParams.from_section(section)

    with pytest.raises(ValueError, match="saturation_window_seconds"):
        HearingBandParams.from_section({"saturation_window_seconds": 0})

    with pytest.raises(ValueError):
        HearingBandParams.from_section([])


def test_retired_maturation_seconds_is_ignored_with_warning(caplog):
    with caplog.at_level("WARNING"):
        parsed = HearingBandParams.from_section({"maturation_seconds": 3600})
    assert parsed == HearingBandParams()
    assert (
        "[perception_feed.stimulus_source.hearing].maturation_seconds is retired and ignored"
        in caplog.text
    )


def test_taps_unity_and_stopband():
    sample_rate = 16000.0
    n_hz = 7995.0
    for low, high in HEARING_BAND_STAGES:
        taps = band_taps(low, high, sample_rate)

        if low is not None and high is not None:
            fc = math.sqrt(low * high)
            centre = band_frequency_response_db(taps, fc, sample_rate)
            assert centre == pytest.approx(0.0, abs=0.01)

            lower_stop = band_frequency_response_db(
                taps, low / math.sqrt(2.0), sample_rate
            )
            upper_stop = band_frequency_response_db(
                taps, high * math.sqrt(2.0), sample_rate
            )
            assert lower_stop <= -40.0
            assert upper_stop <= -40.0

            lower_grid = np.arange(1.0, low / math.sqrt(2.0) + 1.0, 1.0)
            upper_grid = np.arange(high * math.sqrt(2.0), n_hz + 0.1, 5.0)
            max_lower = max(
                band_frequency_response_db(taps, f, sample_rate)
                for f in lower_grid
            )
            max_upper = max(
                band_frequency_response_db(taps, f, sample_rate)
                for f in upper_grid
            )
            assert max_lower <= -40.0
            assert max_upper <= -40.0

            low_edge_response = band_frequency_response_db(taps, low, sample_rate)
            high_edge_response = band_frequency_response_db(taps, high, sample_rate)
            assert low_edge_response == pytest.approx(-6.02, abs=1.0)
            assert high_edge_response == pytest.approx(-6.02, abs=1.0)

        elif low is None and high is not None:
            assert taps.sum() == pytest.approx(1.0, abs=1e-12)

            pass_grid = np.arange(1.0, high / math.sqrt(2.0) + 1.0, 1.0)
            for f in pass_grid:
                response = band_frequency_response_db(taps, f, sample_rate)
                assert response == pytest.approx(0.0, abs=0.1)

            stop_grid = np.arange(high * math.sqrt(2.0), n_hz + 0.1, 5.0)
            max_stop = max(
                band_frequency_response_db(taps, f, sample_rate)
                for f in stop_grid
            )
            assert max_stop <= -40.0

            edge_response = band_frequency_response_db(taps, high, sample_rate)
            assert edge_response == pytest.approx(-6.02, abs=1.0)

        else:
            expected = np.zeros(HEARING_BAND_TAPS)
            expected[HEARING_BAND_TAPS // 2] = 1.0
            assert np.array_equal(taps, expected)
            assert len(taps) == 1025


def test_taps_are_cached_copies():
    a = band_taps(None, 707.1067811865476, 16000.0)
    b = band_taps(None, 707.1067811865476, 16000.0)
    assert np.array_equal(a, b)
    assert a is not b

    a[0] = 999.0
    c = band_taps(None, 707.1067811865476, 16000.0)
    assert c[0] != 999.0
    assert np.array_equal(c, b)


def test_taps_reject_bad_edges():
    bad_edges = [
        (0, 500, 16000),
        (500, 500, 16000),
        (600, 500, 16000),
        (100, 8000, 16000),
        (100, float("nan"), 16000),
        (None, 8000, 16000),
        (0.0, None, 16000),
        (None, None, 0.0),
    ]
    for low, high, sample_rate in bad_edges:
        with pytest.raises(ValueError):
            band_taps(low, high, sample_rate)


def test_highpass_is_total():
    taps = band_taps(200.0, None, 16000.0)
    assert taps.sum() == pytest.approx(0.0, abs=1e-12)

    response_50 = band_frequency_response_db(taps, 50.0, 16000.0)
    assert response_50 <= -40.0

    response_1000 = band_frequency_response_db(taps, 1000.0, 16000.0)
    assert response_1000 == pytest.approx(0.0, abs=0.1)


def test_thud_attenuated_early_and_passed_late():
    for low, high in HEARING_BAND_STAGES:
        taps = band_taps(low, high, 16000.0)
        for freq in (45.0, 50.0, 55.0):
            response = band_frequency_response_db(taps, freq, 16000.0)
            if low is not None:
                assert response <= -55.0
            else:
                assert response == pytest.approx(0.0, abs=1.0)


def test_filter_delay_is_constant():
    for low, high in HEARING_BAND_STAGES:
        taps = band_taps(low, high, 16000.0)
        assert np.allclose(taps, taps[::-1], rtol=0.0, atol=1e-15)
