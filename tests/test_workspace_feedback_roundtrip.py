# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Round-trip tests for workspace feedback through the registry and modules."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.boot.registry import _FEEDBACK_MODULES, construct_module
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.modules.registry import ModuleRegistry
from kaine.workspace import (
    NoveltyTracker,
    RuleBasedSalience,
    StaticAffectModulator,
    StaticGoalScorer,
    Workspace,
)
from kaine.workspace.feedback import (
    REPORT_TYPES,
    FeedbackController,
    WorkspaceFeedbackSettings,
)


def _bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


def _strategy():
    return RuleBasedSalience(
        novelty=NoveltyTracker(window=32),
        goal_scorer=StaticGoalScorer(),
        affect_modulator=StaticAffectModulator(),
    )


class FakeCounterEncoder:
    model_id = "fake/counter"
    latent_dim = 4
    clip_len = 1

    def __init__(self):
        self._n = 0

    async def load(self):
        return None

    async def shutdown(self):
        return None

    async def encode(self, image):  # noqa: ARG002
        self._n += 1
        n = self._n
        return [
            0.1 * (n % 3),
            0.2 + 0.05 * (n % 5),
            0.3,
            0.4 - 0.03 * (n % 4),
        ]

    async def encode_clip(self, frames):
        return await self.encode(frames[-1])


def test_feedback_modules_constant():
    assert _FEEDBACK_MODULES == frozenset(
        {"vision", "audition", "interoception", "sequence"}
    )


@pytest.mark.asyncio
async def test_registry_injects_feedback_for_sequence():
    bus = _bus()
    mod = construct_module(
        "sequence",
        bus,
        {
            "sequence": {"forward_prediction": True},
            "workspace": {"feedback": {"enabled": True, "arm": "full"}},
        },
        registry=ModuleRegistry(),
    )
    assert mod is not None
    assert mod._publish_next_prediction is True


@pytest.mark.asyncio
async def test_registry_injects_feedback_for_vision():
    pytest.importorskip("kaine.modules.vision")
    from kaine.modules.vision import Vision

    bus = _bus()
    mod = construct_module(
        "vision",
        bus,
        {
            "vision": {"forward_prediction": True},
            "workspace": {"feedback": {"enabled": True, "arm": "head_gain"}},
        },
        registry=ModuleRegistry(),
    )
    assert isinstance(mod, Vision)
    assert mod._feedback_settings.arm == "head_gain"

    mod_off = construct_module(
        "vision",
        bus,
        {"vision": {"forward_prediction": True}},
        registry=ModuleRegistry(),
    )
    assert isinstance(mod_off, Vision)
    assert mod_off._feedback_settings is None


def _vision_module(bus, settings):
    pytest.importorskip("kaine.modules.vision")
    from kaine.modules.vision import Vision
    from kaine.modules.vision.forward import LatentForwardModel

    vision = Vision(
        bus,
        encoder=FakeCounterEncoder(),
        forward_prediction=True,
        workspace_feedback=settings,
    )
    vision._forward_model = LatentForwardModel(
        latent_dim=4, units=8, context_dim=24, seed=4
    )
    return vision


def _candidate_events(vision_event, vision_id, *, vision_salience, audition_salience, sequence_salience):
    now = datetime.now(timezone.utc)
    fb = dict(vision_event.payload.get("workspace_feedback", {}))
    conflict_fb = {**fb, "error_ratio": 2.5, "disagreement": 3.0}
    conflict_payload = {**dict(vision_event.payload), "workspace_feedback": conflict_fb}
    vision_candidate = Event(
        source=vision_event.source,
        type=vision_event.type,
        payload=conflict_payload,
        salience=vision_salience,
        timestamp=vision_event.timestamp,
    )
    audition_candidate = Event(
        source="audition",
        type=REPORT_TYPES["audition"],
        payload={"workspace_feedback": {"error_ratio": 0.5, "disagreement": None, "gain": 1.0}},
        salience=audition_salience,
        timestamp=now,
    )
    sequence_candidate = Event(
        source="sequence",
        type="sequence.report",
        payload={"predicted_next_feature_vector": [0.02] * 24},
        salience=sequence_salience,
        timestamp=now,
    )
    candidates = {
        vision_id: vision_candidate,
        "audition.out:1-0": audition_candidate,
        "sequence.out:1-0": sequence_candidate,
    }
    return sorted(candidates.items(), key=lambda kv: (kv[1].source, kv[1].type, kv[0]))


@pytest.mark.asyncio
async def test_workspace_feedback_roundtrip_full():
    settings = WorkspaceFeedbackSettings.from_section(
        {"enabled": True, "arm": "full"}
    )
    bus = _bus()
    vision = _vision_module(bus, settings)

    for _ in range(3):
        await vision.process_frame(None)

    entries = await bus.read("vision.out", last_id="0")
    assert len(entries) == 3
    vision_id, vision_event = entries[-1]

    candidates = _candidate_events(
        vision_event, vision_id, vision_salience=0.9, audition_salience=0.9, sequence_salience=0.1
    )
    workspace = Workspace(
        _strategy(),
        feedback=FeedbackController(settings, clock=lambda: 0.0),
    )
    snapshot = await workspace.select(
        candidates, {"tick_index": 0, "is_experiential": True}
    )

    assert "workspace_feedback" in snapshot.metadata
    fb_meta = snapshot.metadata["workspace_feedback"]
    assert fb_meta["arm"] == "full"
    gains = fb_meta["gains"]
    assert gains["vision"] == pytest.approx(0.9, abs=1e-9)
    assert gains["audition"] == pytest.approx(1.1, abs=1e-9)
    assert fb_meta["sequence_prediction"] is not None

    await vision.on_workspace(snapshot)
    assert vision._feedback_channel.gain == pytest.approx(0.9, abs=1e-9)
    assert list(vision._feedback_channel.sequence_prediction) == pytest.approx(
        [0.02] * 24, abs=1e-9
    )

    await vision.process_frame(None)
    entries = await bus.read("vision.out", last_id="0")
    report = entries[-1][1].payload
    assert report["workspace_feedback"]["gain"] == pytest.approx(0.9, abs=1e-9)


@pytest.mark.asyncio
async def test_workspace_feedback_roundtrip_inhibited():
    settings = WorkspaceFeedbackSettings.from_section(
        {"enabled": True, "arm": "full"}
    )
    bus = _bus()
    vision = _vision_module(bus, settings)

    for _ in range(3):
        await vision.process_frame(None)

    entries = await bus.read("vision.out", last_id="0")
    vision_id, vision_event = entries[-1]

    candidates = _candidate_events(
        vision_event, vision_id, vision_salience=0.05, audition_salience=0.05, sequence_salience=0.05
    )
    workspace = Workspace(
        _strategy(),
        feedback=FeedbackController(settings, clock=lambda: 0.0),
    )
    snapshot = await workspace.select(
        candidates, {"tick_index": 0, "is_experiential": True}
    )

    assert "workspace_feedback" not in snapshot.metadata
    await vision.on_workspace(snapshot)
    assert vision._feedback_channel.gain == pytest.approx(1.0, abs=1e-6)
    assert vision._feedback_channel.sequence_prediction is None


@pytest.mark.asyncio
async def test_workspace_feedback_off_end_to_end():
    bus = _bus()
    vision = _vision_module(bus, None)
    await vision.process_frame(None)

    entries = await bus.read("vision.out", last_id="0")
    _, vision_event = entries[-1]
    assert "workspace_feedback" not in vision_event.payload

    now = datetime.now(timezone.utc)
    candidates = {
        "vision.out:1-0": vision_event,
        "audition.out:1-0": Event(
            source="audition",
            type=REPORT_TYPES["audition"],
            payload={"perception": {}},
            salience=0.9,
            timestamp=now,
        ),
        "sequence.out:1-0": Event(
            source="sequence",
            type="sequence.report",
            payload={"predicted_next_feature_vector": [0.02] * 24},
            salience=0.1,
            timestamp=now,
        ),
    }
    candidates = sorted(candidates.items(), key=lambda kv: (kv[1].source, kv[1].type, kv[0]))

    workspace = Workspace(_strategy(), feedback=None)
    snapshot = await workspace.select(
        candidates, {"tick_index": 0, "is_experiential": True}
    )
    assert "workspace_feedback" not in snapshot.metadata
