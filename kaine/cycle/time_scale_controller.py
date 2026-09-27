# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = ["TimeScaleSettings", "ScaleChange", "TimeScaleController"]


@dataclass(frozen=True)
class TimeScaleSettings:
    ceiling: float
    floor: float = 0.1
    target: float = 0.85
    high: float = 0.95
    low: float = 0.6
    dwell_s: float = 10.0
    window_s: float = 30.0
    max_up_factor: float = 1.25

    def __post_init__(self) -> None:
        if not math.isfinite(self.ceiling) or self.ceiling <= 0:
            raise ValueError(f"ceiling must be a positive finite number, got {self.ceiling!r}")
        if not math.isfinite(self.floor) or self.floor <= 0:
            raise ValueError(f"floor must be a positive finite number, got {self.floor!r}")
        if self.floor > self.ceiling:
            raise ValueError(f"floor ({self.floor}) must be <= ceiling ({self.ceiling})")
        if not math.isfinite(self.target) or self.target <= 0:
            raise ValueError(f"target must be a positive finite number, got {self.target!r}")
        if not math.isfinite(self.high) or self.high <= 0:
            raise ValueError(f"high must be a positive finite number, got {self.high!r}")
        if not math.isfinite(self.low) or self.low <= 0:
            raise ValueError(f"low must be a positive finite number, got {self.low!r}")
        if not (self.low < self.target < self.high):
            raise ValueError(
                f"require low ({self.low}) < target ({self.target}) < high ({self.high})"
            )
        if not math.isfinite(self.dwell_s) or self.dwell_s <= 0:
            raise ValueError(f"dwell_s must be a positive finite number, got {self.dwell_s!r}")
        if not math.isfinite(self.window_s) or self.window_s <= 0:
            raise ValueError(f"window_s must be a positive finite number, got {self.window_s!r}")
        if not math.isfinite(self.max_up_factor) or self.max_up_factor <= 1:
            raise ValueError(
                f"max_up_factor must be a finite number greater than 1, got {self.max_up_factor!r}"
            )


@dataclass(frozen=True)
class ScaleChange:
    old: float
    new: float
    reason: str
    utilization: float


class TimeScaleController:
    def __init__(self, settings: TimeScaleSettings, *, initial_scale: float) -> None:
        if not math.isfinite(initial_scale):
            raise ValueError(f"initial_scale must be finite, got {initial_scale!r}")
        self._settings = settings
        self._initial_scale = float(initial_scale)
        self._ema: float | None = None
        self._last_sample_time: float | None = None
        self._overload_since: float | None = None
        self._headroom_since: float | None = None
        self._last_change_time: float = -math.inf

    @property
    def settings(self) -> TimeScaleSettings:
        return self._settings

    @property
    def utilization(self) -> float | None:
        return self._ema

    def observe(
        self,
        busy_ms: float,
        period_ms: float,
        now_wall_s: float,
        *,
        current_scale: float,
    ) -> ScaleChange | None:
        # Reject invalid / frozen inputs without mutating state.
        if (
            not math.isfinite(busy_ms)
            or not math.isfinite(period_ms)
            or not math.isfinite(now_wall_s)
            or not math.isfinite(current_scale)
            or period_ms <= 0
            or busy_ms < 0
            or current_scale <= 0
        ):
            return None

        u = busy_ms / period_ms

        if self._ema is None:
            self._ema = u
        else:
            dt = now_wall_s - self._last_sample_time
            if dt < 0:
                dt = 0.0
            alpha = 1.0 - math.exp(-dt / self._settings.window_s)
            self._ema += alpha * (u - self._ema)

        self._last_sample_time = now_wall_s
        ema = self._ema

        # Track continuous time above/below the control thresholds.
        if ema > self._settings.high:
            if self._overload_since is None:
                self._overload_since = now_wall_s
        else:
            self._overload_since = None

        if ema < self._settings.low:
            if self._headroom_since is None:
                self._headroom_since = now_wall_s
        else:
            self._headroom_since = None

        # Dwell separation since the last applied change.
        if now_wall_s - self._last_change_time < self._settings.dwell_s:
            return None

        # Overload: scale down to the target utilization.
        if self._overload_since is not None:
            if now_wall_s - self._overload_since >= self._settings.dwell_s:
                s_star = current_scale * self._settings.target / ema
                if s_star < self._settings.floor:
                    s_star = self._settings.floor
                elif s_star > self._settings.ceiling:
                    s_star = self._settings.ceiling
                if s_star < current_scale - 1e-9:
                    return self._apply_change(s_star, current_scale, "overload", now_wall_s, ema)

        # Headroom: scale up, slowly and bounded by the ceiling.
        if self._headroom_since is not None:
            if now_wall_s - self._headroom_since >= 3.0 * self._settings.dwell_s:
                if ema == 0.0:
                    s_star = math.inf
                else:
                    s_star = current_scale * self._settings.target / ema
                new = min(
                    current_scale * self._settings.max_up_factor,
                    s_star,
                    self._settings.ceiling,
                )
                if new > current_scale + 1e-9:
                    return self._apply_change(new, current_scale, "headroom", now_wall_s, ema)

        return None

    def _apply_change(
        self,
        new_scale: float,
        old_scale: float,
        reason: str,
        now_wall_s: float,
        utilization: float,
    ) -> ScaleChange:
        if new_scale < self._settings.floor:
            new_scale = self._settings.floor
        elif new_scale > self._settings.ceiling:
            new_scale = self._settings.ceiling

        self._last_change_time = now_wall_s
        self._overload_since = None
        self._headroom_since = None

        # Utilization is proportional to the time scale; rescale the EMA so we
        # do not over-react before fresh samples arrive.
        if self._ema is not None and old_scale != 0.0:
            self._ema = self._ema * new_scale / old_scale

        return ScaleChange(
            old=old_scale,
            new=new_scale,
            reason=reason,
            utilization=utilization,
        )
