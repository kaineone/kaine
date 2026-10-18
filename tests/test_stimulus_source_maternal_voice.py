# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import numpy as np
import pytest

from kaine.modules.audition.feed import (
    StimulusSourceAudioSchedule,
    StimulusSourceProceduralAudioStream,
    soft_limit,
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


def test_soft_limit():
    knee = 10.0
    ceiling = 12.0

    # Identity below the knee.
    below = np.linspace(-knee, knee, 2001)
    np.testing.assert_array_equal(soft_limit(below, knee=knee, ceiling=ceiling), below)

    # Never above the ceiling (tanh saturates to it in floating point for
    # huge inputs) and strictly below it over the range the stream produces.
    huge = np.array([-1e9, -1e6, -1e3, 0.0, 1e3, 1e6, 1e9])
    limited = soft_limit(huge, knee=knee, ceiling=ceiling)
    assert np.all(np.abs(limited) <= ceiling)
    moderate = np.linspace(-(knee + 5 * (ceiling - knee)), knee + 5 * (ceiling - knee), 1001)
    assert np.all(np.abs(soft_limit(moderate, knee=knee, ceiling=ceiling)) < ceiling)

    # Odd symmetry.
    assert np.allclose(
        soft_limit(-huge, knee=knee, ceiling=ceiling),
        -soft_limit(huge, knee=knee, ceiling=ceiling),
    )

    # Monotonic non-decreasing over a dense grid.
    grid = np.linspace(-1e3, 1e3, 100001)
    out = soft_limit(grid, knee=knee, ceiling=ceiling)
    assert np.all(np.diff(out) >= -1e-12)

    # Numerical derivative just above the knee is essentially 1.
    h = 1e-6
    left = soft_limit(np.array([knee - h]), knee=knee, ceiling=ceiling)[0]
    right = soft_limit(np.array([knee + h]), knee=knee, ceiling=ceiling)[0]
    assert abs(((right - left) / (2 * h)) - 1.0) < 1e-3

    # Validation.
    with pytest.raises(ValueError):
        soft_limit(np.array([1.0]), knee=ceiling, ceiling=ceiling)
    with pytest.raises(ValueError):
        soft_limit(np.array([1.0]), knee=ceiling + 1.0, ceiling=ceiling)
    with pytest.raises(ValueError):
        soft_limit(np.array([1.0]), knee=0.0, ceiling=ceiling)
    with pytest.raises(ValueError):
        soft_limit(np.array([1.0]), knee=-1.0, ceiling=ceiling)


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


def test_voiced_bed_level_lowered(schedule, params):
    voice = _make_voice(schedule, params, seed=schedule.seed)
    n = schedule.frames_per_block

    quiet_start = None
    candidate = 0
    while candidate < 50000:
        rendered = [
            voice.render((candidate + i) * n, n, 0.0) for i in range(200)
        ]
        if all(np.all(r == 0.0) for r in rendered):
            quiet_start = candidate
            break
        candidate += 200
    assert quiet_start is not None, "could not find 200 consecutive silent blocks"

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

    voiced_medians = []
    free_medians = []
    for block_index in range(quiet_start, quiet_start + 200):
        v = np.frombuffer(
            voiced.pcm_at(block_index, awake_seconds=0.0), dtype=np.int16
        )
        f = np.frombuffer(free.pcm_at(block_index), dtype=np.int16)
        voiced_medians.append(float(np.median(np.abs(v))))
        free_medians.append(float(np.median(np.abs(f))))

    ratio_db = 20.0 * np.log10(np.median(voiced_medians) / np.median(free_medians))
    assert -3.0 < ratio_db < -1.5


def test_voiced_soft_limiter_rarely_acts(schedule, params):
    voice = _make_voice(
        schedule, params, seed=schedule.seed, episode_probability=1.0
    )
    n = schedule.frames_per_block
    stream = StimulusSourceProceduralAudioStream(
        schedule,
        params=params,
        clock=None,
        callback=lambda _b: None,
        voice=voice,
        awake=lambda: 0.0,
    )

    base_amp_total = stream._BASE_AMP_TOTAL
    noise_rms = stream._NOISE_RMS
    thud_amp = stream._THUD_AMP
    max_possible = base_amp_total + 4 * noise_rms + thud_amp + voice.headroom
    gain = (_INT16_MAX * 0.9) / max_possible
    knee = _INT16_MAX * 0.9

    voiced_samples = 0
    exceeded = 0
    for block_index in range(20000):
        mix = stream._soundscape(block_index) + voice.render(
            block_index * n, n, 0.0
        )
        scaled = mix * gain
        voice_render = voice.render(block_index * n, n, 0.0)
        nonzero = voice_render != 0.0
        voiced_samples += int(np.count_nonzero(nonzero))
        exceeded += int(np.count_nonzero((np.abs(scaled) > knee) & nonzero))

    assert voiced_samples > 0
    share = exceeded / voiced_samples
    assert share < 0.01


def test_voiced_no_full_scale_over_long_run(schedule, params):
    voice = _make_voice(
        schedule, params, seed=schedule.seed, episode_probability=1.0
    )
    stream = StimulusSourceProceduralAudioStream(
        schedule,
        params=params,
        clock=None,
        callback=lambda _b: None,
        voice=voice,
        awake=lambda: 0.0,
    )

    for block_index in range(20000):
        pcm = stream.pcm_at(block_index, awake_seconds=0.0)
        samples = np.frombuffer(pcm, dtype=np.int16)
        assert np.max(samples) < _INT16_MAX
        assert np.min(samples) > -_INT16_MAX - 1


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
