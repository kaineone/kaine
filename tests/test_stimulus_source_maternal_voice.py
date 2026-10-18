# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import numpy as np
import pytest

from kaine.modules.audition.feed import (
    StimulusSourceAudioSchedule,
    StimulusSourceProceduralAudioStream,
    stimulus_source_soundscape_rms,
)
from kaine.modules.stimulus_source_signal import StimulusSourceParams

_INT16_MAX = 32767


def _reference_pcm(seed, block_index, n, sr, channels, params, maturation_progress):
    """Verbatim copy of the voice-free pcm_at algorithm before the refactor."""
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

    n = max(1, int(n))
    sr = float(max(1, sr))
    channels = max(1, int(channels))
    seed = int(seed)

    t0 = block_index * n / sr
    t = t0 + np.arange(n, dtype=np.float64) / sr
    samples = np.zeros(n, dtype=np.float64)
    two_pi = 2.0 * math.pi

    # Low-frequency soundscape: a few seed-derived sinusoids below the
    # low-pass corner.
    n_base = 4
    base_amp_total = 0.35
    lp = float(params.lowpass_hz)
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
    # FIR. The output is continuous across block boundaries and still a
    # pure function of (seed, block_index).
    noise_rms = 0.08
    samples += noise_rms * lowpassed_noise(seed, block_index, n, sr, lp)

    # Maternal heartbeat thud, phase-shared with the video pulse.
    phase = heartbeat_phase(seed, t, params)
    env = beat_pulse(phase)
    thud_f = 45.0 + 10.0 * _unit_float(
        _keyed_u64(seed, 0, SEED_SALT_AUDIO | 0x40)
    )
    thud_ph = two_pi * _unit_float(
        _keyed_u64(seed, 0, SEED_SALT_AUDIO | 0x41)
    )
    thud_amp = 0.35
    samples += thud_amp * env * np.sin(two_pi * thud_f * t + thud_ph)

    # Fixed headroom so the stream almost never clips; rare noise peaks
    # beyond 4 RMS are clipped.
    max_possible = base_amp_total + 4 * noise_rms + thud_amp
    gain = (_INT16_MAX * 0.9) / max_possible
    samples = np.clip(samples * gain, -_INT16_MAX, _INT16_MAX)

    q = np.rint(samples).astype(np.int16)
    if maturation_progress is not None:
        scale = 1.0 - float(maturation_progress)
        q = (q.astype(np.float64) * scale).astype(np.int16)
    if channels > 1:
        q = np.repeat(q, channels)
    return q.tobytes()


@pytest.fixture
def schedule():
    return StimulusSourceAudioSchedule(
        seed=20260928, sample_rate=16000, channels=1, frames_per_block=480
    )


@pytest.fixture
def params():
    return StimulusSourceParams()


@pytest.mark.parametrize("seed", [0, 20260928])
@pytest.mark.parametrize("channels", [1, 2])
@pytest.mark.parametrize(
    "block_index",
    list(range(300)) + [10000, 123457, 4000000],
)
def test_voice_free_byte_identical(seed, channels, block_index):
    params = StimulusSourceParams()
    schedule = StimulusSourceAudioSchedule(
        seed=seed, sample_rate=16000, channels=channels, frames_per_block=480
    )
    stream = StimulusSourceProceduralAudioStream(
        schedule, params=params, clock=None, callback=lambda _b: None
    )
    maturation = 0.4 if block_index == 77 else None
    expected = _reference_pcm(
        seed, block_index, 480, 16000, channels, params, maturation
    )
    got = stream.pcm_at(block_index, maturation_progress=maturation)
    assert got == expected


def test_soundscape_rms(schedule, params):
    rms = stimulus_source_soundscape_rms(schedule, params)
    assert rms > 0.0
    assert stimulus_source_soundscape_rms(schedule, params) == rms
    with pytest.raises(ValueError):
        stimulus_source_soundscape_rms(schedule, params, seconds=0.0)
    with pytest.raises(ValueError):
        stimulus_source_soundscape_rms(schedule, params, seconds=-1.0)
    with pytest.raises(ValueError):
        stimulus_source_soundscape_rms(schedule, params, seconds=float("inf"))
    with pytest.raises(ValueError):
        stimulus_source_soundscape_rms(schedule, params, seconds=float("nan"))


def _make_voice(schedule, params, seed, episode_probability=1.0):
    pytest.importorskip("av")
    from kaine.modules.audition.maternal_voice import (
        MaternalVoiceLayer,
        MaternalVoiceParams,
        MaternalVoiceRepertoire,
    )

    rep = MaternalVoiceRepertoire.load()
    background_rms = stimulus_source_soundscape_rms(schedule, params)
    return MaternalVoiceLayer(
        rep,
        MaternalVoiceParams(episode_probability=episode_probability),
        seed=seed,
        stimulus_params=params,
        background_rms=background_rms,
    )


def test_voiced_deterministic_and_seed_sensitive(schedule, params):
    voice1 = _make_voice(schedule, params, seed=schedule.seed)
    voice2 = _make_voice(schedule, params, seed=schedule.seed)
    voice3 = _make_voice(schedule, params, seed=schedule.seed + 1)

    stream1 = StimulusSourceProceduralAudioStream(
        schedule,
        params=params,
        clock=None,
        callback=lambda _b: None,
        voice=voice1,
        awake=lambda: 0.0,
    )
    stream2 = StimulusSourceProceduralAudioStream(
        schedule,
        params=params,
        clock=None,
        callback=lambda _b: None,
        voice=voice2,
        awake=lambda: 0.0,
    )
    stream3 = StimulusSourceProceduralAudioStream(
        schedule,
        params=params,
        clock=None,
        callback=lambda _b: None,
        voice=voice3,
        awake=lambda: 0.0,
    )

    for block_index in range(2000):
        b1 = stream1.pcm_at(
            block_index, awake_seconds=stream1._read_awake()
        )
        b2 = stream2.pcm_at(
            block_index, awake_seconds=stream2._read_awake()
        )
        assert b1 == b2

    different = False
    for block_index in range(2000):
        b1 = stream1.pcm_at(
            block_index, awake_seconds=stream1._read_awake()
        )
        b3 = stream3.pcm_at(
            block_index, awake_seconds=stream3._read_awake()
        )
        if b1 != b3:
            different = True
            break
    assert different


def test_voiced_headroom_and_not_just_gain(schedule, params):
    voice = _make_voice(schedule, params, seed=schedule.seed)
    voiced = StimulusSourceProceduralAudioStream(
        schedule,
        params=params,
        clock=None,
        callback=lambda _b: None,
        voice=voice,
        awake=lambda: 0.0,
    )
    free = StimulusSourceProceduralAudioStream(
        schedule, params=params, clock=None, callback=lambda _b: None
    )
    n = schedule.frames_per_block

    for block_index in range(4000):
        pcm = voiced.pcm_at(block_index, awake_seconds=0.0)
        samples = np.frombuffer(pcm, dtype=np.int16)
        assert np.max(samples) < _INT16_MAX
        assert np.min(samples) > -_INT16_MAX - 1

    non_zero_block = None
    for block_index in range(4000):
        rendered = voice.render(block_index * n, n, 0.0)
        if np.any(rendered != 0.0):
            non_zero_block = block_index
            break
    assert non_zero_block is not None, "voice never rendered any non-zero samples"

    voiced_pcm = voiced.pcm_at(non_zero_block, awake_seconds=0.0)
    free_pcm = free.pcm_at(non_zero_block)
    assert voiced_pcm != free_pcm


def test_voiced_awake_frozen(schedule, params):
    # Sleep: awake time stops while stimulus time runs on. Speech continues and
    # no item beyond the initially unlocked ones is ever chosen.
    voice = _make_voice(schedule, params, seed=schedule.seed)
    rep = voice.repertoire
    stream = StimulusSourceProceduralAudioStream(
        schedule, params=params, clock=None, callback=lambda _b: None,
        voice=voice, awake=lambda: 0.0,
    )
    slot_blocks = voice._slot_n // schedule.frames_per_block
    any_nonempty = False
    for slot in range(240):
        # Render the slot's first block through the stream so the plan is
        # fixed by the stream's own awake provider.
        stream.pcm_at(slot * slot_blocks)
        plan = voice.plan_for(slot, 1.0e9)
        if plan:
            any_nonempty = True
        for utt in plan:
            assert utt.item < rep.initial_unlocked
    assert any_nonempty, "no talking happened with a frozen awake provider"


def test_read_awake_returns_provider_or_none(schedule, params):
    free = StimulusSourceProceduralAudioStream(
        schedule, params=params, clock=None, callback=lambda _b: None
    )
    assert free._read_awake() is None

    class FakeVoice:
        peak = 0.0

        class _Rep:
            sample_rate = schedule.sample_rate

        repertoire = _Rep()

        def render(self, start, n, awake):
            return np.zeros(n, dtype=np.float64)

    values = iter([0.0, 1.5, 3.0])
    voiced = StimulusSourceProceduralAudioStream(
        schedule,
        params=params,
        clock=None,
        callback=lambda _b: None,
        voice=FakeVoice(),
        awake=lambda: next(values),
    )
    assert voiced._read_awake() == 0.0
    assert voiced._read_awake() == 1.5
    assert voiced._read_awake() == 3.0


def test_voice_sample_rate_mismatch(schedule, params):
    class BadVoice:
        peak = 0.0

        class _Rep:
            sample_rate = 8000

        repertoire = _Rep()

        def render(self, start, n, awake):
            return np.zeros(n, dtype=np.float64)

    with pytest.raises(ValueError, match="8000"):
        StimulusSourceProceduralAudioStream(
            schedule,
            params=params,
            clock=None,
            callback=lambda _b: None,
            voice=BadVoice(),
        )
