# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""A research run builds the caretaker from the same [caretaker] section as an
unattended run, so welfare notices reach a person (CAL 4.7)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import validate_event
from kaine.cycle import __main__ as cycle_main
from kaine.cycle import caretaker_runtime, control_state
from kaine.cycle.preservation_monitor import PreservationConfig
from kaine.lifecycle.preservation import PreservationResult
from kaine.modules.registry import ModuleRegistry
from kaine.research.ignition_study.overlay import build_overlay

CARETAKER_SECTION = {
    "install_label": "study-box",
    "channels": [{"kind": "desktop"}],
}


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


@pytest.fixture(autouse=True)
def _control_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(control_state, "CONTROL_PATH", tmp_path / "control.json")


class _FakeNotifier:
    """Stands in for CaretakerNotifier: records its config and every notice."""

    instances: list["_FakeNotifier"] = []

    def __init__(self, config):
        self.config = config
        self.started = False
        self.events: list[str] = []
        _FakeNotifier.instances.append(self)

    async def start(self):
        self.started = True
        return "start-id"

    async def send_event(self, event):
        self.events.append(event)
        return []


class _StubFM:
    def __init__(self):
        self.calls = 0

    async def preserve_live(self, registry, *, reason, label, out_root, entity_name,
                            require_encryption=False):
        self.calls += 1
        return PreservationResult(
            ok=True, preservation_id="pid", snapshot_id="snap", reason=reason,
            label=label, run_id="research0001", world_model_captured=False,
        )


def _ctx(bus, tmp_path, *, mode: str, caretaker_section=None):
    preservation = PreservationConfig.from_section(
        {
            "require_encryption": False,
            "incident_path": str(tmp_path / "incident"),
            "divergence_monitor": {"enabled": True, "state_root": str(tmp_path / "state")},
            "welfare_response": {
                "enabled": True,
                "action": "pause",
                "repeat_window_s": 1000.0,
                "repeat_threshold": 2,
                "warmup_s": 0.0,
                "warmup_ceiling_s": 0.0,
                "out_root": str(tmp_path / "backups"),
            },
        }
    )
    config = {"caretaker": caretaker_section} if caretaker_section is not None else {}
    return SimpleNamespace(
        supervision_mode=mode,
        kaine_config=config,
        preservation_cfg=preservation,
        registry=ModuleRegistry(),
        fork_manager=_StubFM(),
        bus=bus,
        stop_event=asyncio.Event(),
    )


@pytest.fixture(autouse=True)
def _fake_notifier(monkeypatch):
    _FakeNotifier.instances = []
    monkeypatch.setattr(caretaker_runtime, "CaretakerNotifier", _FakeNotifier)


async def _gray_zone(bus, category):
    await bus.publish(
        validate_event(
            source="welfare",
            type="welfare.gray_zone",
            payload={"gray_zone_event": category},
            salience=0.8,
            timestamp=datetime.now(timezone.utc),
        )
    )


@pytest.mark.asyncio
async def test_a_research_boot_builds_the_caretaker_from_the_same_section(bus, tmp_path):
    ctx = _ctx(bus, tmp_path, mode="research", caretaker_section=CARETAKER_SECTION)
    assert await cycle_main._phase_safety_net(ctx) is None

    assert ctx.caretaker is _FakeNotifier.instances[0]
    assert ctx.caretaker.started is True
    assert ctx.caretaker.config.install_label == "study-box"
    assert [c.kind for c in ctx.caretaker.config.channels] == ["desktop"]


@pytest.mark.asyncio
async def test_an_unattended_boot_still_builds_it_and_an_operator_boot_does_not(bus, tmp_path):
    unattended = _ctx(bus, tmp_path, mode="unattended", caretaker_section=CARETAKER_SECTION)
    await cycle_main._phase_safety_net(unattended)
    assert unattended.caretaker is not None

    operator = _ctx(bus, tmp_path, mode="operator", caretaker_section=CARETAKER_SECTION)
    await cycle_main._phase_safety_net(operator)
    assert operator.caretaker is None


@pytest.mark.asyncio
async def test_a_gray_zone_crossing_in_a_research_run_reaches_the_caretaker(bus, tmp_path):
    ctx = _ctx(bus, tmp_path, mode="research", caretaker_section=CARETAKER_SECTION)
    await cycle_main._phase_safety_net(ctx)
    monitor = ctx.welfare_monitor
    stop = asyncio.Event()

    await monitor._poll_once(stop)
    await _gray_zone(bus, "sustained_extreme_vad")
    await _gray_zone(bus, "unmaintained_fatigue")
    await monitor._poll_once(stop)
    # The notice is sent from a task the response creates.
    await asyncio.gather(*ctx._caretaker_tasks)

    assert ctx.fork_manager.calls == 1
    assert ctx.caretaker.events == ["welfare_response"]


@pytest.mark.asyncio
async def test_a_research_run_without_a_channel_still_builds_it_and_says_so(
    bus, tmp_path, caplog
):
    ctx = _ctx(bus, tmp_path, mode="research")
    with caplog.at_level("WARNING"):
        assert await cycle_main._phase_safety_net(ctx) is None
    assert ctx.caretaker is not None
    assert "no [caretaker] channel is configured" in caplog.text


def test_an_invalid_caretaker_section_is_refused_before_a_research_boot():
    assert cycle_main._caretaker_config_error({}) is None
    assert cycle_main._caretaker_config_error({"caretaker": CARETAKER_SECTION}) is None
    assert "bogus_key" in cycle_main._caretaker_config_error({"caretaker": {"bogus_key": 1}})


def test_the_study_overlay_passes_the_operator_caretaker_section_to_children(tmp_path):
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    base = repo / "config" / "kaine.toml"
    base.write_text('[vision]\nencoder_local_dir = "state/models"\n')
    operator = repo / "config" / "kaine.operator.toml"
    operator.write_text(
        '[caretaker]\ninstall_label = "study-box"\n\n[[caretaker.channels]]\nkind = "desktop"\n'
    )
    plan = {
        "base_modules": ["recorder"],
        "order": [],
        "collections": {"development": "r_g_"},
        "voice_alignment_steps": [],
    }
    overlay, _, _ = build_overlay(plan, "development", "development", 0, repo, base, operator)
    assert overlay["caretaker"] == {
        "install_label": "study-box",
        "channels": [{"kind": "desktop"}],
    }
