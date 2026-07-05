# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Phantasia events render via named FaithfulRenderer templates (not fallback)."""
from __future__ import annotations

from datetime import datetime, timezone

from kaine.bus.schema import Event
from kaine.faithful.renderer import FaithfulRenderer
from kaine.faithful.templates import fallback_template


_BANNED_PHRASES = (
    "i think",
    "as an ai",
    "maybe",
    "perhaps",
    "in summary",
    "it seems",
)


def _event(type_: str, payload) -> Event:
    return Event(
        source="phantasia",
        type=type_,
        payload=payload,
        salience=0.4,
        timestamp=datetime.now(timezone.utc),
    )


def test_world_error_renders_via_named_template():
    renderer = FaithfulRenderer()
    payload = {"world_error": 0.42, "salience": 0.35, "tick_index": 17}
    ev = _event("phantasia.world_error", payload)
    out = renderer.render_event(ev)
    # Not the generic key=value fallback.
    assert out != fallback_template("phantasia", "phantasia.world_error", payload)
    assert "phantasia" in out.lower()
    assert "error" in out.lower()
    assert "0.42" in out
    assert "0.35" in out


def test_scenario_renders_via_named_template():
    renderer = FaithfulRenderer()
    payload = {
        "seed_memory_id": "m-1",
        "horizon": 8,
        "step_magnitudes": [0.1, 0.2],
        "trajectory_drift": 0.05,
        "encoder_version": "phantasia-encoder-v1",
    }
    ev = _event("phantasia.scenario", payload)
    out = renderer.render_event(ev)
    assert out != fallback_template("phantasia", "phantasia.scenario", payload)
    assert "phantasia" in out.lower()
    assert "scenario" in out.lower()
    assert "8" in out  # horizon summary


def test_phantasia_templates_avoid_banned_phrases():
    renderer = FaithfulRenderer()
    we = renderer.render_event(
        _event("phantasia.world_error", {"world_error": 0.1, "salience": 0.2, "tick_index": 1})
    ).lower()
    sc = renderer.render_event(
        _event("phantasia.scenario", {"seed_memory_id": "x", "horizon": 4, "trajectory_drift": 0.0})
    ).lower()
    for banned in _BANNED_PHRASES:
        assert banned not in we
        assert banned not in sc
