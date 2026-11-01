# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The stimulus effector's bounds through the real effectors module.

Signed act intents go through ``Effectors._handle_intent`` (provenance, the
operator whitelist, the audit log, the ``effectors.action`` event) to the
stimulus effector and its controller on a real programme clock.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.effectors import Effectors
from kaine.modules.effectors.effectors import StimulusRequest
from kaine.modules.effectors.stimulus.config import (
    StimulusControlConfig,
    StimulusControlError,
)
from kaine.modules.effectors.stimulus.controller import ENTITY_HOLDER
from kaine.modules.effectors.stimulus.runtime import StimulusControlRuntime
from kaine.security.intent_signing import compute_intent_signature
from tests.stimulus_media import write_manifest

_SECRET = b"stimulus-effector-test-secret-0032"
_RUN = "stimulus-run"


class _Mono:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    b = AsyncBus(
        BusConfig(password="x", audit_required=False),
        client=fakeredis.FakeRedis(decode_responses=True),
    )
    yield b
    await b.close()


def _manifest(tmp_path, n=3, name="programme.toml", sub="films"):
    pytest.importorskip("av")
    colours = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    return write_manifest(
        tmp_path / sub,
        [(f"{sub}{i}.mkv", colours[i % 4], 300.0 + 100 * i, 0.5) for i in range(n)],
        name=name,
    )


class _Rig:
    def __init__(self, tmp_path, bus, *, whitelisted=True, register=True, **section):
        self.mono = _Mono()
        config = StimulusControlConfig.from_section({"enabled": True, **section})
        self.runtime = StimulusControlRuntime(config, now=self.mono, seed=3)
        self.clock = self.runtime.install_programme(
            str(_manifest(tmp_path)), probe=lambda item: 5000.0, start=False, monotonic=self.mono
        )
        self.clock.start()
        self.audit = tmp_path / "audit.log"
        self.effectors = Effectors(
            bus,
            sandbox_path=tmp_path / "sandbox",
            audit_log_path=self.audit,
            notification_fallback_log=tmp_path / "notify.log",
            enabled_effectors=["stimulus"] if whitelisted else [],
            intent_secret=_SECRET,
        )
        if register:
            self.effectors.register_effector(self.runtime.effector(), StimulusRequest)
        self.bus = bus
        self.seq = 0

    async def act(self, action: str, at: float):
        self.mono.t = at
        self.runtime.controller.poll_once()
        params = {"action": action}
        sig = compute_intent_signature(
            _SECRET, kind="act", effector="stimulus", params=params, run_id=_RUN, seq=self.seq
        )
        payload = {
            "kind": "act",
            "about": "boredom",
            "effector": "stimulus",
            "params": params,
            "run_id": _RUN,
            "seq": self.seq,
            "sig": sig,
        }
        self.seq += 1
        await self.effectors._handle_intent(
            Event(
                source="action_selection",
                type="intent.act",
                payload=payload,
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            )
        )

    def audit_records(self):
        if not self.audit.exists():
            return []
        return [json.loads(line) for line in self.audit.read_text().splitlines() if line.strip()]

    async def actions(self):
        entries = await self.bus.read("effectors.out", last_id="0", count=200)
        return [e.payload for _, e in entries if e.type == "effectors.action"]


async def test_shipped_configuration_has_no_stimulus_effector(tmp_path, bus):
    """Off is absent: an act intent naming it is dropped as for any effector that
    does not exist, and no stimulus request is made."""
    rig = _Rig(tmp_path, bus, whitelisted=False, register=False)
    await rig.act("next", at=1.0)
    assert rig.audit_records() == []
    published = await rig.actions()
    assert published == []
    assert rig.clock.locate()[0] == 0
    assert rig.runtime.tally.record()["commands"]["next"] == 0


async def test_whitelist_required_even_when_registered(tmp_path, bus):
    rig = _Rig(tmp_path, bus, whitelisted=False, register=True)
    await rig.act("louder", at=1.0)
    assert rig.runtime.controller.gain_db == 0.0
    assert rig.audit_records()[0]["blocked"] is True


async def test_a_command_too_soon_is_refused_audited_and_changes_nothing(tmp_path, bus):
    rig = _Rig(tmp_path, bus, min_interval_s=30.0)
    await rig.act("louder", at=1.0)
    assert rig.runtime.controller.gain_db == pytest.approx(2.0)
    await rig.act("next", at=11.0)
    assert rig.clock.locate()[0] == 0
    records = rig.audit_records()
    assert [r["success"] for r in records] == [True, False]
    assert records[1]["error"].startswith("refused:")
    assert records[1]["request"] == {"action": "next"}
    published = await rig.actions()
    assert [p["success"] for p in published] == [True, False]
    record = rig.runtime.tally.record()
    assert record["commands"]["louder"] == 1 and record["refused"]["next"] == 1
    await rig.act("next", at=31.0)
    assert rig.clock.locate()[0] == 1


async def test_gain_at_its_bound_is_refused(tmp_path, bus):
    rig = _Rig(tmp_path, bus, min_interval_s=1.0)
    for k in range(3):
        await rig.act("louder", at=1.0 + 2 * k)
    assert rig.runtime.controller.gain_db == pytest.approx(6.0)
    await rig.act("louder", at=10.0)
    assert rig.runtime.controller.gain_db == pytest.approx(6.0)
    assert rig.audit_records()[-1]["success"] is False
    allowed_now = rig.runtime.effector().allowed_actions()
    assert "louder" not in allowed_now
    for k in range(6):
        await rig.act("quieter", at=20.0 + 2 * k)
    assert rig.runtime.controller.gain_db == pytest.approx(-6.0)
    await rig.act("quieter", at=40.0)
    assert rig.runtime.controller.gain_db == pytest.approx(-6.0)
    allowed_now = rig.runtime.effector().allowed_actions()
    assert "quieter" not in allowed_now


async def test_seeks_are_capped_per_awake_hour(tmp_path, bus):
    rig = _Rig(tmp_path, bus, min_interval_s=1.0, seeks_per_awake_hour=2)
    await rig.act("next", at=1.0)
    await rig.act("previous", at=3.0)
    await rig.act("next", at=5.0)
    assert [r["success"] for r in rig.audit_records()] == [True, True, False]
    allowed_now = rig.runtime.effector().allowed_actions()
    assert "next" not in allowed_now
    # Asleep time is not awake time: an hour of sleep does not refill the budget.
    rig.clock.pause("sleep")
    await rig.act("next", at=3700.0)
    rig.clock.resume("sleep")
    assert rig.audit_records()[-1]["success"] is False
    await rig.act("next", at=3700.0 + 3600.0)
    assert rig.audit_records()[-1]["success"] is True


async def test_pause_and_resume_hold_the_entity_holder(tmp_path, bus):
    rig = _Rig(tmp_path, bus, min_interval_s=1.0, pause_max_s=120.0)
    await rig.act("pause", at=1.0)
    assert ENTITY_HOLDER in rig.clock.holders
    await rig.act("pause", at=3.0)  # already paused: refused
    assert rig.audit_records()[-1]["success"] is False
    await rig.act("resume", at=5.0)
    assert ENTITY_HOLDER not in rig.clock.holders
    await rig.act("resume", at=7.0)  # not paused: refused
    assert rig.audit_records()[-1]["success"] is False


async def test_an_undeclared_action_is_refused(tmp_path, bus):
    rig = _Rig(tmp_path, bus)
    await rig.act("faster", at=1.0)
    rec = rig.audit_records()[-1]
    assert rec["success"] is False and "declared" in rec["error"]
    assert rig.runtime.tally.record()["refused"]["other"] == 1


async def test_one_channel_declares_no_channel_action(tmp_path, bus):
    rig = _Rig(tmp_path, bus)
    effector_now = rig.runtime.effector()
    assert not any(a.startswith("channel:") for a in effector_now.declared_actions)


async def test_two_channels_declare_and_switch(tmp_path, bus):
    second = _manifest(tmp_path, n=2, sub="second")
    mono = _Mono()
    config = StimulusControlConfig.from_section(
        {"enabled": True, "min_interval_s": 1.0, "channels": [str(second)]}
    )
    runtime = StimulusControlRuntime(config, now=mono, seed=3)
    clock = runtime.install_programme(
        str(_manifest(tmp_path)), probe=lambda item: 100.0, start=False, monotonic=mono
    )
    clock.start()
    effector = runtime.effector()
    assert effector.declared_actions[-2:] == ("channel:0", "channel:1")
    allowed_now = effector.allowed_actions()
    assert "channel:0" not in allowed_now
    result = await effector.act(StimulusRequest(action="channel:1"))
    assert result.success
    assert clock.channel == 1 and clock.locate()[0] == 3  # channel 1's first item
    mono.t = 5.0
    again = await effector.act(StimulusRequest(action="channel:1"))
    assert not again.success
    mono.t = 7.0
    nxt = await effector.act(StimulusRequest(action="next"))
    assert nxt.success and clock.locate()[0] == 4
    mono.t = 9.0
    act_result = await effector.act(StimulusRequest(action="next"))
    assert act_result.success
    assert clock.locate()[0] == 3  # wraps inside channel 1
    record = runtime.tally.record()
    runtime.controller.poll_once()
    assert record["commands"]["channel:1"] == 1


async def test_commands_are_refused_before_the_programme_starts(tmp_path):
    mono = _Mono()
    runtime = StimulusControlRuntime(
        StimulusControlConfig.from_section({"enabled": True}), now=mono, seed=3
    )
    runtime.install_programme(
        str(_manifest(tmp_path)), probe=lambda item: 100.0, start=False, monotonic=mono
    )
    result = await runtime.effector().act(StimulusRequest(action="next"))
    assert not result.success and "not started" in result.error
    allowed_now = runtime.allowed_actions()
    assert allowed_now == []


@pytest.mark.parametrize(
    "fault, reason",
    [
        (lambda: StimulusControlError("the programme has ended"), "the programme has ended"),
        (RuntimeError, "RuntimeError"),
    ],
)
async def test_a_command_the_controller_cannot_apply_is_refused(tmp_path, bus, fault, reason):
    """The refusal check passes, then the controller raises (a race, or a fault):
    the command is refused, counted and audited, and changes nothing."""
    rig = _Rig(tmp_path, bus, min_interval_s=30.0)
    controller = rig.runtime.controller

    def _raise(action):  # noqa: ANN001, ANN202
        raise fault()

    real_apply = controller.apply
    controller.apply = _raise
    await rig.act("louder", at=1.0)
    controller.apply = real_apply
    record = rig.audit_records()[-1]
    assert record["success"] is False and record["error"] == f"refused: {reason}"
    assert controller.gain_db == 0.0
    assert rig.runtime.tally.record()["refused"]["louder"] == 1
    # Nothing was accepted, so the interval did not start: the next command lands.
    await rig.act("louder", at=2.0)
    assert rig.audit_records()[-1]["success"] is True
    assert controller.gain_db == pytest.approx(2.0)
