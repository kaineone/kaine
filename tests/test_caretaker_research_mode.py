# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""A research run builds the caretaker from the same [caretaker] section as an
unattended run, so welfare notices reach a person (CAL 4.7)."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import validate_event
from kaine.cycle import __main__ as cycle_main
from kaine.cycle import caretaker, caretaker_runtime, control_state
from kaine.cycle.preservation_monitor import PreservationConfig
from kaine.lifecycle.preservation import PreservationResult
from kaine.modules.registry import ModuleRegistry
from kaine.research.ignition_study.overlay import build_overlay
from kaine.security import crypto

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
async def test_a_freeze_that_cannot_be_written_sends_its_own_notices(
    bus, tmp_path, monkeypatch
):
    real_freeze = control_state.freeze
    calls: list[str] = []

    def _freeze(reason=None, path=None, *, source="operator"):
        calls.append(source)
        if len(calls) == 1:
            raise OSError(28, "No space left on device")
        return real_freeze(reason=reason, path=path, source=source)

    monkeypatch.setattr(control_state, "freeze", _freeze)
    ctx = _ctx(bus, tmp_path, mode="research", caretaker_section=CARETAKER_SECTION)
    await cycle_main._phase_safety_net(ctx)
    monitor = ctx.welfare_monitor
    stop = asyncio.Event()

    await monitor._poll_once(stop)
    await _gray_zone(bus, "sustained_extreme_vad")
    await _gray_zone(bus, "unmaintained_fatigue")
    await monitor._poll_once(stop)
    await asyncio.gather(*ctx._caretaker_tasks)
    # Not "welfare response fired": the entity is NOT paused.
    assert ctx.caretaker.events == ["welfare_freeze_failed"]

    # The next poll retries the freeze, writes it, and says so.
    await monitor._poll_once(stop)
    await asyncio.gather(*ctx._caretaker_tasks)
    assert "welfare" in control_state.read_holder_sources()
    assert ctx.caretaker.events == ["welfare_freeze_failed", "welfare_freeze_placed"]
    assert ctx.fork_manager.calls == 1


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


_SHIPPED_CONFIG = Path(__file__).resolve().parent.parent / "config" / "kaine.toml"


def _hermetic_cwd(tmp_path: Path, monkeypatch) -> None:
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True)
    shutil.copy2(_SHIPPED_CONFIG, cfg_dir / "kaine.toml")
    monkeypatch.chdir(tmp_path)


def test_an_invalid_caretaker_section_refuses_a_research_boot_before_any_state(
    tmp_path: Path, monkeypatch, capsys
):
    _hermetic_cwd(tmp_path, monkeypatch)
    cfg_path = tmp_path / "config" / "kaine.toml"
    cfg_path.write_text(
        cfg_path.read_text() + '\n[caretaker]\ninstall_label = "study-box"\nbogus_key = 1\n'
    )
    monkeypatch.setenv("KAINE_RESEARCH_MODE", "1")
    monkeypatch.setenv("KAINE_STATE_KEY", "11" * 32)
    monkeypatch.setattr(crypto, "_load_key_from_keyring", lambda: None)
    calls: list = []

    async def _fake_boot(**kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(cycle_main, "_boot_and_run", _fake_boot)
    rc = cycle_main.main([])
    assert rc == 1
    assert calls == []
    captured = capsys.readouterr()
    assert "configuration error" in captured.err
    assert "bogus_key" in captured.err


def test_caretaker_ack_cli_writes_matching_ack_for_a_step_directory(tmp_path: Path, monkeypatch):
    step_dir = tmp_path / "development" / "0"
    state_dir = step_dir / "state" / "cycle"
    state_dir.mkdir(parents=True)
    start_id = "abcd1234" * 4
    (state_dir / "caretaker_start.json").write_text(
        json.dumps({"start_id": start_id, "started_at": "2026-10-28T12:00:00+00:00"})
    )
    rc = caretaker.main(["ack", "--data-root", str(step_dir)])
    assert rc == 0
    ack = json.loads((state_dir / "caretaker_ack.json").read_text())
    assert ack["start_id"] == start_id
    assert "acknowledged_at" in ack


def test_caretaker_ack_cli_refuses_when_no_start_record_exists(tmp_path: Path, capsys):
    step_dir = tmp_path / "development" / "0"
    rc = caretaker.main(["ack", "--data-root", str(step_dir)])
    assert rc == 1
    assert "no start record" in capsys.readouterr().err


def test_caretaker_ack_runs_as_a_module(tmp_path: Path):
    step_dir = tmp_path / "development" / "0"
    state_dir = step_dir / "state" / "cycle"
    state_dir.mkdir(parents=True)
    start_id = "0123abcd" * 4
    (state_dir / "caretaker_start.json").write_text(
        json.dumps({"start_id": start_id, "started_at": "2026-10-28T12:00:00+00:00"})
    )
    proc = subprocess.run(
        [sys.executable, "-m", "kaine.cycle.caretaker", "ack", "--data-root", str(step_dir)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    ack = json.loads((state_dir / "caretaker_ack.json").read_text())
    assert ack["start_id"] == start_id
