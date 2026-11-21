# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("av")
import av

from kaine.modules.audition.live import PerceptionUnavailableError
from kaine.modules.audition.maternal_voice import (
    MANIFEST_FORMAT,
    VOICE_DATA_DIR,
    MaternalVoiceLayer,
    MaternalVoiceParams,
    MaternalVoiceRepertoire,
    unlocked_count,
)
from kaine.modules.stimulus_source_signal import (
    StimulusSourceParams,
    maternal_state,
)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1_048_576)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _write_flac(path: Path, arr: np.ndarray) -> None:
    arr = np.asarray(arr, dtype=np.int16, order="C")
    container = av.open(str(path), "w", format="flac")
    stream = container.add_stream("flac", rate=8000)
    stream.layout = "mono"
    frame = av.AudioFrame.from_ndarray(
        arr.reshape(1, -1), format="s16", layout="mono"
    )
    frame.sample_rate = 8000
    for packet in stream.encode(frame):
        container.mux(packet)
    for packet in stream.encode(None):
        container.mux(packet)
    container.close()


def _write_manifest(
    manifest_path: Path,
    items: list[tuple[str, list[np.ndarray]]],
    initial_unlocked: int = 1,
) -> None:
    manifest_items = []
    for idx, (item_id, takes) in enumerate(items):
        take_entries = []
        for t, arr in enumerate(takes):
            file_path = manifest_path.parent / f"{item_id}.t{t}.flac"
            _write_flac(file_path, arr)
            take_entries.append(
                {
                    "file": file_path.name,
                    "frames": int(arr.shape[0]),
                    "rms_dbfs": -20.0,
                    "seconds": arr.shape[0] / 8000.0,
                    "seed": 20260000 + t,
                    "sha256": _hash_file(file_path),
                    "take": t,
                }
            )
        manifest_items.append(
            {
                "id": item_id,
                "index": idx,
                "kind": "phrase",
                "takes": take_entries,
                "text_sha256": "0" * 64,
            }
        )

    manifest = {
        "format": MANIFEST_FORMAT,
        "generator": {"tool": "tests"},
        "initial_unlocked": initial_unlocked,
        "items": manifest_items,
        "sample_rate": 8000,
        "texts_sha256": "0" * 64,
        "total_bytes": 0,
        "total_seconds": 0.0,
    }
    manifest_path.write_text(json.dumps(manifest))


def _synthetic_dir(
    tmp_path: Path,
    n_items: int = 5,
    n_takes: int = 2,
    frames: int = 1600,
    initial_unlocked: int = 2,
) -> Path:
    items = []
    for i in range(n_items):
        takes = []
        for t in range(n_takes):
            freq = 100.0 + i * 50.0 + t * 20.0
            x = np.sin(2.0 * np.pi * freq * np.arange(frames) / 8000.0)
            scale = 32767.0 / max(1.0, float(np.max(np.abs(x))))
            takes.append((x * scale).astype(np.int16))
        items.append((f"item{i:02d}", takes))

    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, items, initial_unlocked=initial_unlocked)
    return tmp_path


def test_params_defaults():
    p = MaternalVoiceParams()
    assert p.enabled is True
    assert p.level_db == 6.0
    assert p.jitter_db == 3.0
    assert p.slot_seconds == 30.0
    assert p.episode_probability == 0.2
    assert p.repeat_share == 0.25
    assert p.unlock_seconds == 3600.0
    assert p.pause_min_seconds == 0.5
    assert p.pause_max_seconds == 1.5
    assert p.as_record() == {
        "enabled": True,
        "level_db": 6.0,
        "jitter_db": 3.0,
        "slot_seconds": 30.0,
        "episode_probability": 0.2,
        "repeat_share": 0.25,
        "unlock_seconds": 3600.0,
        "pause_min_seconds": 0.5,
        "pause_max_seconds": 1.5,
    }


def test_params_from_section_none_and_empty():
    assert MaternalVoiceParams.from_section(None) == MaternalVoiceParams()
    assert MaternalVoiceParams.from_section({}) == MaternalVoiceParams()


def test_params_unknown_key_raises():
    with pytest.raises(ValueError):
        MaternalVoiceParams.from_section({"enabled": True, "unknown": 1})


def test_params_bool_for_float_raises():
    with pytest.raises(ValueError):
        MaternalVoiceParams.from_section({"level_db": True})


@pytest.mark.parametrize(
    "key,value",
    [
        ("level_db", 21.0),
        ("jitter_db", 7.0),
        ("slot_seconds", 4.0),
        ("episode_probability", 1.5),
        ("unlock_seconds", 0.0),
    ],
)
def test_params_out_of_range_raises(key, value):
    with pytest.raises(ValueError):
        MaternalVoiceParams.from_section({key: value})


def test_params_pause_max_below_min_raises():
    with pytest.raises(ValueError):
        MaternalVoiceParams.from_section(
            {"pause_min_seconds": 2.0, "pause_max_seconds": 1.0}
        )


def test_params_enabled_must_be_bool():
    with pytest.raises(ValueError):
        MaternalVoiceParams.from_section({"enabled": "yes"})


@pytest.mark.parametrize(
    "awake,expected",
    [
        (0.0, 2),
        (3600.0, 3),
        (7200.0, 4),
        (1e9, 5),
    ],
)
def test_unlocked_count_progression(awake, expected):
    assert unlocked_count(awake, 2, 5, 3600.0) == expected


def test_unlocked_count_negative_and_nan():
    assert unlocked_count(-10.0, 2, 5, 3600.0) == 2
    assert unlocked_count(float("nan"), 2, 5, 3600.0) == 2


@pytest.mark.skipif(
    not (VOICE_DATA_DIR / "manifest.json").exists(),
    reason="shipped maternal voice data is not present",
)
def test_real_repertoire_loads():
    rep = MaternalVoiceRepertoire.load()
    assert len(rep.takes) == 20
    assert rep.item_ids[0] == "p0-little-boat"
    assert rep.initial_unlocked == 5
    assert rep.sample_rate == 16000
    for item in rep.takes:
        for take in item:
            rms = float(np.sqrt(np.mean(take * take)))
            assert abs(rms - 1.0) < 1e-9


@pytest.mark.skipif(
    not (VOICE_DATA_DIR / "manifest.json").exists(),
    reason="shipped maternal voice data is not present",
)
def test_real_spectrum_below_intrauterine_cutoff():
    rep = MaternalVoiceRepertoire.load(lowpass_hz=500.0)
    all_samples = np.concatenate(
        [t for item in rep.takes for t in item]
    )
    spectrum = np.fft.rfft(all_samples)
    power = np.abs(spectrum) ** 2
    freqs = np.fft.rfftfreq(len(all_samples), 1.0 / rep.sample_rate)
    low_power = float(np.sum(power[freqs < 500.0]))
    high_power = float(np.sum(power[freqs > 1000.0]))
    assert low_power > 0.0
    ratio_db = 10.0 * math.log10(high_power / low_power)
    assert ratio_db <= -40.0


def test_missing_manifest_raises(tmp_path):
    with pytest.raises(PerceptionUnavailableError):
        MaternalVoiceRepertoire.load(tmp_path)


def test_deleted_take_file_raises(tmp_path):
    _synthetic_dir(tmp_path, n_items=2, initial_unlocked=1)
    (tmp_path / "item00.t0.flac").unlink()
    with pytest.raises(PerceptionUnavailableError) as exc_info:
        MaternalVoiceRepertoire.load(tmp_path)
    assert "item00.t0.flac" in str(exc_info.value)


def test_flipped_byte_raises(tmp_path):
    _synthetic_dir(tmp_path, n_items=2, initial_unlocked=1)
    path = tmp_path / "item00.t0.flac"
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    path.write_bytes(bytes(data))
    with pytest.raises(PerceptionUnavailableError) as exc_info:
        MaternalVoiceRepertoire.load(tmp_path)
    assert "item00.t0.flac" in str(exc_info.value)


def test_manifest_frames_off_by_one_raises(tmp_path):
    _synthetic_dir(tmp_path, n_items=2, initial_unlocked=1)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["items"][0]["takes"][0]["frames"] += 1
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(PerceptionUnavailableError) as exc_info:
        MaternalVoiceRepertoire.load(tmp_path)
    assert "item00.t0.flac" in str(exc_info.value)


def test_incompatible_stream_sample_rate_raises(tmp_path):
    _synthetic_dir(tmp_path, n_items=2, initial_unlocked=1)
    with pytest.raises(ValueError):
        MaternalVoiceRepertoire.load(tmp_path, sample_rate=22050)


def test_pyav_absent_raises(monkeypatch, tmp_path):
    _synthetic_dir(tmp_path, n_items=2, initial_unlocked=1)
    monkeypatch.setitem(sys.modules, "av", None)
    with pytest.raises(PerceptionUnavailableError):
        MaternalVoiceRepertoire.load(tmp_path)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda m: m["items"].__setitem__(0, "string"),
        lambda m: m["items"][0].pop("id"),
        lambda m: m["items"][0].update({"id": 5}),
        lambda m: m["items"][0].pop("takes"),
        lambda m: m["items"][0].update({"takes": []}),
        lambda m: m["items"][0]["takes"].__setitem__(0, []),
        lambda m: m["items"][0]["takes"][0].pop("file"),
        lambda m: m["items"][0]["takes"][0].update({"file": None}),
        lambda m: m["items"][0]["takes"][0].update({"file": "../escape.flac"}),
        lambda m: m["items"][0]["takes"][0].update({"file": "/etc/passwd"}),
        lambda m: m["items"][0]["takes"][0].pop("sha256"),
        lambda m: m["items"][0]["takes"][0].update({"frames": "1600"}),
        lambda m: m["items"][0]["takes"][0].update({"frames": True}),
    ],
)
def test_manifest_validation_rejects_malformed_entries(tmp_path, mutator):
    _synthetic_dir(tmp_path, n_items=2, initial_unlocked=1)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    mutator(manifest)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(PerceptionUnavailableError) as exc_info:
        MaternalVoiceRepertoire.load(tmp_path)
    assert "manifest" in str(exc_info.value)


@pytest.mark.skipif(
    not (VOICE_DATA_DIR / "manifest.json").exists(),
    reason="shipped maternal voice data is not present",
)
def test_layer_headroom_equals_target_rms_and_below_peak():
    rep = MaternalVoiceRepertoire.load()
    layer = MaternalVoiceLayer(
        rep,
        MaternalVoiceParams(),
        seed=1,
        stimulus_params=StimulusSourceParams(),
        background_rms=0.16,
    )
    assert layer.headroom == layer.target_rms
    assert layer.headroom < layer.peak


def test_render_determinism(tmp_path):
    rep = MaternalVoiceRepertoire.load(_synthetic_dir(tmp_path))
    params = MaternalVoiceParams(episode_probability=1.0, slot_seconds=5.0)
    stimulus = StimulusSourceParams()
    a = MaternalVoiceLayer(rep, params, seed=42, stimulus_params=stimulus, background_rms=1.0)
    b = MaternalVoiceLayer(rep, params, seed=42, stimulus_params=stimulus, background_rms=1.0)
    slot_n = rep.sample_rate * 5
    for slot in range(20):
        start = slot * slot_n
        np.testing.assert_array_equal(
            a.render(start, slot_n, 0.0),
            b.render(start, slot_n, 0.0),
        )


def test_different_seed_renders_different(tmp_path):
    rep = MaternalVoiceRepertoire.load(_synthetic_dir(tmp_path))
    params = MaternalVoiceParams(episode_probability=1.0, slot_seconds=30.0)
    stimulus = StimulusSourceParams()
    a = MaternalVoiceLayer(rep, params, seed=1, stimulus_params=stimulus, background_rms=1.0)
    b = MaternalVoiceLayer(rep, params, seed=2, stimulus_params=stimulus, background_rms=1.0)
    slot_n = int(round(params.slot_seconds * rep.sample_rate))
    different = False
    for slot in range(240):
        start = slot * slot_n
        if not np.array_equal(a.render(start, slot_n, 0.0), b.render(start, slot_n, 0.0)):
            different = True
            break
    assert different


def test_slot_plan_is_pure_and_plan_for_caches(tmp_path):
    rep = MaternalVoiceRepertoire.load(_synthetic_dir(tmp_path))
    layer = MaternalVoiceLayer(
        rep,
        MaternalVoiceParams(),
        seed=7,
        stimulus_params=StimulusSourceParams(),
        background_rms=1.0,
    )
    p1 = layer.slot_plan(3, 2)
    p2 = layer.slot_plan(3, 2)
    assert p1 == p2

    c1 = layer.plan_for(5, 0.0)
    c2 = layer.plan_for(5, 999999.0)
    assert c1 == c2


def test_repertoire_growth(tmp_path):
    rep = MaternalVoiceRepertoire.load(
        _synthetic_dir(tmp_path, n_items=5, initial_unlocked=2)
    )
    layer = MaternalVoiceLayer(
        rep,
        MaternalVoiceParams(episode_probability=1.0, repeat_share=0.0),
        seed=11,
        stimulus_params=StimulusSourceParams(),
        background_rms=1.0,
    )
    initial = rep.initial_unlocked
    items_initial = set()
    for slot in range(400):
        for u in layer.slot_plan(slot, initial):
            items_initial.add(u.item)
    assert all(i < initial for i in items_initial)

    items_more = set()
    for slot in range(400):
        for u in layer.slot_plan(slot, initial + 3):
            items_more.add(u.item)
    assert max(items_more) >= initial
    assert all(i < initial + 3 for i in items_more)


def test_repeated_passage_share(tmp_path):
    rep = MaternalVoiceRepertoire.load(_synthetic_dir(tmp_path))
    layer = MaternalVoiceLayer(
        rep,
        MaternalVoiceParams(episode_probability=1.0, repeat_share=1.0),
        seed=13,
        stimulus_params=StimulusSourceParams(),
        background_rms=1.0,
    )
    talking = 0
    for slot in range(200):
        plan = layer.slot_plan(slot, len(rep.takes))
        if plan:
            talking += 1
            assert plan[0].item == 0
    assert talking > 0


def test_arousal_pacing(tmp_path):
    rep = MaternalVoiceRepertoire.load(_synthetic_dir(tmp_path))
    silent = MaternalVoiceLayer(
        rep,
        MaternalVoiceParams(episode_probability=0.0),
        seed=17,
        stimulus_params=StimulusSourceParams(),
        background_rms=1.0,
    )
    for slot in range(500):
        assert silent.slot_plan(slot, len(rep.takes)) == ()

    talkative = MaternalVoiceLayer(
        rep,
        MaternalVoiceParams(episode_probability=1.0),
        seed=17,
        stimulus_params=StimulusSourceParams(),
        background_rms=1.0,
    )
    # A slot talks with probability episode_probability * arousal, so the
    # talking share among high-arousal slots exceeds that among low ones.
    high = [0, 0]
    low = [0, 0]
    for slot in range(4000):
        t = slot * talkative._slot_n / rep.sample_rate
        arousal = maternal_state(talkative._seed, t, talkative._stimulus_params)[1]
        talks = bool(talkative.slot_plan(slot, len(rep.takes)))
        if arousal > 0.6:
            high[0] += talks
            high[1] += 1
        elif arousal < 0.4:
            low[0] += talks
            low[1] += 1
    assert high[1] > 0 and low[1] > 0
    assert high[0] / high[1] > low[0] / low[1]


def test_utterances_inside_slot_and_non_overlapping(tmp_path):
    rep = MaternalVoiceRepertoire.load(_synthetic_dir(tmp_path))
    layer = MaternalVoiceLayer(
        rep,
        MaternalVoiceParams(episode_probability=1.0),
        seed=19,
        stimulus_params=StimulusSourceParams(),
        background_rms=1.0,
    )
    for slot in range(200):
        t0 = slot * layer._slot_n
        end = t0 + layer._slot_n
        prev_end = t0
        for u in layer.slot_plan(slot, len(rep.takes)):
            length = rep.takes[u.item][u.take].shape[0]
            assert u.start >= t0
            assert u.start + length <= end
            assert u.start >= prev_end
            prev_end = u.start + length


def test_render_overlap(tmp_path):
    rep = MaternalVoiceRepertoire.load(_synthetic_dir(tmp_path))
    layer = MaternalVoiceLayer(
        rep,
        MaternalVoiceParams(episode_probability=1.0, slot_seconds=10.0),
        seed=23,
        stimulus_params=StimulusSourceParams(),
        background_rms=1.0,
    )
    N = layer._slot_n * 3
    whole = layer.render(0, N, 0.0)
    split = np.concatenate(
        [layer.render(0, N // 2, 0.0), layer.render(N // 2, N - N // 2, 0.0)]
    )
    np.testing.assert_allclose(whole, split)


def test_level_over_one_utterance(tmp_path):
    rep = MaternalVoiceRepertoire.load(_synthetic_dir(tmp_path))
    bg = 2.0
    level_db = -6.0
    params = MaternalVoiceParams(
        episode_probability=1.0,
        jitter_db=0.0,
        level_db=level_db,
        slot_seconds=10.0,
    )
    layer = MaternalVoiceLayer(
        rep,
        params,
        seed=29,
        stimulus_params=StimulusSourceParams(),
        background_rms=bg,
    )
    target = bg * 10.0 ** (level_db / 20.0)
    for slot in range(10):
        plan = layer.slot_plan(slot, len(rep.takes))
        if plan:
            u = plan[0]
            length = rep.takes[u.item][u.take].shape[0]
            rendered = layer.render(u.start, length, 0.0)
            rms = float(np.sqrt(np.mean(rendered * rendered)))
            assert abs(rms - target) / target < 0.01
            return
    pytest.fail("no utterance found in the first 10 slots")


def test_peak_bounds_rendered_samples(tmp_path):
    rep = MaternalVoiceRepertoire.load(_synthetic_dir(tmp_path))
    params = MaternalVoiceParams(
        episode_probability=1.0, slot_seconds=5.0, jitter_db=3.0
    )
    layer = MaternalVoiceLayer(
        rep,
        params,
        seed=31,
        stimulus_params=StimulusSourceParams(),
        background_rms=1.0,
    )
    chunks = [
        layer.render(slot * layer._slot_n, layer._slot_n, 0.0)
        for slot in range(100)
    ]
    all_samples = np.concatenate(chunks)
    max_abs = float(np.max(np.abs(all_samples)))
    assert max_abs <= layer.peak * (1.0 + 1e-12)
