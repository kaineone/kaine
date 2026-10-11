# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Positive control for the information-gain measures in Appendix A.8.

The paper defines per-processor broadcast information gain as
(null_error - error) / running_mean_error, where the null context replaces
other sources by their running means. This module injects a synthetic
informative component into each processor's shadow forward model so we can
verify that the gain measure detects known information and does not pass for
a non-informative component with the same marginal distribution. The live
model and both shadow probes use the live model's running mean error as the
common denominator, so a smaller shadow error cannot inflate the apparent
effect.

The control is off by default and configured only from the
[positive_control] section of a study configuration.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

import numpy as np

from kaine.bus.schema import validate_event

log = logging.getLogger(__name__)

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
    "min_reports",
    "snr",
    "detected",
    "noise_detected",
    "passed",
    "failed",
    "final",
)


@dataclass(frozen=True)
class PositiveControlSettings:
    enabled: bool = False
    min_effect: Optional[float] = None
    min_reports: Optional[int] = None
    snr: Optional[float] = None
    seed: int = 0

    @classmethod
    def from_config(cls, section: Optional[Mapping[str, Any]]) -> "PositiveControlSettings":
        if not section:
            return cls()
        allowed = {"enabled", "min_effect", "min_reports", "snr", "seed"}
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
            if not math.isfinite(min_effect) or min_effect <= 0.0:
                raise ValueError(
                    f"[positive_control].min_effect must be finite and greater than 0, got {min_effect}"
                )

        min_reports = section.get("min_reports", None)
        if min_reports is not None:
            if isinstance(min_reports, bool) or not isinstance(min_reports, int):
                raise ValueError(
                    f"[positive_control].min_reports must be an int, got {min_reports!r}"
                )
            if min_reports < 1:
                raise ValueError(
                    f"[positive_control].min_reports must be >= 1, got {min_reports}"
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

        # Fail at boot if the control is enabled but missing required thresholds.
        if enabled and snr is None:
            raise ValueError(
                "[positive_control].snr must be set when the control is enabled"
            )
        if enabled and min_effect is None:
            raise ValueError(
                "[positive_control].min_effect must be set when the control is enabled"
            )
        if enabled and min_reports is None:
            raise ValueError(
                "[positive_control].min_reports must be set when the control is enabled"
            )

        return cls(
            enabled=enabled,
            min_effect=min_effect,
            min_reports=min_reports,
            snr=snr,
            seed=int(seed),
        )


class ComponentSource:
    """The seeded synthetic context component for one processor.

    Both values scale their noise by the standard deviation of the earlier
    projections only. The informative value is the projection of the current
    input plus scaled noise. The non-informative value is the mean of previous
    projections plus scaled noise.
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

        noise = float(self._noise_rng.standard_normal(1)[0])
        if self._informative:
            return p + (prev_s / math.sqrt(self._snr)) * noise
        return prev_mean + prev_s * math.sqrt(1.0 + 1.0 / self._snr) * noise


class ShadowProbe:
    """Shadow forward model that tracks the raw error drop from one synthetic component."""

    def __init__(self, source: ComponentSource) -> None:
        self._source = source
        self._shadow: Any = None
        self._prev_context: Optional[list[float]] = None
        self._prev_null_context: Optional[list[float]] = None
        self._component_sum = 0.0
        self._component_count = 0
        # The first call only stores the baseline contexts.
        self._started = False

    def prepare(self, live_model: Any) -> None:
        """Build the shadow on the calling thread if it has not been built yet."""
        if not hasattr(live_model, "widened_copy") or not hasattr(
            live_model, "hindsight_step"
        ):
            raise TypeError("live model lacks widened_copy or hindsight_step")
        if self._shadow is None:
            self._shadow = live_model.widened_copy(1)

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

        # First call: create the shadow if still absent and record the baseline.
        if not self._started:
            if self._shadow is None:
                self._shadow = live_model.widened_copy(1)
            self._prev_context = list(context) if context is not None else None
            self._prev_null_context = (
                list(null_context) if null_context is not None else None
            )
            self._started = True
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
        # The null context must use the running mean of earlier components only.
        c_mean = (
            self._component_sum / self._component_count if self._component_count else 0.0
        )
        self._component_sum += c
        self._component_count += 1

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

        if error is None or null_error is None:
            return None

        raw = null_error - error
        if had_context and math.isfinite(raw):
            return raw
        return None


class PositiveControl:
    """Runs the positive control for one processor and reports the verdict."""

    def __init__(
        self,
        processor: str,
        settings: PositiveControlSettings,
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
        )
        self._probe_noise = ShadowProbe(
            ComponentSource(
                informative=False,
                snr=settings.snr,
                seed=settings.seed,
                processor=processor,
            ),
        )
        self._sum_with = 0.0
        self._sum_without = 0.0
        self._sum_noise = 0.0
        self._n = 0

    def prepare(self, live_model: Any) -> None:
        """Build the shadows on the calling thread.

        The modules call it on the event-loop thread before stepping the
        control in a worker thread.
        """
        if not hasattr(live_model, "widened_copy") or not hasattr(
            live_model, "hindsight_step"
        ):
            raise TypeError(
                f"live model for {self._processor} lacks widened_copy or hindsight_step"
            )
        self._probe_info.prepare(live_model)
        self._probe_noise.prepare(live_model)

    def after_report(
        self,
        live_model: Any,
        x: Sequence[float],
        context: Optional[Sequence[float]],
        null_context: Optional[Sequence[float]],
        live_gain: Optional[float],
        live_mean_error: Optional[float],
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

        d_with = self._probe_info.step(
            live_model, x, context, null_context, timespan=timespan
        )
        d_noise = self._probe_noise.step(
            live_model, x, context, null_context, timespan=timespan
        )

        if (
            awake
            and live_gain is not None
            and live_mean_error is not None
            and d_with is not None
            and d_noise is not None
            and math.isfinite(live_gain)
            and math.isfinite(live_mean_error)
            and live_mean_error > 0.0
            and math.isfinite(d_with)
            and math.isfinite(d_noise)
        ):
            self._sum_with += d_with / live_mean_error
            self._sum_without += live_gain
            self._sum_noise += d_noise / live_mean_error
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

        if (
            self._settings.min_effect is None
            or self._settings.min_reports is None
            or n == 0
        ):
            detected = noise_detected = passed = None
        else:
            detected = bool(effect >= self._settings.min_effect)
            noise_detected = bool(noise_effect >= self._settings.min_effect)
            passed = bool(
                n >= self._settings.min_reports and detected and not noise_detected
            )

        return {
            "processor": self._processor,
            "n_reports": n,
            "ig_with": ig_with,
            "ig_without": ig_without,
            "ig_noise": ig_noise,
            "effect": effect,
            "noise_effect": noise_effect,
            "min_effect": self._settings.min_effect,
            "min_reports": self._settings.min_reports,
            "snr": self._settings.snr,
            "detected": detected,
            "noise_detected": noise_detected,
            "passed": passed,
            "failed": False,
            "final": False,
        }

    def final_result(self) -> dict[str, Any]:
        """The current result marked as the run's terminal record for this processor;
        published at a clean shutdown.
        """
        result = self.result()
        result["final"] = True
        return result

    def failure_result(self) -> dict[str, Any]:
        """The current result marked as failed, so a run whose control stopped cannot pass."""
        result = self.result()
        result["failed"] = True
        result["passed"] = False
        result["final"] = True
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


async def finish_positive_controls(modules: Iterable[Any]) -> None:
    """Publish every module's positive-control terminal record.

    The cycle calls this during shutdown before it stops the research log, so
    the terminal records reach the log. A module without a control is skipped.
    """
    for module in modules:
        finish = getattr(module, "finish_positive_control", None)
        if finish is None:
            continue
        try:
            await finish()
        except Exception:
            log.error(
                "%s: finishing the positive control failed",
                getattr(module, "name", module),
                exc_info=True,
            )
