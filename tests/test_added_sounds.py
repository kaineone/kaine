# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The developmental stimulus's added sounds: the recurring melody and the outside voice.

Every test uses the shipped files in kaine/modules/audition/added_sounds_data/ and
the real stream (StimulusSourceProceduralAudioStream), built through the boot
factory where the scenario is about configuration.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("av")

from kaine.boot.perception_feed import (
    _added_sounds_params,
    _build_perception_feed_audio_factory,
    _hearing_band_params,
    _maternal_voice_params,
    _stimulus_source_params,
)
from kaine.modules.audition import added_sounds as added_sounds_mod
from kaine.modules.audition.added_sounds import (
    ADDED_SOUNDS_DATA_DIR,
    RAMP_SECONDS,
    AddedSoundsLayer,
    AddedSoundsParams,
    AddedSoundsRepertoire,
)
from kaine.modules.audition.feed import (
    StimulusSourceAudioSchedule,
    StimulusSourceProceduralAudioStream,
    stimulus_source_soundscape_rms,
)
from kaine.modules.audition.hearing_band import HEARING_BAND_STAGES, HEARING_TOP_TONE_HZ, band_taps
from kaine.modules.audition.live import PerceptionUnavailableError
from kaine.modules.audition.maternal_voice import MaternalVoiceLayer, MaternalVoiceRepertoire

SR = 16000
FPB = 480
SLOT = 30 * SR


@pytest.fixture(scope="module")
def parts():
    """The shipped repertoires and the soundscape level for seed 7, as the boot builds them."""
    feed = {"seed": 7, "stimulus_source": {}}
    params = _stimulus_source_params(feed)
    schedule = StimulusSourceAudioSchedule(seed=7, sample_rate=SR, channels=1, frames_per_block=FPB)
    return {
        "params": params,
        "hearing": _hearing_band_params(feed),
        "voice_params": _maternal_voice_params(feed),
        "voice_rep": MaternalVoiceRepertoire.load(sample_rate=SR, lowpass_hz=HEARING_TOP_TONE_HZ),
        "added_rep": AddedSoundsRepertoire.load(sample_rate=SR, lowpass_hz=HEARING_TOP_TONE_HZ),
        "bg": stimulus_source_soundscape_rms(schedule, params),
    }


def _voice(parts, seed):
    return MaternalVoiceLayer(
        parts["voice_rep"], parts["voice_params"], seed=seed, stimulus_params=parts["params"], background_rms=parts["bg"]
    )


def _layer(parts, seed=7, params=None, voice="default"):
    v = _voice(parts, seed) if voice == "default" else voice
    return AddedSoundsLayer(
        parts["added_rep"],
        params or AddedSoundsParams(),
        seed=seed,
        voice_params=parts["voice_params"],
        voice=v,
        background_rms=parts["bg"],
    )


def _first_slot(layer, kind, start=0, limit=20000):
    for slot in range(start, limit):
        sound = layer.slot_sound(slot)
        if sound is not None and sound.kind == kind:
            return slot, sound
    raise AssertionError(f"no {kind} slot in the first {limit} slots")


def _band_power(x, lo, hi, sr=SR):
    power = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(x.size, 1.0 / sr)
    return float(power[(f >= lo) & (f < hi)].sum()), float(power.sum())


# --- configuration -----------------------------------------------------------


def test_params_defaults_ranges_and_unknown_keys():
    assert AddedSoundsParams.from_section(None) == AddedSoundsParams(True, 0.02, 0.05)
    assert AddedSoundsParams.from_section({"enabled": False, "melody_probability": 0, "outside_voice_probability": 1}) == (
        AddedSoundsParams(False, 0.0, 1.0)
    )
    for bad in (
        {"enabled": 1},
        {"melody_probability": -0.01},
        {"melody_probability": 1.5},
        {"outside_voice_probability": float("nan")},
        {"outside_voice_probability": True},
        {"melody_probability": "0.02"},
        {"level_db": 3.0},
    ):
        with pytest.raises(ValueError, match="added_sounds"):
            AddedSoundsParams.from_section(bad)
    with pytest.raises(ValueError):
        _added_sounds_params({"stimulus_source": {"added_sounds": 3}})


def test_shipped_config_enables_them_at_the_table_rates():
    import tomllib

    cfg = tomllib.loads((Path(__file__).resolve().parents[1] / "config" / "kaine.toml").read_text())
    params = _added_sounds_params(cfg["perception_feed"])
    assert params == AddedSoundsParams(True, 0.02, 0.05)
    # The added_sounds table stays out of the maturation digest's parameters.
    assert _stimulus_source_params(cfg["perception_feed"]) == _stimulus_source_params(
        {"stimulus_source": {k: v for k, v in cfg["perception_feed"]["stimulus_source"].items() if k != "added_sounds"}}
    )


# --- files and manifest --------------------------------------------------------


def test_every_take_is_listed_with_its_digest_and_nothing_else_ships():
    manifest = json.loads((ADDED_SOUNDS_DATA_DIR / "manifest.json").read_text())
    listed = {t["file"]: t["sha256"] for t in manifest["melody"]["takes"]}
    for item in manifest["outside_voice"]["items"]:
        listed.update({t["file"]: t["sha256"] for t in item["takes"]})
    on_disk = {p.name for p in ADDED_SOUNDS_DATA_DIR.glob("*.flac")}
    assert on_disk == set(listed)
    for name, digest in listed.items():
        assert hashlib.sha256((ADDED_SOUNDS_DATA_DIR / name).read_bytes()).hexdigest() == digest
    assert len(manifest["outside_voice"]["items"]) == 10
    assert all(len(item["takes"]) == 2 for item in manifest["outside_voice"]["items"])
    assert manifest["outside_voice"]["generator"]["model_revision"] == "5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18"
    assert "rms" in manifest["outside_voice"]["reference_voice"]["attribution"]


def _copy_data(tmp_path) -> Path:
    data = tmp_path / "added_sounds_data"
    shutil.copytree(ADDED_SOUNDS_DATA_DIR, data)
    return data


def test_a_changed_outside_voice_take_refuses_to_start_naming_it(tmp_path):
    """Spec: a changed file."""
    data = _copy_data(tmp_path)
    take = data / "x03-shopping.t1.flac"
    raw = bytearray(take.read_bytes())
    raw[-10] ^= 0xFF
    take.write_bytes(bytes(raw))
    with pytest.raises(PerceptionUnavailableError, match="x03-shopping.t1.flac") as excinfo:
        AddedSoundsRepertoire.load(data, sample_rate=SR, lowpass_hz=HEARING_TOP_TONE_HZ)
    assert "sha256 mismatch" in str(excinfo.value)


def test_a_missing_melody_take_refuses_to_start_naming_it(tmp_path):
    data = _copy_data(tmp_path)
    (data / "melody.b1.flac").unlink()
    with pytest.raises(PerceptionUnavailableError, match="melody.b1.flac"):
        AddedSoundsRepertoire.load(data, sample_rate=SR, lowpass_hz=HEARING_TOP_TONE_HZ)


def test_a_manifest_without_the_outside_voice_refuses_to_start(tmp_path):
    data = _copy_data(tmp_path)
    manifest = json.loads((data / "manifest.json").read_text())
    del manifest["outside_voice"]
    (data / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(PerceptionUnavailableError, match="outside-voice"):
        AddedSoundsRepertoire.load(data, sample_rate=SR, lowpass_hz=HEARING_TOP_TONE_HZ)


def test_the_boot_factory_stops_the_stimulus_audio_on_a_changed_file(tmp_path, monkeypatch, caplog):
    data = _copy_data(tmp_path)
    take = data / "melody.b0.flac"
    raw = bytearray(take.read_bytes())
    raw[-10] ^= 0xFF
    take.write_bytes(bytes(raw))
    monkeypatch.setattr(added_sounds_mod, "ADDED_SOUNDS_DATA_DIR", data)
    with caplog.at_level("CRITICAL"), pytest.raises(PerceptionUnavailableError, match="melody.b0.flac"):
        _build_perception_feed_audio_factory(
            "stimulus_source", {"seed": 7, "stimulus_source": {}}, sample_rate=SR, channels=1, frames_per_block=FPB
        )
    assert "added sounds are unavailable" in caplog.text


def test_takes_fit_a_slot_and_the_runtime_never_synthesizes():
    src = inspect.getsource(added_sounds_mod)
    for forbidden in ("chatterbox", "np.sin(", "TTS"):
        assert forbidden not in src
    rep = AddedSoundsRepertoire.load(sample_rate=SR, lowpass_hz=HEARING_TOP_TONE_HZ)
    assert rep.longest <= SLOT


# --- the melody ------------------------------------------------------------------


def test_melody_heard_from_the_first_stage(parts):
    """Spec: at least half of the melody layer's power lies inside the stage-0 pass band."""
    layer = _layer(parts)
    slot, sound = _first_slot(layer, "melody")
    x = layer.render(slot * SLOT, SLOT)
    lo, hi = HEARING_BAND_STAGES[0]
    inside, total = _band_power(x, lo, hi)
    assert inside / total >= 0.5
    # Every rendered take: its fundamentals are the note list's, G4 to E5.
    manifest = json.loads((ADDED_SOUNDS_DATA_DIR / "manifest.json").read_text())
    f_lo, f_hi = manifest["melody"]["fundamental_range_hz"]
    assert lo < f_lo and f_hi < hi
    for take in parts["added_rep"].melody:
        inside, total = _band_power(take, lo, hi)
        assert inside / total >= 0.5
    # The melody passes the stage-0 band: most of it is still there after the filter.
    y = np.convolve(x, band_taps(lo, hi, float(SR)), mode="same")
    assert float(np.sum(y * y)) >= 0.5 * float(np.sum(x * x))


def test_melody_level_is_the_voice_level_with_ramps(parts):
    layer = _layer(parts)
    slot, sound = _first_slot(layer, "melody")
    voice_target = parts["bg"] * 10 ** (parts["voice_params"].level_db / 20)
    jitter = 10 ** (parts["voice_params"].jitter_db / 20)
    assert voice_target / jitter - 1e-12 <= sound.gain <= voice_target * jitter + 1e-12
    arr = parts["added_rep"].melody[sound.take]
    x = layer.render(sound.start, arr.size)
    ramp = int(RAMP_SECONDS * SR)
    body = x[ramp:-ramp]
    assert float(np.sqrt(np.mean(body * body))) == pytest.approx(sound.gain, rel=0.25)
    assert abs(x[0]) < 1e-9
    assert float(np.sqrt(np.mean(x[: ramp // 10] ** 2))) < 0.05 * sound.gain
    assert float(np.sqrt(np.mean(x[-ramp // 10:] ** 2))) < 0.05 * sound.gain


# --- the outside voice ---------------------------------------------------------


def test_the_outside_voice_fundamental_arrives_at_the_100_hz_step(parts):
    """Spec: the power below 112 Hz is at least 40 dB higher in stage 2 than in stage 1.

    112 Hz is stage 1's stopband edge (158 Hz / sqrt 2, where the band is down by
    40 dB or more). Between it and the 158 Hz edge stage 1 still passes the voice's
    intonation peaks partly (6 to 27 dB down), so a measure up to 158 Hz reads the
    filter's transition, not the voice's arrival.
    """
    stop_edge = HEARING_BAND_STAGES[1][0] / np.sqrt(2.0)
    stage1 = band_taps(*HEARING_BAND_STAGES[1], float(SR))
    stage2 = band_taps(*HEARING_BAND_STAGES[2], float(SR))
    layer = _layer(parts)
    for start in (0, 5000):
        slot, sound = _first_slot(layer, "outside_voice", start=start)
        x = layer.render(slot * SLOT, SLOT)
        low1, _ = _band_power(np.convolve(x, stage1, mode="same"), 0.0, stop_edge)
        low2, _ = _band_power(np.convolve(x, stage2, mode="same"), 0.0, stop_edge)
        assert 10 * np.log10(low2 / low1) >= 40.0
    # Every take, and its fundamental band carries real power once it arrives.
    for takes in parts["added_rep"].outside:
        for take in takes:
            low1, _ = _band_power(np.convolve(take, stage1, mode="same"), 0.0, stop_edge)
            low2, total2 = _band_power(np.convolve(take, stage2, mode="same"), 0.0, stop_edge)
            assert 10 * np.log10(low2 / low1) >= 40.0
            assert low2 / total2 > 0.01


def test_outside_voice_fundamentals_are_below_stage_one():
    """Every take's fundamental lies below stage 1's lower edge (about 158 Hz)."""
    rep = AddedSoundsRepertoire.load(sample_rate=SR, lowpass_hz=HEARING_TOP_TONE_HZ)
    edge = HEARING_BAND_STAGES[1][0]
    frame, hop = 640, 320  # 40 ms frames
    lags = np.arange(int(SR / 400), int(SR / 60) + 1)  # 60 to 400 Hz
    for takes in rep.outside:
        for take in takes:
            f0 = []
            for i in range(0, take.size - frame - lags[-1], hop):
                seg = take[i:i + frame + lags[-1]]
                head = seg[:frame]
                energy = float(head @ head)
                if energy < 1e-3 * frame:
                    continue
                r = np.array([head @ seg[lag:lag + frame] for lag in lags])
                r /= np.sqrt(energy * np.array([seg[lag:lag + frame] @ seg[lag:lag + frame] for lag in lags]))
                best = int(np.argmax(r))
                if r[best] > 0.7:  # voiced
                    f0.append(SR / lags[best])
            assert len(f0) > 10
            assert float(np.median(f0)) < edge


def test_outside_voice_level_is_the_soundscape_rms(parts):
    layer = _layer(parts)
    slot, sound = _first_slot(layer, "outside_voice")
    assert sound.gain == pytest.approx(parts["bg"])
    arr = parts["added_rep"].outside[sound.item][sound.take]
    x = layer.render(sound.start, arr.size)
    rms = float(np.sqrt(np.mean(x * x)))
    assert 0.6 * parts["bg"] < rms <= parts["bg"]  # the ramps take a little off unit RMS
    assert abs(x[0]) < 1e-9


# --- seeded, entity-independent, one sound per slot ---------------------------------


def test_slots_hold_at_most_one_sound_and_never_share_with_speech(parts):
    voice = _voice(parts, 7)
    layer = _layer(parts, voice=voice)
    counts = {"melody": 0, "outside_voice": 0, "speech": 0, "none": 0}
    n = 6000
    for slot in range(n):
        sound = layer.slot_sound(slot)
        speaks = voice.speaks_in(slot)
        assert bool(voice.slot_plan(slot, 20)) == speaks
        if speaks:
            assert sound is None
            counts["speech"] += 1
        elif sound is None:
            counts["none"] += 1
        else:
            counts[sound.kind] += 1
            lo, hi = slot * SLOT, (slot + 1) * SLOT
            arr = layer._array(sound)
            assert lo <= sound.start and sound.start + arr.size <= hi
    free = n - counts["speech"]
    assert counts["melody"] / free == pytest.approx(0.02, abs=0.008)
    assert counts["outside_voice"] / free == pytest.approx(0.98 * 0.05, abs=0.012)


def test_without_a_voice_every_slot_is_free(parts):
    layer = _layer(parts, voice=None)
    kinds = [layer.slot_sound(s) for s in range(3000)]
    assert sum(1 for k in kinds if k is not None and k.kind == "melody") > 30


def test_the_same_seed_gives_the_same_sounds(parts):
    """Spec: the same seed gives the same sounds; another seed differs."""
    a, b, c = _layer(parts, 7), _layer(parts, 7), _layer(parts, 8)
    plans_a = [a.slot_sound(s) for s in range(4000)]
    assert plans_a == [b.slot_sound(s) for s in range(4000)]
    assert plans_a != [c.slot_sound(s) for s in range(4000)]
    # The stream: identical PCM over a melody slot for the same seed, different for another.
    slot, _ = _first_slot(a, "melody")
    first = slot * SLOT // FPB
    streams = [_stream(parts, seed, layer) for seed, layer in ((7, _layer(parts, 7)), (7, _layer(parts, 7)), (8, _layer(parts, 8)))]
    pcm = [b"".join(s.pcm_at(k, awake_seconds=50.0, hearing_stage=0) for k in range(first, first + 200)) for s in streams]
    assert pcm[0] == pcm[1]
    assert pcm[0] != pcm[2]


def test_the_sounds_do_not_depend_on_the_entity(parts):
    """The layer takes no awake time, stage or entity input; rendering order does not matter."""
    sig = inspect.signature(AddedSoundsLayer.render)
    assert list(sig.parameters) == ["self", "start", "n"]
    layer = _layer(parts)
    slot, sound = _first_slot(layer, "outside_voice")
    forward = layer.render(slot * SLOT, SLOT)
    fresh = _layer(parts)
    for s in range(slot + 50, slot - 1, -1):  # backwards, from far ahead
        fresh.slot_sound(s)
    assert np.array_equal(fresh.render(slot * SLOT, SLOT), forward)
    # In the stream, an added-sound slot is the same whatever the awake time says
    # (the awake time unlocks maternal items, and this slot holds no speech). The
    # blocks start past the band filter's history from the slot before.
    first = slot * SLOT // FPB + 100
    young = _stream(parts, 7, _layer(parts))
    old = _stream(parts, 7, _layer(parts))
    a = b"".join(young.pcm_at(k, awake_seconds=0.0, hearing_stage=4) for k in range(first, first + 60))
    b = b"".join(old.pcm_at(k, awake_seconds=90000.0, hearing_stage=4) for k in range(first, first + 60))
    assert a == b


def _stream(parts, seed, layer, *, hearing=True):
    params = parts["params"]
    schedule = StimulusSourceAudioSchedule(seed=seed, sample_rate=SR, channels=1, frames_per_block=FPB)
    return StimulusSourceProceduralAudioStream(
        schedule,
        params=params,
        clock=None,
        callback=lambda _b: None,
        voice=_voice(parts, seed),
        awake=lambda: 50.0,
        hearing=parts["hearing"] if hearing else None,
        hearing_stage=lambda: 0,
        added=layer,
    )


def test_added_sounds_reach_the_stream_before_the_hearing_band(parts):
    layer = _layer(parts)
    slot, sound = _first_slot(layer, "melody")
    first = slot * SLOT // FPB
    with_added = _stream(parts, 7, layer)
    without = _stream(parts, 7, None)
    a = np.frombuffer(b"".join(with_added.pcm_at(k, awake_seconds=50.0, hearing_stage=0) for k in range(first, first + 1000)), "<i2")
    b = np.frombuffer(b"".join(without.pcm_at(k, awake_seconds=50.0, hearing_stage=0) for k in range(first, first + 1000)), "<i2")
    diff = a.astype(np.float64) - b
    assert float(np.sqrt(np.mean(diff * diff))) > 100.0
    # Through the stage-0 band the melody's energy sits inside 354 to 707 Hz.
    inside, total = _band_power(diff, *HEARING_BAND_STAGES[0])
    assert inside / total > 0.9


def test_without_a_voice_the_headroom_covers_the_added_sounds(parts):
    """With the voice off, the stream still makes room for the added sounds and soft-limits."""
    layer = _layer(parts, voice=None)
    schedule = StimulusSourceAudioSchedule(seed=7, sample_rate=SR, channels=1, frames_per_block=FPB)

    def stream(added):
        return StimulusSourceProceduralAudioStream(
            schedule, params=parts["params"], clock=None, callback=lambda _b: None,
            voice=None, hearing=parts["hearing"], hearing_stage=lambda: 4, added=added,
        )

    quiet = next(s for s in range(10, 4000) if all(layer.slot_sound(k) is None for k in (s - 1, s, s + 1)))
    first = quiet * SLOT // FPB + 100
    a = np.frombuffer(b"".join(stream(None).pcm_at(k, hearing_stage=4) for k in range(first, first + 200)), "<i2")
    b = np.frombuffer(b"".join(stream(layer).pcm_at(k, hearing_stage=4) for k in range(first, first + 200)), "<i2")
    base = StimulusSourceProceduralAudioStream._BASE_AMP_TOTAL + 4 * StimulusSourceProceduralAudioStream._NOISE_RMS
    base += StimulusSourceProceduralAudioStream._THUD_AMP
    expected = base / (base + layer.headroom)
    ratio = float(np.sqrt(np.mean(b.astype(float) ** 2)) / np.sqrt(np.mean(a.astype(float) ** 2)))
    assert ratio == pytest.approx(expected, rel=0.01)


# --- disabled: byte for byte the stream before the added sounds existed --------------

# sha256 of blocks 0..5999 (seed 7, 480-frame blocks at 16 kHz, maternal voice on,
# awake 100 s), computed with the stream at main cb41895b, before the added sounds
# existed. A deliberate change to the bed, voice or band changes them; the added
# sounds must not.
_PRE_ADDED_SOUNDS_DIGESTS = {
    (True, 0): "24e014ef645374b523d5c7a5c3189bf05e96868b4678b95275ee0a069183600c",
    (False, None): "e26b87e52358bb3241d4c6762f949304d7a8098011cada604e81bd1b7c8fd239",
}


@pytest.mark.parametrize("band, stage", list(_PRE_ADDED_SOUNDS_DIGESTS))
def test_disabled_added_sounds_leave_the_audio_unchanged(band, stage):
    """Spec: with the added sounds disabled every block equals the earlier stream's."""
    feed = {"seed": 7, "stimulus_source": {"hearing": {"enabled": band}, "added_sounds": {"enabled": False}}}
    factory = _build_perception_feed_audio_factory(
        "stimulus_source", feed, sample_rate=SR, channels=1, frames_per_block=FPB
    )
    stream = factory(device=None, sample_rate=SR, channels=1, frames_per_block=FPB, callback=lambda _b: None)
    assert stream._added is None
    h = hashlib.sha256()
    for k in range(6000):
        h.update(stream.pcm_at(k, awake_seconds=100.0, hearing_stage=stage))
    assert h.hexdigest() == _PRE_ADDED_SOUNDS_DIGESTS[(band, stage)]


def test_enabled_by_the_boot_factory(parts):
    factory = _build_perception_feed_audio_factory(
        "stimulus_source", {"seed": 7, "stimulus_source": {}}, sample_rate=SR, channels=1, frames_per_block=FPB
    )
    stream = factory(device=None, sample_rate=SR, channels=1, frames_per_block=FPB, callback=lambda _b: None)
    assert isinstance(stream._added, AddedSoundsLayer)
    assert stream._added.params == AddedSoundsParams()
    # Its plans are those of a layer built by hand from the same seed and voice.
    hand = _layer(parts)
    assert [stream._added.slot_sound(s) for s in range(2000)] == [hand.slot_sound(s) for s in range(2000)]
