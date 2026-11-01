# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Bounds the second review required (stimulus-control-act, F1-F3, R2, R6, R7).

F1: pausing is bounded. A pause holds one frame and silence, which builds the
boredom that leads more acts, and with no learner in stage M that loop held the
programme paused for 40-47 % of three-hour runs (a scripted sequence: 99.8 %).
A new pause now waits ``Delta_sc`` after the previous pause ended, and a pause
is taken only while a full one keeps the entity's paused share of the trailing
awake hour within 25 %.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import pytest

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.effectors.effectors import StimulusRequest
from kaine.modules.effectors.stimulus.config import StimulusControlConfig, StimulusControlError
from kaine.modules.effectors.stimulus.controller import ENTITY_HOLDER
from kaine.modules.effectors.stimulus.runtime import StimulusControlRuntime
from kaine.workspace.stimulus_policy import StimulusActSource
from tests.stimulus_media import write_manifest

pytest.importorskip("av")

CAP = 0.25
# The poll step's slack on a measured share (one 0.5 s step in an hour).
SLACK = 0.5 / 3600.0 + 1e-9


class _Mono:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _media(tmp_path, n=4):
    colours = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    return write_manifest(
        tmp_path / "films",
        [(f"{k}.mkv", colours[k % 4], 300.0 + 100 * k, 0.3) for k in range(n)],
    )


def _rig(tmp_path, seed=1, **section):
    mono = _Mono()
    runtime = StimulusControlRuntime(
        StimulusControlConfig.from_section({"enabled": True, **section}), now=mono, seed=seed
    )
    clock = runtime.install_programme(
        str(_media(tmp_path)), probe=lambda item: 4 * 3600.0, start=False, monotonic=mono
    )
    clock.start()
    return mono, runtime, clock


def _act(runtime, action):
    return asyncio.run(runtime.effector().act(StimulusRequest(action=action)))


def test_the_scripted_hold_cycle_cannot_pass_the_bound(tmp_path, caplog):
    """The reviewer's sequence: pause, louder, quieter, louder, then pause again
    just after the release, every 30.05 s, for two hours."""
    mono, runtime, clock = _rig(tmp_path)
    controller = runtime.controller
    sequence = ["pause", "louder", "quieter", "louder"]
    accepted = refused = 0
    next_at, k = 0.0, 0
    with caplog.at_level(logging.WARNING, logger="kaine.modules.effectors.stimulus.controller"):
        while mono.t < 2 * 3600.0:
            if mono.t >= next_at:
                result = _act(runtime, sequence[k % len(sequence)])
                accepted += result.success
                refused += not result.success
                k += 1
                next_at += 30.05
            controller.poll_once()
            assert controller.paused_share_last_awake_hour() <= CAP + SLACK
            mono.t += 0.5
    record = runtime.tally.record()
    assert record["entity_paused_share"] <= CAP + SLACK
    assert record["paused_share_last_awake_hour_max"] <= CAP + SLACK
    assert record["pause_share_refusals"] > 0
    assert refused > 0 and accepted > 0
    warnings = [r.getMessage() for r in caplog.records]
    assert warnings and all("/" not in m for m in warnings)


@pytest.mark.parametrize("seed", range(5))
def test_stage_m_under_sustained_boredom_stays_within_the_bound(tmp_path, seed):
    """Shipped stage M, a boredom lead every 30.1 s (the concern re-entry), 3 h."""
    mono, runtime, clock = _rig(tmp_path, seed=seed)
    effector = runtime.effector()
    source = StimulusActSource(
        lambda snapshot: [],
        allowed_actions=runtime.allowed_actions,
        min_interval_s=runtime.config.min_interval_s,
        clock=mono,
        seed=seed,
        ready=effector.ready,
    )
    lead = Event(
        source="affect", type="affect.drive", payload={"drive": "boredom", "value": 0.8},
        salience=0.9, timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    snapshot = WorkspaceSnapshot(
        tick_index=1, selected_events=[("affect.out:1-0", lead)],
        salience_scores={"affect.out:1-0": 0.9},
    )
    next_lead = 0.0
    while mono.t < 3 * 3600.0:
        if mono.t >= next_lead:
            for intent in source(snapshot):
                asyncio.run(effector.act(StimulusRequest(action=intent.params["action"])))
            next_lead += 30.1
        runtime.controller.poll_once()
        mono.t += 0.5
    record = runtime.tally.record()
    assert record["entity_paused_share"] <= CAP + SLACK, record["entity_paused_share"]
    assert record["paused_share_last_awake_hour_max"] <= CAP + SLACK
    # Formed only when the effector is ready: no act is refused for its interval.
    assert sum(record["refused"].values()) == 0, record["refused"]


def test_a_pause_waits_after_the_previous_pause_ends_whatever_came_between(tmp_path):
    mono, runtime, clock = _rig(tmp_path)
    assert _act(runtime, "pause").success
    mono.t = 90.0
    runtime.controller.poll_once()
    assert _act(runtime, "louder").success  # during the pause
    mono.t = 120.0
    runtime.controller.poll_once()  # released at P_max
    assert ENTITY_HOLDER not in clock.holders
    mono.t = 120.1
    result = _act(runtime, "pause")  # 30.1 s after louder, 0.1 s after the pause ended
    assert not result.success and "after the previous pause ended" in result.error
    mono.t = 150.0
    assert _act(runtime, "pause").success


def test_a_pause_is_taken_only_if_a_full_one_fits_under_the_bound(tmp_path):
    mono, runtime, clock = _rig(tmp_path, pause_max_s=120.0, min_interval_s=1.0)
    t = 0.0
    while True:
        mono.t = t
        runtime.controller.poll_once()
        result = _act(runtime, "pause")
        if not result.success:
            break
        for step in range(1, 241):
            mono.t = t + 0.5 * step
            runtime.controller.poll_once()
        t = mono.t + 1.0
    assert "of the last awake hour" in result.error
    share = runtime.controller.paused_share_last_awake_hour()
    assert share + 120.0 / 3600.0 > CAP  # a full pause would pass the bound
    assert share <= CAP + SLACK


def test_the_bound_cannot_be_widened():
    with pytest.raises(ValueError):
        StimulusControlConfig.from_section({"enabled": True, "pause_share_max": 0.5})
    assert StimulusControlConfig.from_section({"enabled": True}).pause_share_max == CAP


def test_stage_m_forms_no_act_the_effector_would_refuse_for_its_interval(tmp_path):
    """The reviewer's F2 probe: formed at 0.0 and realized at 0.08, then formed
    at 30.02 and realized at 30.03."""
    mono, runtime, clock = _rig(tmp_path, seed=3)
    effector = runtime.effector()
    source = StimulusActSource(
        lambda snapshot: [], allowed_actions=runtime.allowed_actions,
        min_interval_s=30.0, clock=mono, seed=3, ready=effector.ready,
    )
    lead = Event(
        source="affect", type="affect.drive", payload={"drive": "boredom", "value": 0.8, "alert": True},
        salience=0.9, timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    def snap():
        return WorkspaceSnapshot(
            tick_index=1, selected_events=[("affect.out:1-0", lead)],
            salience_scores={"affect.out:1-0": 0.9},
        )

    outcomes = []
    for form_t, realize_t in ((0.0, 0.08), (30.02, 30.03), (30.09, 30.1)):
        mono.t = form_t
        intents = source(snap())
        if not intents:
            outcomes.append((form_t, None))
            continue
        mono.t = realize_t
        outcomes.append((form_t, _act(runtime, intents[0].params["action"]).success))
    # The act at the boundary is not formed (no refused act); the next one is, and lands.
    assert outcomes == [(0.0, True), (30.02, None), (30.09, True)]


def test_the_programme_is_verified_before_the_probe_opens_anything(tmp_path, monkeypatch):
    import av

    manifest = _media(tmp_path)
    text = manifest.read_text(encoding="utf-8")
    first = text.index('sha256 = "') + len('sha256 = "')
    manifest.write_text(text[:first] + "f" * 64 + text[first + 64:], encoding="utf-8")
    opened = []
    monkeypatch.setattr(av, "open", lambda *a, **k: opened.append(a) or (_ for _ in ()).throw(AssertionError("opened")))
    probed = []
    runtime = StimulusControlRuntime(
        StimulusControlConfig.from_section({"enabled": True}), now=_Mono(), seed=1
    )
    with pytest.raises(StimulusControlError) as raised:
        runtime.install_programme(str(manifest), probe=lambda item: probed.append(item) or 1.0, start=False)
    assert opened == [] and probed == []
    assert "verification" in str(raised.value) and str(tmp_path) not in str(raised.value)
    assert runtime.controller is None


def test_awake_time_counts_from_the_programme_start(tmp_path):
    mono = _Mono()
    runtime = StimulusControlRuntime(
        StimulusControlConfig.from_section({"enabled": True}), now=mono, seed=1
    )
    clock = runtime.install_programme(
        str(_media(tmp_path)), probe=lambda item: 3600.0, start=False, monotonic=mono
    )
    controller = runtime.controller
    mono.t = 50.0
    controller.poll_once()  # not started: module start-up is not viewing time
    clock.pause("transition")
    clock.start()
    mono.t = 80.0
    controller.poll_once()  # the crossfade holds the programme
    clock.resume("transition")
    mono.t = 100.0
    controller.poll_once()
    assert controller.awake_seconds() == pytest.approx(20.0)


@pytest.mark.parametrize("holder", ["sleep", "freeze"])
def test_commands_are_refused_while_asleep_or_frozen(tmp_path, holder):
    mono, runtime, clock = _rig(tmp_path)
    clock.pause(holder)
    result = _act(runtime, "louder")
    assert not result.success and "asleep or frozen" in result.error
    assert runtime.controller.gain_db == 0.0
    clock.resume(holder)
    assert _act(runtime, "louder").success


def test_the_interval_refusal_states_the_shortfall(tmp_path):
    mono, runtime, clock = _rig(tmp_path)
    assert _act(runtime, "louder").success
    mono.t = 29.95
    result = _act(runtime, "quieter")
    assert not result.success
    assert "29.95 s after the previous command" in result.error
    assert "0.050 s short" in result.error
