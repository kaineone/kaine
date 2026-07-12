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
    assert enabled == ["audition", "chronos", "lingua", "soma", "topos"]
    # Richer faculties stay off.
    for off in ("mnemos", "eidolon", "thymos", "nous", "phantasia", "vox", "hypnos"):
        assert cfg["modules"][off] is False


def test_audio_is_prediction_error_not_transcript():
    cfg = _cfg()
    assert cfg["audition"]["transcription_enabled"] is False
    assert cfg["audition"]["general_audition"] is True


def test_vision_is_foveated_and_feed_is_raw_av():
    cfg = _cfg()
    assert cfg["topos"]["foveation"] is True
    # Playlist mode: a fixed reference stimulus corpus (manifest-pinned), decoded
    # directly — not a PRNG seed and not screen-captured. The manifest path itself
    # is operator/media-specific and set in the operator config, not the profile.
    assert cfg["perception_feed"]["mode"] == "playlist"


def test_voice_is_self_initiated_no_chatbot():
    cfg = _cfg()
    assert cfg["volition"]["policy"] == "self_initiated_report"
    assert cfg["volition"]["drive_initiative"] is False
