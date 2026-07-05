# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Phantasia observation encoder: fixed-width, no raw sense data, versioned."""
from __future__ import annotations

from datetime import datetime, timezone

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.phantasia.encoder import (
    OBS_DIM,
    VERSION,
    encode_snapshot,
    observation_dim,
)


def _event(source: str, type_: str, payload=None, salience: float = 0.5) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload or {},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _snapshot(events, *, inhibited: bool = False, tick: int = 1) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=tick,
        selected_events=[(f"{i}-0", ev) for i, ev in enumerate(events)],
        inhibited=inhibited,
    )


def test_version_stamp_present():
    assert isinstance(VERSION, str)
    assert VERSION.strip() != ""


def test_observation_dim_is_fixed():
    assert observation_dim() == OBS_DIM
    assert OBS_DIM > 0


def test_encode_produces_fixed_width_vector():
    snap = _snapshot([_event("soma", "soma.report", {"wellness": 0.9}, 0.4)])
    vec = encode_snapshot(snap)
    assert isinstance(vec, list)
    assert len(vec) == OBS_DIM
    assert all(isinstance(v, float) for v in vec)


def test_empty_snapshot_still_fixed_width():
    snap = _snapshot([])
    vec = encode_snapshot(snap)
    assert len(vec) == OBS_DIM
    assert all(v == 0.0 for v in vec)


def test_inhibition_flag_encoded():
    active = encode_snapshot(_snapshot([], inhibited=False))
    inhib = encode_snapshot(_snapshot([], inhibited=True))
    # Last slot is the inhibition flag.
    assert active[-1] == 0.0
    assert inhib[-1] == 1.0


def test_salience_weighted_coalition_buckets():
    quiet = encode_snapshot(_snapshot([_event("soma", "soma.report", salience=0.1)]))
    loud = encode_snapshot(_snapshot([_event("soma", "soma.report", salience=0.9)]))
    # Higher-salience soma event yields a larger soma bucket value.
    assert max(loud) > max(quiet)


def test_affect_summary_from_thymos_state():
    snap = _snapshot([
        _event(
            "thymos",
            "thymos.state",
            {"state": {"arousal": 0.8, "valence": -0.4, "dominance": 0.2}},
            0.5,
        )
    ])
    vec = encode_snapshot(snap)
    # Affect slots are the three before the inhibition flag.
    intensity, valence, dominance = vec[-4], vec[-3], vec[-2]
    assert intensity == 0.8
    assert valence == -0.4
    assert dominance == 0.2


def test_no_raw_sense_data_in_vector():
    """A snapshot carrying transcript text / audio bytes must NOT leak any of
    that into the observation vector — only derived floats appear."""
    snap = _snapshot([
        _event(
            "audition",
            "audition.transcription",
            {
                "text": "secret spoken words",
                "audio_bytes_length": 4096,
                "pcm": b"\x00\x01",
            },
            0.6,
        ),
        _event(
            "topos",
            "topos.report",
            {"change_score": 0.3, "frame_data": "rawpixels"},
            0.5,
        ),
    ])
    vec = encode_snapshot(snap)
    assert len(vec) == OBS_DIM
    # Every element is a plain float — no bytes, no str.
    for v in vec:
        assert isinstance(v, float)
        assert not isinstance(v, (bytes, str))


def test_encoder_is_deterministic():
    snap = _snapshot([_event("nous", "nous.belief", {"statement": "x"}, 0.7)])
    assert encode_snapshot(snap) == encode_snapshot(snap)
