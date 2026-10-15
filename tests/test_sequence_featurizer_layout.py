# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import logging
from datetime import datetime, timezone

import pytest

from kaine.boot.factories.sequence import make_sequence
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.sequence.featurizer import (
    LATEST_LAYOUT,
    SnapshotFeaturizer,
)
from kaine.modules.sequence.module import Sequence


class FakeNetwork:
    """Returns a constant hidden state of the requested size."""

    def __init__(self, units: int = 8, value: float = 0.5) -> None:
        self.units = units
        self.value = value
        self.calls: list[list[float]] = []

    def tick(self, feature_vec: list[float]) -> list[float]:
        self.calls.append(list(feature_vec))
        return [self.value] * self.units


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _event(source: str, salience: float, etype: str = "t.x") -> Event:
    return Event(
        source=source,
        type=etype,
        payload={"k": "v"},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _snapshot(events=None, *, inhibited=False, is_experiential=True, tick=0):
    return WorkspaceSnapshot(
        tick_index=tick,
        selected_events=[("e", e) for e in (events or [])],
        inhibited=inhibited,
        is_experiential=is_experiential,
    )


def test_layout1_audition_overflow_slot23_zero():
    feat = SnapshotFeaturizer(clock=lambda: 0.0, layout=1)
    snap = _snapshot([_event("audition", 0.8)])
    vec = feat.featurize(snap)
    assert len(vec) == 24
    assert vec[11] == pytest.approx(0.8)
    assert vec[23] == pytest.approx(0.0)


def test_layout2_audition_slot23_not_overflow():
    feat = SnapshotFeaturizer(clock=lambda: 0.0, layout=2)
    snap = _snapshot([_event("audition", 0.8)])
    vec = feat.featurize(snap)
    assert len(vec) == 24
    assert vec[23] == pytest.approx(0.8)
    assert vec[11] == pytest.approx(0.0)


def test_effectors_overflow_unchanged_across_layouts():
    for layout in (1, 2):
        feat = SnapshotFeaturizer(clock=lambda: 0.0, layout=layout)
        snap = _snapshot([_event("effectors", 0.6)])
        vec = feat.featurize(snap)
        assert vec[11] == pytest.approx(0.6), f"layout {layout}"
        assert vec[23] == pytest.approx(0.0), f"layout {layout}"


def test_invalid_layout_raises():
    with pytest.raises(ValueError, match="unsupported featurizer layout 99"):
        SnapshotFeaturizer(layout=99)
    with pytest.raises(ValueError, match="unsupported featurizer layout 0"):
        SnapshotFeaturizer(layout=0)


def test_default_layout_is_latest():
    feat = SnapshotFeaturizer(clock=lambda: 0.0)
    assert feat.layout == LATEST_LAYOUT == 2


def test_set_layout_validates():
    feat = SnapshotFeaturizer(clock=lambda: 0.0)
    feat.set_layout(1)
    assert feat.layout == 1
    with pytest.raises(ValueError, match="unsupported featurizer layout 99"):
        feat.set_layout(99)


@pytest.mark.asyncio
async def test_sequence_serializes_featurizer_layout(bus: AsyncBus):
    sequence = Sequence(bus, network=FakeNetwork())
    state = sequence.serialize()
    assert state["featurizer_layout"] == 2


@pytest.mark.asyncio
async def test_sequence_deserialize_missing_key_uses_layout1_before_initialize(
    bus: AsyncBus, caplog
):
    caplog.set_level(logging.INFO)
    sequence = Sequence(bus, network=FakeNetwork())
    sequence.deserialize({"last_interaction_at": None, "user_input_cursors": {}})
    assert sequence._featurizer.layout == 1
    assert "keeps featurizer layout 1" in caplog.text
    await sequence.initialize()
    try:
        vec = sequence._featurizer.featurize(_snapshot([_event("audition", 0.7)]))
        assert vec[11] == pytest.approx(0.7)
        assert vec[23] == pytest.approx(0.0)
    finally:
        await sequence.shutdown()


@pytest.mark.asyncio
async def test_sequence_deserialize_missing_key_uses_layout1_after_initialize(
    bus: AsyncBus, caplog
):
    caplog.set_level(logging.INFO)
    sequence = Sequence(bus, network=FakeNetwork())
    await sequence.initialize()
    try:
        sequence.deserialize({"last_interaction_at": None, "user_input_cursors": {}})
        assert sequence._featurizer.layout == 1
        vec = sequence._featurizer.featurize(_snapshot([_event("audition", 0.6)]))
        assert vec[11] == pytest.approx(0.6)
        assert vec[23] == pytest.approx(0.0)
    finally:
        await sequence.shutdown()


@pytest.mark.asyncio
async def test_sequence_deserialize_unknown_layout_raises(bus: AsyncBus):
    sequence = Sequence(bus, network=FakeNetwork())
    with pytest.raises(ValueError, match="unsupported featurizer layout 99"):
        sequence.deserialize({"featurizer_layout": 99})


@pytest.mark.asyncio
async def test_factory_passes_interaction_event_types(bus: AsyncBus):
    sequence = make_sequence(
        bus,
        {"interaction_event_types": ["audition.emotion"]},
    )
    assert sequence.interaction_event_types == ("audition.emotion",)


def test_factory_rejects_bare_string_interaction_event_types(bus: AsyncBus):
    from kaine.boot.errors import ConfigurationError
    from kaine.boot.factories.sequence import make_sequence

    with pytest.raises(ConfigurationError):
        make_sequence(bus, {"interaction_event_types": "audition.emotion"})


def test_thesis_profile_runs_forward_head_and_shipped_config_does_not():
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    profile = tomllib.loads((root / "config/profiles/thesis_test.toml").read_text())
    shipped = tomllib.loads((root / "config/kaine.toml").read_text())
    assert profile["sequence"]["forward_prediction"] is True
    assert shipped["sequence"]["forward_prediction"] is False
