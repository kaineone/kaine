# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import hashlib

import numpy as np
import pytest

from kaine.modules.audition.feed import (
    StimulusSourceAudioSchedule,
    StimulusSourceProceduralAudioStream,
    stimulus_source_soundscape_rms,
)
from kaine.modules.audition.hearing_band import (
    HEARING_BAND_STAGES,
    HearingBandParams,
    stage_edges,
)
from kaine.modules.audition.hearing_stage_state import HearingStageState
from kaine.modules.audition.maternal_voice import (
    MaternalVoiceLayer,
    MaternalVoiceParams,
    MaternalVoiceRepertoire,
)
from kaine.modules.stimulus_source_signal import StimulusSourceParams


@pytest.fixture(scope="module")
def schedule():
    return StimulusSourceAudioSchedule(
        seed=3, sample_rate=16000, channels=1, frames_per_block=480
    )


@pytest.fixture(scope="module")
def params():
    return StimulusSourceParams()


@pytest.fixture(scope="module")
def background_rms(schedule, params):
    return stimulus_source_soundscape_rms(schedule, params)


@pytest.fixture(scope="module")
def rep_500():
    pytest.importorskip("av")
    return MaternalVoiceRepertoire.load(sample_rate=16000, lowpass_hz=500.0)


@pytest.fixture(scope="module")
def rep_3000():
    pytest.importorskip("av")
    return MaternalVoiceRepertoire.load(sample_rate=16000, lowpass_hz=3000.0)


@pytest.fixture(scope="module")
def voice_500(rep_500, schedule, params, background_rms):
    return MaternalVoiceLayer(
        rep_500,
        MaternalVoiceParams(),
        seed=3,
        stimulus_params=params,
        background_rms=background_rms,
    )


@pytest.fixture(scope="module")
def voice_3000(rep_3000, schedule, params, background_rms):
    return MaternalVoiceLayer(
        rep_3000,
        MaternalVoiceParams(),
        seed=3,
        stimulus_params=params,
        background_rms=background_rms,
    )


def _make_stream(
    schedule, params, *, voice=None, hearing=None, awake=None, hearing_stage=None
):
    return StimulusSourceProceduralAudioStream(
        schedule,
        params=params,
        clock=None,
        callback=lambda _b: None,
        voice=voice,
        hearing=hearing,
        awake=awake,
        hearing_stage=hearing_stage,
    )


def test_disabled_band_is_byte_identical_golden(voice_500, schedule, params):
    expected = {
        (False, False): "6fe2a2c706cfc127518ed1b5371660d17bfe9046dde367d36f46e011a627cb50",
        (True, False): "f1a1ab7fc4d2f18486ba2232f9e7c9e32e331f793679912bd7d7fa4671e524f8",
    }
    for has_voice, hearing in [
        (False, None),
        (False, HearingBandParams(enabled=False)),
        (True, None),
        (True, HearingBandParams(enabled=False)),
    ]:
        voice = voice_500 if has_voice else None
        stream = _make_stream(schedule, params, voice=voice, hearing=hearing)
        blocks = list(range(0, 400)) + list(range(240000, 240400))
        chunks = b"".join(
            stream.pcm_at(k, awake_seconds=k * 0.03) for k in blocks
        )
        digest = hashlib.sha256(chunks).hexdigest()
        assert digest == expected[(has_voice, False)]


def test_band_is_deterministic_and_seed_keyed(voice_3000, schedule, params):
    a = 100.0
    s1 = _make_stream(
        schedule, params, voice=voice_3000, hearing=HearingBandParams()
    )
    s2 = _make_stream(
        schedule, params, voice=voice_3000, hearing=HearingBandParams()
    )
    b1 = b"".join(s1.pcm_at(k, awake_seconds=a, hearing_stage=2) for k in range(50))
    b2 = b"".join(s2.pcm_at(k, awake_seconds=a, hearing_stage=2) for k in range(50))
    assert b1 == b2

    schedule4 = StimulusSourceAudioSchedule(
        seed=4, sample_rate=16000, channels=1, frames_per_block=480
    )
    s3 = _make_stream(
        schedule4, params, voice=voice_3000, hearing=HearingBandParams()
    )
    b3 = b"".join(s3.pcm_at(k, awake_seconds=a, hearing_stage=2) for k in range(50))
    assert b3 != b1


def test_block_independent_of_render_history(
    schedule, params, rep_3000, background_rms
):
    layer_params = MaternalVoiceParams()
    for awake, stage in ((100.0, 0), (30000.0, 2), (90000.0, 4)):
        for k in (5, 7777, 3000000):
            layer_only = MaternalVoiceLayer(
                rep_3000,
                layer_params,
                seed=3,
                stimulus_params=params,
                background_rms=background_rms,
            )
            only = _make_stream(
                schedule,
                params,
                voice=layer_only,
                hearing=HearingBandParams(),
            ).pcm_at(k, awake_seconds=awake, hearing_stage=stage)

            layer_hist = MaternalVoiceLayer(
                rep_3000,
                layer_params,
                seed=3,
                stimulus_params=params,
                background_rms=background_rms,
            )
            hist_stream = _make_stream(
                schedule,
                params,
                voice=layer_hist,
                hearing=HearingBandParams(),
            )
            last = None
            for j in range(k - 10, k + 1):
                last = hist_stream.pcm_at(
                    j, awake_seconds=awake, hearing_stage=stage
                )
            assert only == last

    for k in (0, 1):
        layer = MaternalVoiceLayer(
            rep_3000,
            layer_params,
            seed=3,
            stimulus_params=params,
            background_rms=background_rms,
        )
        stream = _make_stream(
            schedule, params, voice=layer, hearing=HearingBandParams()
        )
        for j in range(0, k + 1):
            out = stream.pcm_at(j, awake_seconds=0.0)

        layer2 = MaternalVoiceLayer(
            rep_3000,
            layer_params,
            seed=3,
            stimulus_params=params,
            background_rms=background_rms,
        )
        only = _make_stream(
            schedule, params, voice=layer2, hearing=HearingBandParams()
        ).pcm_at(k, awake_seconds=0.0)
        assert out == only


def test_restart_resumes_band(schedule, params, tmp_path):
    path = tmp_path / "hearing_stage.json"
    path.write_text('{"version": 1, "stage": 2, "dwell_seconds": 10.0}')
    state_a = HearingStageState.load(HearingBandParams(), path=path)
    state_b = HearingStageState.load(HearingBandParams(), path=path)
    stream_a = _make_stream(
        schedule,
        params,
        hearing=HearingBandParams(),
        hearing_stage=lambda: state_a.stage,
    )
    stream_b = _make_stream(
        schedule,
        params,
        hearing=HearingBandParams(),
        hearing_stage=lambda: state_b.stage,
    )
    assert stream_a.pcm_at(1234) == stream_b.pcm_at(1234)
    assert stream_a.pcm_at(1234) == stream_a.pcm_at(1234, hearing_stage=2)
    assert stream_a.pcm_at(1234) != stream_a.pcm_at(1234, hearing_stage=0)
    assert stage_edges(state_a.stage) == HEARING_BAND_STAGES[2]


def test_spectrum_follows_moving_edges(schedule, params):
    stream = _make_stream(schedule, params, hearing=HearingBandParams())
    stage0_below_300 = None
    for s in range(5):
        a = 600.0 + s * 3600.0
        k0 = int(a / 0.03)
        chunks = b"".join(
            stream.pcm_at(k, awake_seconds=a, hearing_stage=s)
            for k in range(k0, k0 + 2000)
        )
        x = np.frombuffer(chunks, dtype="<i2").astype(np.float64)
        x = x[2000:]
        pwr = np.abs(np.fft.rfft(x)) ** 2
        freqs = np.fft.rfftfreq(x.size, 1 / 16000.0)

        lo, hi = HEARING_BAND_STAGES[s]
        in_band = np.ones_like(freqs, dtype=bool)
        if lo is not None:
            in_band &= freqs >= lo
        else:
            in_band &= freqs >= 0.0
        if hi is not None:
            in_band &= freqs <= hi
        else:
            in_band &= freqs <= 8000.0

        out_band = np.zeros_like(freqs, dtype=bool)
        if lo is not None:
            out_band |= freqs < lo / np.sqrt(2)
        if hi is not None:
            out_band |= freqs > hi * np.sqrt(2)

        p_in = float(np.sum(pwr[in_band]))
        p_out = float(np.sum(pwr[out_band]))
        if s < 4:
            assert 10.0 * np.log10(p_in / p_out) >= 40.0

        below_300 = freqs < 300.0
        p_below = float(np.sum(pwr[below_300]))
        if s == 0:
            stage0_below_300 = p_below
        elif s == 2:
            assert 10.0 * np.log10(p_below / stage0_below_300) >= 10.0


def test_heartbeat_thud_heard_from_stage_two(schedule, params):
    on = _make_stream(schedule, params, hearing=HearingBandParams())
    off = _make_stream(schedule, params, hearing=None)

    def thud_power(chunks):
        x = np.frombuffer(chunks, dtype="<i2").astype(np.float64)[2000:]
        pwr = np.abs(np.fft.rfft(x)) ** 2
        freqs = np.fft.rfftfreq(x.size, 1 / 16000.0)
        mask = (freqs >= 40.0) & (freqs <= 60.0)
        return float(np.sum(pwr[mask]))

    for s in range(5):
        a = 600.0 + s * 3600.0
        k0 = int(a / 0.03)
        on_chunks = b"".join(
            on.pcm_at(k, awake_seconds=a, hearing_stage=s)
            for k in range(k0, k0 + 2000)
        )
        off_chunks = b"".join(
            off.pcm_at(k, awake_seconds=a) for k in range(k0, k0 + 2000)
        )
        p_on = thud_power(on_chunks)
        p_off = thud_power(off_chunks)
        ratio_db = 10.0 * np.log10(p_on / p_off)
        if s in (0, 1):
            assert ratio_db <= -40.0
        else:
            assert abs(ratio_db) <= 1.0


def test_open_band_is_the_band_off_stream_delayed(schedule, params):
    on = _make_stream(schedule, params, hearing=HearingBandParams())
    off = _make_stream(schedule, params, hearing=None)
    awake = 600.0
    k0 = 3000000

    on_chunks = b"".join(
        on.pcm_at(k, awake_seconds=awake, hearing_stage=4)
        for k in range(k0, k0 + 10)
    )
    off_chunks = b"".join(
        off.pcm_at(k, awake_seconds=awake) for k in range(k0 - 2, k0 + 10)
    )

    on_x = np.frombuffer(on_chunks, dtype="<i2")
    off_x = np.frombuffer(off_chunks, dtype="<i2")
    start = 2 * 480 - 512
    expected = off_x[start:start + 10 * 480]
    assert np.array_equal(on_x, expected)


def test_band_reaches_voice_formants_late(
    schedule, params, rep_3000, background_rms
):
    layer_params = MaternalVoiceParams()
    probe = MaternalVoiceLayer(
        rep_3000,
        layer_params,
        seed=3,
        stimulus_params=params,
        background_rms=background_rms,
    )
    n = 480000
    slot = None
    for t in range(400):
        chunk = probe.render(t * n, n, 0.0)
        if np.any(chunk):
            slot = t
            break
    assert slot is not None, "no talking slot found in 400 slots"

    start_block = slot * 1000

    layer0 = MaternalVoiceLayer(
        rep_3000,
        layer_params,
        seed=3,
        stimulus_params=params,
        background_rms=background_rms,
    )
    stream0 = _make_stream(
        schedule, params, voice=layer0, hearing=HearingBandParams()
    )
    chunks0 = b"".join(
        stream0.pcm_at(start_block + i, awake_seconds=600.0, hearing_stage=0)
        for i in range(1000)
    )

    layer4 = MaternalVoiceLayer(
        rep_3000,
        layer_params,
        seed=3,
        stimulus_params=params,
        background_rms=background_rms,
    )
    stream4 = _make_stream(
        schedule, params, voice=layer4, hearing=HearingBandParams()
    )
    chunks4 = b"".join(
        stream4.pcm_at(start_block + i, awake_seconds=600.0, hearing_stage=4)
        for i in range(1000)
    )

    def formant_ratio(chunks):
        x = np.frombuffer(chunks, dtype="<i2").astype(np.float64)
        pwr = np.abs(np.fft.rfft(x)) ** 2
        freqs = np.fft.rfftfreq(x.size, 1 / 16000.0)
        formant = (freqs >= 1000.0) & (freqs <= 2800.0)
        p_formant = float(np.sum(pwr[formant]))
        p_total = float(np.sum(pwr))
        return 10.0 * np.log10(p_formant / p_total)

    assert formant_ratio(chunks4) - formant_ratio(chunks0) >= 20.0


def test_disabled_params_attach_nothing(schedule, params, voice_3000):
    def provider() -> float:
        return 123.0

    disabled = _make_stream(
        schedule,
        params,
        hearing=HearingBandParams(enabled=False),
        awake=provider,
    )
    assert disabled._read_awake() is None

    band_only = _make_stream(
        schedule,
        params,
        hearing=HearingBandParams(enabled=True),
        awake=provider,
    )
    assert band_only._read_awake() is None

    with_voice = _make_stream(
        schedule,
        params,
        voice=voice_3000,
        hearing=HearingBandParams(enabled=True),
        awake=provider,
    )
    assert with_voice._read_awake() == 123.0


def test_filter_follows_the_stage_provider_not_the_awake_time(schedule, params):
    def render(stage, awake):
        stream = _make_stream(
            schedule,
            params,
            hearing=HearingBandParams(),
            awake=lambda: awake,
            hearing_stage=lambda: stage,
        )
        return b"".join(stream.pcm_at(k) for k in range(300, 330))

    assert render(0, 100.0) == render(0, 90000.0)
    assert render(4, 100.0) == render(4, 90000.0)
    assert render(0, 50000.0) != render(4, 50000.0)


def test_changing_the_stage_mid_stream_changes_later_blocks(schedule, params):
    stage = {"value": 0}
    stream = _make_stream(
        schedule,
        params,
        hearing=HearingBandParams(),
        hearing_stage=lambda: stage["value"],
    )
    before = stream.pcm_at(500)
    assert stream.pcm_at(500) == before
    stage["value"] = 4
    after = stream.pcm_at(500)
    assert after != before
    assert after == stream.pcm_at(500, hearing_stage=4)


def test_no_stage_provider_means_stage_zero(schedule, params):
    stream = _make_stream(schedule, params, hearing=HearingBandParams())
    assert stream.pcm_at(500) == stream.pcm_at(500, hearing_stage=0)


def test_disabled_band_ignores_the_stage_provider(schedule, params):
    plain = _make_stream(schedule, params)
    disabled = _make_stream(
        schedule,
        params,
        hearing=HearingBandParams(enabled=False),
        hearing_stage=lambda: 3,
    )
    for k in (0, 1, 777, 240000):
        assert disabled.pcm_at(k) == plain.pcm_at(k)
