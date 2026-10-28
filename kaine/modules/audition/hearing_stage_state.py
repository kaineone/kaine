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

The file carries the owning entity's id. A later entity adopts it only when the
id is its own or one of its lineage ancestors, so a fork carries its parent's
stage and a stranger's file is ignored.
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
        entity_id: str | None = None,
        lineage: tuple[str, ...] = (),
    ) -> None:
        if not _finite_number(lp_floor) or not (0.0 <= lp_floor < 1.0):
            raise ValueError(f"lp_floor must be a finite number in [0, 1), got {lp_floor!r}")
        self._params = params
        self._path = Path(path) if path is not None else None
        self._lp_floor = float(lp_floor)
        self._entity_id = entity_id
        self._lineage = tuple(lineage)
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
        entity_id: str | None = None,
        lineage: tuple[str, ...] = (),
    ) -> "HearingStageState":
        """Build a state from ``path``.

        The file is adopted only when it belongs to this entity or to one of its
        ancestors. A foreign, unkeyed or unreadable file starts the state at
        stage 0 and the next save replaces it.
        """
        state = cls(
            params,
            path=path,
            lp_floor=lp_floor,
            entity_id=entity_id,
            lineage=lineage,
        )
        state.reload()
        return state

    def reload(self) -> bool:
        """Re-read the file under the adoption rule; return True when it was adopted.

        A revive restores the file after the owner is built, so the boot calls
        this once the revive has landed. Without an adoptable file the state
        returns to stage 0 and dwell 0.
        """
        path = self._path
        adopted = self._read_adoptable(path) if path is not None and path.exists() else None
        with self._lock:
            self._saturated = 0.0
            self._last_awake = None
            if adopted is None:
                self._stage = 0
                self._dwell = 0.0
            else:
                self._stage, self._dwell = adopted
            self._dwell_at_save = self._dwell
        return adopted is not None

    def _read_adoptable(self, path: Path) -> tuple[int, float] | None:
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
            owner = raw.get("entity_id")
            if owner is not None and not isinstance(owner, str):
                raise ValueError("entity_id is not a string")
        except (OSError, ValueError) as exc:
            log.warning("hearing stage file %s is unusable (%s); starting at stage 0", path, exc)
            return None
        if self._entity_id is None:
            if owner is not None:
                log.warning(
                    "hearing stage file %s belongs to entity %s and this owner has no entity id; starting at stage 0",
                    path,
                    owner,
                )
                return None
        elif owner is None:
            log.warning("hearing stage file %s has no entity id; starting at stage 0", path)
            return None
        elif owner != self._entity_id and owner not in self._lineage:
            log.warning(
                "hearing stage file %s belongs to entity %s, which is neither %s nor an ancestor; starting at stage 0",
                path,
                owner,
                self._entity_id,
            )
            return None
        return stage, float(dwell)

    @property
    def params(self) -> HearingBandParams:
        return self._params

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
                "entity_id": self._entity_id,
                "stage": self._stage,
                "dwell_seconds": self._dwell,
            }
            self._dwell_at_save = self._dwell
        try:
            write_json_atomic(self._path, payload)
        except Exception as exc:
            log.warning("could not save hearing stage to %s: %s", self._path, exc)
