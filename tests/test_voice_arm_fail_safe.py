# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import os
from pathlib import Path

from kaine.lifecycle.divergence import assess_divergence, voice_paths_for
from tests.test_divergence_voice_arm import _state, _write_intent, _write_measures


def test_corpus_cannot_be_listed_counts_as_spoken(tmp_path, monkeypatch):
    root = _state(tmp_path)
    corpus_dir = root / "lingua" / "intent_log"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    real_scandir = os.scandir

    def fake_scandir(path):
        if Path(path) == corpus_dir:
            raise PermissionError("denied")
        return real_scandir(path)

    monkeypatch.setattr("kaine.lifecycle.divergence.os.scandir", fake_scandir)

    result = assess_divergence(state_root=root)

    assert result.diverged
    assert result.signals["voice_has_spoken"] is True
    assert result.signals["voice_vote"] == "diverged"
    assert result.signals["voice_reason"] == "measurement_missing"


def test_stat_denied_on_live_log_counts_as_spoken(tmp_path, monkeypatch):
    root = _state(tmp_path)
    _write_intent(root, "intent_expression.jsonl", "hello world")
    live_log = root / "lingua" / "intent_expression.jsonl"
    real_stat = os.stat

    def fake_stat(path, *args, **kwargs):
        if Path(path) == live_log:
            raise PermissionError("denied")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr("kaine.lifecycle.divergence.os.stat", fake_stat)

    result = assess_divergence(state_root=root)

    assert result.diverged
    assert result.signals["voice_has_spoken"] is True
    assert result.signals["voice_vote"] == "diverged"
    assert result.signals["voice_reason"] == "measurement_missing"


def test_missing_live_log_and_no_corpus_abstains(tmp_path):
    root = _state(tmp_path)
    result = assess_divergence(state_root=root)
    assert not result.diverged
    assert result.signals["voice_vote"] == "abstain"
    assert result.signals["voice_has_spoken"] is False
    assert result.signals["voice_reason"] is None


def test_live_log_path_is_directory_counts_as_spoken(tmp_path):
    root = _state(tmp_path)
    live_log = root / "lingua" / "intent_expression.jsonl"
    live_log.mkdir(parents=True, exist_ok=True)
    result = assess_divergence(state_root=root)
    assert result.diverged
    assert result.signals["voice_has_spoken"] is True
    assert result.signals["voice_vote"] == "diverged"
    assert result.signals["voice_reason"] == "measurement_missing"


def test_unreadable_voice_paths_config_counts_as_spoken_and_diverged(tmp_path):
    root = _state(tmp_path)
    vp = voice_paths_for({"lingua": "not-a-table"}, root)
    assert vp.unreadable is True
    result = assess_divergence(state_root=root, voice_paths=vp)
    assert result.diverged
    assert result.signals["voice_has_spoken"] is True
    assert result.signals["voice_vote"] == "diverged"
    assert result.signals["voice_reason"] == "voice_paths_unreadable"
    assert "voice data paths could not be read" in result.summary


def test_failed_measurement_record_diverged(tmp_path):
    root = _state(tmp_path)
    _write_intent(root, "intent_expression.jsonl", "hello world")
    _write_measures(
        root,
        {"measurement_failed": True, "timestamp": "2024-01-01T00:00:00+00:00"},
    )
    result = assess_divergence(state_root=root, distinctiveness_threshold=1.0)
    assert result.diverged
    assert result.signals["voice_vote"] == "diverged"
    assert result.signals["voice_reason"] == "measurement_failed"
    assert result.signals["voice_measures_found"] is True
    assert "latest voice measurement failed" in result.summary

    _write_measures(root, {"distinctiveness": 0.1})
    result2 = assess_divergence(state_root=root, distinctiveness_threshold=1.0)
    assert not result2.diverged
    assert result2.signals["voice_vote"] == "not_diverged"
    assert result2.signals["voice_reason"] == "below_threshold"
