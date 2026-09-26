# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Gestation owner: readiness readout and bounded probe protocol.

This component measures a gestating entity's readiness for birth. It does not
actuate the entity, push it toward any target, or change lifecycle stage.
The probe protocol is bounded (hard maxima), disclosed via ``gestation.probe``
events, and never runs while the cycle is frozen (which covers a welfare
response, since the welfare net freezes) or in the first readout period after
boot.

Markers and their research sites:
  * ``endogenous_self_sustain`` — self-rhythm amplitude during withdrawal vs.
    the preceding driven window (Khazipov & Luhmann 2006).
  * ``entrain_then_autonomy`` — phase-locking value to the maternal beat during
    the driven window, plus self-sustain during withdrawal
    (Feldman & Eidelman 2003).
  * ``hrv_variability`` — coefficient of variation of self-rhythm wrap
    intervals (Feldman & Eidelman 2003).
  * ``womb_prediction_error`` — Topos raw prediction-error ratio across
    gestation (Ciaunica 2021).
  * ``return_to_baseline_seconds`` — Soma interoceptive surprise recovery after
    perturbation (Feldman 2012).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

from kaine.bus.schema import Event

log = logging.getLogger(__name__)

READINESS_TYPE = "gestation.readiness"
PROBE_TYPE = "gestation.probe"
SOURCE = "gestation"
WITHDRAWAL_MAX_SECONDS = 30.0
PERTURBATION_MAX_SECONDS = 10.0


@dataclass(frozen=True)
class GestationReadoutConfig:
    readout_period_seconds: float = 60.0
    sample_hz: float = 10.0
    withdrawal_period_seconds: float = 1800.0
    withdrawal_seconds: float = 20.0
    perturbation_period_seconds: float = 3600.0
    perturbation_seconds: float = 5.0
    baseline_drive_fraction: float = 0.5
    entrainment_plv_floor: float = 0.5
    hrv_window_seconds: float = 300.0
    recovery_tolerance: float = 0.25
    recovery_cap_seconds: float = 300.0

    @classmethod
    def from_dict(cls, data) -> "GestationReadoutConfig":
        if not isinstance(data, dict):
            raise ValueError("GestationReadoutConfig expects a dict")
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        extra = set(data.keys()) - allowed
        if extra:
            raise ValueError(f"Unknown keys: {sorted(extra)}")

        kwargs: dict[str, float] = {}
        for field in cls.__dataclass_fields__.values():
            name = field.name
            if name not in data:
                kwargs[name] = field.default
                continue

            value = data[name]
            if isinstance(value, bool):
                raise ValueError(f"{name} must be numeric, not bool")
            if not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite number")
            fv = float(value)
            if not math.isfinite(fv) or fv <= 0.0:
                raise ValueError(f"{name} must be finite and > 0")
            if name == "withdrawal_seconds" and fv > WITHDRAWAL_MAX_SECONDS:
                raise ValueError(
                    f"{name} must be <= {WITHDRAWAL_MAX_SECONDS}"
                )
            if name == "perturbation_seconds" and fv > PERTURBATION_MAX_SECONDS:
                raise ValueError(
                    f"{name} must be <= {PERTURBATION_MAX_SECONDS}"
                )
            if name == "baseline_drive_fraction" and not (0.0 < fv <= 1.0):
                raise ValueError(f"{name} must be in (0, 1]")
            if name == "entrainment_plv_floor" and not (0.0 < fv <= 1.0):
                raise ValueError(f"{name} must be in (0, 1]")
            kwargs[name] = fv

        return cls(**kwargs)


def phase_locking_value(phases_a, phases_b) -> float | None:
    """Mean resultant length of phase differences."""
    if len(phases_a) != len(phases_b):
        return None
    if len(phases_a) < 2:
        return None
    diffs = np.array(phases_a, dtype=float) - np.array(phases_b, dtype=float)
    return float(abs(np.mean(np.exp(1j * diffs))))


def self_sustains(driven_amplitudes, withdrawn_amplitudes) -> bool | None:
    """Whether the self-rhythm sustains after drive removal."""
    if not driven_amplitudes or not withdrawn_amplitudes:
        return None
    driven_mean = float(np.mean(driven_amplitudes))
    withdrawn_mean = float(np.mean(withdrawn_amplitudes))
    return withdrawn_mean >= 0.5 * driven_mean and withdrawn_mean > 0.0


def hrv_cv(times, phases) -> float | None:
    """Coefficient of variation of self-rhythm wrap intervals."""
    if len(times) != len(phases):
        return None
    if len(phases) < 2:
        return None
    phases_arr = np.array(phases, dtype=float)
    wraps = np.where(phases_arr[1:] - phases_arr[:-1] < -np.pi)[0] + 1
    if len(wraps) < 4:
        return None
    wrap_times = np.array(times, dtype=float)[wraps]
    intervals = np.diff(wrap_times)
    mean_interval = float(np.mean(intervals))
    if mean_interval == 0.0:
        return None
    return float(np.std(intervals, ddof=0)) / mean_interval


def recovery_seconds(
    times,
    values,
    *,
    perturbation_start: float,
    perturbation_end: float,
    tolerance: float,
    cap: float,
) -> float | None:
    """Time for interoceptive surprise to settle after a perturbation."""
    if not times or not values or len(times) != len(values):
        return None

    times_arr = np.array(times, dtype=float)
    values_arr = np.array(values, dtype=float)

    baseline_mask = (times_arr >= perturbation_start - 60.0) & (
        times_arr < perturbation_start
    )
    baseline_values = values_arr[baseline_mask]
    if len(baseline_values) == 0:
        return None
    baseline = float(np.median(baseline_values))
    if baseline <= 0.0:
        return None

    threshold = baseline * (1.0 + tolerance)
    post_indices = np.where(times_arr >= perturbation_end)[0]
    if len(post_indices) == 0:
        return None

    for idx in post_indices:
        t = float(times_arr[idx])
        # The window never reaches back before the perturbation started: for a
        # perturbation shorter than 5 s it would otherwise include baseline
        # values and report instant recovery.
        window_mask = (
            (times_arr >= max(t - 5.0, perturbation_start)) & (times_arr <= t)
        )
        window_values = values_arr[window_mask]
        if len(window_values) > 0 and float(np.median(window_values)) <= threshold:
            return float(t - perturbation_end)

    if float(times_arr[-1]) >= perturbation_end + cap:
        return float(cap)
    return None


class GestationOwner:
    def __init__(
        self,
        bus: Any,
        *,
        soma: Any,
        drive: Any,
        beat_phase: Callable[[], float],
        is_paused: Callable[[], bool],
        config: GestationReadoutConfig,
        clock: Callable[[], float],
        state_path: Path | None = None,
    ) -> None:
        self._bus = bus
        self._soma = soma
        self._drive = drive
        self._beat_phase = beat_phase
        self._is_paused = is_paused
        self._config = config
        self._clock = clock
        self._state_path = (
            state_path if state_path is not None else Path("state/lifecycle/gestation_readout.json")
        )

        self._drive.scale = self._config.baseline_drive_fraction
        self._started_at = self._clock()

        max_samples = int(
            max(
                self._config.hrv_window_seconds,
                self._config.withdrawal_seconds * 2.0,
                120.0,
            )
            * self._config.sample_hz
            * 1.5
        )
        self._samples: deque[
            tuple[float, float | None, float | None, float | None, str]
        ] = deque(maxlen=max(max_samples, 16))

        soma_maxlen = int((self._config.recovery_cap_seconds + 120.0) * 2.0)
        self._soma_series: deque[tuple[float, float]] = deque(maxlen=max(soma_maxlen, 16))

        self._next_withdrawal_at: float = (
            self._started_at + self._config.readout_period_seconds
        )
        self._next_perturbation_at: float = (
            self._started_at
            + self._config.readout_period_seconds
            + self._config.withdrawal_seconds
            + 60.0
        )
        self._next_readout_at: float = (
            self._started_at + self._config.readout_period_seconds
        )

        self._probe_state: str = "idle"
        self._probe_kind: str | None = None
        self._probe_start: float | None = None
        self._probe_end: float | None = None

        self._last_perturbation: tuple[float, float] | None = None
        self._last_soma_read_at: float = -1.0

        self._topos_cursor: str | None = None
        self._soma_cursor: str | None = None

        self._endogenous_self_sustain: bool | None = None
        self._entrain_then_autonomy: bool | None = None
        self._hrv_variability: float | None = None
        self._womb_prediction_error: float | None = None
        self._return_to_baseline_seconds: float | None = None

        self._baseline: float | None = None
        self._load_baseline()

    def _load_baseline(self) -> None:
        if not self._state_path.exists():
            return
        try:
            text = self._state_path.read_text(encoding="utf-8")
            data = json.loads(text)
            baseline = data.get("prediction_error_baseline")
            if (
                isinstance(baseline, (int, float))
                and not isinstance(baseline, bool)
                and baseline > 0.0
            ):
                self._baseline = float(baseline)
        except Exception:
            log.warning("gestation: could not load baseline", exc_info=True)

    def _persist_baseline(self) -> None:
        if self._state_path is None:
            return
        if self._baseline is None or self._baseline <= 0.0:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"prediction_error_baseline": self._baseline}),
                encoding="utf-8",
            )
            os.replace(tmp, self._state_path)
        except Exception:
            log.warning("gestation: could not persist baseline", exc_info=True)

    def _paused(self) -> bool:
        try:
            return bool(self._is_paused())
        except Exception:
            return True

    async def _ensure_cursors(self) -> None:
        if self._topos_cursor is None:
            try:
                latest = await self._bus.latest("topos.out")
                self._topos_cursor = latest[0] if latest else "0"
            except Exception:
                log.warning("gestation: failed to initialise topos cursor", exc_info=True)
                self._topos_cursor = "0"
        if self._soma_cursor is None:
            try:
                latest = await self._bus.latest("soma.out")
                self._soma_cursor = latest[0] if latest else "0"
            except Exception:
                log.warning("gestation: failed to initialise soma cursor", exc_info=True)
                self._soma_cursor = "0"

    async def step(self) -> None:
        await self._ensure_cursors()
        now = self._clock()
        paused = self._paused()

        if paused and self._probe_state != "idle":
            await self._abort_probe(now)
        elif not paused:
            await self._handle_probes(now)

        self._sample(now)
        await self._read_soma_reports(now)

        if now >= self._next_readout_at:
            await self._do_readout(now)
            self._next_readout_at += self._config.readout_period_seconds

    async def run(self, stop_event: asyncio.Event) -> None:
        try:
            while not stop_event.is_set():
                try:
                    await self.step()
                except Exception:
                    log.warning("gestation: step failed, continuing", exc_info=True)
                try:
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=1.0 / self._config.sample_hz,
                    )
                except TimeoutError:
                    pass
        finally:
            if self._probe_state != "idle":
                try:
                    self._drive.scale = self._config.baseline_drive_fraction
                except Exception:
                    log.warning("gestation: failed to restore drive on exit", exc_info=True)

    def _sample(self, now: float) -> None:
        phase: float | None = None
        amplitude: float | None = None
        try:
            state = self._soma.self_rhythm_state()
            if state is not None:
                phase = float(state[0])
                amplitude = float(state[1])
        except Exception:
            pass

        beat: float | None = None
        try:
            beat = float(self._beat_phase())
        except Exception:
            pass

        self._samples.append((now, phase, amplitude, beat, self._probe_state))

    async def _handle_probes(self, now: float) -> None:
        if self._probe_state != "idle":
            if now >= (self._probe_end or now):
                await self._end_probe(now)
            return

        if now < self._started_at + self._config.readout_period_seconds:
            return

        if now >= self._next_withdrawal_at:
            await self._start_probe(now, "withdrawal")
        elif now >= self._next_perturbation_at:
            await self._start_probe(now, "perturbation")

    async def _start_probe(self, now: float, kind: str) -> None:
        if kind == "withdrawal":
            seconds = min(self._config.withdrawal_seconds, WITHDRAWAL_MAX_SECONDS)
            self._drive.scale = 0.0
            self._next_withdrawal_at += self._config.withdrawal_period_seconds
        else:
            seconds = min(self._config.perturbation_seconds, PERTURBATION_MAX_SECONDS)
            self._drive.scale = 1.0
            self._next_perturbation_at += self._config.perturbation_period_seconds

        self._probe_state = kind
        self._probe_kind = kind
        self._probe_start = now
        self._probe_end = now + seconds
        await self._publish_probe_event(kind, "start", seconds)

    async def _end_probe(self, now: float) -> None:
        kind = self._probe_kind
        start = self._probe_start
        end = self._probe_end
        seconds = (end - start) if start is not None and end is not None else 0.0

        self._drive.scale = self._config.baseline_drive_fraction
        await self._publish_probe_event(kind, "end", seconds, aborted=False)

        self._probe_state = "idle"
        self._probe_kind = None
        self._probe_start = None
        self._probe_end = None

        if kind == "withdrawal" and start is not None and end is not None:
            await self._compute_withdrawal_markers(start, end)
        elif kind == "perturbation" and start is not None and end is not None:
            self._last_perturbation = (start, end)

    async def _abort_probe(self, now: float) -> None:
        if self._probe_state == "idle":
            return
        kind = self._probe_kind
        start = self._probe_start
        seconds = (now - start) if start is not None else 0.0

        self._drive.scale = self._config.baseline_drive_fraction
        await self._publish_probe_event(kind, "end", seconds, aborted=True)

        self._probe_state = "idle"
        self._probe_kind = None
        self._probe_start = None
        self._probe_end = None

    async def _publish_probe_event(
        self,
        kind: str,
        phase: str,
        seconds: float,
        aborted: bool | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "kind": kind,
            "phase": phase,
            "seconds": float(seconds),
        }
        if aborted is not None:
            payload["aborted"] = bool(aborted)
        event = Event(
            source=SOURCE,
            type=PROBE_TYPE,
            payload=payload,
            salience=0.05,
            timestamp=datetime.now(timezone.utc),
        )
        try:
            await self._bus.publish(event)
        except Exception:
            log.warning("gestation: failed to publish probe event", exc_info=True)

    async def _compute_withdrawal_markers(self, start: float, end: float) -> None:
        duration = end - start
        driven = [
            s for s in self._samples if start - duration <= s[0] < start
        ]
        withdrawn = [s for s in self._samples if start <= s[0] <= end]

        driven_amps = [s[2] for s in driven if s[2] is not None]
        withdrawn_amps = [s[2] for s in withdrawn if s[2] is not None]
        self._endogenous_self_sustain = self_sustains(driven_amps, withdrawn_amps)

        driven_phases = [s[1] for s in driven if s[1] is not None]
        driven_beats = [s[3] for s in driven if s[3] is not None]
        plv = phase_locking_value(driven_phases, driven_beats)
        if (
            plv is not None
            and self._endogenous_self_sustain is not None
        ):
            self._entrain_then_autonomy = (
                plv >= self._config.entrainment_plv_floor
                and self._endogenous_self_sustain
            )
        else:
            self._entrain_then_autonomy = None

    async def _read_soma_reports(self, now: float) -> None:
        if now - self._last_soma_read_at < 1.0:
            return
        self._last_soma_read_at = now

        if self._soma_cursor is None:
            return

        try:
            entries = await self._bus.read(
                "soma.out", last_id=self._soma_cursor, count=1000
            )
            for entry_id, event in entries:
                self._soma_cursor = entry_id
                if event.type != "soma.report":
                    continue
                err = (
                    event.payload.get("prediction_error")
                    if isinstance(event.payload, dict)
                    else None
                )
                if (
                    isinstance(err, (int, float))
                    and not isinstance(err, bool)
                    and math.isfinite(err)
                ):
                    self._soma_series.append((now, float(err)))
        except Exception:
            log.warning("gestation: failed to read soma reports", exc_info=True)

        cutoff = now - (self._config.recovery_cap_seconds + 120.0)
        while self._soma_series and self._soma_series[0][0] < cutoff:
            self._soma_series.popleft()

    async def _read_topos_errors(self) -> list[float]:
        if self._topos_cursor is None:
            return []
        try:
            entries = await self._bus.read(
                "topos.out", last_id=self._topos_cursor, count=1000
            )
        except Exception:
            log.warning("gestation: failed to read topos reports", exc_info=True)
            return []

        errors: list[float] = []
        for entry_id, event in entries:
            self._topos_cursor = entry_id
            if event.type != "topos.report":
                continue
            err = (
                event.payload.get("prediction_error")
                if isinstance(event.payload, dict)
                else None
            )
            if (
                isinstance(err, (int, float))
                and not isinstance(err, bool)
                and math.isfinite(err)
            ):
                errors.append(float(err))
        return errors

    async def _do_readout(self, now: float) -> None:
        hrv_cutoff = now - self._config.hrv_window_seconds
        hrv_times = []
        hrv_phases = []
        for t, phase, _amp, _beat, _state in self._samples:
            if t >= hrv_cutoff and phase is not None:
                hrv_times.append(t)
                hrv_phases.append(phase)
        self._hrv_variability = hrv_cv(hrv_times, hrv_phases)

        current_errors = await self._read_topos_errors()
        ratio: float | None = None
        if current_errors:
            median_current = float(np.median(current_errors))
            if self._baseline is None and len(current_errors) >= 3:
                self._baseline = median_current
                self._persist_baseline()
            if self._baseline is not None and self._baseline > 0.0:
                ratio = median_current / self._baseline
        self._womb_prediction_error = ratio

        recovery: float | None = None
        if self._last_perturbation is not None:
            pert_start, pert_end = self._last_perturbation
            recovery = recovery_seconds(
                [s[0] for s in self._soma_series],
                [s[1] for s in self._soma_series],
                perturbation_start=pert_start,
                perturbation_end=pert_end,
                tolerance=self._config.recovery_tolerance,
                cap=self._config.recovery_cap_seconds,
            )
        self._return_to_baseline_seconds = recovery

        await self._publish_readout(now)

    async def _publish_readout(self, now: float) -> None:
        payload = {"readout": self.readout()}
        event = Event(
            source=SOURCE,
            type=READINESS_TYPE,
            payload=payload,
            salience=0.05,
            timestamp=datetime.now(timezone.utc),
        )
        try:
            await self._bus.publish(event)
        except Exception:
            log.warning("gestation: failed to publish readiness", exc_info=True)

    def readout(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self._endogenous_self_sustain is not None:
            result["endogenous_self_sustain"] = self._endogenous_self_sustain
        if self._entrain_then_autonomy is not None:
            result["entrain_then_autonomy"] = self._entrain_then_autonomy
        if self._hrv_variability is not None:
            result["hrv_variability"] = self._hrv_variability
        if self._womb_prediction_error is not None:
            result["womb_prediction_error"] = self._womb_prediction_error
        if self._return_to_baseline_seconds is not None:
            result["return_to_baseline_seconds"] = self._return_to_baseline_seconds
        return result
