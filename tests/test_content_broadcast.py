# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.workspace.content import ContentLevel
from kaine.workspace.feedback import (
    FEEDBACK_KEY,
    LATENT_KEYS,
    REPORT_TYPES,
    FeedbackController,
    WorkspaceFeedbackSettings,
)


def _settings(**kw):
    defaults = {
        "arm": "head_only",
        "pi_min": 0.5,
        "pi_max": 1.5,
        "disagreement_threshold": 0.8,
        "conflict_error_ratio": 1.5,
        "gain_step": 0.05,
        "gain_relax_s": 120.0,
        "refractory_s": 2.0,
        "head_learning_rate": 1e-3,
    }
    defaults.update(kw)
    return WorkspaceFeedbackSettings(**defaults)


def _make_event(source, latent=None, ratio=0.5, gain=1.0, salience=0.6):
    payload = {
        FEEDBACK_KEY: {
            "error_ratio": ratio,
            "disagreement": 0.0,
            "gain": gain,
        },
    }
    if latent is not None:
        key = LATENT_KEYS.get(source, "latent")
        payload[key] = latent
    return Event(
        source=source,
        type=REPORT_TYPES[source],
        payload=payload,
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _snapshot(events, threshold=0.35):
    scored = {}
    entries = []
    for i, (src, ev) in enumerate(events):
        eid = f"{src}:{i}"
        entries.append((eid, ev))
        scored[eid] = ev.salience
    return WorkspaceSnapshot(
        tick_index=0,
        selected_events=entries,
        inhibited=False,
        salience_scores=scored,
        metadata={"access_threshold": threshold},
    )


def test_broadcast_carries_content_when_enabled():
    rng = np.random.default_rng(42)
    vis_latent = rng.standard_normal(8).tolist()
    content = ContentLevel({"vision": 8}, code_dim=4)
    ctrl = FeedbackController(_settings(), content=content, clock=lambda: 1.0)

    ev = _make_event("vision", latent=vis_latent)
    snap = _snapshot([("vision", ev)])
    meta = ctrl.on_broadcast(snap, now=1.0)

    assert meta is not None
    assert "content" in meta
    assert "z_k" in meta["content"]
    assert "predictions" in meta["content"]
    assert "losses" in meta["content"]
    assert meta["content"]["z_k"] is not None
    assert len(meta["content"]["z_k"]) == 4


def test_no_content_key_when_disabled():
    ctrl = FeedbackController(_settings(), content=None, clock=lambda: 1.0)

    ev = _make_event("vision", latent=[0.1] * 8)
    snap = _snapshot([("vision", ev)])
    meta = ctrl.on_broadcast(snap, now=1.0)

    assert meta is not None
    assert "content" not in meta


def test_content_prediction_present_for_accessed_processor():
    rng = np.random.default_rng(99)
    vis_latent = rng.standard_normal(8).tolist()
    content = ContentLevel({"vision": 8, "audition": 4}, code_dim=4)
    ctrl = FeedbackController(_settings(), content=content, clock=lambda: 1.0)

    ev = _make_event("vision", latent=vis_latent)
    snap = _snapshot([("vision", ev)])
    meta = ctrl.on_broadcast(snap, now=1.0)

    assert "vision" in meta["content"]["predictions"]
    pred = meta["content"]["predictions"]["vision"]
    assert len(pred) == 8


def test_content_trains_on_broadcast():
    rng = np.random.default_rng(77)
    vis_latent = rng.standard_normal(8).tolist()
    content = ContentLevel({"vision": 8}, code_dim=4)
    ctrl = FeedbackController(_settings(), content=content, clock=lambda: 1.0)

    ev = _make_event("vision", latent=vis_latent)
    snap = _snapshot([("vision", ev)])
    meta = ctrl.on_broadcast(snap, now=1.0)

    assert "vision" in meta["content"]["losses"]
    first_loss = meta["content"]["losses"]["vision"]
    assert isinstance(first_loss, float)
    assert first_loss > 0.0


def test_multiprocessor_content():
    rng = np.random.default_rng(55)
    vis_latent = rng.standard_normal(8).tolist()
    aud_latent = rng.standard_normal(4).tolist()
    content = ContentLevel({"vision": 8, "audition": 4}, code_dim=4)
    ctrl = FeedbackController(_settings(), content=content, clock=lambda: 1.0)

    vis_ev = _make_event("vision", latent=vis_latent)
    aud_ev = _make_event("audition", latent=aud_latent)
    snap = _snapshot([("vision", vis_ev), ("audition", aud_ev)])
    meta = ctrl.on_broadcast(snap, now=1.0)

    assert "vision" in meta["content"]["predictions"]
    assert "audition" in meta["content"]["predictions"]
    assert len(meta["content"]["predictions"]["vision"]) == 8
    assert len(meta["content"]["predictions"]["audition"]) == 4


def test_coalition_unchanged_by_content():
    """Content level must not change which processors are accessed."""
    rng = np.random.default_rng(33)
    vis_latent = rng.standard_normal(8).tolist()
    content = ContentLevel({"vision": 8}, code_dim=4)

    ctrl_with = FeedbackController(_settings(), content=content, clock=lambda: 1.0)
    ctrl_without = FeedbackController(_settings(), content=None, clock=lambda: 1.0)

    ev = _make_event("vision", latent=vis_latent, ratio=0.5)
    snap = _snapshot([("vision", ev)])

    meta_with = ctrl_with.on_broadcast(snap, now=1.0)
    meta_without = ctrl_without.on_broadcast(snap, now=1.0)

    assert meta_with is not None and meta_without is not None
    assert meta_with["arm"] == meta_without["arm"]
    assert meta_with["gains"] == meta_without["gains"]
    assert meta_with["episodes"] == meta_without["episodes"]
