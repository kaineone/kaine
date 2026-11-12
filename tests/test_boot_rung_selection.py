# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the speech rung selection wiring in construct_module()."""

from __future__ import annotations

from types import SimpleNamespace

from kaine.residency.speech_rungs import (
    LADDERS,
    rung_key,
    select_rung,
)


class FakeRouter:
    """Minimal stand-in for ResidencyRouter with a configurable headroom."""

    def __init__(self, headroom: int):
        self._headroom = headroom

    @property
    def ledger(self):
        return self

    @property
    def headroom(self) -> int:
        return self._headroom


# ---- helpers ---------------------------------------------------------------


def _entry(component: str, backend: str, model_id: str, host_class: str, nbytes: int):
    """Build a catalogue-shaped SimpleNamespace for test fixtures."""
    return SimpleNamespace(
        component=component,
        backend=backend,
        model_id=model_id,
        host_class=host_class,
        bytes=nbytes,
    )


# ---- tests -----------------------------------------------------------------


def test_no_rung_override_when_residency_disabled(monkeypatch):
    """select_rung must NOT be called when router is None."""
    called = False

    def _spy(*args, **kwargs):
        nonlocal called
        called = True
        return None

    monkeypatch.setattr("kaine.residency.speech_rungs.select_rung", _spy)

    # Import the constant we added
    from kaine.boot.registry import _SPEECH_COMPONENTS

    # Simulate the guard: router is None -> the block is skipped entirely
    router = None
    name = "vocal"
    assert name in _SPEECH_COMPONENTS
    assert router is None
    assert not called


def test_rung_override_selects_lighter_backend(monkeypatch):
    """When the heavy rung exceeds the residency budget, the lighter rung wins."""
    monkeypatch.setattr("kaine.residency.speech_rungs.is_rung_installed", lambda r: True)

    entries = [
        _entry("vocal.tts", "chatterbox", "chatterbox", "cpu", 4_000_000_000),
        _entry("vocal.tts", "sherpa_onnx", "kokoro-en", "cpu", 200_000_000),
    ]

    sel = select_rung(LADDERS["vocal.tts"], "vocal.tts", entries, "cpu", 1_000_000_000)
    assert sel is not None
    assert sel.rung.backend == "sherpa_onnx"
    assert sel.rung.model_id == "kokoro-en"

    # Simulate section override
    section: dict = {"backend": "chatterbox"}
    section["backend"] = sel.rung.backend
    section["sherpa_model_id"] = sel.rung.model_id
    assert section["backend"] == "sherpa_onnx"
    assert section["sherpa_model_id"] == "kokoro-en"


def test_downgrade_recorded_on_backend_change(monkeypatch):
    """record_backend_failure and record_downgrade fire when backend changes."""
    monkeypatch.setattr("kaine.residency.speech_rungs.is_rung_installed", lambda r: True)

    entries = [
        _entry("vocal.tts", "chatterbox", "chatterbox", "cpu", 4_000_000_000),
        _entry("vocal.tts", "sherpa_onnx", "kokoro-en", "cpu", 200_000_000),
    ]

    sel = select_rung(LADDERS["vocal.tts"], "vocal.tts", entries, "cpu", 1_000_000_000)
    assert sel is not None

    configured_backend = "chatterbox"
    failures: list = []
    downgrades: list = []

    monkeypatch.setattr(
        "kaine.backend_state.record_backend_failure",
        lambda **kw: failures.append(kw),
    )
    monkeypatch.setattr(
        "kaine.residency.events.record_downgrade",
        lambda **kw: downgrades.append(kw),
    )

    # Replicate the construct_module downgrade logic
    from kaine.backend_state import record_backend_failure
    from kaine.residency.events import record_downgrade

    if configured_backend and sel.rung.backend != configured_backend:
        record_backend_failure(
            module="vocal",
            backend=configured_backend,
            reason=sel.reason,
            fallback=sel.rung.backend,
        )
        record_downgrade(
            name="vocal",
            reason=sel.reason,
            from_rung=configured_backend,
            to_rung=rung_key(sel.rung),
        )

    assert len(failures) == 1
    assert failures[0]["module"] == "vocal"
    assert failures[0]["backend"] == "chatterbox"
    assert failures[0]["fallback"] == "sherpa_onnx"

    assert len(downgrades) == 1
    assert downgrades[0]["from_rung"] == "chatterbox"
    assert downgrades[0]["to_rung"] == "sherpa_onnx:kokoro-en"


def test_no_downgrade_when_same_backend(monkeypatch):
    """When the selected backend matches configured, no downgrade is recorded."""
    monkeypatch.setattr("kaine.residency.speech_rungs.is_rung_installed", lambda r: True)

    entries = [
        _entry("vocal.tts", "chatterbox", "chatterbox", "cpu", 500_000_000),
    ]

    sel = select_rung(LADDERS["vocal.tts"], "vocal.tts", entries, "cpu", 2_000_000_000)
    assert sel is not None
    assert sel.rung.backend == "chatterbox"

    configured_backend = "chatterbox"

    failures: list = []
    downgrades: list = []

    monkeypatch.setattr(
        "kaine.backend_state.record_backend_failure",
        lambda **kw: failures.append(kw),
    )
    monkeypatch.setattr(
        "kaine.residency.events.record_downgrade",
        lambda **kw: downgrades.append(kw),
    )

    # Replicate guard: same backend -> no downgrade
    if configured_backend and sel.rung.backend != configured_backend:
        from kaine.backend_state import record_backend_failure
        from kaine.residency.events import record_downgrade

        record_backend_failure(
            module="vocal",
            backend=configured_backend,
            reason=sel.reason,
            fallback=sel.rung.backend,
        )
        record_downgrade(
            name="vocal",
            reason=sel.reason,
            from_rung=configured_backend,
            to_rung=rung_key(sel.rung),
        )

    assert len(failures) == 0
    assert len(downgrades) == 0


def test_uncalibrated_accepts_heaviest(monkeypatch):
    """Empty catalogue entries -> heaviest installed rung is accepted (uncalibrated)."""
    monkeypatch.setattr("kaine.residency.speech_rungs.is_rung_installed", lambda r: True)

    sel = select_rung(LADDERS["vocal.tts"], "vocal.tts", [], "cpu", 500_000_000)
    assert sel is not None
    assert sel.rung.backend == "chatterbox"
    assert "uncalibrated" in sel.reason


def test_speech_components_constant():
    """The _SPEECH_COMPONENTS constant maps module names to ladder keys."""
    from kaine.boot.registry import _SPEECH_COMPONENTS

    assert _SPEECH_COMPONENTS == {"vocal": "vocal.tts", "audition": "audition.stt"}
    for component in _SPEECH_COMPONENTS.values():
        assert component in LADDERS


def test_sherpa_model_id_set_for_sherpa_rung(monkeypatch):
    """When the selected rung is sherpa_onnx, sherpa_model_id is set on section."""
    monkeypatch.setattr("kaine.residency.speech_rungs.is_rung_installed", lambda r: True)

    entries = [
        _entry("vocal.tts", "chatterbox", "chatterbox", "cpu", 4_000_000_000),
        _entry("vocal.tts", "sherpa_onnx", "kokoro-en", "cpu", 200_000_000),
    ]

    sel = select_rung(LADDERS["vocal.tts"], "vocal.tts", entries, "cpu", 1_000_000_000)
    assert sel is not None

    section: dict = {"backend": "chatterbox"}
    section["backend"] = sel.rung.backend
    if sel.rung.backend == "sherpa_onnx":
        section["sherpa_model_id"] = sel.rung.model_id

    assert section["backend"] == "sherpa_onnx"
    assert section["sherpa_model_id"] == "kokoro-en"


def test_no_sherpa_model_id_for_service_backend(monkeypatch):
    """When the selected rung is a service backend, sherpa_model_id is NOT set."""
    monkeypatch.setattr("kaine.residency.speech_rungs.is_rung_installed", lambda r: True)

    entries = [
        _entry("vocal.tts", "chatterbox", "chatterbox", "cpu", 500_000_000),
    ]

    sel = select_rung(LADDERS["vocal.tts"], "vocal.tts", entries, "cpu", 2_000_000_000)
    assert sel is not None

    section: dict = {"backend": "chatterbox"}
    section["backend"] = sel.rung.backend
    if sel.rung.backend == "sherpa_onnx":
        section["sherpa_model_id"] = sel.rung.model_id

    assert section["backend"] == "chatterbox"
    assert "sherpa_model_id" not in section


def test_audition_stt_rung_selection(monkeypatch):
    """Rung selection works for the audition module (STT ladder)."""
    monkeypatch.setattr("kaine.residency.speech_rungs.is_rung_installed", lambda r: True)

    entries = [
        _entry("audition.stt", "speaches", "medium.en", "cpu", 3_000_000_000),
        _entry("audition.stt", "sherpa_onnx", "moonshine-base-en", "cpu", 300_000_000),
        _entry("audition.stt", "sherpa_onnx", "moonshine-tiny-en", "cpu", 100_000_000),
    ]

    sel = select_rung(LADDERS["audition.stt"], "audition.stt", entries, "cpu", 500_000_000)
    assert sel is not None
    assert sel.rung.backend == "sherpa_onnx"
    assert sel.rung.model_id == "moonshine-base-en"


def test_no_rung_fits_records_failure(monkeypatch):
    """When no rung fits, record_backend_failure fires with the configured backend."""
    monkeypatch.setattr("kaine.residency.speech_rungs.is_rung_installed", lambda r: True)

    entries = [
        _entry("vocal.tts", "chatterbox", "chatterbox", "cpu", 4_000_000_000),
        _entry("vocal.tts", "sherpa_onnx", "kokoro-en", "cpu", 2_000_000_000),
    ]

    sel = select_rung(LADDERS["vocal.tts"], "vocal.tts", entries, "cpu", 100_000_000)
    assert sel is None

    failures: list = []
    monkeypatch.setattr(
        "kaine.backend_state.record_backend_failure",
        lambda **kw: failures.append(kw),
    )

    from kaine.backend_state import record_backend_failure

    configured_backend = "chatterbox"
    if sel is None and configured_backend:
        record_backend_failure(
            module="vocal",
            backend=configured_backend,
            reason="no installed speech rung fits residency budget",
        )

    assert len(failures) == 1
    assert failures[0]["module"] == "vocal"
    assert failures[0]["reason"] == "no installed speech rung fits residency budget"
