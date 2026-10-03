# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Gestation owner: readiness readout and bounded probe protocol.

This component measures a gestating entity's readiness for birth. It does not
actuate the entity, push it toward any target, or change lifecycle stage.
The probe protocol is bounded (hard maxima), disclosed via ``gestation.probe``
events, and never runs while the cycle is frozen (which covers a welfare
response, since the welfare net freezes) or in the first readout period after
boot. The schedule is intentionally jittered and the perturbation is a bounded
rise, so an exactly periodic probe cannot be learned by a predictive mind and
thereby shape what it measures.

Markers and their research sites:
  * ``endogenous_self_sustain`` — self-rhythm amplitude during withdrawal vs.
    the preceding driven window (Khazipov & Luhmann 2006).
  * ``entrain_then_autonomy`` — band-limited PLV between the self-rhythm's
    generator activity and the maternal beat during the driven window,
    relative to surrogate maternal beats from other mothers, and frequency
    pull of the withdrawn self-rhythm toward the beat
    (Lachaux 1999; Van Leeuwen 2003, 2009; Zoefel 2018; Notbohm 2016;
    Duecker 2021).
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
import scipy.signal

from kaine.bus.schema import Event
from kaine.modules.perception_prng import keyed_u64, unit_float
from kaine.storage import resolve

log = logging.getLogger(__name__)

READINESS_TYPE = "gestation.readiness"
PROBE_TYPE = "gestation.probe"
SOURCE = "gestation"
WITHDRAWAL_MAX_SECONDS = 30.0
PERTURBATION_MAX_SECONDS = 10.0

_JITTER_SALT_WITHDRAWAL = 0xB710
_JITTER_SALT_PERTURBATION = 0xB720


@dataclass(frozen=True)
class GestationReadoutConfig:
    readout_period_seconds: float = 60.0
    sample_hz: float = 10.0
    withdrawal_period_seconds: float = 1800.0
    withdrawal_seconds: float = 20.0
    perturbation_period_seconds: float = 3600.0
    perturbation_seconds: float = 5.0
    baseline_drive_fraction: float = 0.5
    perturbation_drive_fraction: float = 0.75
    probe_jitter_fraction: float = 0.25
    entrainment_window_seconds: float = 300.0
    entrainment_band_low_hz: float = 0.3
    entrainment_band_high_hz: float = 2.0
    edge_trim_seconds: float = 2.0
    frequency_pull_floor: float = 0.5
    baseline_withdrawals: float = 3.0
    hrv_window_seconds: float = 300.0
    recovery_tolerance: float = 0.25
    recovery_cap_seconds: float = 300.0

    @classmethod
    def from_dict(cls, data) -> "GestationReadoutConfig":
        # An absent [perception_feed.womb.readout] table means the defaults.
        if data is None:
            data = {}
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
            if not math.isfinite(fv):
                raise ValueError(f"{name} must be finite and > 0")

            if name == "probe_jitter_fraction":
                if fv < 0.0 or fv > 0.5:
                    raise ValueError(f"{name} must be in [0.0, 0.5]")
                kwargs[name] = fv
                continue

            if fv <= 0.0:
                raise ValueError(f"{name} must be finite and > 0")

            if name == "perturbation_drive_fraction" and fv > 1.0:
                raise ValueError(f"{name} must be <= 1.0")
            if name == "baseline_drive_fraction" and fv > 1.0:
                raise ValueError(f"{name} must be in (0, 1]")
            if name == "frequency_pull_floor" and fv > 1.0:
                raise ValueError(f"{name} must be <= 1.0")
            if name == "withdrawal_seconds" and fv > WITHDRAWAL_MAX_SECONDS:
                raise ValueError(
                    f"{name} must be <= {WITHDRAWAL_MAX_SECONDS}"
                )
            if name == "perturbation_seconds" and fv > PERTURBATION_MAX_SECONDS:
                raise ValueError(
                    f"{name} must be <= {PERTURBATION_MAX_SECONDS}"
                )
            kwargs[name] = fv

        baseline = kwargs["baseline_drive_fraction"]
        perturbation = kwargs["perturbation_drive_fraction"]
        if not (baseline < perturbation <= 1.0):
            raise ValueError(
                "perturbation_drive_fraction must be greater than "
                "baseline_drive_fraction and at most 1.0"
            )

        sample_hz = kwargs["sample_hz"]
        low = kwargs["entrainment_band_low_hz"]
        high = kwargs["entrainment_band_high_hz"]
        if not (low < high < sample_hz / 2.0):
            raise ValueError(
                "entrainment_band_low_hz must be less than "
                "entrainment_band_high_hz, which must be below sample_hz/2"
            )
        if kwargs["edge_trim_seconds"] * 2.0 >= kwargs["entrainment_window_seconds"]:
            raise ValueError(
                "entrainment_window_seconds must be greater than "
                "2 * edge_trim_seconds"
            )
        if kwargs["frequency_pull_floor"] > 1.0:
            raise ValueError("frequency_pull_floor must be <= 1.0")

        return cls(**kwargs)


def phase_locking_value(phases_a, phases_b) -> float | None:
    """Mean resultant length of phase differences."""
    if len(phases_a) != len(phases_b):
        return None
    if len(phases_a) < 2:
        return None
    diffs = np.array(phases_a, dtype=float) - np.array(phases_b, dtype=float)
    return float(abs(np.mean(np.exp(1j * diffs))))


def band_phase(values, sample_hz, low_hz, high_hz, trim_samples) -> np.ndarray | None:
    """Band-pass, Hilbert-transform, and return the instantaneous phase.

    A zero-phase 2nd-order Butterworth band-pass is applied, the analytic
    signal is computed, and ``trim_samples`` is removed from each end.
    """
    arr = np.asarray(values, dtype=float)
    n = arr.size
    if n < 2 * trim_samples + 2:
        return None

    mean = float(np.mean(arr))
    sos = scipy.signal.butter(
        2, [low_hz, high_hz], btype="band", fs=sample_hz, output="sos"
    )
    filtered = scipy.signal.sosfiltfilt(sos, arr - mean)
    analytic = scipy.signal.hilbert(filtered)
    phase = np.angle(analytic)

    if trim_samples:
        phase = phase[trim_samples:-trim_samples]
    if phase.size < 2:
        return None

    return phase


def entrainment_plv(
    activity,
    beats,
    surrogate_beats,
    sample_hz,
    low_hz,
    high_hz,
    trim_samples,
) -> tuple[float | None, float | None]:
    """PLV of self-rhythm activity vs. the true beat and the max surrogate PLV.

    ``surrogate_beats`` is a list of phase series, one per surrogate mother.
    Returns ``(plv, surrogate_max)``; ``surrogate_max`` is None when no
    surrogates are supplied.
    """
    phase = band_phase(activity, sample_hz, low_hz, high_hz, trim_samples)
    if phase is None:
        return (None, None)

    beats_arr = np.asarray(beats, dtype=float)
    if trim_samples:
        beats_arr = beats_arr[trim_samples:-trim_samples]
    if beats_arr.size != phase.size:
        return (None, None)

    plv = phase_locking_value(phase, beats_arr)

    surrogate_max = None
    if surrogate_beats:
        surr_plvs: list[float] = []
        for sb in surrogate_beats:
            sb_arr = np.asarray(sb, dtype=float)
            if trim_samples:
                sb_arr = sb_arr[trim_samples:-trim_samples]
            if sb_arr.size == phase.size:
                sp = phase_locking_value(phase, sb_arr)
                if sp is not None:
                    surr_plvs.append(sp)
        if surr_plvs:
            surrogate_max = float(max(surr_plvs))

    return (plv, surrogate_max)


def withdrawn_frequency(times, activity, sample_hz, low_hz, high_hz) -> float | None:
    """Least-squares frequency (Hz) of band-passed activity during withdrawal."""
    arr = np.asarray(activity, dtype=float)
    t = np.asarray(times, dtype=float)
    if arr.size < 4 or t.size != arr.size:
        return None

    mean = float(np.mean(arr))
    sos = scipy.signal.butter(
        2, [low_hz, high_hz], btype="band", fs=sample_hz, output="sos"
    )
    filtered = scipy.signal.sosfiltfilt(sos, arr - mean)
    phase = np.unwrap(np.angle(scipy.signal.hilbert(filtered)))
    if phase.size < 2:
        return None

    slope = np.polyfit(t, phase, 1)[0]
    return float(slope / (2.0 * math.pi))


def beat_frequency(times, beats) -> float | None:
    """Slope of the unwrapped beat phase over a window, in Hz."""
    arr = np.asarray(beats, dtype=float)
    t = np.asarray(times, dtype=float)
    if arr.size < 2 or t.size != arr.size:
        return None

    phase = np.unwrap(arr)
    slope = np.polyfit(t, phase, 1)[0]
    return float(slope / (2.0 * math.pi))


def frequency_pull(f_w, f_w0, f_beat) -> float | None:
    """Frequency pull of the withdrawn rhythm toward the beat."""
    if f_w is None or f_w0 is None or f_beat is None:
        return None
    denom = abs(f_w0 - f_beat)
    if denom < 0.05:
        return None
    return 1.0 - abs(f_w - f_beat) / denom


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
        seed: int = 0,
        state_path: Path | None = None,
        surrogate_beat_phases: Callable[[], list[float]] | None = None,
    ) -> None:
        self._bus = bus
        self._soma = soma
        self._drive = drive
        self._beat_phase = beat_phase
        self._surrogate_beat_phases = surrogate_beat_phases
        self._is_paused = is_paused
        self._config = config
        self._clock = clock
        self._seed = int(seed)
        self._state_path = resolve(
            state_path if state_path is not None else Path("state/lifecycle/gestation_readout.json")
        )

        self._jitter_counter_withdrawal: int = 0
        self._jitter_counter_perturbation: int = 0

        self._drive.scale = self._config.baseline_drive_fraction
        self._started_at = self._clock()

        max_samples = int(
            (
                self._config.entrainment_window_seconds
                + self._config.withdrawal_seconds * 2.0
                + 120.0
            )
            * self._config.sample_hz
            * 1.5
        )
        self._samples: deque[
            tuple[float, float | None, float | None, float | None, str, float | None, tuple | None]
        ] = deque(maxlen=max(max_samples, 16))

        soma_maxlen = int((self._config.recovery_cap_seconds + 120.0) * 2.0)
        self._soma_series: deque[tuple[float, float]] = deque(maxlen=max(soma_maxlen, 16))

        self._settle_until: float = (
            self._started_at + self._config.readout_period_seconds
        )
        self._paused_last_step: bool = False
        self._last_probe_end: float = -float("inf")

        settle_end = self._settle_until
        self._next_withdrawal_at: float = (
            settle_end
            + self._jitter_unit("withdrawal")
            * self._config.probe_jitter_fraction
            * self._config.withdrawal_period_seconds
        )
        self._next_perturbation_at: float = (
            self._started_at
            + self._config.readout_period_seconds
            + self._config.withdrawal_seconds
            + 60.0
            + self._jitter_unit("perturbation")
            * self._config.probe_jitter_fraction
            * self._config.perturbation_period_seconds
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

        self._entrainment_plv: float | None = None
        self._entrainment_plv_surrogate_max: float | None = None
        self._self_rhythm_freq_withdrawn: float | None = None
        self._frequency_pull: float | None = None

        self._baseline: float | None = None
        self._self_rhythm_baseline_hz: float | None = None
        self._self_rhythm_baseline_count: int = 0
        self._load_baseline()

    def _jitter_unit(self, kind: str) -> float:
        """Return a fresh unit draw for ``kind`` and advance its counter."""
        if kind == "withdrawal":
            salt = _JITTER_SALT_WITHDRAWAL
            counter = self._jitter_counter_withdrawal
            self._jitter_counter_withdrawal = counter + 1
        else:
            salt = _JITTER_SALT_PERTURBATION
            counter = self._jitter_counter_perturbation
            self._jitter_counter_perturbation = counter + 1
        return unit_float(keyed_u64(self._seed, counter, salt))

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

            self_baseline = data.get("self_rhythm_baseline_hz")
            if (
                isinstance(self_baseline, (int, float))
                and not isinstance(self_baseline, bool)
                and self_baseline > 0.0
            ):
                self._self_rhythm_baseline_hz = float(self_baseline)
                count = data.get("self_rhythm_baseline_count", 0)
                if isinstance(count, int) and not isinstance(count, bool):
                    self._self_rhythm_baseline_count = max(0, count)
        except Exception:
            log.warning("gestation: could not load baseline", exc_info=True)

    def _persist_baseline(self) -> None:
        if self._state_path is None:
            return
        if (self._baseline is None or self._baseline <= 0.0) and (
            self._self_rhythm_baseline_count <= 0
        ):
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".tmp")
            data: dict[str, Any] = {}
            if self._baseline is not None and self._baseline > 0.0:
                data["prediction_error_baseline"] = self._baseline
            if self._self_rhythm_baseline_count > 0:
                data["self_rhythm_baseline_hz"] = self._self_rhythm_baseline_hz
                data["self_rhythm_baseline_count"] = self._self_rhythm_baseline_count
            tmp.write_text(
                json.dumps(data),
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
            if self._paused_last_step:
                self._settle_until = now + self._config.readout_period_seconds
            await self._handle_probes(now)

        self._paused_last_step = paused

        self._sample(now)
        await self._read_soma_reports(now)

        if now >= self._next_readout_at:
            await self._do_readout(now)
            self._next_readout_at = now + self._config.readout_period_seconds

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
                    # Expected periodic wake-up; continue the loop.
                    continue
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
            # No self-rhythm reading this tick: the sample records None and the
            # marker windows skip it.
            log.debug("gestation: self-rhythm read failed", exc_info=True)

        activity: float | None = None
        try:
            if hasattr(self._soma, "self_rhythm_activity"):
                raw = self._soma.self_rhythm_activity()
                if raw is not None:
                    activity = float(raw)
        except Exception:
            log.debug("gestation: self-rhythm activity read failed", exc_info=True)

        beat: float | None = None
        try:
            beat = float(self._beat_phase())
        except Exception:
            # No maternal beat phase this tick: the sample records None and the
            # phase-locking pairs skip it.
            log.debug("gestation: beat phase read failed", exc_info=True)

        surrogates: tuple | None = None
        if self._surrogate_beat_phases is not None:
            try:
                phases = self._surrogate_beat_phases()
                if phases is not None:
                    surrogates = tuple(float(p) for p in phases)
            except Exception:
                log.debug("gestation: surrogate beat read failed", exc_info=True)

        self._samples.append(
            (now, phase, amplitude, beat, self._probe_state, activity, surrogates)
        )

    async def _handle_probes(self, now: float) -> None:
        if self._probe_state != "idle":
            if now >= (self._probe_end or now):
                await self._end_probe(now)
            return

        if now < self._settle_until:
            return

        min_probe_at = self._last_probe_end + max(
            60.0, self._config.withdrawal_seconds
        )
        if now < min_probe_at:
            return

        # When both are due, the more overdue one goes first, so neither kind can
        # starve the other.
        due = [
            (self._next_withdrawal_at, "withdrawal"),
            (self._next_perturbation_at, "perturbation"),
        ]
        due = [d for d in due if now >= d[0]]
        if due:
            await self._start_probe(now, min(due)[1])

    async def _start_probe(self, now: float, kind: str) -> None:
        if kind == "withdrawal":
            seconds = min(self._config.withdrawal_seconds, WITHDRAWAL_MAX_SECONDS)
            self._drive.scale = 0.0
            u = self._jitter_unit("withdrawal")
            self._next_withdrawal_at = now + self._config.withdrawal_period_seconds * (
                1.0 + self._config.probe_jitter_fraction * (2.0 * u - 1.0)
            )
        else:
            seconds = min(self._config.perturbation_seconds, PERTURBATION_MAX_SECONDS)
            # Perturbation is a bounded rise, not a full-strength drive.
            self._drive.scale = self._config.perturbation_drive_fraction
            u = self._jitter_unit("perturbation")
            self._next_perturbation_at = now + self._config.perturbation_period_seconds * (
                1.0 + self._config.probe_jitter_fraction * (2.0 * u - 1.0)
            )

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

        # The drive is restored now, which may be a tick after the planned end;
        # the spacing to the next probe counts from this real end.
        self._last_probe_end = float(now)

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

        self._last_probe_end = float(now)

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
            s
            for s in self._samples
            if start - duration <= s[0] < start and s[4] == "idle"
        ]
        withdrawn = [
            s
            for s in self._samples
            if start <= s[0] <= end and s[4] == "withdrawal"
        ]

        driven_amps = [s[2] for s in driven if s[2] is not None]
        withdrawn_amps = [s[2] for s in withdrawn if s[2] is not None]
        self._endogenous_self_sustain = self_sustains(driven_amps, withdrawn_amps)

        cfg = self._config
        sample_hz = cfg.sample_hz
        low_hz = cfg.entrainment_band_low_hz
        high_hz = cfg.entrainment_band_high_hz
        trim_samples = int(cfg.edge_trim_seconds * sample_hz)

        # Entrainment over the driven window before withdrawal.
        idle_window = cfg.entrainment_window_seconds
        expected_idle = int(idle_window * sample_hz)
        idle = [
            s
            for s in self._samples
            if start - idle_window <= s[0] < start and s[4] == "idle"
        ]
        valid_idle = [
            s for s in idle if s[5] is not None and s[3] is not None
        ]
        if self._surrogate_beat_phases is not None:
            valid_idle = [
                s
                for s in valid_idle
                if s[6] is not None and all(x is not None for x in s[6])
            ]

        idle_acts = np.array([s[5] for s in valid_idle], dtype=float)
        idle_beats = np.array([s[3] for s in valid_idle], dtype=float)
        idle_surrogates: list[np.ndarray] = []
        if (
            self._surrogate_beat_phases is not None
            and valid_idle
            and valid_idle[0][6] is not None
        ):
            k = len(valid_idle[0][6])
            for idx in range(k):
                idle_surrogates.append(
                    np.array([s[6][idx] for s in valid_idle], dtype=float)
                )

        plv: float | None = None
        surrogate_max: float | None = None
        if (
            valid_idle
            and len(valid_idle) >= 0.8 * expected_idle
            and expected_idle > 0
        ):
            plv, surrogate_max = entrainment_plv(
                idle_acts,
                idle_beats,
                idle_surrogates,
                sample_hz,
                low_hz,
                high_hz,
                trim_samples,
            )

        # Withdrawn self-rhythm frequency.
        expected_withdrawn = int(cfg.withdrawal_seconds * sample_hz)
        valid_withdrawn = [s for s in withdrawn if s[5] is not None]
        f_w: float | None = None
        if (
            valid_withdrawn
            and len(valid_withdrawn) >= 0.6 * expected_withdrawn
            and expected_withdrawn > 0
        ):
            f_w = withdrawn_frequency(
                [s[0] for s in valid_withdrawn],
                [s[5] for s in valid_withdrawn],
                sample_hz,
                low_hz,
                high_hz,
            )

        # Beat frequency over the entrainment window.
        f_beat: float | None = None
        if valid_idle:
            f_beat = beat_frequency(
                [s[0] for s in valid_idle],
                idle_beats,
            )

        # Update own baseline f_w0 from the first withdrawals.
        if f_w is not None:
            target = int(cfg.baseline_withdrawals)
            if self._self_rhythm_baseline_count < target:
                n = self._self_rhythm_baseline_count
                current = self._self_rhythm_baseline_hz or 0.0
                n += 1
                self._self_rhythm_baseline_hz = (current * (n - 1) + f_w) / n
                self._self_rhythm_baseline_count = n
                self._persist_baseline()

        # Frequency pull toward the beat.
        pull: float | None = None
        f_w0 = self._self_rhythm_baseline_hz
        if (
            f_w0 is not None
            and self._self_rhythm_baseline_count >= int(cfg.baseline_withdrawals)
        ):
            pull = frequency_pull(f_w, f_w0, f_beat)

        if (
            plv is None
            or surrogate_max is None
            or self._endogenous_self_sustain is None
            or pull is None
        ):
            marker = None
        else:
            marker = (
                plv > surrogate_max
                and self._endogenous_self_sustain
                and pull >= cfg.frequency_pull_floor
            )

        self._entrainment_plv = plv
        self._entrainment_plv_surrogate_max = surrogate_max
        self._self_rhythm_freq_withdrawn = f_w
        self._frequency_pull = pull
        self._entrain_then_autonomy = marker

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
        for (
            t,
            phase,
            _amp,
            _beat,
            _state,
            _activity,
            _surrogates,
        ) in self._samples:
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
        if self._entrainment_plv is not None:
            result["entrainment_plv"] = self._entrainment_plv
        if self._entrainment_plv_surrogate_max is not None:
            result["entrainment_plv_surrogate_max"] = self._entrainment_plv_surrogate_max
        if self._self_rhythm_freq_withdrawn is not None:
            result["self_rhythm_freq_withdrawn"] = self._self_rhythm_freq_withdrawn
        if self._frequency_pull is not None:
            result["frequency_pull"] = self._frequency_pull
        return result
