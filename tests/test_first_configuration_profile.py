# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The first-configuration profile resolves to the first configuration (config level)."""
from __future__ import annotations

from kaine.config import load_kaine_config

_MISSING_OPERATOR = "/nonexistent-operator-for-tests.toml"


def _cfg():
    return load_kaine_config(profile="first_configuration", operator_path=_MISSING_OPERATOR)


def test_enables_exactly_the_first_configuration_processors():
    cfg = _cfg()
    enabled = sorted(k for k, v in cfg["modules"].items() if v)
    # The first configuration is the four predictive processors plus language, affect (the
    # affective precision core whose arousal weights the competition) and sleep
    # (fatigue-triggered sleep; voice alignment stays off).
    assert enabled == sorted(["audition", "sequence", "sleep", "language", "interoception", "affect", "vision"])
    # Richer faculties stay off.
    for off in ("episodic_memory", "self_model", "planning", "world_model", "vocal"):
        assert cfg["modules"][off] is False


def test_audio_is_prediction_error_not_transcript():
    cfg = _cfg()
    assert cfg["audition"]["transcription_enabled"] is False
    assert cfg["audition"]["general_audition"] is True


def test_vision_is_foveated_and_feed_runs_out_of_box():
    cfg = _cfg()
    assert cfg["vision"]["foveation"] is True
    # The committed profile defaults to the seeded feed so a fresh install runs
    # with no media; the reproducible perceptual run upgrades to a reference
    # stimulus corpus (mode="playlist" + a manifest) via the operator config.
    assert cfg["perception_feed"]["mode"] == "seeded"


def test_voice_is_self_initiated_no_chatbot():
    cfg = _cfg()
    assert cfg["action_selection"]["policy"] == "self_initiated_report"
    assert cfg["action_selection"]["drive_initiative"] is False


def test_language_organ_samples_in_general_use():
    cfg = _cfg()
    # Greedy decoding is set only by study configurations.
    assert cfg["language"]["temperature"] == 0.7
