# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The single persisted owner of the hearing stage.

Stage k (0..4) ends when audition's own learning progress, restarted at the
step, stays below ``lp_floor`` for ``saturation_window_seconds`` awake seconds,
once the stage has run ``min_dwell_seconds``; or when it has run
``max_dwell_seconds`` (paper A.7, Table A1). ``observe`` is the only place the
rule lives. The audio stream, the visual source, the affect module and the
maturation gate read the stage from here and never compute one.

Dwell advances only by positive deltas of the awake-time provider, so rests add
none, and it persists across restarts. The saturation window is held in memory
only and starts fresh after a restart. A missing learning-progress reading
counts as unsaturated.
"""

from __future__ import annotations

import json
import logging
import math
import threading
from pathlib import Path

from kaine.modules.audition.hearing_band import HEARING_FINAL_STAGE, HearingBandParams
from kaine.state_io import write_json_atomic

__all__ = ("HearingStageState",)

log = logging.getLogger(__name__)

_VERSION = 1
_AUTOSAVE_DWELL_SECONDS = 30.0


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


class HearingStageState:
    """Hearing stage, dwell and saturation counters, with optional persistence."""

    def __init__(
        self,
        params: HearingBandParams,
        *,
        path: Path | None = None,
        lp_floor: float = 0.20,
    ) -> None:
        if not _finite_number(lp_floor) or not (0.0 <= lp_floor < 1.0):
            raise ValueError(f"lp_floor must be a finite number in [0, 1), got {lp_floor!r}")
        self._params = params
        self._path = Path(path) if path is not None else None
        self._lp_floor = float(lp_floor)
        self._lock = threading.Lock()
        self._stage = 0
        self._dwell = 0.0
        self._saturated = 0.0
        self._last_awake: float | None = None
        self._dwell_at_save = 0.0

    @classmethod
    def load(
        cls,
        params: HearingBandParams,
        *,
        path: Path | None,
        lp_floor: float = 0.20,
    ) -> "HearingStageState":
        """Build a state from ``path``; an unreadable or invalid file starts at stage 0."""
        state = cls(params, path=path, lp_floor=lp_floor)
        if path is None:
            return state
        path = Path(path)
        if not path.exists():
            return state
        try:
            raw = json.loads(path.read_text())
            if not isinstance(raw, dict):
                raise ValueError("not an object")
            stage = raw.get("stage")
            dwell = raw.get("dwell_seconds")
            if isinstance(stage, bool) or not isinstance(stage, int):
                raise ValueError("stage is not an integer")
            if not (0 <= stage <= HEARING_FINAL_STAGE):
                raise ValueError("stage out of range")
            if not _finite_number(dwell) or dwell < 0.0:
                raise ValueError("dwell_seconds is not a non-negative number")
        except (OSError, ValueError) as exc:
            log.warning("hearing stage file %s is unusable (%s); starting at stage 0", path, exc)
            return state
        state._stage = stage
        state._dwell = float(dwell)
        state._dwell_at_save = state._dwell
        return state

    @property
    def stage(self) -> int:
        with self._lock:
            return self._stage

    @property
    def complete(self) -> bool:
        with self._lock:
            return self._stage == HEARING_FINAL_STAGE

    @property
    def dwell_seconds(self) -> float:
        with self._lock:
            return self._dwell

    @property
    def saturated_seconds(self) -> float:
        with self._lock:
            return self._saturated

    def observe(self, awake_seconds: float, lp: float | None) -> int | None:
        """Advance dwell and the saturation window; return the new stage on a step.

        The first call after construction only anchors the awake time. Returns
        None when the stage did not change.
        """
        advanced: int | None = None
        save_now = False
        with self._lock:
            awake = float(awake_seconds) if _finite_number(awake_seconds) else None
            if self._last_awake is None:
                if awake is not None:
                    self._last_awake = awake
                return None
            delta = 0.0
            if awake is not None:
                delta = max(0.0, awake - self._last_awake)
                self._last_awake = awake
            if self._stage >= HEARING_FINAL_STAGE:
                return None

            self._dwell += delta
            if _finite_number(lp) and lp < self._lp_floor:
                self._saturated += delta
            else:
                self._saturated = 0.0

            p = self._params
            if self._dwell >= p.max_dwell_seconds or (
                self._dwell >= p.min_dwell_seconds
                and self._saturated >= p.saturation_window_seconds
            ):
                self._stage += 1
                advanced = self._stage
                log.info(
                    "hearing stage %d ends at %.0f s dwell; stage %d begins",
                    advanced - 1,
                    self._dwell,
                    advanced,
                )
                self._dwell = 0.0
                self._saturated = 0.0
                save_now = True
            elif (
                self._path is not None
                and self._dwell - self._dwell_at_save >= _AUTOSAVE_DWELL_SECONDS
            ):
                save_now = True
        if save_now:
            self.save()
        return advanced

    def save(self) -> None:
        """Write the stage and dwell; a failed write is logged and never raised."""
        if self._path is None:
            return
        with self._lock:
            payload = {
                "version": _VERSION,
                "stage": self._stage,
                "dwell_seconds": self._dwell,
            }
            self._dwell_at_save = self._dwell
        try:
            write_json_atomic(self._path, payload)
        except Exception as exc:
            log.warning("could not save hearing stage to %s: %s", self._path, exc)
