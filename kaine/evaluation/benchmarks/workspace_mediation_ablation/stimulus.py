# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Deterministic stimulus for the workspace-mediation ablation.

Two things drive a run, both scripted (no randomness — reproducible from the
seed alone):

* **Substrate metrics per tick** for the real Soma module, via
  ``ScriptedMetricsReader``. A battery that perturbs the substrate on some ticks
  makes Soma's prediction error spike, so Soma periodically wins selection — the
  coverage the primary coupling measure needs (a run where Soma never enters the
  coalition is underpowered, not a clean NULL).

* **Extra candidate events per tick** (user-utterance-shaped) so the per-tick
  candidate count can exceed the workspace ``top_k`` and competitive selection
  actually *excludes* — otherwise the minimal set never competes and the ablation
  would test broadcast mediation + gating, not competition.

Batteries are pure functions of the tick index. ``NEUTRAL`` keeps the substrate
flat and rarely injects, tending toward NULL/underpowered; ``SOMA_SALIENT``
spikes the substrate and injects regularly, exercising both coupling and
competition; ``DECOUPLED`` spikes the substrate on a schedule uncorrelated with
the injected events (a control where competitive coupling should be weak).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from kaine.bus.schema import Event

_BASE_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)

# Metric keys Soma's feature vector reads (see soma/forward.py metrics_to_feature_vector).
_BASE_METRICS = {
    "cpu_percent": 12.0,
    "ram_percent": 30.0,
    "cycle_latency_avg_ms": 100.0,
    "gpu_0_temp_c": 45.0,
}


class ScriptedMetricsReader:
    """A ``MetricsReader`` returning caller-scripted metrics per tick.

    Implements the injectable metrics-source protocol Soma accepts (``reader=``),
    so the real Soma forward model runs against deterministic substrate readings
    with no psutil/pynvml and no wall-clock — the reproducibility keystone for the
    Soma arm.
    """

    def __init__(self, per_tick: list[dict[str, float]]) -> None:
        self._per_tick = [dict(m) for m in per_tick]
        self._i = 0

    async def initialize(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    def update_cycle_latency_sample(self, wall_duration_ms: float) -> None:
        # Latency is supplied by the script; the cycle's real sample is ignored.
        return None

    async def read_metrics(self) -> dict[str, float]:
        idx = min(self._i, len(self._per_tick) - 1) if self._per_tick else 0
        self._i += 1
        return dict(self._per_tick[idx]) if self._per_tick else dict(_BASE_METRICS)


def _utterance(seq: int, text: str, salience: float) -> Event:
    """A user-utterance-shaped candidate event (matches Volition's speak match)."""
    return Event(
        source="audition",
        type="audition.transcription",
        payload={"text": text, "seq": seq},
        salience=salience,
        timestamp=_BASE_EPOCH,
    )


@dataclass(frozen=True)
class MediationStimulus:
    """A named battery: per-tick substrate metrics + per-tick extra candidates.

    ``metrics_at(i)`` feeds Soma; ``extra_candidates_at(i)`` returns additional
    (non-Soma, non-Chronos) candidate events for tick ``i`` (utterances), used to
    push the candidate count past ``top_k`` so selection competes.
    """

    name: str
    _metrics: Callable[[int], dict[str, float]]
    _extras: Callable[[int], list[Event]]

    def metrics_series(self, n_ticks: int) -> list[dict[str, float]]:
        return [self._metrics(i) for i in range(n_ticks)]

    def extra_candidates_at(self, i: int) -> list[Event]:
        return list(self._extras(i))


def _flat_metrics(_i: int) -> dict[str, float]:
    return dict(_BASE_METRICS)


def _spiked_metrics(period: int, magnitude: float) -> Callable[[int], dict[str, float]]:
    def f(i: int) -> dict[str, float]:
        m = dict(_BASE_METRICS)
        if period > 0 and i % period == 0 and i > 0:
            # A substrate perturbation: drives Soma's prediction error up so Soma
            # becomes salient and can win selection on this tick.
            m["cpu_percent"] = _BASE_METRICS["cpu_percent"] + magnitude
            m["cycle_latency_avg_ms"] = _BASE_METRICS["cycle_latency_avg_ms"] + magnitude * 8.0
            m["gpu_0_temp_c"] = _BASE_METRICS["gpu_0_temp_c"] + magnitude * 0.4
        return m
    return f


def _regular_utterances(period: int) -> Callable[[int], list[Event]]:
    def f(i: int) -> list[Event]:
        if period > 0 and i % period == 0:
            # A short repeating utterance; salience mid-range so it competes with,
            # but does not always dominate, the predictive modules.
            return [_utterance(i, f"tick {i}: status?", 0.5)]
        return []
    return f


def _no_utterances(_i: int) -> list[Event]:
    return []


# The neutral battery: flat substrate, sparse injection. Soma stays quiet and
# competition is light — a run that should tend toward NULL / underpowered, so a
# WIN here would be meaningful.
NEUTRAL_STIMULUS = MediationStimulus(
    name="neutral",
    _metrics=_flat_metrics,
    _extras=_regular_utterances(6),
)

# The main coverage battery: substrate spikes make Soma salient on a schedule,
# and regular utterances push the candidate count past a low top_k so selection
# competes. Exercises both the coupling measure and genuine competition.
SOMA_SALIENT_STIMULUS = MediationStimulus(
    name="soma_salient",
    _metrics=_spiked_metrics(period=4, magnitude=40.0),
    _extras=_regular_utterances(2),
)

# A control where the substrate perturbation schedule is uncorrelated with the
# injected events (spikes on primes), so competitive coupling should be weak — a
# battery on which a NEGATIVE or NULL is plausible.
DECOUPLED_STIMULUS = MediationStimulus(
    name="decoupled",
    _metrics=lambda i: (
        {**_BASE_METRICS, "cpu_percent": _BASE_METRICS["cpu_percent"] + 40.0}
        if i in (2, 3, 5, 7, 11, 13)
        else dict(_BASE_METRICS)
    ),
    _extras=_regular_utterances(3),
)

STIMULUS_BY_NAME: dict[str, MediationStimulus] = {
    "neutral": NEUTRAL_STIMULUS,
    "soma_salient": SOMA_SALIENT_STIMULUS,
    "decoupled": DECOUPLED_STIMULUS,
}

__all__ = [
    "ScriptedMetricsReader",
    "MediationStimulus",
    "NEUTRAL_STIMULUS",
    "SOMA_SALIENT_STIMULUS",
    "DECOUPLED_STIMULUS",
    "STIMULUS_BY_NAME",
]
