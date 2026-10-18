# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unit tests for the hearing band schedule and filter design."""

import math

import numpy as np
import pytest

from kaine.modules.audition.hearing_band import (
    HEARING_BAND_STAGES,
    HearingBandParams,
    band_edges,
    band_frequency_response_db,
    band_taps,
    hearing_stage,
)


def test_stage_edges_follow_tone_grid():
    assert HEARING_BAND_STAGES[0] == pytest.approx((353.5534, 707.1068), abs=1e-4)
    assert HEARING_BAND_STAGES[1] == pytest.approx((158.1139, 707.1068), abs=1e-4)
    assert HEARING_BAND_STAGES[2] == pytest.approx((100.0, 707.1068), abs=1e-4)
    assert HEARING_BAND_STAGES[3] == pytest.approx((100.0, 1732.0508), abs=1e-4)
    assert HEARING_BAND_STAGES[4] == pytest.approx((100.0, 3000.0), abs=1e-4)


def test_schedule_shape():
    params = HearingBandParams(maturation_seconds=86400.0)
    cases = [
        (-5, 0),
        (float("nan"), 0),
        (float("inf"), 0),
        (0, 0),
        (21599.999, 0),
        (21600, 1),
        (43199.9, 1),
        (43200, 2),
        (64800, 3),
        (86399.9, 3),
        (86400, 4),
        (10**7, 4),
    ]
    for awake, expected in cases:
        assert hearing_stage(awake, params) == expected

    W = params.maturation_seconds
    low_edges = []
    high_edges = []
    times = []
    for T in range(0, int(2 * W) + 1, 600):
        low, high = band_edges(T, params)
        times.append(T)
        low_edges.append(low)
        high_edges.append(high)

    for i in range(1, len(times)):
        assert low_edges[i] <= low_edges[i - 1]
        assert high_edges[i] >= high_edges[i - 1]

    low_hit_index = next(i for i, low in enumerate(low_edges) if low == 100.0)
    high_move_index = next(
        i for i, high in enumerate(high_edges) if high != high_edges[0]
    )
    assert low_hit_index < high_move_index


def test_from_section_defaults_and_validation():
    default = HearingBandParams.from_section(None)
    assert default.enabled is True
    assert default.maturation_seconds == 86400.0

    empty = HearingBandParams.from_section({})
    assert empty.enabled is True
    assert empty.maturation_seconds == 86400.0

    configured = HearingBandParams.from_section(
        {"enabled": False, "maturation_seconds": 3600}
    )
    assert configured.enabled is False
    assert configured.maturation_seconds == 3600.0

    invalid_sections = [
        {"enabled": 1},
        {"maturation_seconds": True},
        {"maturation_seconds": "x"},
        {"maturation_seconds": float("nan")},
        {"maturation_seconds": 59.0},
        {"maturation_seconds": 2592001.0},
        {"unknown": 1},
    ]
    for section in invalid_sections:
        with pytest.raises(ValueError):
            HearingBandParams.from_section(section)

    with pytest.raises(ValueError):
        HearingBandParams.from_section([])


def test_taps_unity_centre_and_stopband():
    sample_rate = 16000.0
    for low, high in HEARING_BAND_STAGES:
        taps = band_taps(low, high, sample_rate)
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
        upper_grid = np.arange(high * math.sqrt(2.0), 7995.1, 5.0)

        max_lower = max(
            band_frequency_response_db(taps, f, sample_rate) for f in lower_grid
        )
        max_upper = max(
            band_frequency_response_db(taps, f, sample_rate) for f in upper_grid
        )
        assert max_lower <= -40.0
        assert max_upper <= -40.0

        low_edge_response = band_frequency_response_db(taps, low, sample_rate)
        high_edge_response = band_frequency_response_db(taps, high, sample_rate)
        assert low_edge_response == pytest.approx(-6.02, abs=1.0)
        assert high_edge_response == pytest.approx(-6.02, abs=1.0)


def test_taps_are_cached_copies():
    a = band_taps(100.0, 3000.0, 16000.0)
    b = band_taps(100.0, 3000.0, 16000.0)
    assert np.array_equal(a, b)
    assert a is not b

    a[0] = 999.0
    c = band_taps(100.0, 3000.0, 16000.0)
    assert c[0] != 999.0
    assert np.array_equal(c, b)


def test_taps_reject_bad_edges():
    bad_edges = [
        (0, 500, 16000),
        (500, 500, 16000),
        (600, 500, 16000),
        (100, 8000, 16000),
        (100, float("nan"), 16000),
    ]
    for low, high, sample_rate in bad_edges:
        with pytest.raises(ValueError):
            band_taps(low, high, sample_rate)


def test_thud_below_final_band():
    low, high = HEARING_BAND_STAGES[-1]
    taps = band_taps(low, high, 16000.0)
    for freq in (45.0, 50.0, 55.0):
        response = band_frequency_response_db(taps, freq, 16000.0)
        assert response <= -55.0
