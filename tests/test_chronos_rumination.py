# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.modules.chronos.rumination import (
    RecurrenceRuminationDetector,
    RuminationDetector,
    RuminationResult,
)


def test_protocol_runtime_checkable():
    assert isinstance(RecurrenceRuminationDetector(), RuminationDetector)


def test_invalid_args_rejected():
    with pytest.raises(ValueError):
        RecurrenceRuminationDetector(window=1)
    with pytest.raises(ValueError):
        RecurrenceRuminationDetector(threshold=1)
    with pytest.raises(ValueError):
        RecurrenceRuminationDetector(bucket_resolution=0.0)


def test_distinct_states_no_rumination():
    det = RecurrenceRuminationDetector(window=8, threshold=3)
    for i in range(8):
        result = det.observe([i * 1.0, 0.0])
    assert result.detected is False
    assert result.habituation < 0.5


def test_repeated_state_triggers_rumination():
    det = RecurrenceRuminationDetector(window=8, threshold=4)
    for _ in range(5):
        result = det.observe([1.0, 0.0, 0.0])
    assert result.detected is True
    assert result.dominant_count >= 4


def test_habituation_high_when_dominated_by_one_bucket():
    det = RecurrenceRuminationDetector(window=8, threshold=10)
    for _ in range(8):
        result = det.observe([2.0, 2.0])
    # Single dominant bucket → habituation = 1 - 1/8 = 0.875
    assert result.habituation == pytest.approx(7 / 8)


def test_habituation_zero_when_all_distinct():
    det = RecurrenceRuminationDetector(window=8, threshold=10)
    for i in range(8):
        result = det.observe([i * 1.0, 0.0])
    # 8 unique buckets in window of 8 → habituation 0.0
    assert result.habituation == pytest.approx(0.0)


def test_quantization_groups_similar_states():
    det = RecurrenceRuminationDetector(
        window=8, threshold=3, bucket_resolution=0.5
    )
    # Both states round to the same bucket at resolution 0.5
    det.observe([0.10, 0.10])
    det.observe([0.20, 0.15])
    c = det.observe([0.00, 0.05])
    # All three should land in the same quantized bucket
    assert c.dominant_count >= 3


def test_result_dataclass_is_frozen():
    result = RuminationResult(detected=True, habituation=0.5, dominant_bucket="x", dominant_count=4)
    with pytest.raises(Exception):
        result.detected = False  # type: ignore[misc]
