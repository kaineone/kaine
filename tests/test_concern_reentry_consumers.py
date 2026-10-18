# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Consumers of affect.drive re-entries (paper A.4)."""


def test_research_event_observer_keeps_reentry_field():
    from kaine.evaluation.observers.research_event_observer import _allowed_fields

    fields = _allowed_fields("affect.drive")
    assert "reentry" in fields
    assert {"drive", "value", "alert"} <= fields


def test_self_inference_ignores_reentry_crossings():
    from kaine.modules.self_model.self_inference import SelfInferenceEngine

    engine = SelfInferenceEngine(enabled=True)

    engine.observe_affect_drive(
        {"drive": "curiosity", "value": 0.8, "alert": False, "reentry": True}
    )
    assert engine._drive_counts["curiosity"] == 0

    engine.observe_affect_drive({"drive": "curiosity", "value": 0.7, "alert": True})
    assert engine._drive_counts["curiosity"] == 1


def test_affect_drive_template_renders_reentry_and_crossing():
    from kaine.faithful.templates import _fmt, _t_affect_drive

    reentry = _t_affect_drive(
        {"drive": "boredom", "value": 0.85, "alert": False, "reentry": True}
    )
    assert reentry == f"Affect drive {_fmt('boredom')} remains above threshold at {_fmt(0.85)}."

    crossing = _t_affect_drive({"drive": "boredom", "value": 0.7, "alert": True})
    assert crossing == f"Affect drive {_fmt('boredom')} crossed threshold at {_fmt(0.7)}."
