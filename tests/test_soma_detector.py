# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.modules.soma.detector import (
    AlertResult,
    AnomalyDetector,
    ThresholdAnomalyDetector,
)


def test_no_alerts_when_all_under_threshold():
    detector = ThresholdAnomalyDetector(
        {"cpu_percent": 90.0, "ram_percent": 90.0}
    )
    result = detector.evaluate({"cpu_percent": 80.0, "ram_percent": 50.0})
    assert result.keys == ()
    assert result.is_alert is False


def test_breach_triggers_alert():
    detector = ThresholdAnomalyDetector({"cpu_percent": 90.0})
    result = detector.evaluate({"cpu_percent": 95.0})
    assert result.keys == ("cpu_percent",)
    assert result.is_alert is True


def test_equal_to_threshold_not_alert():
    detector = ThresholdAnomalyDetector({"cpu_percent": 90.0})
    result = detector.evaluate({"cpu_percent": 90.0})
    assert result.is_alert is False


def test_missing_metric_does_not_alert():
    detector = ThresholdAnomalyDetector(
        {"cpu_percent": 90.0, "ram_percent": 90.0}
    )
    result = detector.evaluate({"cpu_percent": 50.0})
    assert result.is_alert is False


def test_wildcard_threshold_matches_gpu_keys():
    detector = ThresholdAnomalyDetector({"gpu_*_temp_c": 80.0})
    result = detector.evaluate(
        {"gpu_0_temp_c": 85.0, "gpu_1_temp_c": 70.0, "cpu_percent": 10.0}
    )
    assert "gpu_0_temp_c" in result.keys
    assert "gpu_1_temp_c" not in result.keys
    assert "cpu_percent" not in result.keys


def test_multiple_breaches_sorted():
    detector = ThresholdAnomalyDetector(
        {"cpu_percent": 90.0, "ram_percent": 90.0}
    )
    result = detector.evaluate({"cpu_percent": 95.0, "ram_percent": 99.0})
    assert result.keys == ("cpu_percent", "ram_percent")


def test_unknown_threshold_key_ignored():
    detector = ThresholdAnomalyDetector({"not_a_metric": 50.0})
    result = detector.evaluate({"cpu_percent": 99.0})
    assert result.is_alert is False


def test_threshold_value_must_be_numeric():
    with pytest.raises(ValueError):
        ThresholdAnomalyDetector({"cpu_percent": None})  # type: ignore[arg-type]


def test_protocol_runtime_checkable():
    assert isinstance(ThresholdAnomalyDetector({}), AnomalyDetector)


def test_alert_result_dataclass_is_frozen():
    result = AlertResult(keys=("cpu_percent",))
    with pytest.raises(Exception):
        result.keys = ()  # type: ignore[misc]
