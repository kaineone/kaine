# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Stage M of the stimulus-control act through the real action layer.

A broadcast led by the entity's own boredom or restlessness drive event yields
one signed act intent naming the stimulus effector, its action drawn uniformly
from what the programme can take now; the effectors module verifies and
realizes it against the real programme clock.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.effectors import Effectors
from kaine.modules.effectors.effectors import StimulusRequest
from kaine.modules.effectors.stimulus.config import StimulusControlConfig
from kaine.modules.effectors.stimulus.runtime import StimulusControlRuntime
from kaine.security.intent_signing import IntentSigner
from kaine.workspace.action_selection import (
    ACT,
    ACTION_SELECTION_SOURCE,
    INTENT_TYPES,
    ActionSelection,
)
from kaine.workspace.drive_policy import DriveBiasedActionSelectionPolicy
from kaine.workspace.stimulus_policy import StimulusActSource, stage_m_generator
from tests.stimulus_media import write_manifest

_SECRET = b"stimulus-stage-m-test-secret-00032"


class _Mono:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _event(source, type_, payload, salience=0.7):
    return Event(
        source=source, type=type_, payload=payload, salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _snapshot(lead, *, others=(), inhibited=False, tick=1):
    members = [("affect.out:1-0", lead)] + [(f"vision.out:{i}-0", e) for i, e in enumerate(others)]
    scores = {"affect.out:1-0": 0.9}
    scores.update({f"vision.out:{i}-0": 0.5 for i in range(len(others))})
    return WorkspaceSnapshot(
        tick_index=tick, selected_events=members, inhibited=inhibited, salience_scores=scores
    )


def _drive(name):
    return _event("affect", "affect.drive", {"drive": name, "value": 0.8, "alert": True})


def _source(allowed, *, mono, developing=False, seed=11, interval=30.0):
    return StimulusActSource(
        DriveBiasedActionSelectionPolicy(),
        allowed_actions=lambda: list(allowed),
        min_interval_s=interval,
        clock=mono,
        seed=seed,
        developing=lambda: developing,
    )


@pytest.mark.parametrize("drive", ["boredom", "restlessness"])
def test_a_drive_led_broadcast_yields_one_stimulus_act(drive):
    mono = _Mono()
    source = _source(["pause", "next", "louder"], mono=mono)
    intents = source(_snapshot(_drive(drive)))
    acts = [i for i in intents if i.kind == ACT]
    assert len(acts) == 1
    act = acts[0]
    assert act.effector == "stimulus"
    assert act.params["action"] in {"pause", "next", "louder"}
    assert act.entry_id == "affect.out:1-0" and act.about_kind == "felt"


@pytest.mark.parametrize(
    "lead",
    [
        _drive("social_drive"),
        _drive("curiosity"),
        _event("vision", "vision.report", {"prediction_error": 0.4}),
    ],
)
def test_other_leads_yield_no_stimulus_act(lead):
    source = _source(["next"], mono=_Mono())
    assert [i for i in source(_snapshot(lead)) if i.kind == ACT] == []


def test_a_boredom_event_that_does_not_lead_yields_nothing():
    mono = _Mono()
    source = _source(["next"], mono=mono)
    snap = WorkspaceSnapshot(
        tick_index=1,
        selected_events=[("affect.out:1-0", _drive("boredom")), ("vision.out:1-0", _event("vision", "vision.report", {}))],
        salience_scores={"affect.out:1-0": 0.4, "vision.out:1-0": 0.8},
    )
    assert [i for i in source(snap) if i.kind == ACT] == []


def test_the_developmental_phase_derives_no_stimulus_act():
    source = _source(["next"], mono=_Mono(), developing=True)
    assert [i for i in source(_snapshot(_drive("boredom"))) if i.kind == ACT] == []


def test_the_command_interval_spaces_the_acts():
    mono = _Mono()
    source = _source(["next"], mono=mono, interval=30.0)
    assert len([i for i in source(_snapshot(_drive("boredom"))) if i.kind == ACT]) == 1
    mono.t = 29.0
    assert [i for i in source(_snapshot(_drive("boredom"))) if i.kind == ACT] == []
    mono.t = 30.0
    assert len([i for i in source(_snapshot(_drive("boredom"))) if i.kind == ACT]) == 1


def test_no_allowed_action_yields_nothing():
    source = _source([], mono=_Mono())
    assert [i for i in source(_snapshot(_drive("boredom"))) if i.kind == ACT] == []


def test_the_draw_is_uniform_and_reproducible_from_the_seed():
    allowed = ["pause", "next", "previous", "quieter"]
    picks = []
    mono = _Mono()
    source = _source(allowed, mono=mono, seed=5, interval=1.0)
    for k in range(4000):
        mono.t = float(k)
        picks += [i.params["action"] for i in source(_snapshot(_drive("boredom"))) if i.kind == ACT]
    counts = Counter(picks)
    assert set(counts) == set(allowed)
    for n in counts.values():
        assert abs(n - 1000) < 120  # within ~4 sd of a uniform draw
    replay = stage_m_generator(5)
    assert picks[:50] == [allowed[replay.randrange(4)] for _ in range(50)]


def test_inner_policy_hooks_stay_reachable():
    inner = DriveBiasedActionSelectionPolicy()
    source = StimulusActSource(
        inner, allowed_actions=lambda: [], min_interval_s=1.0, clock=_Mono(), seed=0
    )
    source.note_external_intent("speak")
    assert source.speak_in_flight is True
    source.mark_realized()
    assert inner.speak_in_flight is False


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    b = AsyncBus(
        BusConfig(password="x", audit_required=False),
        client=fakeredis.FakeRedis(decode_responses=True),
    )
    yield b
    await b.close()


async def test_gain_at_its_bound_is_never_drawn_and_the_act_is_realized(tmp_path, bus):
    """The real path: ActionSelection signs, the bus carries, the effectors module
    verifies and the stimulus effector moves the real programme clock."""
    pytest.importorskip("av")
    mono = _Mono()
    runtime = StimulusControlRuntime(
        StimulusControlConfig.from_section({"enabled": True, "min_interval_s": 1.0}),
        now=mono,
        seed=9,
    )
    manifest = write_manifest(
        tmp_path / "films", [("a.mkv", (255, 0, 0), 300.0, 0.5), ("b.mkv", (0, 255, 0), 500.0, 0.5)]
    )
    clock = runtime.install_programme(
        str(manifest), probe=lambda item: 5000.0, start=False, monotonic=mono
    )
    clock.start()
    effectors = Effectors(
        bus,
        sandbox_path=tmp_path / "sandbox",
        audit_log_path=tmp_path / "audit.log",
        notification_fallback_log=tmp_path / "n.log",
        enabled_effectors=["stimulus"],
        intent_secret=_SECRET,
    )
    effectors.register_effector(runtime.effector(), StimulusRequest)
    await effectors.initialize()
    selection = ActionSelection(
        StimulusActSource(
            DriveBiasedActionSelectionPolicy(),
            allowed_actions=runtime.allowed_actions,
            min_interval_s=runtime.config.min_interval_s,
            clock=mono,
            seed=runtime.seed,
        ),
        signer=IntentSigner(_SECRET, "stage-m-run"),
    )
    # Raise the gain to its bound first so "louder" is not allowed.
    for k in range(3):
        mono.t = 1.0 + 2 * k
        runtime.controller.apply("louder")
    drawn = []
    try:
        for k in range(40):
            mono.t = 10.0 + 2.0 * k
            runtime.controller.poll_once()
            gain_before = runtime.controller.gain_db
            for intent in selection.select(_snapshot(_drive("boredom"), tick=k)):
                if intent.kind != ACT:
                    continue
                assert intent.sig and intent.run_id == "stage-m-run"
                drawn.append((gain_before, intent.params["action"]))
                await bus.publish(
                    _event(ACTION_SELECTION_SOURCE, INTENT_TYPES[intent.kind], intent.to_event_payload(), 0.5)
                )
            await asyncio.sleep(0.06)
        at_bound = [a for g, a in drawn if g == pytest.approx(6.0)]
        assert at_bound, "the gain never sat at its bound during the draws"
        assert "louder" not in at_bound
        assert len(drawn) == 40
        published = await bus.read("effectors.out", last_id="0", count=200)
        results = [e.payload for _, e in published if e.type == "effectors.action"]
        assert len(results) == 40
        assert all(r["effector"] == "stimulus" for r in results)
        # Every drawn act was one the programme could take when it was drawn.
        assert all(r["success"] for r in results), [r for r in results if not r["success"]]
        record = runtime.tally.record()
        assert sum(record["commands"].values()) == 40
    finally:
        await effectors.shutdown()
