# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json
import os
from pathlib import Path

import pytest

from kaine.lifecycle.divergence import (
    VoicePaths,
    assess_divergence,
    default_voice_paths,
    voice_paths_for,
)
from kaine.modules.hypnos.voice_measures import FUNCTION_WORDS, style_profile


def _state(tmp_path):
    return tmp_path / "state"


def _write_intent(root, filename, text):
    lingua = root / "lingua"
    lingua.mkdir(parents=True, exist_ok=True)
    (lingua / filename).write_text(
        json.dumps({"generated_text": text}) + "\n", encoding="utf-8"
    )


def _write_measures(root, measures):
    lingua = root / "lingua"
    lingua.mkdir(parents=True, exist_ok=True)
    (lingua / "voice_measures_latest.json").write_text(
        json.dumps(measures), encoding="utf-8"
    )


def test_silent_being_not_diverged_abstains(tmp_path):
    root = _state(tmp_path)
    result = assess_divergence(state_root=root)
    assert not result.diverged
    assert result.signals["voice_vote"] == "abstain"
    assert result.signals["voice_has_spoken"] is False


def test_silent_being_with_consolidation_over_threshold_is_diverged(tmp_path):
    root = _state(tmp_path)
    hypnos = root / "hypnos"
    hypnos.mkdir(parents=True, exist_ok=True)
    (hypnos / "consolidation_divergence.json").write_text(
        json.dumps({"divergence_rate": 0.9, "divergence_magnitude": 0.0}),
        encoding="utf-8",
    )
    result = assess_divergence(state_root=root)
    assert result.diverged
    assert result.signals["voice_vote"] == "abstain"


def test_spoken_no_measures_file_is_diverged(tmp_path):
    root = _state(tmp_path)
    _write_intent(root, "intent_expression.jsonl", "hello world")
    result = assess_divergence(state_root=root)
    assert result.diverged
    assert result.signals["voice_vote"] == "diverged"
    assert result.signals["voice_measures_found"] is False


def test_spoken_unreadable_measures_file_is_diverged(tmp_path):
    root = _state(tmp_path)
    _write_intent(root, "intent_expression.jsonl", "hello world")
    _write_measures(root, "this is not json")
    result = assess_divergence(state_root=root)
    assert result.diverged
    assert result.signals["voice_vote"] == "diverged"


def test_spoken_null_distinctiveness_is_diverged(tmp_path):
    root = _state(tmp_path)
    _write_intent(root, "intent_expression.jsonl", "hello world")
    _write_measures(root, {"distinctiveness": None})
    result = assess_divergence(state_root=root)
    assert result.diverged
    assert result.signals["voice_vote"] == "diverged"


def test_spoken_zero_distinctiveness_at_zero_threshold_is_diverged(tmp_path):
    root = _state(tmp_path)
    _write_intent(root, "intent_expression.jsonl", "hello world")
    _write_measures(root, {"distinctiveness": 0.0})
    result = assess_divergence(state_root=root, distinctiveness_threshold=0.0)
    assert result.diverged
    assert result.signals["voice_vote"] == "diverged"


def test_spoken_low_distinctiveness_at_high_threshold_not_diverged(tmp_path):
    root = _state(tmp_path)
    _write_intent(root, "intent_expression.jsonl", "hello world")
    _write_measures(root, {"distinctiveness": 0.1})
    result = assess_divergence(state_root=root, distinctiveness_threshold=0.5)
    assert not result.diverged
    assert result.signals["voice_vote"] == "not_diverged"


def test_unreadable_intent_log_counts_as_spoken(tmp_path):
    root = _state(tmp_path)
    log_dir = root / "lingua" / "intent_log"
    log_dir.mkdir(parents=True, exist_ok=True)
    p = log_dir / "sleep-1.jsonl"
    p.write_text(json.dumps({"generated_text": "hello world"}) + "\n")
    p.chmod(0o000)
    try:
        result = assess_divergence(state_root=root)
        assert result.diverged
        assert result.signals["voice_has_spoken"] is True
        assert result.signals["voice_vote"] == "diverged"
    finally:
        p.chmod(0o644)


def test_signals_carry_voice_values(tmp_path):
    root = _state(tmp_path)
    _write_intent(root, "intent_expression.jsonl", "hello world")
    _write_measures(
        root,
        {
            "distinctiveness": 0.3,
            "self_consistency": 0.2,
            "grounding": 0.8,
        },
    )
    result = assess_divergence(state_root=root, distinctiveness_threshold=0.5)
    s = result.signals
    assert s["voice_has_spoken"] is True
    assert s["voice_distinctiveness"] == pytest.approx(0.3)
    assert s["voice_self_consistency"] == pytest.approx(0.2)
    assert s["voice_grounding"] == pytest.approx(0.8)
    assert s["voice_distinctiveness_threshold"] == pytest.approx(0.5)
    assert s["voice_vote"] == "not_diverged"
    assert s["voice_measures_found"] is True
    assert "voice" in result.summary.lower()


def test_spoken_non_finite_distinctiveness_is_diverged(tmp_path):
    """A NaN or infinite distinctiveness is not a measurement; it must never
    read as "below threshold"."""
    root = _state(tmp_path)
    _write_intent(root, "intent_expression.jsonl", "hello")
    for bad in ("NaN", "Infinity"):
        (root / "lingua" / "voice_measures_latest.json").write_text(
            '{"distinctiveness": ' + bad + "}", encoding="utf-8"
        )
        result = assess_divergence(state_root=root, distinctiveness_threshold=0.5)
        assert result.diverged, bad
        assert result.signals["voice_vote"] == "diverged"


def test_voice_arm_is_its_own_preservation_edge():
    """The safety net names the voice arm, so it has its own rising edge even
    when another arm is already active."""
    from kaine.cycle.preservation_monitor import _active_arms
    from kaine.lifecycle.divergence import DivergenceAssessment

    both = DivergenceAssessment(
        diverged=True,
        signals={"consolidation_divergence_signal": True, "voice_vote": "diverged"},
    )
    assert _active_arms(both) == frozenset({"consolidation", "voice"})
    abstain = DivergenceAssessment(diverged=False, signals={"voice_vote": "abstain"})
    assert _active_arms(abstain) == frozenset()


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0])
def test_non_finite_or_negative_threshold_falls_back_to_protective_zero(tmp_path, bad):
    root = _state(tmp_path)
    _write_intent(root, "intent_expression.jsonl", "hello world")
    _write_measures(root, {"distinctiveness": 0.1})
    result = assess_divergence(state_root=root, distinctiveness_threshold=bad)
    assert result.diverged
    assert result.signals["voice_vote"] == "diverged"
    assert result.signals["voice_distinctiveness_threshold"] == 0.0


@pytest.mark.parametrize("bad", ["nan", "inf", -1.0, "lots"])
def test_config_threshold_reader_never_silences_the_arm(bad):
    from kaine.lifecycle.divergence import voice_alignment_thresholds_from_config

    cfg = {"hypnos": {"voice_alignment": {"distinctiveness_threshold": bad}}}
    assert voice_alignment_thresholds_from_config(cfg)[2] == 0.0


@pytest.mark.parametrize("bad", ["nan", "inf", -1.0, "lots"])
def test_boot_refuses_a_threshold_that_is_not_finite_and_non_negative(bad):
    from kaine.boot.errors import VoiceAlignmentConfigError
    from kaine.boot.factories.hypnos import voice_alignment_config_from_section

    with pytest.raises(VoiceAlignmentConfigError, match="distinctiveness_threshold"):
        voice_alignment_config_from_section({"distinctiveness_threshold": bad})


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.5])
def test_voice_config_refuses_a_threshold_that_is_not_finite_and_non_negative(tmp_path, bad):
    from kaine.modules.hypnos.voice_alignment import VoiceAlignmentConfig

    with pytest.raises(ValueError, match="distinctiveness_threshold"):
        VoiceAlignmentConfig(
            intent_log_path=tmp_path / "log.jsonl",
            adapter_output_dir=tmp_path / "adapters",
            distinctiveness_threshold=bad,
        )


def test_reason_names_the_measured_distinctiveness_and_threshold(tmp_path):
    root = _state(tmp_path)
    _write_intent(root, "intent_expression.jsonl", "hello world")
    _write_measures(root, {"distinctiveness": 0.6})
    result = assess_divergence(state_root=root, distinctiveness_threshold=0.5)
    assert result.diverged
    assert "0.6000" in result.summary and "threshold 0.5" in result.summary
    assert "uncalibrated" not in result.summary


def test_reason_names_a_missing_measurement(tmp_path):
    root = _state(tmp_path)
    _write_intent(root, "intent_expression.jsonl", "hello world")
    result = assess_divergence(state_root=root, distinctiveness_threshold=0.5)
    assert "no readable voice distinctiveness measurement" in result.summary


def test_configured_voice_paths_find_speech_outside_default(tmp_path):
    root = _state(tmp_path)
    custom = tmp_path / "custom"
    custom.mkdir(parents=True, exist_ok=True)
    live = custom / "intent_expression.jsonl"
    live.write_text(
        json.dumps({"generated_text": "hello custom"}) + "\n", encoding="utf-8"
    )
    cfg = {
        "lingua": {"intent_log_path": str(live)},
        "hypnos": {"voice_alignment": {"intent_log_path": str(live)}},
    }
    voice_paths = voice_paths_for(cfg, root)

    result = assess_divergence(state_root=root, voice_paths=voice_paths)
    assert result.diverged
    assert result.signals["voice_has_spoken"] is True
    assert result.signals["voice_vote"] == "diverged"

    default_paths = default_voice_paths(root)
    result_default = assess_divergence(state_root=root, voice_paths=default_paths)
    assert not result_default.diverged
    assert result_default.signals["voice_vote"] == "abstain"


def test_unparseable_intent_line_counts_as_spoken(tmp_path):
    root = _state(tmp_path)
    lingua = root / "lingua"
    lingua.mkdir(parents=True, exist_ok=True)
    (lingua / "intent_expression.jsonl").write_text(
        "not json at all\n", encoding="utf-8"
    )
    result = assess_divergence(state_root=root)
    assert result.diverged
    assert result.signals["voice_has_spoken"] is True
    assert result.signals["voice_vote"] == "diverged"


def test_live_log_read_before_corpus_rotation(tmp_path, monkeypatch):
    """Hypnos rotates the live log the moment it is opened. The records then
    sit only in the corpus, so a corpus listed before the read would miss
    them and the being would read as silent."""
    root = _state(tmp_path)
    live = root / "lingua" / "intent_expression.jsonl"
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_text(json.dumps({"generated_text": "hello"}) + "\n", encoding="utf-8")
    corpus = live.parent / "intent_log"
    corpus.mkdir()

    real_open = Path.open
    rotated = []

    def rotating_open(self, *args, **kwargs):
        if self == live and not rotated:
            rotated.append(True)
            os.replace(live, corpus / "sleep-1.jsonl")
            live.write_text("", encoding="utf-8")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", rotating_open)
    voice_paths = VoicePaths(
        intent_logs=(live,),
        measures_latest=live.parent / "voice_measures_latest.json",
    )
    result = assess_divergence(state_root=root, voice_paths=voice_paths)
    assert rotated
    assert result.signals["voice_has_spoken"] is True
    assert result.signals["voice_vote"] == "diverged"


def test_lowercase_i_function_word_is_counted():
    profile = style_profile(["I think I am here"])
    idx = FUNCTION_WORDS.index("i")
    assert profile["function_words"][idx] > 0
