# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The thesis-test profile resolves to the base-thesis form (config level)."""
from __future__ import annotations

from kaine.config import load_kaine_config

_MISSING_OPERATOR = "/nonexistent-operator-for-tests.toml"


def _cfg():
    return load_kaine_config(profile="thesis_test", operator_path=_MISSING_OPERATOR)


def test_enables_exactly_the_thesis_processors():
    cfg = _cfg()
    enabled = sorted(k for k, v in cfg["modules"].items() if v)
    # The base thesis is the four externally-grounded processors plus Lingua and
    # Thymos, the affective precision core whose arousal weights the competition.
    assert enabled == ["audition", "chronos", "lingua", "soma", "thymos", "topos"]
    # Richer faculties stay off.
    for off in ("mnemos", "eidolon", "nous", "phantasia", "vox", "hypnos"):
        assert cfg["modules"][off] is False


def test_audio_is_prediction_error_not_transcript():
    cfg = _cfg()
    assert cfg["audition"]["transcription_enabled"] is False
    assert cfg["audition"]["general_audition"] is True


def test_vision_is_foveated_and_feed_runs_out_of_box():
    cfg = _cfg()
    assert cfg["topos"]["foveation"] is True
    # The committed profile defaults to the seeded feed so a fresh install runs
    # with no media; the reproducible perceptual run upgrades to a reference
    # stimulus corpus (mode="playlist" + a manifest) via the operator config.
    assert cfg["perception_feed"]["mode"] == "seeded"


def test_voice_is_self_initiated_no_chatbot():
    cfg = _cfg()
    assert cfg["volition"]["policy"] == "self_initiated_report"
    assert cfg["volition"]["drive_initiative"] is False
