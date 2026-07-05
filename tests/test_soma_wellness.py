# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.modules.soma.wellness import compute_wellness, normalize_metric


def test_healthy_metrics_yield_full_wellness():
    metrics = {"cpu_percent": 0.0, "ram_percent": 0.0}
    assert compute_wellness(metrics) == pytest.approx(1.0)


def test_mid_range_cpu_yields_half_wellness():
    assert compute_wellness({"cpu_percent": 50.0}) == pytest.approx(0.5)


def test_max_cpu_yields_zero_wellness():
    assert compute_wellness({"cpu_percent": 100.0}) == 0.0


def test_unknown_keys_dont_break_or_contribute():
    metrics = {"cpu_percent": 0.0, "disk_read_bytes": 1234567.0}
    assert compute_wellness(metrics) == pytest.approx(1.0)


def test_gpu_temp_curve_above_min():
    assert compute_wellness({"gpu_0_temp_c": 30.0}) == pytest.approx(1.0)
    assert compute_wellness({"gpu_0_temp_c": 55.0}) == pytest.approx(0.5)
    assert compute_wellness({"gpu_0_temp_c": 80.0}) == pytest.approx(0.0)


def test_gpu_vram_curve():
    assert compute_wellness({"gpu_0_vram_percent": 0.0}) == pytest.approx(1.0)
    assert compute_wellness({"gpu_0_vram_percent": 100.0}) == 0.0


def test_cycle_latency_curve_against_target():
    assert (
        compute_wellness(
            {"cycle_latency_avg_ms": 300.0}, cycle_latency_target_ms=300.0
        )
        == pytest.approx(1.0)
    )
    assert (
        compute_wellness(
            {"cycle_latency_avg_ms": 600.0}, cycle_latency_target_ms=300.0
        )
        == pytest.approx(0.5)
    )
    assert (
        compute_wellness(
            {"cycle_latency_avg_ms": 900.0}, cycle_latency_target_ms=300.0
        )
        == 0.0
    )


def test_weighted_average_two_metrics():
    metrics = {"cpu_percent": 10.0, "ram_percent": 20.0}
    # cpu contribution 0.9, ram 0.8 → equal weights → mean 0.85
    assert compute_wellness(metrics) == pytest.approx(0.85)


def test_weights_skew_contribution():
    metrics = {"cpu_percent": 0.0, "ram_percent": 100.0}
    # cpu contribution 1.0, ram 0.0; cpu weight 9 + ram weight 1 → 0.9
    assert (
        compute_wellness(metrics, weights={"cpu_percent": 9.0, "ram_percent": 1.0})
        == pytest.approx(0.9)
    )


def test_gpu_absence_does_not_penalize():
    # No gpu_* keys; wellness must come from cpu+ram only.
    metrics = {"cpu_percent": 10.0, "ram_percent": 20.0}
    assert compute_wellness(metrics) == pytest.approx(0.85)


def test_normalize_metric_returns_none_for_unknown_keys():
    assert normalize_metric("not_a_known_key", 5.0) is None


def test_normalize_metric_clamps_extreme_inputs():
    assert normalize_metric("cpu_percent", 200.0) == 0.0
    assert normalize_metric("cpu_percent", -50.0) == 1.0


def test_empty_metrics_returns_full_wellness():
    assert compute_wellness({}) == 1.0


def test_zero_weight_skips_metric():
    metrics = {"cpu_percent": 100.0, "ram_percent": 0.0}
    result = compute_wellness(metrics, weights={"cpu_percent": 0.0})
    assert result == pytest.approx(1.0)
