# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from typing import Optional


def _clamp(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def normalize_metric(
    key: str,
    value: float,
    *,
    cycle_latency_target_ms: float = 300.0,
    gpu_temp_min_c: float = 30.0,
    gpu_temp_max_c: float = 80.0,
) -> Optional[float]:
    """Normalize a metric into [0, 1], 1 = healthy. Return None if no curve.

    Keys with no defined normalization curve are excluded from wellness
    so they neither raise nor falsely inflate the score.
    """
    if key in ("cpu_percent", "ram_percent"):
        return _clamp(1.0 - value / 100.0)
    if key.startswith("gpu_") and key.endswith("_temp_c"):
        span = max(gpu_temp_max_c - gpu_temp_min_c, 1e-9)
        return _clamp(1.0 - max(value - gpu_temp_min_c, 0.0) / span)
    if key.startswith("gpu_") and key.endswith("_vram_percent"):
        return _clamp(1.0 - value / 100.0)
    if key == "cycle_latency_avg_ms":
        target = max(cycle_latency_target_ms, 1.0)
        return _clamp(1.0 - max(value - target, 0.0) / (2.0 * target))
    return None


def compute_wellness(
    metrics: dict[str, float],
    weights: Optional[dict[str, float]] = None,
    *,
    cycle_latency_target_ms: float = 300.0,
    gpu_temp_min_c: float = 30.0,
    gpu_temp_max_c: float = 80.0,
) -> float:
    """Weighted average of normalized contributions across present metrics."""
    weights = weights or {}
    weighted_sum = 0.0
    total_weight = 0.0
    for key, value in metrics.items():
        contribution = normalize_metric(
            key,
            value,
            cycle_latency_target_ms=cycle_latency_target_ms,
            gpu_temp_min_c=gpu_temp_min_c,
            gpu_temp_max_c=gpu_temp_max_c,
        )
        if contribution is None:
            continue
        weight = float(weights.get(key, 1.0))
        if weight <= 0:
            continue
        weighted_sum += weight * contribution
        total_weight += weight
    if total_weight <= 0:
        return 1.0
    return _clamp(weighted_sum / total_weight)
