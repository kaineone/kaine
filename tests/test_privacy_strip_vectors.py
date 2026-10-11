# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

from kaine.bus import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.mnemos import module as mnemos_module
from kaine.privacy_filter import strip_vectors


def test_strip_vectors_removes_vector_fields_and_long_numeric_lists():
    payload = {
        "text": "keep me",
        "latent": [0.1] * 768,
        "feature_vector": list(range(24)),
        "unknown_long_vector": [0.0] * 16,
        "short_vector": [0.0] * 15,
        "saliences": [0.0] * 20,
        "nested": {"foveal": [0.2] * 32, "body": "nested text"},
    }
    stripped = strip_vectors(payload)
    assert stripped["text"] == "keep me"
    assert "latent" not in stripped
    assert "feature_vector" not in stripped
    assert "unknown_long_vector" not in stripped
    assert stripped["short_vector"] == [0.0] * 15
    assert stripped["saliences"] == [0.0] * 20
    assert "foveal" not in stripped["nested"]
    assert stripped["nested"]["body"] == "nested text"


def test_serialize_snapshot_strips_topos_vectors_and_omits_tick_and_entry_ids():
    values = [0.123456 + i * 1e-6 for i in range(768)]
    event = (
        "entry-42",
        Event(
            source="topos",
            type="topos.report",
            payload={
                "latent": list(values),
                "peripheral": list(values),
                "foveal": list(values),
            },
            salience=0.8,
            timestamp=datetime.now(timezone.utc),
        ),
    )
    snapshot = WorkspaceSnapshot(
        tick_index=7,
        selected_events=[event],
        inhibited=False,
    )
    text = mnemos_module._serialize_snapshot(snapshot)
    assert "tick=" not in text
    assert "@" not in text
    assert "topos:topos.report=" in text
    for value in values:
        assert str(value) not in text
    assert "<raw-perceptual omitted>" not in text


def test_strip_vectors_removes_short_named_vector_fields():
    # A named vector field is removed whatever its length; the 16-item backstop
    # alone would keep these.
    payload = {"latent": [0.1, 0.2, 0.3], "foveal": [0.4], "label": "scene"}
    assert strip_vectors(payload) == {"label": "scene"}
