# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Spot ``spot.incident`` bus annotation — freeze-run-annotation change.

Covers the ``spot-supervisor`` ADDED requirements:

* Spot publishes a structured ``spot.incident`` event at each lifecycle
  transition (detect, freeze, snapshot, restart) IN ADDITION to the unchanged
  ephemeral ``spot.status`` / ``spot.log`` events.
* Each event carries the shared ``incident_id``, ``module``, ``transition``, the
  fault metadata, and the transition-specific operational fields.
* The cycle position is present: ``poll_index`` always; ``tick_index`` when a
  tick-index provider is wired, and absent (never fabricated) when it is not.
* Operator filesystem paths in free-text are scrubbed to ``<PATH>``.

A capturing bus double records every published (type, payload) so the test can
assert the new path was taken without touching Redis.
"""
from __future__ import annotations

import asyncio

import pytest

from kaine.cycle import control_state, escalation_state
from kaine.cycle.spot import IncidentLogConfig, Spot, SpotConfig
from kaine.lifecycle.manager import ForkManager
from kaine.modules.base import BaseModule
from kaine.modules.registry import ModuleRegistry
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor


@pytest.fixture(autouse=True)
def _state_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(control_state, "CONTROL_PATH", tmp_path / "control.json")
    monkeypatch.setattr(
        escalation_state, "ESCALATION_PATH", tmp_path / "escalation.json"
    )
    yield


@pytest.fixture(autouse=True)
def _plaintext_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


class _CapturingBus:
    """Records every published event as (type, payload)."""

    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []

    async def publish(self, event):
        self.published.append((event.type, dict(event.payload)))
        return "fake-id"

    async def current_workspace_id(self):
        # BaseModule.initialize() reads this when the recovered module spawns
        # its normal workspace consumer task.
        return "0"

    async def subscribe_workspace(self, last_id="$", count=32, poll_interval_s=0.05):
        # A long-running consumer the recovered module's task awaits; it simply
        # blocks so the module stays "alive" (a running, non-crashed task).
        while True:
            await asyncio.sleep(3600)
            yield  # pragma: no cover

    def of_type(self, type_: str) -> list[dict]:
        return [p for t, p in self.published if t == type_]


async def _finished_task(coro):
    t = asyncio.create_task(coro)
    await asyncio.gather(t, return_exceptions=True)
    return t


class _LightDeadMod(BaseModule):
    """Pure (light-restart) module that crashed; recovers on first restart."""

    name = "lingua"

    def __init__(self, bus, *, path_in_exc: str | None = None):
        super().__init__(bus)
        self._path_in_exc = path_in_exc
        self._healthy = False

    async def _spawn_crash(self) -> None:
        msg = "organ crashed"
        if self._path_in_exc:
            msg = f"No such file or directory: '{self._path_in_exc}'"

        async def _boom():
            raise FileNotFoundError(msg)

        self._tasks = [await _finished_task(_boom())]

    async def initialize(self) -> None:
        if self._healthy:
            await super().initialize()
        else:
            await self._spawn_crash()

    async def restart(self) -> None:
        self._healthy = True
        await self.shutdown()
        self._stopped = asyncio.Event()
        await self.initialize()


def _spot(registry, fm, bus, tmp_path, *, tick_provider=None):
    cfg = SpotConfig(
        enabled=True,
        restart_backoff_s=0.0,
        incident_log=IncidentLogConfig(enabled=True, path=str(tmp_path / "incidents")),
    )
    return Spot(
        registry=registry,
        fork_manager=fm,
        kaine_config={},
        config=cfg,
        rebuild_module=lambda n: None,
        bus=bus,
        tick_index_provider=tick_provider,
    )


async def _drive_one_incident(bus, tmp_path, *, tick_provider=None, path_in_exc=None):
    mod = _LightDeadMod(bus, path_in_exc=path_in_exc)
    await mod.initialize()
    registry = ModuleRegistry()
    registry.register(mod)
    fm = ForkManager(tmp_path / "forks")
    spot = _spot(registry, fm, bus, tmp_path, tick_provider=tick_provider)
    await spot._incident_log.start()
    await spot._poll_once(asyncio.Event())  # detect->freeze->snapshot->restart
    await spot._incident_log.stop()
    await registry.get("lingua").shutdown()
    return spot


# --------------------------------------------------------------------------- #


async def test_incident_event_published_per_transition(tmp_path):
    bus = _CapturingBus()
    await _drive_one_incident(bus, tmp_path)

    incidents = bus.of_type("spot.incident")
    transitions = [p["transition"] for p in incidents]
    for expected in ("detect", "freeze", "snapshot", "restart"):
        assert expected in transitions, f"missing spot.incident for {expected}"

    # Every event shares the one incident_id and names the module.
    ids = {p["incident_id"] for p in incidents}
    assert len(ids) == 1 and next(iter(ids))
    assert all(p["module"] == "lingua" for p in incidents)


async def test_status_and_log_events_still_published(tmp_path):
    bus = _CapturingBus()
    await _drive_one_incident(bus, tmp_path)
    # The existing ephemeral events must remain (not replaced).
    assert bus.of_type("spot.status"), "spot.status must still be published"
    assert bus.of_type("spot.log"), "spot.log must still be published"
    assert bus.of_type("spot.incident"), "spot.incident must be added"


async def test_transition_specific_fields_present(tmp_path):
    bus = _CapturingBus()
    await _drive_one_incident(bus, tmp_path)
    incidents = bus.of_type("spot.incident")
    by = {p["transition"]: p for p in incidents}

    assert by["detect"]["fault_class"] == "dead"
    assert by["freeze"]["fault_type"] == "dead"
    assert by["freeze"]["source"] == "spot"
    assert "snapshot_id" in by["snapshot"]
    restart = by["restart"]
    assert restart["path"] == "light"
    assert restart["outcome"] == "recovered"
    assert restart["post_assess"] == "alive"
    assert isinstance(restart["latency_ms"], (int, float))


async def test_cycle_position_includes_tick_when_provider_wired(tmp_path):
    bus = _CapturingBus()
    await _drive_one_incident(bus, tmp_path, tick_provider=lambda: 42)
    incidents = bus.of_type("spot.incident")
    assert incidents
    for p in incidents:
        assert p["poll_index"] == 1
        assert p["tick_index"] == 42


async def test_no_fabricated_tick_without_provider(tmp_path):
    bus = _CapturingBus()
    await _drive_one_incident(bus, tmp_path, tick_provider=None)
    incidents = bus.of_type("spot.incident")
    assert incidents
    for p in incidents:
        assert p["poll_index"] == 1
        assert "tick_index" not in p  # honest: no provider => no tick


async def test_provider_exception_is_swallowed(tmp_path):
    def _boom():
        raise RuntimeError("tick read failed")

    bus = _CapturingBus()
    await _drive_one_incident(bus, tmp_path, tick_provider=_boom)
    incidents = bus.of_type("spot.incident")
    assert incidents
    for p in incidents:
        assert "tick_index" not in p
        assert p["poll_index"] == 1


async def test_operator_path_scrubbed_in_incident_event(tmp_path):
    secret = "/home/operator/projects/kaine/state/x.json"
    bus = _CapturingBus()
    await _drive_one_incident(bus, tmp_path, path_in_exc=secret)
    incidents = bus.of_type("spot.incident")
    detect = next(p for p in incidents if p["transition"] == "detect")
    assert "FileNotFoundError" in detect["exception_repr"]
    assert "<PATH>" in detect["exception_repr"]
    # The raw operator path appears in NO published payload.
    import json

    blob = json.dumps(bus.published)
    assert secret not in blob
    assert "/home/operator" not in blob
