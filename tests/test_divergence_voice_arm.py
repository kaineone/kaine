# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json

import pytest

from kaine.lifecycle.divergence import assess_divergence


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
