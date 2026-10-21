# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Template tests for the developmental feed and health board panels."""

from __future__ import annotations

import re

from kaine.dashboard.diagnostics import _templates


def _render(name: str, **ctx):
    return _templates().env.get_template(name).render(**ctx)


def test_stimulus_source_perception_feed():
    html = _render(
        "_perception_feed.html",
        perception_feed={
            "mode": "stimulus_source",
            "reproducible": True,
            "descriptor": {"seed": 42},
            "stimulus_source": {
                "heartbeat_bpm": 70.0,
                "heartbeat_drift": 0.05,
                "colour_ramp_seconds": 3600.0,
                "colour_hue_gain": 1.0,
                "maternal_voice_enabled": True,
                "hearing_enabled": True,
                "hearing_maturation_seconds": 43200.0,
            },
        },
    )
    assert "stimulus source" in html
    assert "70.0 bpm base" in html
    assert "ramp time constant 3600.0 s" in html
    assert "maternal voice" in html
    assert "on" in html
    assert "widens over 43200.0 s" in html
    assert 'id="feed-hearing-stage"' in html


def test_stimulus_source_hearing_disabled():
    html = _render(
        "_perception_feed.html",
        perception_feed={
            "mode": "stimulus_source",
            "reproducible": True,
            "descriptor": {},
            "stimulus_source": {"hearing_enabled": False},
        },
    )
    assert "hearing band" in html
    assert "off" in html
    assert 'id="feed-hearing-stage"' not in html


def test_seeded_block_no_stimulus_source_heading():
    html = _render(
        "_perception_feed.html",
        perception_feed={
            "mode": "seeded",
            "reproducible": True,
            "descriptor": {"seed": 123, "video": None, "audio": None},
        },
    )
    assert "stimulus source" not in html
    assert "seeded descriptor" in html


def test_health_board_deterministic_feed():
    html = _render(
        "_health_board.html",
        health={
            "modules": [
                {
                    "name": "vision",
                    "enabled": True,
                    "initialized": True,
                    "capturing": True,
                    "feed": "stimulus_source",
                }
            ]
        },
    )
    assert "capturing (stimulus_source)" in html
    assert "🔴" not in html


def test_health_board_live_feed_red_dot():
    html = _render(
        "_health_board.html",
        health={
            "modules": [
                {
                    "name": "audition",
                    "enabled": True,
                    "initialized": True,
                    "capturing": True,
                    "feed": "live",
                }
            ]
        },
    )
    assert "🔴 capturing" in html


def test_development_panel_ids_and_no_inline_handlers():
    html = _render("_development_panel.html")
    assert 'id="dev-hearing"' in html
    assert 'id="dev-world"' in html
    assert 'id="dev-passes-row"' in html
    assert 'id="dev-consolidation-not-required"' in html
    assert not re.search(r"\son\w+\s*=", html, re.IGNORECASE)
