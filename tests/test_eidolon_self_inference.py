# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for SelfInferenceEngine (eidolon-self-inference change).

Coverage:
- Behavioral norms not populated below speech_pattern_min_count (6.1).
- Behavioral norms populated correctly above min count (6.1).
- VAD stats update on maintenance cycle end (6.1).
- No raw speech text written (6.1) — load-bearing privacy invariant.
- Disabled engine: no fields updated, no crash (6.4).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kaine.modules.eidolon.document import SelfModel
from kaine.modules.eidolon.self_inference import SelfInferenceEngine, _NORM_PREFIX


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine(**kwargs) -> SelfInferenceEngine:
    defaults = {"enabled": True, "speech_pattern_min_count": 3}
    defaults.update(kwargs)
    return SelfInferenceEngine(**defaults)


def _lingua_payload(text: str = "hello") -> dict:
    """Simulate a lingua.out payload.  text is provided to show it is discarded."""
    return {"text": text, "model": "qwen"}


def _thymos_state_payload(v: float, a: float, d: float) -> dict:
    return {"state": {"valence": v, "arousal": a, "dominance": d}}


def _drive_payload(drive: str, value: float = 1.0) -> dict:
    return {"drive": drive, "value": value}


def _policy_payload(action: str, efe: float = -0.5) -> dict:
    return {"policy": action, "expected_free_energy": efe, "horizon": 1}


# ---------------------------------------------------------------------------
# 6.1 Behavioral norms
# ---------------------------------------------------------------------------

def test_norms_empty_below_min_count():
    """Fields remain empty if observations are below speech_pattern_min_count."""
    engine = _make_engine(speech_pattern_min_count=5)
    model = SelfModel()

    # Observe 4 events — one short of the threshold.
    for _ in range(4):
        engine.observe_lingua(_lingua_payload("some text"), "internal.thought")

    updated = engine.maintenance_cycle_end(model)
    # behavioral_norms must still be empty; no speculative entry.
    assert updated.behavioral_norms == []


def test_norms_populated_above_min_count():
    """behavioral_norms gains an entry when count >= speech_pattern_min_count."""
    engine = _make_engine(speech_pattern_min_count=3)
    model = SelfModel()

    for _ in range(3):
        engine.observe_lingua(_lingua_payload("text here"), "internal.thought")

    updated = engine.maintenance_cycle_end(model)
    assert len(updated.behavioral_norms) == 1
    assert updated.behavioral_norms[0] == f"{_NORM_PREFIX}internal.thought"


def test_norms_accumulate_multiple_types():
    """Multiple speech types each produce their own norm entry."""
    engine = _make_engine(speech_pattern_min_count=2)
    model = SelfModel()

    for _ in range(2):
        engine.observe_lingua(_lingua_payload(), "internal.thought")
        engine.observe_lingua(_lingua_payload(), "think")

    updated = engine.maintenance_cycle_end(model)
    assert len(updated.behavioral_norms) == 2
    assert f"{_NORM_PREFIX}internal.thought" in updated.behavioral_norms
    assert f"{_NORM_PREFIX}think" in updated.behavioral_norms


def test_unrecognised_speech_type_not_counted():
    """Event types outside the recognised set are silently ignored."""
    engine = _make_engine(speech_pattern_min_count=1)
    model = SelfModel()

    engine.observe_lingua(_lingua_payload(), "some.unknown.type")
    updated = engine.maintenance_cycle_end(model)
    assert updated.behavioral_norms == []


# ---------------------------------------------------------------------------
# 6.1 VAD statistics on maintenance cycle
# ---------------------------------------------------------------------------

def test_vad_stats_empty_before_cycle():
    """personality_baseline remains empty when no VAD samples have been observed."""
    engine = _make_engine()
    model = SelfModel()
    updated = engine.maintenance_cycle_end(model)
    assert updated.personality_baseline == {}


def test_vad_stats_update_on_maintenance_cycle():
    """VAD rolling mean/variance are computed after a maintenance cycle end."""
    engine = _make_engine(vad_window_cycles=5)
    model = SelfModel()

    # Feed two VAD samples via thymos.state events.
    engine.observe_thymos_state(_thymos_state_payload(0.5, 0.3, 0.1))
    updated = engine.maintenance_cycle_end(model)
    # After first cycle, the window has one sample.
    pb = updated.personality_baseline
    assert "valence_mean" in pb
    assert "arousal_mean" in pb
    assert "dominance_mean" in pb
    assert abs(pb["valence_mean"] - 0.5) < 1e-4
    assert abs(pb["arousal_mean"] - 0.3) < 1e-4
    assert abs(pb["dominance_mean"] - 0.1) < 1e-4
    # Variance should be 0 for a single-sample window.
    assert pb["valence_var"] == pytest.approx(0.0)


def test_vad_stats_rolling_mean():
    """Rolling mean aggregates across multiple maintenance cycles."""
    engine = _make_engine(vad_window_cycles=10)
    model = SelfModel()

    # Three cycles with different VAD.
    for v, a, d in [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.5, 0.5, 0.5)]:
        engine.observe_thymos_state(_thymos_state_payload(v, a, d))
        model = engine.maintenance_cycle_end(model)

    pb = model.personality_baseline
    assert abs(pb["valence_mean"] - 0.5) < 1e-3
    assert abs(pb["arousal_mean"] - 0.5) < 1e-3


# ---------------------------------------------------------------------------
# 6.1 No raw speech text written — load-bearing privacy invariant
# ---------------------------------------------------------------------------

def test_no_raw_speech_text_in_self_model(tmp_path: Path):
    """Raw speech text must NOT appear anywhere in the persisted self-model JSON.

    This is a load-bearing safety invariant: Eidolon derives only numeric /
    categorical summaries from speech events; transcript content is never
    stored.
    """
    from kaine.modules.eidolon.document import save_atomic

    engine = _make_engine(speech_pattern_min_count=1)
    model = SelfModel()

    secret = "do not store this secret utterance text"

    # Simulate 5 observations that include the secret text in the payload.
    for _ in range(3):
        # observe_lingua intentionally discards the text field.
        engine.observe_lingua({"text": secret}, "internal.thought")

    model = engine.maintenance_cycle_end(model)

    # Persist to disk.
    p = tmp_path / "self_model.json"
    save_atomic(p, model)
    written = p.read_text(encoding="utf-8")

    # The secret text must not appear anywhere in the JSON.
    assert secret not in written, (
        "raw speech text found in persisted self_model.json — privacy boundary violated"
    )
    # Individual words of the secret also must not appear (partial match guard).
    for word in secret.split():
        if len(word) > 4:  # skip very short common words
            assert word not in written, (
                f"word {word!r} from raw speech found in persisted self_model.json"
            )


def test_no_raw_speech_text_in_memory_model():
    """The in-memory SelfModel JSON must not contain raw speech text."""
    engine = _make_engine(speech_pattern_min_count=1)
    model = SelfModel()

    secret = "private_utterance_content_xyz"
    for _ in range(2):
        engine.observe_lingua({"text": secret}, "internal.thought")

    model = engine.maintenance_cycle_end(model)

    serialized = model.to_json()
    assert secret not in serialized, "raw speech text found in in-memory SelfModel JSON"


# ---------------------------------------------------------------------------
# 6.4 Disabled engine
# ---------------------------------------------------------------------------

def test_disabled_engine_no_update():
    """When enabled=False, maintenance_cycle_end returns the model unchanged."""
    engine = SelfInferenceEngine(enabled=False)
    model = SelfModel(values=["honesty"])

    # Try to feed observations — must be silently ignored.
    engine.observe_lingua({"text": "ignored"}, "internal.thought")
    engine.observe_thymos_state(_thymos_state_payload(0.5, 0.3, 0.0))
    engine.observe_thymos_drive(_drive_payload("curiosity"))
    engine.observe_nous_policy(_policy_payload("request_think"))

    updated = engine.maintenance_cycle_end(model)

    # Model must be identical (not even a new object with different fields).
    assert updated.values == ["honesty"]
    assert updated.behavioral_norms == []
    assert updated.personality_baseline == {}
    assert updated.capability_map == {}


def test_disabled_engine_no_crash():
    """Disabled engine must not crash under any observation sequence."""
    engine = SelfInferenceEngine(enabled=False)
    model = SelfModel()

    for _ in range(100):
        engine.observe_lingua({"text": "x"}, "internal.thought")
        engine.observe_thymos_state({"state": {}})
        engine.observe_thymos_drive({"drive": "curiosity"})
        engine.observe_nous_policy({"policy": "no_op"})
        model = engine.maintenance_cycle_end(model)

    assert model == SelfModel()


# ---------------------------------------------------------------------------
# Values derived from norms + drives
# ---------------------------------------------------------------------------

def test_values_derived_from_norms_and_drives():
    """values contains drive labels when both norm and drive thresholds are met."""
    engine = _make_engine(speech_pattern_min_count=2)
    model = SelfModel()

    # Enough speech observations for norms.
    for _ in range(2):
        engine.observe_lingua(_lingua_payload(), "internal.thought")

    # Enough drive crossings.
    for _ in range(2):
        engine.observe_thymos_drive(_drive_payload("curiosity"))

    model = engine.maintenance_cycle_end(model)
    assert "drive:curiosity" in model.values


def test_values_empty_when_no_norms():
    """values remains empty when norms are not yet populated."""
    engine = _make_engine(speech_pattern_min_count=10)
    model = SelfModel()

    # Only drives, no norms.
    for _ in range(5):
        engine.observe_thymos_drive(_drive_payload("curiosity"))

    model = engine.maintenance_cycle_end(model)
    assert model.values == []


def test_set_whitelist_commands_surfaces_effectors():
    """set_whitelist_commands injects the Praxis effector whitelist so a
    maintenance cycle surfaces capability_map['effectors'], sorted
    (eidolon-self-inference "Capability map from Praxis whitelist")."""
    engine = SelfInferenceEngine(enabled=True)
    engine.set_whitelist_commands(["notify", "file_write"])
    model = engine.maintenance_cycle_end(SelfModel())
    assert model.capability_map.get("effectors") == ["file_write", "notify"]


def test_set_whitelist_commands_empty_leaves_effectors_absent():
    """An empty whitelist produces no 'effectors' entry (not an empty list)."""
    engine = SelfInferenceEngine(enabled=True)
    engine.set_whitelist_commands([])
    model = engine.maintenance_cycle_end(SelfModel())
    assert "effectors" not in model.capability_map
