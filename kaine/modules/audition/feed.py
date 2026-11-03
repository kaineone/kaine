# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Deterministic auditory-feed sources for reproducible research runs.

Both sources implement the ``_AudioStream`` protocol from
``kaine/modules/audition/live.py`` (``start()`` / ``stop()`` / ``close()``) and
plug into ``LiveMicrophone`` via its ``stream_factory`` seam. They run a small
producer thread that pushes ``frames_per_block``-sized int16 little-endian PCM
blocks into the ``callback`` at the configured ``sample_rate`` — the exact
contract ``_default_stream_factory`` (sounddevice) fulfils today, so the VAD /
segmentation pipeline downstream is unchanged.

WHY DETERMINISTIC: a research run must present a bit-identical stimulus stream so
results replicate, and the stream must be copyright-free. A live microphone is
neither replayable nor copyright-free. See
openspec/changes/unified-perception-feed.

CROSS-MODAL COHERENCE: the seeded audio source shares the seed and the
``surprise_interval`` cadence with the seeded VIDEO source, so a surprise slot
fires both a visual blob and an audio burst — coherent and cross-modally bound by
construction (NOT frame-locked across the two module loops; coherence is via the
shared seed + cadence). The playlist audio source walks the SAME checksummed
manifest as the playlist video source AND shares its ``PlaylistClock``: both
surfaces derive the currently-playing item from one monotonic origin + per-item
durations, so at any wall-clock moment picture and sound are on the same manifest
item and cross item boundaries together (live / statistical tier). The audio
is paced against that clock, so its delivered position stays on the clock's
offset within one block, or within 0.5 s while catching up after a stall
(openspec/changes/playlist-feed-av-sync). This is the fix for the dual-decoder
desync where audio ran at 1x while video crawled at the tick rate and the two
drifted onto different items (openspec/changes/playlist-realtime-av-sync).

ZERO PERSISTENCE INVARIANT (eyes-and-ears): raw PCM lives only in process memory
— a bounded producer thread emits blocks straight into the callback and never
opens a file for writing. The seeded source persists only ``(seed, schedule)``;
the playlist source persists nothing beyond the manifest it is handed. The
build-time guard in tests/test_zero_persistence_invariant.py covers this module.
"""
from __future__ import annotations

import logging
import math
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from kaine.modules.audition.live import PerceptionUnavailableError
from kaine.modules.perception_prng import keyed_u64 as _keyed_u64
from kaine.modules.perception_prng import unit_float as _unit_float
from kaine.modules.vision.feed import (
    AV_TIME_BASE,
    PlaylistClock,
    PlaylistManifest,
    PlaylistPosition,
    container_duration_s,
    container_origin_s,
)

if TYPE_CHECKING:  # numpy-importing; loaded lazily at render time
    import numpy as np

    from kaine.modules.audition.hearing_band import HearingBandParams
    from kaine.modules.audition.maternal_voice import MaternalVoiceLayer
    from kaine.modules.stimulus_source_signal import StimulusSourceParams
    from kaine.modules.vision.feed import StimulusSourceClock

log = logging.getLogger(__name__)

_INT16_MAX = 32767


def soft_limit(x: "np.ndarray", *, knee: float, ceiling: float) -> "np.ndarray":
    """A smooth tanh knee on the rare speech peaks above the headroom.

    This is a design choice: with the defaults it acts on about 0.25% of
    speech samples and the bed is 2.4 dB lower than without the voice.
    """
    import numpy as np

    if not (0.0 < knee < ceiling):
        raise ValueError("knee must satisfy 0 < knee < ceiling")

    abs_x = np.abs(x)
    sign_x = np.sign(x)
    scale = ceiling - knee
    return np.where(
        abs_x > knee,
        sign_x * (knee + scale * np.tanh((abs_x - knee) / scale)),
        x,
    )


# ---------------------------------------------------------------------------
# Seeded procedural audio schedule
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeededAudioSchedule:
    """Reproducible auditory schedule. The whole soundscape is a pure function
    of these parameters plus the frame (block) index — nothing else.

    ``surprise_interval`` is SHARED with the video schedule so surprises are
    cross-modal; ``base_strength`` scales the learnable base soundscape and
    ``surprise_strength`` scales the seed-keyed bursts (either may be 0 to
    silence one layer). The schedule carries no PCM — only these knobs.
    """

    seed: int = 0
    sample_rate: int = 16000
    channels: int = 1
    frames_per_block: int = 480  # 30 ms @ 16 kHz — matches the mic's VAD frame
    surprise_interval: int = 150
    base_strength: float = 0.3
    surprise_strength: float = 1.0

    def as_descriptor(self) -> dict[str, Any]:
        """The reproducible covariate: enough to regenerate the exact stream."""
        return {
            "seed": int(self.seed),
            "sample_rate": int(self.sample_rate),
            "channels": int(self.channels),
            "frames_per_block": int(self.frames_per_block),
            "surprise_interval": int(self.surprise_interval),
            "base_strength": float(self.base_strength),
            "surprise_strength": float(self.surprise_strength),
        }


@dataclass(frozen=True)
class StimulusSourceAudioSchedule:
    """Reproducible stimulus source audio schedule.

    The PCM stream is a pure function of ``(seed, block_index, params)``.
    Only these knobs persist; no samples are written to disk.
    """

    seed: int = 0
    sample_rate: int = 16000
    channels: int = 1
    frames_per_block: int = 480  # 30 ms @ 16 kHz

    def as_descriptor(self) -> dict[str, Any]:
        return {
            "seed": int(self.seed),
            "sample_rate": int(self.sample_rate),
            "channels": int(self.channels),
            "frames_per_block": int(self.frames_per_block),
        }


# Salts namespace the keyed draws. The base soundscape and the surprise CONTENT
# use audio-only salts (independent of the video draws). The surprise ONSET
# salt is DELIBERATELY shared with the video source so that — for the same seed
# and the same surprise_interval — both modalities decide a slot fires from the
# identical coin flip, making surprises cross-modal (a video blob and an audio
# burst on the same slot). See SeededProceduralSource._SALT_ONSET in
# kaine/modules/vision/feed.py.
_SALT_AUDIO_BASE = 0xE100
_SALT_AUDIO_CONTENT = 0xE3
# Shared with the video source's onset draw (vision.feed _SALT_ONSET = 0xA1).
_SALT_SHARED_ONSET = 0xA1


@dataclass(frozen=True)
class _AudioBaseParams:
    """Per-seed parameters of the learnable base soundscape — a small sum of
    low-frequency sinusoids whose frequencies/phases/amplitudes are seed-derived.
    All bounded so the texture is smooth and learnable (the auditory analogue of
    the drifting visual gradients)."""

    freqs: tuple[float, ...]
    phases: tuple[float, ...]
    amps: tuple[float, ...]


def _derive_audio_base_params(seed: int, n_partials: int = 3) -> _AudioBaseParams:
    """Map a seed to its base-soundscape partials via the shared keyed PRNG.

    Frequencies sit in [80, 440) Hz (low, learnable, well below Nyquist for
    16 kHz); phases span a full turn; amplitudes are normalised so the partials
    sum to ~1.0 before ``base_strength`` scales them."""
    freqs: list[float] = []
    phases: list[float] = []
    raw_amps: list[float] = []
    for k in range(n_partials):
        f = 80.0 + 360.0 * _unit_float(_keyed_u64(seed, 0, _SALT_AUDIO_BASE | (0x10 + k)))
        ph = _unit_float(_keyed_u64(seed, 0, _SALT_AUDIO_BASE | (0x20 + k)))
        a = 0.4 + 0.6 * _unit_float(_keyed_u64(seed, 0, _SALT_AUDIO_BASE | (0x30 + k)))
        freqs.append(f)
        phases.append(ph)
        raw_amps.append(a)
    total = sum(raw_amps) or 1.0
    amps = [a / total for a in raw_amps]
    return _AudioBaseParams(
        freqs=tuple(freqs), phases=tuple(phases), amps=tuple(amps)
    )


class SeededProceduralAudioStream:
    """An ``_AudioStream`` that emits ``pcm(seed, block_index)`` as a pure
    function of ``(seed, block_index)`` — byte-identical across runs of a seed.

    Two layers, mirroring the seeded video source:

    - a learnable BASE SOUNDSCAPE: a sum of a few seed-derived low-frequency
      sinusoids — continuous, smooth texture the world model can learn to
      predict. Keeps Audition's RMS/VAD seeing continuous input (no dead
      silence), so segmentation still chunks it into "utterances" of sound.
    - SURPRISE BURSTS on the SHARED cadence (``surprise_interval``), whose timbre
      and amplitude come from a seed-keyed content draw. Reproducible given the
      seed; not derivable from the observed audio without it.

    HONEST NOTE: this is *sound*, not speech. STT may transcribe a block as
    empty; the research signal is auditory prediction-error + salience, not
    words. Documented in docs and the spec.

    Persists only ``(seed, schedule)``; never a sample of PCM.
    """

    def __init__(
        self,
        schedule: SeededAudioSchedule,
        *,
        callback: Callable[[bytes], None],
    ) -> None:
        self._schedule = schedule
        self._callback = callback
        self._base = _derive_audio_base_params(int(schedule.seed))
        self._index = 0
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()

    @property
    def schedule(self) -> SeededAudioSchedule:
        return self._schedule

    # --- _AudioStream protocol ---------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stopped.clear()
        self._thread = threading.Thread(
            target=self._produce, name="seeded-audio-producer", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def close(self) -> None:
        self.stop()

    # --- producer ----------------------------------------------------------

    def _produce(self) -> None:
        s = self._schedule
        block_seconds = max(1, s.frames_per_block) / float(max(1, s.sample_rate))
        next_deadline = time.monotonic()
        while not self._stopped.is_set():
            pcm = self.pcm_at(self._index)
            self._index += 1
            try:
                self._callback(pcm)
            except Exception:
                log.debug("seeded audio callback raised", exc_info=True)
            # Pace emission at real time so the downstream queue is not flooded;
            # the data itself is independent of timing (seek-safe).
            next_deadline += block_seconds
            sleep_for = next_deadline - time.monotonic()
            if sleep_for > 0:
                self._stopped.wait(timeout=sleep_for)
            else:
                # We fell behind — reset the clock so we don't busy-spin.
                next_deadline = time.monotonic()

    # --- pure synthesis -----------------------------------------------------

    def pcm_at(self, block_index: int) -> bytes:
        """Synthesize the int16 LE PCM block at ``block_index`` as a pure
        function of ``(seed, block_index)``. Byte-identical across runs and
        independent of read order (seek-safe)."""
        s = self._schedule
        n = max(1, int(s.frames_per_block))
        sr = float(max(1, s.sample_rate))
        channels = max(1, int(s.channels))
        two_pi = 2.0 * math.pi

        # Absolute sample offset of this block, so phase is continuous across
        # blocks (a function of block_index, not of any running accumulator).
        sample0 = block_index * n
        base_amp = max(0.0, float(s.base_strength))

        # --- Base soundscape: sum of seed-derived low-freq sinusoids --------
        samples = [0.0] * n
        if base_amp > 0.0:
            for f, ph, a in zip(self._base.freqs, self._base.phases, self._base.amps):
                w = two_pi * f / sr
                p0 = two_pi * ph
                amp = base_amp * a
                for i in range(n):
                    samples[i] += amp * math.sin(w * (sample0 + i) + p0)

        # --- Surprise burst -------------------------------------------------
        # On a shared cadence slot the burst is a seed-keyed band-limited tone +
        # noise, so the surprise is cross-modal (a video blob fires the same
        # slot) yet not anticipable from the audio without the seed.
        if self._is_surprise_block(block_index):
            content = _keyed_u64(s.seed, block_index, _SALT_AUDIO_CONTENT)
            burst_amp = min(1.0, max(0.0, float(s.surprise_strength)))
            # Burst carrier in [600, 3000) Hz — clearly distinct from the base.
            burst_f = 600.0 + 2400.0 * (((content >> 8) & 0xFFFF) / 65535.0)
            w = two_pi * burst_f / sr
            # A short envelope so the burst is a transient within the block.
            burst_len = min(n, max(1, n // 2))
            for i in range(burst_len):
                env = 0.5 - 0.5 * math.cos(two_pi * i / max(1, burst_len - 1))
                # Seed-keyed deterministic "noise" overlay (no RNG state).
                noise_u = _keyed_u64(s.seed, sample0 + i, _SALT_AUDIO_CONTENT)
                noise = (_unit_float(noise_u) * 2.0 - 1.0)
                samples[i] += burst_amp * env * (0.7 * math.sin(w * (sample0 + i)) + 0.3 * noise)

        # Clip to [-1, 1] then quantise to int16 LE; replicate across channels.
        out = bytearray()
        for v in samples:
            if v > 1.0:
                v = 1.0
            elif v < -1.0:
                v = -1.0
            q = int(round(v * _INT16_MAX))
            if q > _INT16_MAX:
                q = _INT16_MAX
            elif q < -_INT16_MAX - 1:
                q = -_INT16_MAX - 1
            packed = struct.pack("<h", q)
            for _ in range(channels):
                out += packed
        return bytes(out)

    def _is_surprise_block(self, block_index: int) -> bool:
        """A surprise fires on shared cadence slots (every ``surprise_interval``
        blocks, index > 0), with a seed-keyed coin flip on each slot — mirroring
        the video source so the modalities share the same slots. Strength 0
        silences it."""
        interval = int(self._schedule.surprise_interval)
        if interval <= 0 or block_index <= 0:
            return False
        if block_index % interval != 0:
            return False
        if self._schedule.surprise_strength <= 0.0:
            return False
        slot = block_index // interval
        onset = _keyed_u64(self._schedule.seed, slot, _SALT_SHARED_ONSET)
        return _unit_float(onset) < 0.75

    def surprise_indices(self, count: int) -> list[int]:
        """The block indices in ``[0, count)`` on which a surprise fires — used
        by tests to assert cadence and cross-modal alignment with the video."""
        return [i for i in range(count) if self._is_surprise_block(i)]


class StimulusSourceProceduralAudioStream:
    """An ``_AudioStream`` that emits the stimulus source auditory feed.

    The soundscape is low-frequency-dominant and low-passed
    (Benzaquen 1990; Parga 2018; Webb 2015), with a periodic ~50 Hz thud
    phase-locked to the same maternal heartbeat that drives the video pulse
    (Van Leeuwen 2009; Webb 2015).  The heartbeat is external; the entity's
    own rhythm is emergent, not synthesised here.

    When a maternal-voice layer is given, its pre-rendered, low-pass filtered
    speech is added to the mix and the headroom grows by the voice's RMS level;
    a soft limiter rounds the rare peaks above it (Querleu et al. 1988;
    Gerhardt and Abrams 2000); without one the output is unchanged.

    When an enabled hearing band is given, the bed and the voice pass a
    band-pass that widens with the hearing stage in the order fetal hearing
    matures (Hepper and Shahidullah 1994); the stage comes from the stage
    owner (``hearing_stage``). Without a band, or
    with it disabled, the output is unchanged. The awake time is read only
    for the maternal voice's unlock.

    Persists only ``(seed, schedule, params, clock)``; no PCM is written.
    """

    _MAX_LAG_BLOCKS = 5
    _BASE_AMP_TOTAL = 0.35
    _NOISE_RMS = 0.08
    _THUD_AMP = 0.35

    def __init__(
        self,
        schedule: StimulusSourceAudioSchedule,
        *,
        params: StimulusSourceParams,
        clock: StimulusSourceClock,
        callback: Callable[[bytes], None],
        voice: MaternalVoiceLayer | None = None,
        awake: Callable[[], float] | None = None,
        hearing: HearingBandParams | None = None,
        hearing_stage: Callable[[], int] | None = None,
    ) -> None:
        self._schedule = schedule
        self._params = params
        self._clock = clock
        self._callback = callback
        self._voice = voice
        self._awake = awake
        self._hearing = hearing if (hearing is not None and hearing.enabled) else None
        self._hearing_stage = hearing_stage
        self._mix_cache: dict[int, "np.ndarray"] = {}
        self._mix_newest: int | None = None
        self._mix_lock = threading.Lock()
        if voice is not None and voice.repertoire.sample_rate != schedule.sample_rate:
            raise ValueError(
                f"voice sample rate {voice.repertoire.sample_rate} does not match "
                f"schedule sample rate {schedule.sample_rate}"
            )
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()

    @property
    def schedule(self) -> StimulusSourceAudioSchedule:
        return self._schedule

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stopped.clear()
        self._thread = threading.Thread(
            target=self._produce, name="stimulus-source-audio-producer", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def close(self) -> None:
        self.stop()

    @staticmethod
    def _advance(k: int | None, now_k: int) -> int:
        """Return the next block index to emit.

        ``None`` means the stream has not emitted anything yet.  Small lags
        are replayed; a lag larger than ``_MAX_LAG_BLOCKS`` jumps forward to
        the clock so the producer never falls arbitrarily far behind.
        """
        if k is None or now_k - k > StimulusSourceProceduralAudioStream._MAX_LAG_BLOCKS:
            return now_k
        return k

    def _read_awake(self) -> float | None:
        """Return the current awake time, or ``None`` if no awake provider is set
        or no voice is attached (only the voice unlock uses the awake time)."""
        if self._awake is None or self._voice is None:
            return None
        return float(self._awake())

    def _read_stage(self) -> int:
        """Return the stage owner's current hearing stage (0 with no provider)."""
        if self._hearing_stage is None:
            return 0
        return int(self._hearing_stage())

    def _mix(self, block_index: int, awake: float) -> "np.ndarray":
        """Return the unfiltered float mix of ``block_index``."""
        import numpy as np

        if block_index < 0:
            n = max(1, int(self._schedule.frames_per_block))
            return np.zeros(n, dtype=np.float64)

        with self._mix_lock:
            cached = self._mix_cache.get(block_index)
            if cached is not None:
                return cached

            n = max(1, int(self._schedule.frames_per_block))
            samples = self._soundscape(block_index)
            if self._voice is not None:
                samples = samples + self._voice.render(block_index * n, n, awake)

            # Keep only blocks within 8 of the newest requested index.
            newest = self._mix_newest
            if newest is None or block_index > newest:
                self._mix_newest = block_index
                newest = block_index
            cutoff = newest - 8
            for key in list(self._mix_cache.keys()):
                if key < cutoff:
                    del self._mix_cache[key]

            self._mix_cache[block_index] = samples
            return samples

    def _produce(self) -> None:
        s = self._schedule
        bs = max(1, s.frames_per_block) / float(max(1, s.sample_rate))
        k = None
        while not self._stopped.is_set():
            if self._clock.born():
                log.info("stimulus source audio: maturation transition complete; the stimulus source falls silent")
                return
            now_k = int(self._clock.stimulus_source_seconds() / bs)
            k = self._advance(k, now_k)
            if k > now_k:
                self._stopped.wait(timeout=(k - now_k) * bs)
                continue
            try:
                pcm = self.pcm_at(
                    k,
                    maturation_progress=self._clock.maturation_progress(),
                    awake_seconds=self._read_awake(),
                    hearing_stage=self._read_stage() if self._hearing is not None else None,
                )
            except Exception:
                log.error(
                    "stimulus source audio: synthesis failed at block %d; the stimulus source audio stream stops",
                    k,
                    exc_info=True,
                )
                return
            if self._clock.born():
                return
            try:
                self._callback(pcm)
            except Exception:
                log.debug("stimulus source audio callback raised", exc_info=True)
            else:
                self._clock.mark_delivered("audio", k)
            k += 1

    def _soundscape(self, block_index: int) -> np.ndarray:
        """Return the voice-free float soundscape for ``block_index``."""
        import math

        import numpy as np

        from kaine.modules.perception_prng import keyed_u64 as _keyed_u64
        from kaine.modules.perception_prng import unit_float as _unit_float
        from kaine.modules.stimulus_source_signal import (
            SEED_SALT_AUDIO,
            beat_pulse,
            heartbeat_phase,
            lowpassed_noise,
        )

        s = self._schedule
        p = self._params
        n = max(1, int(s.frames_per_block))
        sr = float(max(1, s.sample_rate))
        seed = int(s.seed)

        t0 = block_index * n / sr
        t = t0 + np.arange(n, dtype=np.float64) / sr
        samples = np.zeros(n, dtype=np.float64)
        two_pi = 2.0 * math.pi

        # Low-frequency soundscape: a few seed-derived sinusoids below the
        # low-pass corner.
        n_base = 4
        base_amp_total = self._BASE_AMP_TOTAL
        lp = float(p.lowpass_hz)
        max_base_f = min(250.0, 0.8 * lp)
        base_freq_range = max_base_f - 30.0
        for k in range(n_base):
            f = 30.0 + base_freq_range * _unit_float(
                _keyed_u64(seed, k, SEED_SALT_AUDIO | 0x10 | k)
            )
            ph = two_pi * _unit_float(
                _keyed_u64(seed, k, SEED_SALT_AUDIO | 0x20 | k)
            )
            samples += (base_amp_total / n_base) * np.sin(two_pi * f * t + ph)

        # Real low-passed noise: white noise through a Hamming-windowed sinc
        # FIR.  The output is continuous across block boundaries and still a
        # pure function of ``(seed, block_index)``.  Low-pass, low-frequency
        # intrauterine soundscape (Benzaquen 1990; Parga 2018; Webb 2015).
        noise_rms = self._NOISE_RMS
        samples += noise_rms * lowpassed_noise(seed, block_index, n, sr, lp)

        # Maternal heartbeat thud, phase-shared with the video pulse.
        phase = heartbeat_phase(seed, t, p)
        env = beat_pulse(phase)
        thud_f = 45.0 + 10.0 * _unit_float(
            _keyed_u64(seed, 0, SEED_SALT_AUDIO | 0x40)
        )
        thud_ph = two_pi * _unit_float(
            _keyed_u64(seed, 0, SEED_SALT_AUDIO | 0x41)
        )
        thud_amp = self._THUD_AMP
        samples += thud_amp * env * np.sin(two_pi * thud_f * t + thud_ph)
        return samples

    def pcm_at(
        self,
        block_index: int,
        *,
        maturation_progress: float | None = None,
        awake_seconds: float | None = None,
        hearing_stage: int | None = None,
    ) -> bytes:
        """Synthesize the int16 LE PCM block at ``block_index``.

        Pure function of ``(seed, block_index, params, maturation_progress)``
        and, with a voice, of the awake time at each slot's first rendering.
        With an enabled hearing band the block is additionally a pure function
        of the hearing stage and the voice plans, regardless of which blocks
        were rendered before it. ``hearing_stage`` defaults to the stage
        provider's current stage (0 with no provider).
        """
        import numpy as np

        s = self._schedule
        n = max(1, int(s.frames_per_block))
        channels = max(1, int(s.channels))

        if self._hearing is None:
            samples = self._soundscape(block_index)
            if self._voice is not None:
                awake = (
                    awake_seconds
                    if awake_seconds is not None
                    else (
                        float(self._awake())
                        if self._awake is not None
                        else 0.0
                    )
                )
                samples = samples + self._voice.render(block_index * n, n, awake)
        else:
            from kaine.modules.audition.hearing_band import (
                HEARING_BAND_TAPS,
                band_taps,
                stage_edges,
            )

            if awake_seconds is not None:
                awake = float(awake_seconds)
            elif self._awake is not None:
                awake = float(self._awake())
            else:
                awake = 0.0

            hist = -(-(HEARING_BAND_TAPS - 1) // n)
            x = np.concatenate(
                [self._mix(block_index - j, awake) for j in range(hist, 0, -1)]
                + [self._mix(block_index, awake)]
            )
            keep = n + HEARING_BAND_TAPS - 1
            x = x[-keep:]

            stage = hearing_stage if hearing_stage is not None else self._read_stage()
            low, high = stage_edges(stage)
            taps = band_taps(low, high, float(max(1, s.sample_rate)))
            samples = np.convolve(x, taps, mode="valid")

        base_amp_total = self._BASE_AMP_TOTAL
        noise_rms = self._NOISE_RMS
        thud_amp = self._THUD_AMP

        # Headroom for the fixed bed. With a voice the headroom grows by the
        # voice's RMS level and a soft limiter catches the rare peaks above it.
        max_possible = base_amp_total + 4 * noise_rms + thud_amp
        if self._voice is not None:
            max_possible = max_possible + self._voice.headroom
            gain = (_INT16_MAX * 0.9) / max_possible
            samples = soft_limit(
                samples * gain,
                knee=_INT16_MAX * 0.9,
                # One step below full scale, so rounding never reaches it.
                ceiling=float(_INT16_MAX - 1),
            )
        else:
            gain = (_INT16_MAX * 0.9) / max_possible
            samples = np.clip(samples * gain, -_INT16_MAX, _INT16_MAX)

        q = np.rint(samples).astype(np.int16)
        if maturation_progress is not None:
            scale = 1.0 - float(maturation_progress)
            q = (q.astype(np.float64) * scale).astype(np.int16)
        if channels > 1:
            q = np.repeat(q, channels)
        return q.tobytes()


def stimulus_source_soundscape_rms(
    schedule: StimulusSourceAudioSchedule,
    params: "StimulusSourceParams",
    *,
    seconds: float = 60.0,
) -> float:
    """RMS of the voice-free float soundscape over the first ``seconds``.

    The reference level the maternal voice is set against (its first minute of
    stimulus time for the run seed). ``seconds`` must be finite and greater
    than 0 (ValueError).
    """
    if not math.isfinite(seconds) or seconds <= 0.0:
        raise ValueError("seconds must be finite and greater than 0")

    import numpy as np

    s = schedule
    n = max(1, int(s.frames_per_block))
    sr = float(max(1, s.sample_rate))
    blocks = math.ceil(seconds * sr / n)

    stream = StimulusSourceProceduralAudioStream(
        schedule,
        params=params,
        clock=None,  # type: ignore[arg-type]
        callback=lambda _b: None,
        voice=None,
        awake=None,
    )

    sum_sq = 0.0
    count = 0
    for block_index in range(blocks):
        samples = stream._soundscape(block_index)
        sum_sq += float(np.sum(samples * samples))
        count += samples.shape[0]
    return math.sqrt(sum_sq / max(1, count))


# ---------------------------------------------------------------------------
# Playlist audio source
# ---------------------------------------------------------------------------


class PlaylistAudioStream:
    """An ``_AudioStream`` over the SAME operator-supplied, checksummed manifest
    as the playlist video source.

    ``start()`` verifies EVERY item's sha256 before the run (shared ``verify()``
    semantics); any mismatch raises ``PlaylistVerificationError`` (fail-closed).
    It then decodes each media file's AUDIO track in manifest order via PyAV
    (``av``), resamples to ``sample_rate`` / ``channels``, and emits int16 LE PCM
    blocks into the callback. Each resampled frame contributes exactly its
    ``frame.samples`` (never its padded plane buffer), placed on the item's
    timeline by the decoded timestamps (``_ItemTimeline``): a timestamp gap is
    heard as silence, audio before the position is trimmed, and each item is
    padded or trimmed to its length on the shared clock, so every item's sound
    starts when the clock reaches it. Blocks are paced against the shared clock
    (``_pace_to_clock``): each goes out when the clock reaches its place, a
    stall is caught up by emitting the owed blocks at once (up to
    ``_MAX_OWED_S``) or, further behind, skipped forward to the clock, so the
    delivered position never keeps a lag. ``av`` is required; if it is absent the
    source raises ``PerceptionUnavailableError`` with an install hint — honest
    failure, NEVER a silent no-op or synthetic substitute.

    Persists nothing beyond the manifest it is handed (zero-persistence).
    """

    def __init__(
        self,
        manifest: PlaylistManifest,
        *,
        callback: Callable[[bytes], None],
        sample_rate: int = 16000,
        channels: int = 1,
        frames_per_block: int = 480,
        media_root: str | Path | None = None,
        playlist_clock: PlaylistClock | None = None,
    ) -> None:
        if int(channels) not in (1, 2):
            # The resampler gives mono or stereo; any other count would be
            # resampled to stereo and then rejected frame by frame.
            raise ValueError(
                f"the playlist audio feed delivers 1 or 2 channels; got channels = {channels}"
            )
        self._manifest = manifest
        self._callback = callback
        self._sample_rate = int(sample_rate)
        self._channels = int(channels)
        self._frames_per_block = int(frames_per_block)
        self._root = (
            Path(media_root)
            if media_root is not None
            else Path(manifest.manifest_path).parent
        )
        # Shared start-clock with the video source (injected at boot) so both
        # surfaces report the same item at the same wall-clock moment. A private
        # clock keeps a standalone audio stream working on its own.
        self._clock = playlist_clock or PlaylistClock(len(manifest.items))
        self._delivered_lock = threading.Lock()
        self._delivered: tuple[int, float] | None = None
        self._produce_item_idx = -1
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()
        # The pacing wait (stop wins); tests drive a manual clock through it.
        self._pace_wait: Callable[[float], object] = lambda seconds: self._stopped.wait(
            timeout=seconds
        )
        self._skips = 0  # skips forward to the clock (content-free count)
        self._jumps = 0  # jumps of the presented position followed (stimulus control)
        # The shared clock's position epoch when it has one (a stimulus-control
        # ProgrammeClock); a change makes the pacing resync to the clock.
        self._pace_epoch: Any = None
        # The producer moved from a channel's last item to its first (a wrap on
        # a stimulus-control clock): its next block waits for the clock's lap.
        self._wrap_pending = False
        self._item_failures = 0  # items that failed to open or decode

    @property
    def manifest(self) -> PlaylistManifest:
        return self._manifest

    @property
    def clock(self) -> PlaylistClock:
        return self._clock

    @property
    def current_item(self) -> PlaylistPosition | None:
        """The item currently heard, from the SHARED clock — so it always agrees
        with the video source's ``current_item``. ``None`` before playback starts
        or once the playlist is exhausted. Content-free provenance."""
        if not self._clock.started:
            return None
        idx, offset = self._clock.locate()
        items = self._manifest.items
        if idx >= len(items):
            return None
        it = items[idx]
        return PlaylistPosition(
            title=Path(it.path).name, order=it.order, offset=offset, item_idx=idx
        )

    @property
    def delivered_position(self) -> tuple[int, float] | None:
        """The seconds of the current item's audio actually handed to the
        listener so far, measured by the producer thread. ``None`` before the
        first block is emitted. Content-free provenance."""
        with self._delivered_lock:
            delivered = self._delivered
        if delivered is None:
            return None
        return delivered[0], max(0.0, delivered[1])

    def _begin_item(self, item_idx: int, offset_s: float, *, carried_s: float = 0.0) -> None:
        """Start accounting for ``item_idx``. A producer that resyncs to the
        shared clock seeks to ``offset_s`` inside the item, so the delivered
        position starts there rather than at zero. ``carried_s`` of the
        previous item still queued ahead of this item's first sample start
        its timeline that much earlier, so pacing stays exact across the
        boundary (the reported position never goes below zero)."""
        self._produce_item_idx = item_idx
        with self._delivered_lock:
            self._delivered = (item_idx, max(0.0, float(offset_s)) - max(0.0, float(carried_s)))

    def _update_delivered(self, pcm: bytes, item_idx: int) -> float:
        """Account for ``pcm`` being handed to the listener.

        Returns the block duration in seconds. Resets the cumulative counter
        when the producer moves to a new item.
        """
        with self._delivered_lock:
            if self._delivered is None or self._delivered[0] != item_idx:
                self._delivered = (item_idx, 0.0)
            frames = len(pcm) // (self._channels * 2)
            seconds = frames / float(self._sample_rate)
            self._delivered = (item_idx, self._delivered[1] + seconds)
            return seconds

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        return p if p.is_absolute() else (self._root / p)

    def verify(self) -> None:
        """Hash every item and compare to the manifest (shared fail-closed
        semantics with the video source). A mismatch voids reproducibility, so
        the run must not proceed on unverified media."""
        self._manifest.verify_against(self._root)

    # --- _AudioStream protocol ---------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        # Verify BEFORE importing/decoding anything — a changed file must stop
        # the run before a single sample is read.
        self.verify()
        try:
            import av  # type: ignore[import-untyped]  # noqa: F401
        except ImportError as exc:
            raise PerceptionUnavailableError(
                "PyAV (av) not installed — playlist audio decode requires it; "
                "install with: pip install -e .[audio]"
            ) from exc
        self._stopped.clear()
        self._thread = threading.Thread(
            target=self._produce, name="playlist-audio-producer", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def close(self) -> None:
        self.stop()

    # --- producer ----------------------------------------------------------

    def _clock_duration(self, idx: int) -> float | None:
        """The item's length on the shared clock, or ``None`` when unknown."""
        getter = getattr(self._clock, "duration", None)
        if not callable(getter):
            return None
        try:
            value = getter(idx)
        except Exception:
            log.debug("playlist clock duration lookup failed", exc_info=True)
            return None
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
        return None

    def _produce(self) -> None:
        import av  # type: ignore[import-untyped]

        frame_bytes = self._channels * 2
        block_bytes = self._frames_per_block * frame_bytes
        rate = float(max(1, self._sample_rate))
        carry = bytearray()

        def _emit(pcm: bytes) -> None:
            # Paced against the shared clock (which also owns pause): wait
            # until the clock reaches this block's place on the item timeline.
            # Raises _SkipForward when the block is owed too late to catch up.
            self._pace_to_clock()
            if self._stopped.is_set():
                return
            self._update_delivered(pcm, self._produce_item_idx)
            try:
                self._callback(pcm)
            except Exception:
                log.debug("playlist audio callback raised", exc_info=True)

        def _push(pcm: bytes) -> bool:
            """Queue PCM and emit every full block. False once stopped."""
            carry.extend(pcm)
            while len(carry) >= block_bytes:
                if self._stopped.is_set():
                    return False
                _emit(bytes(carry[:block_bytes]))
                del carry[:block_bytes]
            return not self._stopped.is_set()

        def _push_silence(samples: int) -> bool:
            """Queue ``samples`` frames of silence, a block at a time."""
            remaining = max(0, int(samples)) * frame_bytes
            zeros = bytes(block_bytes)
            while remaining > 0:
                chunk = min(remaining, block_bytes)
                if not _push(zeros[:chunk]):
                    return False
                remaining -= chunk
            return not self._stopped.is_set()

        def _push_frame(rframe: Any, timeline: _ItemTimeline) -> bool:
            """Queue exactly the resampled frame's samples (never its padded
            plane), trimmed to the item's timeline."""
            pcm = _frame_pcm(rframe, self._channels)
            skip, keep = timeline.take(len(pcm) // self._channels)
            if keep <= 0:
                return not self._stopped.is_set()
            lo = skip * self._channels
            return _push(pcm[lo : lo + keep * self._channels].tobytes())

        def _silence_rest_of_item(idx: int) -> bool:
            """Silence from the delivered (and queued) position to the item's
            length on the clock. With no known length, deliver nothing more:
            the next item's first block waits until the clock reaches it."""
            end_s = self._clock_duration(idx)
            if end_s is None:
                return not self._stopped.is_set()
            with self._delivered_lock:
                delivered = self._delivered
            pos = delivered[1] if delivered is not None and delivered[0] == idx else 0.0
            pos += len(carry) / float(frame_bytes) / rate
            return _push_silence(int(round(max(0.0, end_s - pos) * rate)))

        def _play_item(idx: int, item: Any, item_start: float) -> bool:
            """Decode one item from ``item_start`` onto its timeline. False
            once stopped; raises _SkipForward when the clock got away."""
            media = self._resolve(item.path)
            container = av.open(str(media))
            try:
                # Register this item's length on the shared clock (first
                # writer wins). Both surfaces register the container
                # duration, so they agree on the boundary.
                container_s = container_duration_s(container)
                if container_s is not None:
                    self._clock.set_duration(idx, container_s)
                end_s = self._clock_duration(idx) or container_s
                timeline = _ItemTimeline(self._sample_rate, start_s=item_start, end_s=end_s)
                if not container.streams.audio:
                    # Heard as silence for the item's length, so the next
                    # item's sound starts when the clock reaches it.
                    # Index only: the path carries the mount and the title.
                    log.warning(
                        "playlist audio item %d has no audio track; %.3f s of silence",
                        idx,
                        timeline.remaining() / rate,
                    )
                    return _push_silence(timeline.remaining())
                origin = container_origin_s(container)
                resampler = av.audio.resampler.AudioResampler(
                    format="s16",
                    layout="mono" if self._channels == 1 else "stereo",
                    rate=self._sample_rate,
                )
                stream = container.streams.audio[0]
                # H1 — seek within the located item up to the clock's
                # offset. Prefer a fast container seek; if PyAV refuses,
                # decode from the start: the timeline trims every frame
                # before the offset, and frames wholly before it are not
                # even resampled (no _emit, so no pacing waits).
                if item_start > 0:
                    try:
                        container.seek(
                            int((item_start + origin) * AV_TIME_BASE),
                            any_frame=False,
                        )
                    except Exception as exc:
                        log.warning(
                            "playlist audio item %d: seek failed (%s); "
                            "decode-and-dropping to offset %.3fs",
                            idx,
                            type(exc).__name__,
                            item_start,
                        )
                for frame in container.decode(stream):
                    if self._stopped.is_set():
                        return False
                    t_in = _media_time(frame, origin)
                    if timeline.wholly_before(t_in, frame):
                        continue
                    # Per-frame pause park (between frames, which covers
                    # the first block of each item): no PyAV frame iteration
                    # while asleep, so decoders truly idle. Stop wins.
                    self._clock.wait_if_paused(stop_check=self._stopped.is_set)
                    if self._stopped.is_set():
                        return False
                    if not _push_silence(timeline.place(t_in)):
                        return False
                    for rframe in resampler.resample(frame):
                        if rframe is not None and not _push_frame(rframe, timeline):
                            return False
                # Drain the resampler's buffered tail for this item.
                for rframe in _flush_resampler(resampler):
                    if not _push_frame(rframe, timeline):
                        return False
                # Pad (or, via the cap in take(), trim) to the item's length.
                log.info("playlist audio item %d: %s", idx, timeline.summary())
                return _push_silence(timeline.remaining())
            finally:
                container.close()

        # Align to the shared playback origin (idempotent across both feeds) so
        # audio and video start item 0 at the same wall-clock moment.
        self._clock.start()
        # H1 — resync to the shared clock on producer start: a restarted
        # producer must resume at the clock's CURRENT position (the same
        # position the video source is showing), not replay item 0.
        # locate() -> (item_idx, offset_s). A not-yet-anchored clock degrades
        # to a full replay (idx 0, offset 0), which is exactly the old
        # behaviour on the very first start.
        try:
            start_idx, start_offset = self._clock.locate()
        except Exception:
            log.warning(
                "playlist clock locate failed; replaying from start",
                exc_info=True,
            )
            start_idx, start_offset = 0, 0.0
        if start_idx is None:
            start_idx, start_offset = 0, 0.0
        epoch_of = getattr(self._clock, "position_epoch", None)
        self._pace_epoch = epoch_of() if callable(epoch_of) else None
        self._wrap_pending = False
        items = self._manifest.items
        idx, item_start = int(start_idx), float(start_offset)
        try:
            while idx < len(items):
                if self._stopped.is_set():
                    return
                # A partial block of the previous item is still queued; the
                # item's timeline starts that much before its first sample.
                carried_s = len(carry) / float(frame_bytes) / rate
                self._begin_item(idx, item_start, carried_s=carried_s)
                try:
                    try:
                        played = _play_item(idx, items[idx], item_start)
                    except _SkipForward:
                        raise
                    except Exception as exc:
                        # One item failing (unreadable after verify, a decode
                        # error the decoder does not conceal) must not silence
                        # the rest of the programme: hear silence for the rest
                        # of this item and go on with the next on the clock.
                        self._note_item_failure(idx, exc)
                        played = _silence_rest_of_item(idx)
                    if not played:
                        return
                except _SkipForward as skip:
                    # Too far behind to catch up: drop what is queued and
                    # resume where the clock is (the same path as a restart).
                    carry.clear()
                    self._note_skip(skip)
                    self._wrap_pending = False
                    idx, item_start = skip.idx, max(0.0, skip.offset)
                    continue
                following = self._following_item(idx)
                # On a clock that wraps within a channel, the item after the
                # channel's last is its first: ordered by the clock's lap, not
                # by manifest index.
                self._wrap_pending = following <= idx
                idx, item_start = following, 0.0
            # Flush a final short block (zero-padded) so no audio is dropped.
            if carry and not self._stopped.is_set():
                pad = block_bytes - len(carry)
                if pad > 0:
                    carry += b"\x00" * pad
                try:
                    _emit(bytes(carry[:block_bytes]))
                except _SkipForward:
                    pass  # the programme ended while this block was owed
        except Exception:
            log.exception("playlist audio producer crashed")

    def _pace_to_clock(self) -> None:
        """Wait until the shared clock reaches the next block's place.

        The next block starts at the delivered position. A block that is due
        or owed up to ``_MAX_OWED_S`` goes out at once, so after a stall the
        owed blocks are emitted back to back and the delivered position
        returns to the clock instead of keeping the lag. A block owed more
        than that raises ``_SkipForward`` to the clock's position. While the
        clock is paused the producer parks on it; stop wins over every wait.
        """
        with self._delivered_lock:
            delivered = self._delivered
        if delivered is None:
            b_idx, b_start = self._produce_item_idx, 0.0
        else:
            b_idx, b_start = delivered
        located = getattr(self._clock, "locate_with_epoch", None)
        while not self._stopped.is_set():
            self._clock.wait_if_paused(stop_check=self._stopped.is_set)
            if self._stopped.is_set():
                return
            # A clock that can jump (stimulus control) gives its position and
            # its position epoch from one reading; the plain clock has neither.
            if callable(located):
                c_idx, c_off, epoch = located()
            else:
                epoch = None
                c_idx, c_off = self._clock.locate()
            if epoch != self._pace_epoch:
                self._pace_epoch = epoch
                expected_wrap = (
                    self._wrap_pending
                    and c_idx == b_idx
                    and -_MAX_OWED_S <= c_off - b_start <= _MAX_OWED_S
                )
                self._wrap_pending = False
                if not expected_wrap:
                    # The presented position jumped: resync at the clock (the
                    # restart path), whichever way it moved.
                    raise _SkipForward(c_idx, c_off, 0.0, jump=True)
            if callable(located) and c_idx >= len(self._manifest.items):
                # The viewing ended at its perceived length, wherever the
                # wrapping position was: not a lag.
                raise _SkipForward(c_idx, c_off, 0.0, jump=True)
            if self._wrap_pending and epoch == self._pace_epoch:
                # The clock is still on the channel's last item: this block of
                # its first item is due when the clock's lap turns.
                self._pace_wait(_WRAP_POLL_S)
                continue
            if c_idx == b_idx:
                owed = c_off - b_start
            elif c_idx > b_idx:
                owed = self._span(b_idx, b_start, c_idx, c_off)
            else:
                owed = -self._span(c_idx, c_off, b_idx, b_start)
            if owed > _MAX_OWED_S:
                raise _SkipForward(c_idx, c_off, owed)
            if owed >= -_PACE_EPSILON_S:
                return
            self._pace_wait(min(-owed, _PACE_POLL_S))

    def _following_item(self, idx: int) -> int:
        """The item after ``idx``: the next in the manifest, or, on a clock that
        wraps within programme channels (stimulus control), the next item of
        ``idx``'s channel."""
        following = getattr(self._clock, "following_item", None)
        if callable(following):
            return int(following(idx))
        return idx + 1

    def _span(self, from_idx: int, from_off: float, to_idx: int, to_off: float) -> float:
        """Programme seconds from one item position to a later one; infinite
        when a length in between is not yet known (or when ``to_idx`` is past
        the last item, the remainder of the programme plus nothing)."""
        total = 0.0
        for k in range(from_idx, min(to_idx, len(self._manifest.items))):
            d = self._clock_duration(k)
            if d is None:
                return math.inf
            total += d
        return total - from_off + to_off

    def _note_item_failure(self, idx: int, exc: BaseException) -> None:
        """Log an item that failed to open or decode: index and exception
        type only (its text can carry the path, so the title)."""
        self._item_failures += 1
        report = getattr(self._clock, "report_unplayable", None)
        if callable(report):
            report(idx)
        log.warning(
            "playlist audio item %d failed (%s); heard as silence for the rest "
            "of its length, the programme goes on",
            idx,
            type(exc).__name__,
        )

    def _note_skip(self, skip: _SkipForward) -> None:
        """Log a skip forward, content-free: the first at warning, later ones
        at debug (each is counted). A followed jump of the presented position
        is not a lag, and is logged at debug."""
        if skip.jump:
            self._jumps += 1
            log.debug(
                "playlist audio followed a jump of the programme to item %d at %.3f s",
                skip.idx,
                skip.offset,
            )
            return
        self._skips += 1
        level = logging.WARNING if self._skips == 1 else logging.DEBUG
        log.log(
            level,
            "playlist audio fell %.3f s behind the shared clock (more than %.1f s "
            "to catch up); skipped forward to item %d at %.3f s (skip %d; later "
            "skips are logged at debug)",
            skip.owed,
            _MAX_OWED_S,
            skip.idx,
            skip.offset,
            self._skips,
        )


#: Most audio owed at once that the producer catches up by emitting the owed
#: blocks back to back; further behind, it skips forward to the clock.
_MAX_OWED_S = 0.5

#: Longest single pacing wait, so pause, stop and clock changes are noticed.
_PACE_POLL_S = 0.25

#: The pacing wait while a channel's wrap is pending (the clock is within a
#: block of the lap turning).
_WRAP_POLL_S = 0.005

#: A block this close to due goes out (positions are float sums of block
#: lengths, so "exactly due" can come out a rounding error early).
_PACE_EPSILON_S = 1e-6


class _SkipForward(Exception):
    """The audio is owed more than ``_MAX_OWED_S``: resume at the clock."""

    def __init__(self, idx: int, offset: float, owed: float, *, jump: bool = False) -> None:
        super().__init__(idx, offset, owed)
        self.idx = int(idx)
        self.offset = float(offset)
        self.owed = float(owed)
        # The presented position jumped (stimulus control), rather than lag.
        self.jump = bool(jump)


#: Audio more than this far off the item's timeline is re-placed: a later
#: timestamp is preceded by silence, an earlier one is trimmed. Larger than one
#: Vorbis/Opus frame's millisecond rounding, smaller than a perceptible
#: audio-leading lip-sync error (~45 ms, ITU-R BT.1359).
_TIMELINE_TOLERANCE_S = 0.040


class _ItemTimeline:
    """Where the playlist audio is on one item's timeline, in samples.

    ``pos`` counts the samples placed for the item (from the resync offset).
    ``place`` compares a decoded frame's media time with ``pos`` and returns
    the silence to insert before it (a timestamp gap) or arranges for the
    frame's head to be trimmed (audio before the position: after a seek, or
    overlapping timestamps). ``take`` applies that trim and the item's end, so
    an item never delivers more than its length on the shared clock;
    ``remaining`` is the silence that pads a short item to that length.
    """

    def __init__(
        self,
        sample_rate: int,
        *,
        start_s: float,
        end_s: float | None,
        tolerance_s: float = _TIMELINE_TOLERANCE_S,
    ) -> None:
        self._rate = int(sample_rate)
        self.pos = int(round(max(0.0, start_s) * self._rate))
        self.end = int(round(end_s * self._rate)) if end_s else None
        self._tolerance = int(round(tolerance_s * self._rate))
        self._trim = 0
        # Content-free accounting, logged when the item ends.
        self.filled = 0    # silence inserted for timestamp gaps
        self.trimmed = 0   # samples dropped before the position
        self.capped = 0    # samples dropped past the item's end

    def wholly_before(self, t_in: float | None, frame: Any) -> bool:
        """True when a decoded frame ends before the position (so it need not
        be resampled at all)."""
        if t_in is None:
            return False
        samples = getattr(frame, "samples", None)
        rate = getattr(frame, "sample_rate", None)
        if not isinstance(samples, int) or not isinstance(rate, int) or rate <= 0:
            return False
        end = int(round((t_in + samples / rate) * self._rate))
        return end < self.pos - self._tolerance

    def place(self, t_in: float | None) -> int:
        """Silence samples to insert before a frame starting at ``t_in``."""
        self._trim = 0
        if t_in is None:
            return 0
        gap = int(round(t_in * self._rate)) - self.pos
        if gap > self._tolerance:
            if self.end is not None:
                gap = max(0, min(gap, self.end - self.pos))
            self.pos += gap
            self.filled += gap
            return gap
        if gap < -self._tolerance:
            self._trim = -gap
        return 0

    def take(self, n: int) -> tuple[int, int]:
        """``(skip, keep)`` for ``n`` resampled samples: the head to trim and
        the count to deliver (never past the item's end)."""
        skip = min(self._trim, n)
        self._trim -= skip
        self.trimmed += skip
        keep = n - skip
        if self.end is not None:
            capped = max(0, min(keep, self.end - self.pos))
            self.capped += keep - capped
            keep = capped
        self.pos += keep
        return skip, keep

    def summary(self) -> str:
        """One content-free line on how the item's audio was placed."""
        rate = float(self._rate)
        return (
            f"{self.filled / rate:.3f} s of timestamp gaps filled with silence, "
            f"{self.trimmed / rate:.3f} s before the position trimmed, "
            f"{self.capped / rate:.3f} s past the item's end dropped, "
            f"{self.remaining() / rate:.3f} s padded to the item's length"
        )

    def remaining(self) -> int:
        """Samples of silence that pad the item to its end (0 when unknown)."""
        if self.end is None:
            return 0
        return max(0, self.end - self.pos)


def _media_time(frame: Any, origin: float) -> float | None:
    """A decoded frame's time on the item's timeline, or ``None`` without a
    timestamp."""
    pts = getattr(frame, "pts", None)
    time_base = getattr(frame, "time_base", None)
    if pts is None or not time_base:
        return None
    return float(pts) * float(time_base) - origin


def _frame_pcm(frame: Any, channels: int) -> "np.ndarray":
    """Exactly ``frame.samples`` int16 samples per channel, interleaved.

    A PyAV plane is a padded buffer (a 193-sample mono s16 frame is a 512-byte
    plane), so the plane bytes are never used: ``to_ndarray()`` gives
    ``(1, samples x channels)`` for a packed layout and ``(channels, samples)``
    for a planar one, which is transposed to interleave.
    """
    import numpy as np

    samples = int(frame.samples)
    arr = np.asarray(frame.to_ndarray())
    if arr.dtype != np.int16:
        raise ValueError(f"playlist audio resampler gave {arr.dtype}, expected int16")
    fmt = getattr(frame, "format", None)
    planar = bool(getattr(fmt, "is_planar", False))
    if planar and arr.ndim == 2 and arr.shape[0] == channels:
        flat = arr[:, :samples].T.reshape(-1)
    else:
        flat = arr.reshape(-1)[: samples * channels]
    if flat.size != samples * channels:
        raise ValueError(
            f"playlist audio frame holds {flat.size} values, expected "
            f"{samples} samples x {channels} channels"
        )
    return np.ascontiguousarray(flat, dtype="<i2")


def _flush_resampler(resampler: Any) -> list[Any]:
    """The resampler's buffered tail at the end of an item."""
    try:
        out = resampler.resample(None)
    except Exception:
        log.debug("playlist audio resampler flush raised", exc_info=True)
        return []
    return [f for f in (out or ()) if f is not None]


__all__ = [
    "SeededAudioSchedule",
    "SeededProceduralAudioStream",
    "StimulusSourceAudioSchedule",
    "StimulusSourceProceduralAudioStream",
    "stimulus_source_soundscape_rms",
    "soft_limit",
    "PlaylistAudioStream",
    "PlaylistPosition",
]
