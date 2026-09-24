# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""A deterministic, stim-responsive reference data source for the simulator.

Why this exists: Cortical Labs' free simulator, by its own documentation,
"generates non-learning control data that does not respond to stimulation." That
is correct for a baseline control, but it means the *closed loop* (stimulate,
observe the evoked response) cannot be exercised on the default source, and its
random path is not reproducible across in-process re-opens.

`ReferenceCulture` is a pluggable `SimulatorDataSource` (the SDK's documented
extension point) that fixes both for offline development:

- **Deterministic.** `read(from_timestamp, frame_count)` is a pure function of
  `(seed, from_timestamp, committed stims)`, so a seeded run reproduces exactly,
  in-process or across processes.
- **Stim-responsive.** A committed stim on a channel raises the evoked spike rate
  on that channel (and, optionally, its neighbours) for a short response window,
  so encode→stim→record→decode is a real loop.

It is a stand-in for characterising the pipeline in simulation, not a biophysical
model. On real tissue the culture replaces it entirely; nothing here ships toward
hardware. See `docs/biological-welfare.md`.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from cl.sim import (
    DataSourceBatch,
    DataSourceSpike,
    DataSourceStim,
    SimulatorDataSource,
    SimulatorDataSourceMetadata,
)

_FPS = 25_000  # the SDK requires a 25 kHz sample rate
_SPIKE_SAMPLES = 75  # cl._sim._data_buffer.SPIKE_SAMPLES_TOTAL
_ZERO_WAVEFORM = np.zeros(_SPIKE_SAMPLES, dtype=np.float32)
_EPOCH = 250  # absolute-time generation block (10 ms). Keeps read() output a pure
#             # function of absolute timestamps, independent of how loop() chunks
#             # its reads, which is what makes a seeded run reproducible.


class ReferenceCulture(SimulatorDataSource):
    """Deterministic synthetic culture whose spiking responds to stimulation."""

    def __init__(
        self,
        *,
        seed: int = 42,
        channel_count: int = 64,
        baseline_hz: float = 4.0,
        evoked_spikes: int = 10,
        response_ms: float = 20.0,
        neighbour_radius: int = 0,
    ) -> None:
        self._seed = int(seed)
        self._channel_count = int(channel_count)
        self._baseline_hz = float(baseline_hz)
        self._evoked_spikes = int(evoked_spikes)
        self._response_frames = int(response_ms * _FPS / 1000.0)
        self._neighbour_radius = int(neighbour_radius)
        # committed stims observed in this (subprocess) source:
        # (timestamp, channel, amplitude_fraction in [0, 1])
        self._stims: list[tuple[int, int, float]] = []

    # -- metadata ---------------------------------------------------------------
    @property
    def metadata(self) -> SimulatorDataSourceMetadata:
        return SimulatorDataSourceMetadata(
            channel_count=self._channel_count,
            frames_per_second=_FPS,
            start_timestamp=0,
            seekable=True,
            realtime_only=False,
            supports_accelerated=True,
        )

    # -- stim observation -------------------------------------------------------
    def on_stim(self, stim: DataSourceStim) -> None:
        # Evoked strength scales with stimulation amplitude, so the encoded input
        # actually modulates the response (the default sim ignores stimulation
        # entirely). Peak |current| / 3 uA → fraction in [0, 1].
        peak = max((abs(c) for c in stim.phase_currents_uA), default=0.0)
        amp = min(peak / 3.0, 1.0)
        self._stims.append((int(stim.timestamp), int(stim.channel), float(amp)))
        # bound memory: keep only stims that can still evoke into future reads
        horizon = int(stim.timestamp) - 10 * self._response_frames
        if len(self._stims) > 4096:
            self._stims = [s for s in self._stims if s[0] >= horizon]

    # -- data production (all keyed by ABSOLUTE time, not by read window) --------
    @staticmethod
    def _spike(ts: int, ch: int) -> DataSourceSpike:
        return DataSourceSpike(
            timestamp=int(ts), channel=int(ch),
            samples=_ZERO_WAVEFORM, channel_mean_sample=0.0,
        )

    def _baseline(
        self, from_timestamp: int, frame_count: int
    ) -> tuple[np.ndarray, list[DataSourceSpike]]:
        end = from_timestamp + frame_count
        frames = np.zeros((frame_count, self._channel_count), dtype=np.int16)
        spikes: list[DataSourceSpike] = []
        lam = self._baseline_hz * _EPOCH / _FPS
        first_ep, last_ep = from_timestamp // _EPOCH, (end - 1) // _EPOCH
        for ep in range(first_ep, last_ep + 1):
            ep_start = ep * _EPOCH
            # frames for this epoch, keyed by absolute epoch index
            block = np.random.default_rng([self._seed, ep, 1]).integers(
                -25, 26, size=(_EPOCH, self._channel_count), dtype=np.int16
            )
            lo, hi = max(from_timestamp, ep_start), min(end, ep_start + _EPOCH)
            frames[lo - from_timestamp : hi - from_timestamp] = block[
                lo - ep_start : hi - ep_start
            ]
            # baseline spikes for this epoch, keyed by absolute epoch index
            rng_s = np.random.default_rng([self._seed, ep, 2])
            counts = rng_s.poisson(lam, size=self._channel_count)
            for ch in range(self._channel_count):
                n = int(counts[ch])
                if n == 0:
                    continue
                for off in rng_s.integers(0, _EPOCH, size=n):
                    ts = ep_start + int(off)
                    if from_timestamp <= ts < end:
                        spikes.append(self._spike(ts, ch))
        return frames, spikes

    def _evoked(self, from_timestamp: int, frame_count: int) -> list[DataSourceSpike]:
        end = from_timestamp + frame_count
        spikes: list[DataSourceSpike] = []
        for stim_ts, stim_ch, amp in self._stims:
            if stim_ts + self._response_frames <= from_timestamp or stim_ts >= end:
                continue
            channels = [stim_ch]
            for d in range(1, self._neighbour_radius + 1):
                channels += [stim_ch - d, stim_ch + d]
            for ch in channels:
                if not (0 <= ch < self._channel_count):
                    continue
                # keyed by (seed, stim, channel) only; spikes live at absolute
                # timestamps in [stim_ts, stim_ts + response); window just filters.
                rng = np.random.default_rng([self._seed, stim_ts, ch])
                base = self._evoked_spikes if ch == stim_ch else self._evoked_spikes // 2
                n = int(round(base * amp))  # amplitude modulates the response
                if n <= 0:
                    continue
                for off in rng.integers(0, self._response_frames, size=n):
                    ts = stim_ts + int(off)
                    if from_timestamp <= ts < end:
                        spikes.append(self._spike(ts, ch))
        return spikes

    def read(self, from_timestamp: int, frame_count: int) -> DataSourceBatch:
        frames, spikes = self._baseline(from_timestamp, frame_count)
        spikes += self._evoked(from_timestamp, frame_count)
        return DataSourceBatch(frames=frames, spikes=tuple(spikes))


def make_reference_culture(**config: Any) -> ReferenceCulture:
    """Importable factory for `cl.sim.set_simulator_data_source`.

    Registered by path so the producer subprocess can build it independently:

        cl.sim.set_simulator_data_source(
            "kaine_cl1.substrate.sources:make_reference_culture",
            config={"seed": 42, "evoked_spikes": 12},
        )
    """
    return ReferenceCulture(**config)
