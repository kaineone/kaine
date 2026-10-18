# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import logging

import pytest

pytest.importorskip("av")

from kaine.boot.perception_feed import (
    _build_perception_feed_audio_factory,
    _maternal_voice_params,
    _stimulus_source_params,
    gather_perception_feed_descriptor,
)
from kaine.lifecycle.stage import stimulus_source_params_digest
from kaine.modules.audition.feed import (
    StimulusSourceAudioSchedule,
    StimulusSourceProceduralAudioStream,
)
from kaine.modules.audition.live import PerceptionUnavailableError
from kaine.modules.audition.maternal_voice import (
    MaternalVoiceLayer,
    MaternalVoiceParams,
)
from kaine.modules.vision.feed import StimulusSourceClock


def _make_stream(feed):
    factory = _build_perception_feed_audio_factory(
        "stimulus_source",
        feed,
        sample_rate=16000,
        channels=1,
        frames_per_block=480,
    )
    return factory(
        device=None,
        sample_rate=16000,
        channels=1,
        frames_per_block=480,
        callback=lambda b: None,
    )


def test_stimulus_source_audio_includes_maternal_voice():
    stream = _make_stream({"seed": 7, "stimulus_source": {}})
    assert isinstance(stream._voice, MaternalVoiceLayer)
    assert callable(stream._awake)


def test_stimulus_source_voice_disabled_matches_voiceless():
    stream = _make_stream({"seed": 7, "stimulus_source": {"voice": {"enabled": False}}})
    assert stream._voice is None

    clock = StimulusSourceClock(lived_offset_seconds=0.0)
    params = _stimulus_source_params({"seed": 7, "stimulus_source": {}})
    schedule = StimulusSourceAudioSchedule(
        seed=7,
        sample_rate=16000,
        channels=1,
        frames_per_block=480,
    )
    direct = StimulusSourceProceduralAudioStream(
        schedule,
        params=params,
        clock=clock,
        callback=lambda b: None,
    )
    for block in range(50):
        assert stream.pcm_at(block) == direct.pcm_at(block)


def test_stimulus_source_voice_validation():
    with pytest.raises(ValueError):
        _build_perception_feed_audio_factory(
            "stimulus_source",
            {"seed": 7, "stimulus_source": {"voice": {"unknown_key": 1}}},
            sample_rate=16000,
            channels=1,
            frames_per_block=480,
        )
    with pytest.raises(ValueError):
        _build_perception_feed_audio_factory(
            "stimulus_source",
            {"seed": 7, "stimulus_source": {"voice": "not a table"}},
            sample_rate=16000,
            channels=1,
            frames_per_block=480,
        )


def test_stimulus_source_voice_missing_repertoire(monkeypatch, caplog):
    def fake_load(*args, **kwargs):
        raise PerceptionUnavailableError("gone")

    monkeypatch.setattr(
        "kaine.modules.audition.maternal_voice.MaternalVoiceRepertoire.load",
        fake_load,
    )
    with caplog.at_level(logging.CRITICAL, logger="kaine.boot.perception_feed"):
        with pytest.raises(PerceptionUnavailableError):
            _build_perception_feed_audio_factory(
                "stimulus_source",
                {"seed": 7, "stimulus_source": {}},
                sample_rate=16000,
                channels=1,
                frames_per_block=480,
            )
    assert any("maternal voice" in r.message for r in caplog.records)


def test_stimulus_source_params_digest_ignores_voice():
    base = {"seed": 7, "stimulus_source": {}}
    changed = {"seed": 7, "stimulus_source": {"voice": {"level_db": 3.0}}}
    assert stimulus_source_params_digest(
        _stimulus_source_params(base)
    ) == stimulus_source_params_digest(_stimulus_source_params(changed))


def test_maternal_voice_params_defaults_and_read():
    defaults = _maternal_voice_params({})
    assert defaults.enabled is True
    assert defaults.level_db == MaternalVoiceParams.from_section(None).level_db
    custom = _maternal_voice_params(
        {"stimulus_source": {"voice": {"level_db": 3.0}}}
    )
    assert custom.level_db == 3.0


def test_gather_perception_feed_descriptor_maternal_voice(monkeypatch):
    monkeypatch.setattr(
        "kaine.boot.perception_feed._stimulus_source_lived_offset",
        lambda stage_path=None: 0.0,
    )
    config = {
        "perception_feed": {
            "mode": "stimulus_source",
            "seed": 7,
            "stimulus_source": {},
        },
    }
    descriptor = gather_perception_feed_descriptor(config)
    mv = descriptor["maternal_voice"]
    assert mv["enabled"] is True
    assert isinstance(mv["manifest_sha256"], str)
    assert len(mv["manifest_sha256"]) == 64
