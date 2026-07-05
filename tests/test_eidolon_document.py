# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json
from pathlib import Path

import pytest

from kaine.modules.eidolon.document import SelfModel, load, save_atomic


def test_empty_default():
    m = SelfModel()
    assert m.values == []
    assert m.behavioral_norms == []
    assert m.capability_map == {}
    assert m.personality_baseline == {}
    assert m.identity_history == []
    assert m.internal_speech_count == 0
    assert m.external_speech_count == 0
    assert m.voice_observations == []


def test_roundtrip_json_with_voice_fields():
    m = SelfModel(
        internal_speech_count=3,
        external_speech_count=5,
        voice_observations=[
            {"timestamp": 1.0, "channel": "internal", "length": 4, "word_count": 1},
            {"timestamp": 2.0, "channel": "external", "length": 11, "word_count": 2},
        ],
    )
    m2 = SelfModel.from_json(m.to_json())
    assert m == m2
    assert m2.external_speech_count == 5
    assert m2.voice_observations[1]["channel"] == "external"


def test_pre_change_model_loads_with_voice_defaults():
    # A self-model persisted before this change has no voice fields.
    legacy = json.dumps(
        {
            "values": ["honesty"],
            "internal_speech_count": 9,
            # no external_speech_count, no voice_observations
        }
    )
    m = SelfModel.from_json(legacy)
    assert m.values == ["honesty"]
    assert m.internal_speech_count == 9
    assert m.external_speech_count == 0
    assert m.voice_observations == []


def test_roundtrip_json():
    m = SelfModel(
        values=["honesty", "curiosity"],
        personality_baseline={"openness": 0.7},
        internal_speech_count=42,
    )
    text = m.to_json()
    m2 = SelfModel.from_json(text)
    assert m == m2


def test_with_updates_returns_new_instance():
    m = SelfModel()
    m2 = m.with_updates(internal_speech_count=5)
    assert m.internal_speech_count == 0  # original unchanged
    assert m2.internal_speech_count == 5
    assert m is not m2


def test_load_missing_file_returns_empty(tmp_path: Path):
    path = tmp_path / "missing.json"
    m = load(path)
    assert m == SelfModel()


def test_load_existing_file(tmp_path: Path):
    path = tmp_path / "x.json"
    path.write_text(json.dumps({"values": ["honesty"]}), encoding="utf-8")
    m = load(path)
    assert m.values == ["honesty"]


def test_save_atomic_writes_file(tmp_path: Path):
    path = tmp_path / "a" / "b" / "model.json"
    save_atomic(path, SelfModel(values=["x"]))
    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["values"] == ["x"]


def test_save_atomic_overwrites_existing(tmp_path: Path):
    path = tmp_path / "model.json"
    save_atomic(path, SelfModel(values=["one"]))
    save_atomic(path, SelfModel(values=["two"]))
    loaded = SelfModel.from_json(path.read_text())
    assert loaded.values == ["two"]


def test_dataclass_is_frozen():
    m = SelfModel()
    with pytest.raises(Exception):
        m.internal_speech_count = 99  # type: ignore[misc]


def test_load_empty_file_returns_empty(tmp_path: Path):
    path = tmp_path / "empty.json"
    path.write_text("", encoding="utf-8")
    m = load(path)
    assert m == SelfModel()


def test_personality_baseline_floats_preserved():
    m = SelfModel(personality_baseline={"openness": 0.7, "conscientiousness": 0.5})
    m2 = SelfModel.from_json(m.to_json())
    assert m2.personality_baseline == {"openness": 0.7, "conscientiousness": 0.5}


# ---- launch name ------------------------------------------------------------

def test_generate_launch_name_is_kaine_plus_surname():
    import random
    from kaine.modules.eidolon.document import generate_launch_name
    name = generate_launch_name(rng=random.Random(0))
    parts = name.split()
    assert parts[0] == "Kaine"
    assert len(parts) == 2 and parts[1]


def test_name_round_trips_through_json():
    from kaine.modules.eidolon.document import SelfModel
    m = SelfModel(name="Kaine Vale", values=["honesty"])
    assert SelfModel.from_json(m.to_json()).name == "Kaine Vale"


def test_name_defaults_empty():
    from kaine.modules.eidolon.document import SelfModel
    assert SelfModel().name == ""


def test_surname_pool_is_the_full_sl_list():
    from kaine.modules.eidolon.document import _SURNAMES
    s = set(_SURNAMES)
    assert len(_SURNAMES) > 300                 # the full released SL set
    assert "Resident" not in s                  # the no-name placeholder is excluded
    # A spread of real SL last names across the years is present.
    for n in ("Voxel", "Atheria", "Aurora", "Blackwood", "Krampus", "Seraphim", "Doge"):
        assert n in s, n
    assert _SURNAMES == tuple(dict.fromkeys(_SURNAMES))  # no duplicates
