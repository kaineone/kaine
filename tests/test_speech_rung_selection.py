# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from types import SimpleNamespace

from kaine.residency.speech_rungs import (
    STT_LADDER,
    TTS_LADDER,
    select_rung,
)


def test_select_heaviest_when_all_fit(monkeypatch):
    """When all rungs are installed and fit, select the heaviest."""
    monkeypatch.setattr("kaine.residency.speech_rungs.is_rung_installed", lambda r: True)
    entries = [
        SimpleNamespace(
            component="vocal.tts",
            backend="chatterbox",
            model_id="chatterbox",
            host_class="cpu",
            bytes=2_000_000_000,
        ),
    ]
    sel = select_rung(TTS_LADDER, "vocal.tts", entries, "cpu", 4_000_000_000)
    assert sel is not None
    assert sel.rung.backend == "chatterbox"
    assert sel.hints == ()


def test_select_lighter_when_heavy_exceeds_budget(monkeypatch):
    """When the heaviest rung exceeds budget, select the next lighter."""
    monkeypatch.setattr("kaine.residency.speech_rungs.is_rung_installed", lambda r: True)
    entries = [
        SimpleNamespace(
            component="vocal.tts",
            backend="chatterbox",
            model_id="chatterbox",
            host_class="cpu",
            bytes=4_000_000_000,
        ),
        SimpleNamespace(
            component="vocal.tts",
            backend="sherpa_onnx",
            model_id="kokoro-en",
            host_class="cpu",
            bytes=200_000_000,
        ),
    ]
    sel = select_rung(TTS_LADDER, "vocal.tts", entries, "cpu", 1_000_000_000)
    assert sel is not None
    assert sel.rung.backend == "sherpa_onnx"
    assert sel.rung.model_id == "kokoro-en"


def test_select_skips_uninstalled_with_hint(monkeypatch):
    """Uninstalled rungs are skipped and produce hints."""
    monkeypatch.setattr(
        "kaine.residency.speech_rungs.is_rung_installed",
        lambda r: r.backend != "speaches",
    )
    entries = [
        SimpleNamespace(
            component="audition.stt",
            backend="sherpa_onnx",
            model_id="moonshine-base-en",
            host_class="cpu",
            bytes=300_000_000,
        ),
    ]
    sel = select_rung(STT_LADDER, "audition.stt", entries, "cpu", 1_000_000_000)
    assert sel is not None
    assert sel.rung.model_id == "moonshine-base-en"
    assert len(sel.hints) == 0


def test_select_none_when_nothing_installed(monkeypatch):
    """Returns None when no rung is installed."""
    monkeypatch.setattr("kaine.residency.speech_rungs.is_rung_installed", lambda r: False)
    sel = select_rung(STT_LADDER, "audition.stt", [], "cpu", 4_000_000_000)
    assert sel is None


def test_select_uncalibrated_rung_accepted(monkeypatch):
    """A rung with no calibration data is accepted (cannot prove it does not fit)."""
    monkeypatch.setattr("kaine.residency.speech_rungs.is_rung_installed", lambda r: True)
    sel = select_rung(TTS_LADDER, "vocal.tts", [], "cpu", 1_000_000_000)
    assert sel is not None
    assert sel.rung.backend == "chatterbox"
    assert "uncalibrated" in sel.reason


def test_select_no_budget_accepts_heaviest(monkeypatch):
    """With budget_bytes=None, the heaviest installed rung is selected."""
    monkeypatch.setattr("kaine.residency.speech_rungs.is_rung_installed", lambda r: True)
    sel = select_rung(TTS_LADDER, "vocal.tts", [], "cpu", None)
    assert sel is not None
    assert sel.rung.backend == "chatterbox"


def test_select_stt_walks_full_ladder(monkeypatch):
    """STT selection walks all three rungs when heavier ones do not fit."""
    monkeypatch.setattr("kaine.residency.speech_rungs.is_rung_installed", lambda r: True)
    entries = [
        SimpleNamespace(
            component="audition.stt",
            backend="speaches",
            model_id="medium.en",
            host_class="cpu",
            bytes=2_000_000_000,
        ),
        SimpleNamespace(
            component="audition.stt",
            backend="sherpa_onnx",
            model_id="moonshine-base-en",
            host_class="cpu",
            bytes=500_000_000,
        ),
        SimpleNamespace(
            component="audition.stt",
            backend="sherpa_onnx",
            model_id="moonshine-tiny-en",
            host_class="cpu",
            bytes=100_000_000,
        ),
    ]
    sel = select_rung(STT_LADDER, "audition.stt", entries, "cpu", 200_000_000)
    assert sel is not None
    assert sel.rung.model_id == "moonshine-tiny-en"


def test_hints_for_absent_sherpa_models(monkeypatch):
    """Hints include fetch commands for absent sherpa models."""

    def _installed(r):
        return r.backend == "speaches"

    monkeypatch.setattr("kaine.residency.speech_rungs.is_rung_installed", _installed)
    entries = [
        SimpleNamespace(
            component="audition.stt",
            backend="speaches",
            model_id="medium.en",
            host_class="cpu",
            bytes=100_000_000,
        ),
    ]
    sel = select_rung(STT_LADDER, "audition.stt", entries, "cpu", 1_000_000_000)
    assert sel is not None
    assert sel.rung.backend == "speaches"
    assert len(sel.hints) == 0
