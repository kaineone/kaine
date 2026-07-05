# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.faithful.templates import TEMPLATES, fallback_template


_BANNED_PHRASES = (
    "i think",
    "as an ai",
    "maybe",
    "perhaps",
    "in summary",
    "it seems",
)


_SAMPLE_PAYLOADS: dict[tuple[str, str], dict] = {
    ("soma", "soma.report"): {"wellness": 0.85, "alerts": []},
    ("soma", "soma.fatigue"): {"value": 75.3, "threshold": 100.0, "crossed": False},
    ("soma", "soma.regulation"): {
        "action": "reduce_rate",
        "reason": "prediction error 0.8 sustained above threshold",
        "severity": 1,
    },
    ("chronos", "chronos.report"): {
        "anomaly_score": 0.3,
        "habituation_score": 0.4,
        "rumination_detected": False,
        "time_since_last_interaction_s": 12.5,
    },
    ("topos", "topos.report"): {
        "change_score": 0.2,
        "habituation_score": 0.7,
        "encoder_model_id": "facebook/dinov2-small",
    },
    ("nous", "nous.belief"): {
        "statement": "salience_high",
        "frequency": 0.9,
        "confidence": 0.5,
        "kind": "belief",
    },
    ("nous", "nous.policy"): {
        "policy": "request_think",
        "expected_free_energy": -1.531,
        "horizon": 1,
    },
    ("mnemos", "mnemos.recall"): {
        "count": 3,
        "collection": "episodic",
        "max_affect_intensity": 0.6,
    },
    ("thymos", "thymos.emotion"): {"emotion": "joy"},
    ("thymos", "thymos.drive"): {"drive": "curiosity", "value": 0.75},
    ("thymos", "thymos.state"): {
        "state": {"valence": 0.1, "arousal": 0.5},
        "drives": {"curiosity": 0.3},
        "emotion": "neutral",
    },
    ("thymos", "thymos.goal"): {
        "action": "added",
        "description": "explore the perimeter",
    },
    ("eidolon", "eidolon.drift"): {
        "score": 0.8,
        "top_drifted_sources": ["soma", "chronos"],
    },
    ("cycle", "cycle.tick"): {
        "tick_index": 42,
        "wall_duration_ms": 12.0,
        "slip_ms": 0,
    },
    ("audition", "audition.transcription"): {
        "text": "hello there",
        "source_label": "microphone",
    },
    ("audition", "audition.emotion"): {
        "category": "calm",
        "confidence": 0.7,
    },
    ("empatheia", "empatheia.agent_model"): {
        "agent_id": "operator",
        "agent_label": "operator",
        "familiarity": 0.45,
        "reliability": 0.88,
        "interaction_count": 12,
    },
    ("empatheia", "empatheia.social_error"): {
        "agent_id": "operator",
        "agent_label": "operator",
        "salience": 0.72,
        "deviation_magnitude": 0.84,
    },
    ("phantasia", "phantasia.world_error"): {
        "world_error": 0.42,
        "salience": 0.35,
        "tick_index": 17,
    },
    ("phantasia", "phantasia.scenario"): {
        "seed_memory_id": "m-1",
        "horizon": 8,
        "step_magnitudes": [0.1, 0.2, 0.3],
        "trajectory_drift": 0.05,
        "encoder_version": "phantasia-encoder-v1",
    },
    # --- v4 additions ---
    ("nous", "nous.timeout"): {
        "elapsed_ms": 120.0,
        "num_factors": 3,
        "num_actions": 4,
    },
    ("audition", "audition.prosody"): {
        "source_label": "microphone",
        "mean_pitch_hz": 145.0,
        "mean_energy": 0.42,
        "speaking_rate_syllables_per_s": 4.1,
    },
    ("vox", "vox.synthesized"): {
        "text_length": 42,
        "bytes_produced": 24000,
        "output_format": "wav",
        "voice": "example_voice",
        "exaggeration": 0.5,
        "cfg_weight": 0.6,
        "temperature": 0.8,
        "speed_factor": 1.0,
        "latency_ms": 220.0,
        "success": True,
    },
    ("mnemos", "mnemos.replay"): {
        "memory_id": "short_term:3",
        "affect_intensity": 0.6,
        "affect": {"valence": 0.3, "arousal": 0.5},
        "source_timestamp": 1700000000.0,
        "replayed_at": 1700001000.0,
    },
    ("hypnos", "hypnos.sleep.started"): {
        "started_at": 1700000000.0,
    },
    ("hypnos", "hypnos.sleep.completed"): {
        "total_elapsed_ms": 4200.0,
        "phases": [
            {"name": "light_consolidation", "success": True, "elapsed_ms": 800.0},
            {"name": "deep_consolidation", "success": True, "elapsed_ms": 3200.0},
        ],
        "fatigue_triggered": False,
    },
    ("hypnos", "hypnos.association"): {
        "seed_memory_id": "m-42",
        "horizon": 5,
        "trajectory_drift": 0.03,
    },
    ("eidolon", "eidolon.self_model"): {
        "values": ["autonomy", "honesty"],
        "behavioral_norms": ["non-deception"],
        "personality_baseline": {"openness": 0.8, "conscientiousness": 0.7},
        "capability_map": {"language": 0.9, "reasoning": 0.8},
    },
}


def test_every_shipped_template_has_sample_payload():
    missing = set(TEMPLATES.keys()) - set(_SAMPLE_PAYLOADS.keys())
    assert not missing, f"missing sample payloads for {missing}"


@pytest.mark.parametrize("key", list(TEMPLATES.keys()))
def test_template_returns_non_empty_string(key):
    fn = TEMPLATES[key]
    out = fn(_SAMPLE_PAYLOADS[key])
    assert isinstance(out, str)
    assert out.strip()


@pytest.mark.parametrize("key", list(TEMPLATES.keys()))
def test_template_avoids_banned_phrases(key):
    fn = TEMPLATES[key]
    out = fn(_SAMPLE_PAYLOADS[key]).lower()
    for banned in _BANNED_PHRASES:
        assert banned not in out, f"template {key} contains banned phrase {banned!r}"


def test_fallback_for_known_source_pair():
    out = fallback_template("xmod", "x.report", {"a": 1, "b": "y"})
    assert "xmod" in out
    assert "x.report" in out
    assert "a=1" in out
    assert "b=y" in out


def test_fallback_with_empty_payload():
    out = fallback_template("xmod", "x.report", {})
    assert "no payload" in out


def test_soma_report_alerts_branch():
    out = TEMPLATES[("soma", "soma.report")]({"wellness": 0.2, "alerts": ["cpu_percent"]})
    assert "cpu_percent" in out
    assert "alerts" in out


def test_thymos_state_renders_state_and_drives():
    out = TEMPLATES[("thymos", "thymos.state")]({
        "state": {"valence": 0.0, "arousal": 0.5, "dominance": 0.0},
        "drives": {"curiosity": 0.4, "boredom": 0.2},
        "emotion": "neutral",
    })
    assert "valence" in out
    assert "curiosity" in out
    assert "emotion" in out.lower()


def test_cycle_tick_omits_slip_when_zero():
    out = TEMPLATES[("cycle", "cycle.tick")]({"tick_index": 1, "wall_duration_ms": 10, "slip_ms": 0})
    assert "slip" not in out.lower()


def test_soma_fatigue_crossed_branch():
    out = TEMPLATES[("soma", "soma.fatigue")]({"value": 105.0, "threshold": 100.0, "crossed": True})
    assert "crossed" in out.lower() or "maintenance" in out.lower()
    assert "105" in out or "105.0" in out


def test_soma_fatigue_not_crossed():
    out = TEMPLATES[("soma", "soma.fatigue")]({"value": 50.0, "threshold": 100.0, "crossed": False})
    assert "50" in out


def test_soma_regulation_renders_action():
    out = TEMPLATES[("soma", "soma.regulation")](
        {"action": "shed_module", "reason": "too hot", "severity": 2}
    )
    assert "shed_module" in out
    assert "2" in out
