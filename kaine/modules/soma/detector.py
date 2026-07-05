# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class AlertResult:
    """Alerts emitted by an AnomalyDetector for one metrics dict."""

    keys: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_alert(self) -> bool:
        return len(self.keys) > 0


@runtime_checkable
class AnomalyDetector(Protocol):
    def evaluate(self, metrics: dict[str, float]) -> AlertResult: ...


class ThresholdAnomalyDetector:
    """v1 detector: a metric > its configured threshold becomes an alert.

    Glob-style wildcard matching is supported for keys like
    `gpu_*_temp_c`, letting one threshold cover every GPU on the host.
    Missing metrics never alert; unknown thresholds are ignored.
    """

    def __init__(self, thresholds: dict[str, float]) -> None:
        if any(v is None for v in thresholds.values()):
            raise ValueError("threshold values must be numeric")
        self._thresholds = {str(k): float(v) for k, v in thresholds.items()}

    @property
    def thresholds(self) -> dict[str, float]:
        return dict(self._thresholds)

    def evaluate(self, metrics: dict[str, float]) -> AlertResult:
        alerts: list[str] = []
        for key, value in metrics.items():
            for tkey, tvalue in self._thresholds.items():
                if _key_matches(key, tkey) and value > tvalue:
                    alerts.append(key)
                    break
        return AlertResult(keys=tuple(sorted(alerts)))


def _key_matches(metric_key: str, threshold_key: str) -> bool:
    if metric_key == threshold_key:
        return True
    if "*" not in threshold_key:
        return False
    prefix, _, suffix = threshold_key.partition("*")
    return metric_key.startswith(prefix) and metric_key.endswith(suffix)
