# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json
import uuid

import pytest

from kaine.cycle.development import DevelopmentOwner
from tests.test_development_owner import (
    FakeBus,
    FakeClock,
    FakeDrive,
    FakeInteroception,
    _config,
)


class FakeRhythm:
    def __init__(self, identity=None):
        self.identity = identity if identity is not None else uuid.uuid4().hex
        self.identity_restored = False


class RhythmInteroception(FakeInteroception):
    def __init__(self, rhythm):
        super().__init__()
        self._self_rhythm = rhythm


def _owner(tmp_path, interoception):
    return DevelopmentOwner(
        FakeBus(),
        interoception=interoception,
        drive=FakeDrive(),
        beat_phase=lambda: 0.0,
        is_paused=lambda: False,
        config=_config(),
        clock=FakeClock(),
        seed=7,
        state_path=tmp_path / "development_readout.json",
    )


def test_plain_restart_keeps_identity_and_progress(tmp_path):
    rhythm1 = FakeRhythm()
    owner1 = _owner(tmp_path, RhythmInteroception(rhythm1))
    owner1._active_lived_seconds = 7200.0
    owner1._entrainment_consecutive_passes = 2
    owner1._viability_history.append({"lived_hours": 2.0, "pull": 0.01})
    owner1._persist_progress()

    key1 = owner1._baseline_key
    identity1 = rhythm1.identity
    history1 = list(owner1._viability_history)

    rhythm2 = FakeRhythm()
    owner2 = _owner(tmp_path, RhythmInteroception(rhythm2))
    assert rhythm2.identity == identity1
    assert owner2._baseline_key == key1
    assert owner2._active_lived_seconds == 7200.0
    assert owner2._entrainment_consecutive_passes == 2
    assert owner2._viability_history == history1


def test_revive_identity_wins_and_is_stored(tmp_path):
    identity_path = tmp_path / "self_rhythm_identity.json"
    identity_path.write_text(
        json.dumps({"identity": "a" * 32}),
        encoding="utf-8",
    )

    rhythm = FakeRhythm(identity="b" * 32)
    rhythm.identity_restored = True
    owner = _owner(tmp_path, RhythmInteroception(rhythm))
    assert rhythm.identity == "b" * 32
    assert owner._baseline_key.endswith("b" * 32)

    data = json.loads(identity_path.read_text(encoding="utf-8"))
    assert data.get("identity") == "b" * 32


def test_progress_of_another_entity_is_still_ignored(tmp_path):
    rhythm1 = FakeRhythm()
    owner1 = _owner(tmp_path, RhythmInteroception(rhythm1))
    owner1._active_lived_seconds = 7200.0
    owner1._entrainment_consecutive_passes = 2
    owner1._viability_history.append({"lived_hours": 2.0, "pull": 0.01})
    owner1._persist_progress()

    progress_path = tmp_path / "development_progress.json"
    progress_path.write_text(
        json.dumps({"key": "8:" + uuid.uuid4().hex}),
        encoding="utf-8",
    )

    rhythm2 = FakeRhythm()
    owner2 = _owner(tmp_path, RhythmInteroception(rhythm2))
    assert owner2._baseline_key == owner1._baseline_key
    assert owner2._active_lived_seconds == 0.0
    assert owner2._entrainment_consecutive_passes == 0
    assert owner2._viability_history == []


@pytest.mark.parametrize(
    "contents",
    [
        json.dumps({"identity": "not-hex"}),
        "not json",
    ],
    ids=["invalid-identity", "invalid-json"],
)
def test_malformed_identity_file_is_rewritten(tmp_path, contents):
    identity_path = tmp_path / "self_rhythm_identity.json"
    identity_path.write_text(contents, encoding="utf-8")

    rhythm = FakeRhythm(identity="c" * 32)
    _owner(tmp_path, RhythmInteroception(rhythm))
    assert rhythm.identity == "c" * 32

    data = json.loads(identity_path.read_text(encoding="utf-8"))
    assert data.get("identity") == "c" * 32


def test_no_self_rhythm_writes_nothing(tmp_path):
    owner = _owner(tmp_path, FakeInteroception())
    assert owner._baseline_key == "7:none"
    assert not (tmp_path / "self_rhythm_identity.json").exists()


def test_real_oscillator_restart_and_revive(tmp_path):
    pytest.importorskip("snntorch")
    from kaine.oscillator.module_oscillator import make_self_rhythm_oscillator

    osc1 = make_self_rhythm_oscillator(seed=1)
    owner1 = _owner(tmp_path, RhythmInteroception(osc1))
    owner1._active_lived_seconds = 3600.0
    owner1._persist_progress()
    identity1 = osc1.identity

    osc2 = make_self_rhythm_oscillator(seed=1)
    owner2 = _owner(tmp_path, RhythmInteroception(osc2))
    assert osc2.identity == identity1
    assert owner2._active_lived_seconds == 3600.0

    revived_dir = tmp_path / "revived"
    revived_dir.mkdir()
    osc3 = make_self_rhythm_oscillator(seed=1)
    osc3.deserialize(osc1.serialize())
    _owner(revived_dir, RhythmInteroception(osc3))
    assert osc3.identity == identity1

    identity_file = revived_dir / "self_rhythm_identity.json"
    assert identity_file.exists()
    data = json.loads(identity_file.read_text(encoding="utf-8"))
    assert data.get("identity") == identity1
