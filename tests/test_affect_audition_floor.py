# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Audition's own learning-progress floor (audition-learning-progress-floor)."""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.modules.affect import Affect

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


def _report(source: str, err: float) -> Event:
    return Event(
        source=source,
        type="vision.report" if source == "vision" else "audition.perception",
        payload={"alert": False, "prediction_error": err},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


async def _fed(bus, *, audition_floor=None, audition_fall=0.15, vision_fall=0.15) -> Affect:  # noqa: ANN001
    """An affect module whose audition and vision errors fall by the given relative amounts over the span."""
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        learning_progress_floor=0.20,
        audition_learning_progress_floor=audition_floor,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )
    for _ in range(240):
        t[0] += 1.0
        late = t[0] > 120.0
        await affect._handle_peer_event("audition.out", _report("audition", (1.0 - audition_fall) if late else 1.0))
        await affect._handle_peer_event("vision.out", _report("vision", (1.0 - vision_fall) if late else 1.0))
    t[0] += 1.0
    return affect


async def test_without_the_key_every_source_uses_the_shared_floor(bus):
    affect = await _fed(bus, audition_fall=0.30, vision_fall=0.25)
    per_source, pooled = affect._learning_progress_terms(affect._clock())
    expected = max(0.0, pooled - 0.20) / 0.80
    assert affect._progress()[0] == pytest.approx(expected)
    assert affect.learning_progress_floor_for("audition") == 0.20
    assert affect.learning_progress_floor_for("vision") == 0.20


async def test_audition_progress_is_floored_by_its_own_floor(bus):
    affect = await _fed(bus, audition_floor=0.10, audition_fall=0.15, vision_fall=0.15)
    per_source, _ = affect._learning_progress_terms(affect._clock())
    assert per_source["audition"] == pytest.approx(0.15)
    assert per_source["vision"] == pytest.approx(0.15)
    # Vision at 0.15 is under its 0.20 floor; audition at 0.15 is 0.05 over its 0.10 floor.
    assert affect._progress()[0] == pytest.approx(0.05 / 0.90)
    shared = await _fed(bus, audition_floor=None, audition_fall=0.15, vision_fall=0.15)
    assert shared._progress()[0] == 0.0


@pytest.mark.parametrize("bad", [-0.1, 1.0, math.nan, math.inf, True, "0.1"])
async def test_the_audition_floor_is_validated(bus, bad):
    with pytest.raises(ValueError, match="audition_learning_progress_floor"):
        Affect(bus, audition_learning_progress_floor=bad)


async def test_the_factory_and_the_stage_owner_read_it(bus, tmp_path):
    from kaine.boot.factories.affect import make_affect
    from kaine.boot.perception_feed import _install_shared_stimulus_source_clock

    affect = make_affect(bus, {"learning_progress_floor": 0.2, "audition_learning_progress_floor": 0.12})
    assert affect.learning_progress_floor_for("audition") == 0.12
    feed: dict[str, object] = {"stimulus_source": {}}
    _install_shared_stimulus_source_clock(
        feed, {"affect": {"audition_learning_progress_floor": 0.12}}, None, stage_path=tmp_path / "stage.json"
    )
    assert feed["_hearing_stage_state"]._lp_floor == 0.12
    feed = {"stimulus_source": {}}
    _install_shared_stimulus_source_clock(feed, {"affect": {"learning_progress_floor": 0.2}}, None, stage_path=tmp_path / "s2.json")
    assert feed["_hearing_stage_state"]._lp_floor == 0.2


async def test_the_stimulus_version_follows_the_audition_floor():
    import json
    import tomllib
    from pathlib import Path

    from kaine.boot.stimulus_version import developmental_stimulus_version

    cfg = tomllib.loads((Path(__file__).resolve().parents[1] / "config" / "kaine.toml").read_text())
    base = developmental_stimulus_version(cfg)
    changed = json.loads(json.dumps(cfg))
    changed["affect"]["audition_learning_progress_floor"] = 0.05
    assert developmental_stimulus_version(changed) != base
