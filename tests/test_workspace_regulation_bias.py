# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import math
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.boot.errors import ConfigurationError
from kaine.boot.wiring import _wire_affect_development, make_regulation_bias
from kaine.bus.schema import Event
from kaine.workspace.core import Workspace
from kaine.workspace.regulation_bias import RegulationBias


class IntensityStrategy:
    """Deterministic salience strategy: score equals event intensity."""

    async def score(self, event, context):
        return float(event.salience)


def _clock():
    t = [0.0]
    return t, lambda: t[0]


def _event(source, type, payload, salience=0.0):
    return Event(
        source=source,
        type=type,
        payload=payload,
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _candidate(source, salience):
    return _event(source, f"{source}.signal", {}, salience)


def test_regulation_bias_no_event():
    _t, clock = _clock()
    bias = RegulationBias(clock)
    assert bias.factor_for_source("vision") == 1.0
    assert bias.factor_for_source("audition") == 1.0
    assert bias.describe() is None


def test_regulation_bias_tier1_vision():
    t, clock = _clock()
    bias = RegulationBias(clock)
    reg = _event(
        "affect",
        "affect.regulation",
        {
            "tier": 1,
            "action": "attentional_deployment",
            "source": "vision",
            "bias": 0.2,
            "decay_s": 20,
        },
    )
    bias.observe([("r:1", reg)])
    assert bias.describe() == {"source": "vision", "factor": pytest.approx(0.8)}
    assert bias.factor_for_source("vision") == pytest.approx(0.8)
    assert bias.factor_for_source("audition") == 1.0
    t[0] = 20
    assert bias.factor_for_source("vision") == pytest.approx(1.0 - 0.2 * math.exp(-1))
    for time in (0, 5, 50, 500):
        t[0] = time
        f = bias.factor_for_source("vision")
        assert 0.8 <= f <= 1.0


def test_regulation_bias_later_event_replaces():
    _t, clock = _clock()
    bias = RegulationBias(clock)
    vision = _event(
        "affect",
        "affect.regulation",
        {"tier": 1, "source": "vision", "bias": 0.2, "decay_s": 20},
    )
    audition = _event(
        "affect",
        "affect.regulation",
        {"tier": 1, "source": "audition", "bias": 0.2, "decay_s": 20},
    )
    bias.observe([("r:1", vision), ("r:2", audition)])
    assert bias.describe() == {"source": "audition", "factor": pytest.approx(0.8)}
    assert bias.factor_for_source("audition") == pytest.approx(0.8)
    assert bias.factor_for_source("vision") == 1.0


def test_regulation_bias_ignores_invalid():
    _t, clock = _clock()
    bias = RegulationBias(clock)
    valid = _event(
        "affect",
        "affect.regulation",
        {"tier": 1, "source": "vision", "bias": 0.2, "decay_s": 20},
    )
    bias.observe([("r:1", valid)])

    invalid = [
        # wrong tier
        _event("affect", "affect.regulation", {"tier": 2, "source": "audition", "bias": 0.2, "decay_s": 20}),
        _event("affect", "affect.regulation", {"tier": 3, "source": "audition", "bias": 0.2, "decay_s": 20}),
        # missing or empty target
        _event("affect", "affect.regulation", {"tier": 1, "source": None, "bias": 0.2, "decay_s": 20}),
        _event("affect", "affect.regulation", {"tier": 1, "source": "", "bias": 0.2, "decay_s": 20}),
        # out-of-range bias
        _event("affect", "affect.regulation", {"tier": 1, "source": "audition", "bias": 1.5, "decay_s": 20}),
        # bool / non-finite values
        _event("affect", "affect.regulation", {"tier": 1, "source": "audition", "bias": True, "decay_s": 20}),
        _event("affect", "affect.regulation", {"tier": 1, "source": "audition", "bias": 0.2, "decay_s": 0}),
        _event("affect", "affect.regulation", {"tier": 1, "source": "audition", "bias": 0.2, "decay_s": True}),
        # wrong event source
        _event("vision", "affect.regulation", {"tier": 1, "source": "audition", "bias": 0.2, "decay_s": 20}),
    ]
    bias.observe([("r:x", e) for e in invalid])
    assert bias.describe() == {"source": "vision", "factor": pytest.approx(0.8)}
    assert bias.factor_for_source("vision") == pytest.approx(0.8)
    assert bias.factor_for_source("audition") == 1.0


@pytest.mark.asyncio
async def test_workspace_untriggered_bias_same_as_disabled():
    strategy = IntensityStrategy()
    _t, clock = _clock()
    holder = RegulationBias(clock)
    ws_off = Workspace(strategy, regulation_bias=None)
    ws_neutral = Workspace(strategy, regulation_bias=holder)
    candidates = [
        ("v:1", _candidate("vision", 0.6)),
        ("a:1", _candidate("audition", 0.5)),
    ]
    snap_off = await ws_off.select(candidates, {})
    snap_neutral = await ws_neutral.select(candidates, {})
    assert snap_off.selected_events == snap_neutral.selected_events
    assert snap_off.salience_scores == snap_neutral.salience_scores
    assert snap_off.inhibited == snap_neutral.inhibited
    assert snap_off.metadata == snap_neutral.metadata


@pytest.mark.asyncio
async def test_workspace_active_bias():
    strategy = IntensityStrategy()
    t, clock = _clock()
    holder = RegulationBias(clock)
    reg = _event(
        "affect",
        "affect.regulation",
        {"tier": 1, "source": "vision", "bias": 0.2, "decay_s": 20},
    )
    holder.observe([("r:1", reg)])
    ws = Workspace(strategy, regulation_bias=holder)
    candidates = [
        ("v:1", _candidate("vision", 0.6)),
        ("a:1", _candidate("audition", 0.5)),
    ]

    snap = await ws.select(candidates, {})
    assert snap.salience_scores["v:1"] == pytest.approx(0.48)
    assert snap.salience_scores["a:1"] == pytest.approx(0.5)
    assert [eid for eid, _ in snap.selected_events] == ["a:1", "v:1"]
    assert snap.metadata["regulation_bias"] == {"source": "vision", "factor": pytest.approx(0.8)}

    t[0] = 200
    snap_later = await ws.select(candidates, {})
    assert [eid for eid, _ in snap_later.selected_events][0] == "v:1"


@pytest.mark.asyncio
async def test_workspace_bias_gated_off():
    _t, clock = _clock()
    bias = make_regulation_bias({"workspace": {"regulation_bias": False}}, clock)
    assert bias is None
    strategy = IntensityStrategy()
    ws_off = Workspace(strategy, regulation_bias=None)
    ws_gated = Workspace(strategy, regulation_bias=bias)
    candidates = [
        ("v:1", _candidate("vision", 0.6)),
        ("a:1", _candidate("audition", 0.5)),
        (
            "r:1",
            _event(
                "affect",
                "affect.regulation",
                {"tier": 1, "source": "vision", "bias": 0.2, "decay_s": 20},
                salience=0.1,
            ),
        ),
    ]
    snap_off = await ws_off.select(candidates, {})
    snap_gated = await ws_gated.select(candidates, {})
    assert snap_off.selected_events == snap_gated.selected_events
    assert snap_off.salience_scores == snap_gated.salience_scores
    assert snap_off.inhibited == snap_gated.inhibited
    assert snap_off.metadata == snap_gated.metadata


def test_make_regulation_bias_defaults_and_validation():
    _t, clock = _clock()
    assert isinstance(make_regulation_bias({}, clock), RegulationBias)
    with pytest.raises(ConfigurationError, match="regulation_bias must be true or false"):
        make_regulation_bias({"workspace": {"regulation_bias": "off"}}, clock)


def test_study_arms_keep_regulation_bias_false():
    _t, clock = _clock()
    repo_root = Path(__file__).resolve().parents[1]
    files = sorted((repo_root / "config" / "studies").glob("workspace_mediation_*.toml"))
    assert files, "no workspace_mediation study configs found"
    for path in files:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        assert data["workspace"]["regulation_bias"] is False
        assert make_regulation_bias(data, clock) is None


def test_wire_affect_development():
    class FakeRegistry:
        def __init__(self):
            self.modules = {}

        def __contains__(self, name):
            return name in self.modules

        def get(self, name):
            return self.modules[name]

    class FakeAffect:
        def __init__(self):
            self.probe = None

        def set_development_probe(self, probe):
            self.probe = probe

    registry = FakeRegistry()
    registry.modules["affect"] = FakeAffect()
    def probe() -> bool:
        return True

    _wire_affect_development(registry, probe)
    assert registry.affect_development_probe is probe
    assert registry.modules["affect"].probe is probe

    new_affect = FakeAffect()
    registry.modules["affect"] = new_affect
    _wire_affect_development(registry)
    assert new_affect.probe is probe

    no_affect_registry = FakeRegistry()
    _wire_affect_development(no_affect_registry, probe=lambda: False)
    assert not no_affect_registry.modules
