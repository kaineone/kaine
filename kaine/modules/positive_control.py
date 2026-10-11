# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Positive control for the information-gain measures in Appendix A.8.

The paper defines per-processor broadcast information gain as
(null_error - error) / running_mean_error, where the null context replaces
other sources by their running means. This module injects a synthetic
informative component into each processor's shadow forward model so we can
verify that the gain measure detects known information and does not pass for
a non-informative component with the same marginal distribution.

The control is off by default and configured only from the
[positive_control] section of a study configuration.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

import numpy as np

from kaine.bus.schema import validate_event

PROCESSORS: tuple[str, ...] = ("topos", "audition", "soma")
POSITIVE_CONTROL_SOURCE: str = "positive_control"
RESULT_EVENT_TYPE: str = "positive_control.result"
RESULT_FIELDS: tuple[str, ...] = (
    "processor",
    "n_reports",
    "ig_with",
    "ig_without",
    "ig_noise",
    "effect",
    "noise_effect",
    "min_effect",
    "snr",
    "detected",
    "noise_detected",
    "passed",
    "failed",
)


@dataclass(frozen=True)
class PositiveControlSettings:
    enabled: bool = False
    min_effect: Optional[float] = None
    snr: Optional[float] = None
    seed: int = 0

    @classmethod
    def from_config(cls, section: Optional[Mapping[str, Any]]) -> "PositiveControlSettings":
        if not section:
            return cls()
        allowed = {"enabled", "min_effect", "snr", "seed"}
        unknown = set(section) - allowed
        if unknown:
            raise ValueError(f"unknown keys in [positive_control]: {sorted(unknown)}")

        enabled = section.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError(
                f"[positive_control].enabled must be a bool, got {enabled!r}"
            )

        min_effect = section.get("min_effect", None)
        if min_effect is not None:
            if isinstance(min_effect, bool) or not isinstance(min_effect, (int, float)):
                raise ValueError(
                    f"[positive_control].min_effect must be a number, got {min_effect!r}"
                )
            min_effect = float(min_effect)
            if not math.isfinite(min_effect) or min_effect < 0:
                raise ValueError(
                    f"[positive_control].min_effect must be finite and non-negative, got {min_effect}"
                )

        snr = section.get("snr", None)
        if snr is not None:
            if isinstance(snr, bool) or not isinstance(snr, (int, float)):
                raise ValueError(
                    f"[positive_control].snr must be a number, got {snr!r}"
                )
            snr = float(snr)
            if not math.isfinite(snr) or snr <= 0:
                raise ValueError(
                    f"[positive_control].snr must be finite and positive, got {snr}"
                )

        seed = section.get("seed", 0)
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError(f"[positive_control].seed must be an int, got {seed!r}")

        if enabled and snr is None:
            raise ValueError(
                "[positive_control].snr must be set when the control is enabled"
            )

        return cls(enabled=enabled, min_effect=min_effect, snr=snr, seed=int(seed))


class ComponentSource:
    """A source that either copies the input projection or replaces it.

    The informative value is the projection of the current input plus scaled
    noise. The non-informative value is the mean of previous projections plus
    scaled noise; it uses only the statistics gathered before the current input.
    """

    def __init__(self, *, informative: bool, snr: float, seed: int, processor: str) -> None:
        if processor not in PROCESSORS:
            raise ValueError(
                f"processor must be one of {PROCESSORS}, got {processor}"
            )
        idx = PROCESSORS.index(processor)
        self._informative = bool(informative)
        self._snr = float(snr)
        self._processor = processor
        # Independent seeded streams: 0 for the direction, 1 and 2 for the two noises.
        self._dir_rng = np.random.default_rng([seed, idx, 0])
        self._noise_rng = np.random.default_rng([seed, idx, 1 if informative else 2])
        self._u: Optional[np.ndarray] = None
        self._dim: Optional[int] = None
        self._count = 0
        self._mean = 0.0
        self._m2 = 0.0

    def next(self, x: Sequence[float]) -> float:
        arr = np.asarray(x, dtype=float)
        if arr.ndim != 1:
            raise ValueError("input must be one-dimensional")
        if self._dim is None:
            self._dim = arr.shape[0]
            raw = self._dir_rng.standard_normal(self._dim)
            norm = float(np.linalg.norm(raw))
            if norm == 0.0:
                raise ValueError("random direction collapsed to zero")
            self._u = raw / norm
        elif arr.shape[0] != self._dim:
            raise ValueError(
                f"input length changed from {self._dim} to {arr.shape[0]}"
            )

        p = float(self._u @ arr)
        prev_mean = self._mean
        prev_s = math.sqrt(self._m2 / (self._count - 1)) if self._count >= 2 else 0.0
        self._count += 1
        delta = p - self._mean
        self._mean += delta / self._count
        delta2 = p - self._mean
        self._m2 += delta * delta2
        s = math.sqrt(self._m2 / (self._count - 1)) if self._count >= 2 else 0.0

        noise = float(self._noise_rng.standard_normal(1)[0])
        if self._informative:
            return p + (s / math.sqrt(self._snr)) * noise
        return prev_mean + prev_s * math.sqrt(1.0 + 1.0 / self._snr) * noise


class ShadowProbe:
    def __init__(self, source: ComponentSource, *, window: int) -> None:
        self._source = source
        self._window = int(window)
        self._shadow: Any = None
        self._prev_context: Optional[list[float]] = None
        self._prev_null_context: Optional[list[float]] = None
        self._component_sum = 0.0
        self._component_count = 0
        self._errors: deque[float] = deque(maxlen=self._window)

    def step(
        self,
        live_model: Any,
        x: Sequence[float],
        context: Optional[Sequence[float]],
        null_context: Optional[Sequence[float]],
        *,
        timespan: Optional[float] = None,
    ) -> Optional[float]:
        if not hasattr(live_model, "widened_copy") or not hasattr(
            live_model, "hindsight_step"
        ):
            raise TypeError("live model lacks widened_copy or hindsight_step")

        if self._shadow is None:
            self._shadow = live_model.widened_copy(1)
            self._prev_context = list(context) if context is not None else None
            self._prev_null_context = (
                list(null_context) if null_context is not None else None
            )
            return None

        full_width = getattr(self._shadow, "context_dim", None)
        if full_width is None:
            full_width = getattr(self._shadow, "_context_dim")
        width = int(full_width) - 1

        self._shadow.suspended = bool(getattr(live_model, "suspended", False))

        prev = self._prev_context if self._prev_context is not None else [0.0] * width
        prev_null = self._prev_null_context
        x_list = list(x)

        kwargs: dict[str, Any] = {}
        if timespan is not None:
            kwargs["timespan"] = timespan

        if any(not math.isfinite(v) for v in x_list):
            self._shadow.hindsight_step(x_list, prev + [0.0], None, **kwargs)
            self._prev_context = list(context) if context is not None else None
            self._prev_null_context = (
                list(null_context) if null_context is not None else None
            )
            return None

        c = self._source.next(x_list)
        self._component_sum += c
        self._component_count += 1
        c_mean = self._component_sum / self._component_count

        ctx = prev + [c]
        null_ctx = (prev_null + [c_mean]) if prev_null is not None else None
        error, null_error = self._shadow.hindsight_step(
            x_list, ctx, null_ctx, **kwargs
        )

        had_context = self._prev_context is not None
        self._prev_context = list(context) if context is not None else None
        self._prev_null_context = (
            list(null_context) if null_context is not None else None
        )

        if error is None:
            return None

        self._errors.append(float(error))
        mean_error = sum(self._errors) / len(self._errors)
        if mean_error <= 0.0:
            return None
        if had_context and null_error is not None:
            return (null_error - error) / mean_error
        return None


class PositiveControl:
    def __init__(
        self,
        processor: str,
        settings: PositiveControlSettings,
        *,
        window: int = 32,
    ) -> None:
        if processor not in PROCESSORS:
            raise ValueError(
                f"processor must be one of {PROCESSORS}, got {processor}"
            )
        if not settings.enabled:
            raise ValueError("positive control is disabled in [positive_control]")
        if settings.snr is None:
            raise ValueError(
                "[positive_control].snr must be set when the control is enabled"
            )

        self._processor = processor
        self._settings = settings
        self._probe_info = ShadowProbe(
            ComponentSource(
                informative=True,
                snr=settings.snr,
                seed=settings.seed,
                processor=processor,
            ),
            window=window,
        )
        self._probe_noise = ShadowProbe(
            ComponentSource(
                informative=False,
                snr=settings.snr,
                seed=settings.seed,
                processor=processor,
            ),
            window=window,
        )
        self._sum_with = 0.0
        self._sum_without = 0.0
        self._sum_noise = 0.0
        self._n = 0

    def after_report(
        self,
        live_model: Any,
        x: Sequence[float],
        context: Optional[Sequence[float]],
        null_context: Optional[Sequence[float]],
        live_gain: Optional[float],
        *,
        awake: bool,
        timespan: Optional[float] = None,
    ) -> Optional[dict[str, Any]]:
        if not hasattr(live_model, "widened_copy") or not hasattr(
            live_model, "hindsight_step"
        ):
            raise TypeError(
                f"live model for {self._processor} lacks widened_copy or hindsight_step"
            )

        g_with = self._probe_info.step(
            live_model, x, context, null_context, timespan=timespan
        )
        g_noise = self._probe_noise.step(
            live_model, x, context, null_context, timespan=timespan
        )

        if (
            awake
            and live_gain is not None
            and g_with is not None
            and g_noise is not None
        ):
            self._sum_with += g_with
            self._sum_without += live_gain
            self._sum_noise += g_noise
            self._n += 1
            return self.result()
        return None

    def result(self) -> dict[str, Any]:
        n = self._n
        ig_with = self._sum_with / n if n else None
        ig_without = self._sum_without / n if n else None
        ig_noise = self._sum_noise / n if n else None
        effect = (ig_with - ig_without) if n else None
        noise_effect = (ig_noise - ig_without) if n else None

        if self._settings.min_effect is None or n == 0:
            detected = noise_detected = passed = None
        else:
            detected = bool(effect >= self._settings.min_effect)
            noise_detected = bool(noise_effect >= self._settings.min_effect)
            passed = detected and not noise_detected

        return {
            "processor": self._processor,
            "n_reports": n,
            "ig_with": ig_with,
            "ig_without": ig_without,
            "ig_noise": ig_noise,
            "effect": effect,
            "noise_effect": noise_effect,
            "min_effect": self._settings.min_effect,
            "snr": self._settings.snr,
            "detected": detected,
            "noise_detected": noise_detected,
            "passed": passed,
            "failed": False,
        }

    def failure_result(self) -> dict[str, Any]:
        """The current result marked as failed, so a run whose control stopped cannot pass."""
        result = self.result()
        result["failed"] = True
        result["passed"] = False
        return result


async def publish_result(bus: Any, result: Mapping[str, Any]) -> str:
    event = validate_event(
        source=POSITIVE_CONTROL_SOURCE,
        type=RESULT_EVENT_TYPE,
        payload=dict(result),
        salience=0.0,
        timestamp=datetime.now(timezone.utc),
    )
    return await bus.publish(event)
