# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Seeded, deterministic stimulus for the workspace-mediation development harness.

The stimulus drives Soma with scripted metrics and Topos with scripted frame
vectors. It also emits background candidate events each tick so the candidate
count exceeds the workspace capacity and selection must exclude.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from kaine.bus.schema import Event

_BASE_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)

# Metric keys Interoception's feature vector reads (see soma/forward.py metrics_to_feature_vector).
_BASE_METRICS = {
    "cpu_percent": 12.0,
    "ram_percent": 30.0,
    "cycle_latency_avg_ms": 100.0,
    "gpu_0_temp_c": 45.0,
}


class ScriptedMetricsReader:
    """A ``MetricsReader`` returning caller-scripted metrics per tick.

    Implements the injectable metrics-source protocol Interoception accepts (``reader=``),
    so the real Interoception forward model runs against deterministic substrate readings
    with no psutil/pynvml and no wall-clock — the reproducibility keystone for the
    Interoception arm.
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


LATENT_DIM: int = 8


class VectorEncoder:
    """A per-frame vector encoder for the harness.

    The frame is its own latent, so encode is the identity cast to float.
    Implements the Vision Encoder protocol with ``clip_len == 1``.
    """

    model_id = "harness/vector-encoder"
    clip_len = 1

    def __init__(self, latent_dim: int = LATENT_DIM) -> None:
        self._latent_dim = latent_dim

    @property
    def latent_dim(self) -> int:
        return self._latent_dim

    async def load(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def encode(self, image: Any) -> list[float]:
        return [float(v) for v in image]

    async def encode_clip(self, frames: Any) -> list[float]:
        return await self.encode(frames[-1])


# A report at tick t-1 enters the context adopted at the end of tick t-1, which
# conditions the prediction of input t+1. This lag-2 relation is the cross-module
# signal the information-gain measure is meant to capture.
LAG: int = 2


@dataclass(frozen=True)
class StimulusScript:
    """Deterministic per-tick inputs for the two measured processors.

    ``soma_metrics`` is one metric dict per tick. ``topos_frames`` is one frame
    vector per tick. ``background`` is one list of stand-in candidate events
    per tick.
    """

    soma_metrics: list[dict[str, float]]
    topos_frames: list[list[float]]
    background: list[list[Event]]


@dataclass(frozen=True)
class MediationStimulus:
    """A named stimulus battery with optional cross-module coupling.

    ``script`` is a pure function of its arguments: the same seed, ticks, and
    background count always produce the same ``StimulusScript``.
    """

    name: str
    coupled: bool
    event_rate: float = 0.15
    n_scenes: int = 3
    frame_noise: float = 0.02

    def script(
        self, seed: int, ticks: int, *, n_background: int = 2
    ) -> StimulusScript:
        """Generate the deterministic stimulus script."""
        if ticks <= 0:
            raise ValueError(f"ticks must be positive, got {ticks}")
        if n_background < 0:
            raise ValueError(f"n_background must be >= 0, got {n_background}")

        soma_rng = random.Random(f"{seed}:{self.name}:soma")
        topos_rng = random.Random(f"{seed}:{self.name}:topos")
        scenes_rng = random.Random(f"{seed}:{self.name}:scenes")
        background_rng = random.Random(f"{seed}:{self.name}:background")

        soma_led = [soma_rng.random() < self.event_rate for _ in range(ticks)]
        topos_led = [topos_rng.random() < self.event_rate for _ in range(ticks)]

        scenes = [
            [scenes_rng.gauss(0.0, 1.0) for _ in range(LATENT_DIM)]
            for _ in range(self.n_scenes)
        ]

        soma_metrics: list[dict[str, float]] = []
        topos_frames: list[list[float]] = []
        background: list[list[Event]] = []

        scene_idx = 0
        for t in range(ticks):
            # Jitter the base substrate, then add a spike on spike ticks.
            m = dict(_BASE_METRICS)
            m["cpu_percent"] += soma_rng.uniform(-1.0, 1.0)
            spike = False
            if self.coupled:
                if soma_led[t] or (t >= LAG and topos_led[t - LAG]):
                    spike = True
            elif soma_led[t]:
                spike = True
            if spike:
                m["cpu_percent"] += 40.0
                m["cycle_latency_avg_ms"] += 40.0 * 8.0
                m["gpu_0_temp_c"] += 40.0 * 0.4
            soma_metrics.append(m)

            # Advance the scene on cut ticks; add per-component sensor noise.
            cut = False
            if self.coupled:
                if topos_led[t] or (t >= LAG and soma_led[t - LAG]):
                    cut = True
            elif topos_led[t]:
                cut = True
            if cut:
                scene_idx = (scene_idx + 1) % self.n_scenes
            frame = [v + topos_rng.gauss(0.0, self.frame_noise) for v in scenes[scene_idx]]
            topos_frames.append(frame)

            # Background candidates stand in for the other base-thesis candidates.
            # They carry no information about either processor's input.
            tick_bg = [
                Event(
                    source="chronos",
                    type="chronos.report",
                    payload={"harness": "background"},
                    salience=background_rng.uniform(0.05, 0.5),
                    timestamp=_BASE_EPOCH,
                )
                for _ in range(n_background)
            ]
            background.append(tick_bg)

        return StimulusScript(
            soma_metrics=soma_metrics,
            topos_frames=topos_frames,
            background=background,
        )


COUPLED_STIMULUS = MediationStimulus(
    name="coupled",
    coupled=True,
)

INDEPENDENT_STIMULUS = MediationStimulus(
    name="independent",
    coupled=False,
)

STIMULUS_BY_NAME = {
    s.name: s for s in (COUPLED_STIMULUS, INDEPENDENT_STIMULUS)
}

__all__ = [
    "ScriptedMetricsReader",
    "LATENT_DIM",
    "VectorEncoder",
    "LAG",
    "StimulusScript",
    "MediationStimulus",
    "COUPLED_STIMULUS",
    "INDEPENDENT_STIMULUS",
    "STIMULUS_BY_NAME",
]
