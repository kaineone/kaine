# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Spot durable incident log — one JSONL record per lifecycle transition.

Covers the spec-delta scenarios in
``openspec/changes/spot-incident-log/specs/spot-supervisor/spec.md``:

* Log survives reboot + ``clear_escalation()`` does not touch it.
* Disabled Spot writes nothing.
* Enabled Spot + disabled incident log writes nothing, but bus events persist.
* Dead module -> exception captured; operator paths scrubbed to ``<PATH>``.
* Hung module -> ``exception_repr`` is null.
* Health metrics present in the detect record.
* Snapshot: all-ok vs partial-serialize-error vs whole-snapshot-failure.
* Restart: light recover vs heavy fail records.
* Encryption on/off reflected in the snapshot record + on-disk bytes.
* Retention purge disabled (no file deleted regardless of age).

The bus/registry/ForkManager are real lightweight objects (as the existing spot
tests use); state encryption is toggled via the process-global StateEncryptor.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle import control_state, escalation_state
from kaine.cycle.escalation_state import clear_escalation
from kaine.cycle.incident_log import IncidentLog, scrub_paths
from kaine.cycle.spot import IncidentLogConfig, Spot, SpotConfig
from kaine.lifecycle.manager import ForkManager
from kaine.modules.base import BaseModule
from kaine.modules.registry import ModuleRegistry
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor


# --------------------------------------------------------------------------- #
# Fixtures + helpers
# --------------------------------------------------------------------------- #


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


@pytest.fixture(autouse=True)
def _state_to_tmp(tmp_path, monkeypatch):
    # Redirect control/escalation files so the supervisor never touches the repo.
    monkeypatch.setattr(control_state, "CONTROL_PATH", tmp_path / "control.json")
    monkeypatch.setattr(
        escalation_state, "ESCALATION_PATH", tmp_path / "escalation.json"
    )
    yield


@pytest.fixture(autouse=True)
def _plaintext_encryptor():
    # Default to a disabled (plaintext) encryptor; tests that need encryption
    # install their own and this restores the default afterwards.
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


def _read_records(incidents_dir: Path) -> list[dict]:
    """Read every JSONL line under ``incidents_dir``, decrypting per the active
    process-global StateEncryptor (plaintext passes straight through)."""
    from kaine.security.crypto import get_state_encryptor

    enc = get_state_encryptor()
    records: list[dict] = []
    for f in sorted(incidents_dir.glob("incidents-*.jsonl")):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            records.append(json.loads(enc.decrypt_text(line)))
    return records


def _by_transition(records: list[dict], transition: str) -> list[dict]:
    return [r for r in records if r.get("transition") == transition]


def _spot(registry, fork_manager, rebuild, bus, incidents_dir, *, max_attempts=5):
    cfg = SpotConfig(
        enabled=True,
        max_restart_attempts=max_attempts,
        restart_backoff_s=0.0,
        incident_log=IncidentLogConfig(enabled=True, path=str(incidents_dir)),
    )
    spot = Spot(
        registry=registry,
        fork_manager=fork_manager,
        kaine_config={},
        config=cfg,
        rebuild_module=rebuild,
        bus=bus,
    )
    return spot


async def _finished_task(coro):
    t = asyncio.create_task(coro)
    await asyncio.gather(t, return_exceptions=True)
    return t


class _LightDeadMod(BaseModule):
    """Pure module (light restart path). Crashes once via a task that raised
    with an operator filesystem path in the message; recovers cleanly on the
    next restart so the incident closes with a 'recovered' restart record."""

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

        t = await _finished_task(_boom())
        self._tasks = [t]

    async def initialize(self) -> None:
        if self._healthy:
            await super().initialize()  # spawn a normal long-running workspace task
        else:
            await self._spawn_crash()

    async def restart(self) -> None:
        # First restart makes the module healthy thereafter.
        self._healthy = True
        await self.shutdown()
        self._stopped = asyncio.Event()
        await self.initialize()


class _HungMod(BaseModule):
    name = "soma"

    async def initialize(self) -> None:
        await super().initialize()  # long-running workspace task keeps running
        self._last_heartbeat -= 10_000.0  # force stale -> hung


class _HeavyDeadMod(BaseModule):
    """Holds external resources (heavy path) and never recovers — rebuild raises,
    so the incident escalates after max attempts."""

    name = "heavy"

    def holds_external_resources(self) -> bool:
        return True

    async def _spawn_dead_task(self) -> None:
        async def _boom():
            raise RuntimeError("organ crashed")

        t = await _finished_task(_boom())
        self._tasks.append(t)

    async def shutdown(self) -> None:
        await super().shutdown()
        await self._spawn_dead_task()

    async def initialize(self) -> None:
        await self._spawn_dead_task()


# --------------------------------------------------------------------------- #
# Path scrub unit tests
# --------------------------------------------------------------------------- #


def test_scrub_paths_replaces_posix_home():
    out = scrub_paths(
        "FileNotFoundError: '/home/operator/projects/kaine/x.json'"
    )
    assert "/home/operator" not in out
    assert "<PATH>" in out


def test_scrub_paths_replaces_root_users_and_windows():
    assert scrub_paths("at /root/secret") == "at <PATH>"
    assert scrub_paths("at /Users/op/file") == "at <PATH>"
    assert scrub_paths(r"open C:\Users\op\f.txt failed") == "open <PATH> failed"


def test_scrub_paths_passes_through_none_and_clean_text():
    assert scrub_paths(None) is None
    assert scrub_paths("ValueError: bad input") == "ValueError: bad input"


def test_scrub_paths_replaces_non_home_posix_roots():
    """S2 — operator paths under /tmp, /var, /opt (etc.) are scrubbed too."""
    assert (
        scrub_paths("FileNotFoundError: /tmp/kaine-preflight-abc/x.sock")
        == "FileNotFoundError: <PATH>"
    )
    assert (
        scrub_paths("PermissionError: /var/lib/kaine/state.db")
        == "PermissionError: <PATH>"
    )
    assert scrub_paths("at /opt/kaine/bin/run") == "at <PATH>"
    # Other roots from the review are covered by the same aggressive pattern.
    for root in ("/proc/123/maps", "/srv/data/x", "/mnt/vol/y", "/run/a", "/etc/passwd"):
        assert scrub_paths(f"err {root}") == "err <PATH>", root


# --------------------------------------------------------------------------- #
# Disabled-paths scenarios
# --------------------------------------------------------------------------- #


async def test_disabled_spot_writes_no_incident_files(bus, tmp_path):
    # Scenario: Disabled Spot produces no log.
    incidents = tmp_path / "incidents"
    mod = _LightDeadMod(bus)
    await mod.initialize()
    registry = ModuleRegistry()
    registry.register(mod)
    fm = ForkManager(tmp_path / "forks")
    cfg = SpotConfig(
        enabled=False,
        incident_log=IncidentLogConfig(enabled=True, path=str(incidents)),
    )
    spot = Spot(
        registry=registry,
        fork_manager=fm,
        kaine_config={},
        config=cfg,
        rebuild_module=lambda n: None,
        bus=bus,
    )
    stop = asyncio.Event()
    await spot._poll_once(stop)  # _config.enabled is False -> immediate return
    assert not incidents.exists() or list(incidents.glob("*.jsonl")) == []


async def test_enabled_spot_disabled_log_writes_nothing_but_keeps_bus(bus, tmp_path):
    # Scenario: Enabled Spot with disabled incident log.
    incidents = tmp_path / "incidents"
    mod = _LightDeadMod(bus)
    await mod.initialize()
    registry = ModuleRegistry()
    registry.register(mod)
    fm = ForkManager(tmp_path / "forks")
    cfg = SpotConfig(
        enabled=True,
        restart_backoff_s=0.0,
        incident_log=IncidentLogConfig(enabled=False, path=str(incidents)),
    )
    published: list[tuple[str, dict]] = []

    class _CapturingBus:
        async def publish(self, event):
            published.append((event.type, event.payload))

    spot = Spot(
        registry=registry,
        fork_manager=fm,
        kaine_config={},
        config=cfg,
        rebuild_module=lambda n: None,
        bus=_CapturingBus(),
    )
    assert spot._incident_log.enabled is False
    stop = asyncio.Event()
    await spot._poll_once(stop)
    # No incident files.
    assert not incidents.exists() or list(incidents.glob("*.jsonl")) == []
    # Ephemeral bus events still published.
    types = [t for t, _ in published]
    assert "spot.status" in types
    assert "spot.log" in types
    await registry.get("lingua").shutdown()


# --------------------------------------------------------------------------- #
# Detect record scenarios
# --------------------------------------------------------------------------- #


async def test_dead_module_exception_captured_and_path_scrubbed(bus, tmp_path):
    # Scenarios: Dead module — exception captured; path scrubbed; health present.
    incidents = tmp_path / "incidents"
    secret_path = "/home/operator/projects/kaine/state/x.json"
    mod = _LightDeadMod(bus, path_in_exc=secret_path)
    await mod.initialize()
    registry = ModuleRegistry()
    registry.register(mod)
    fm = ForkManager(tmp_path / "forks")
    spot = _spot(registry, fm, lambda n: None, bus, incidents)
    await spot._incident_log.start()
    stop = asyncio.Event()
    await spot._poll_once(stop)
    await spot._incident_log.stop()

    detects = _by_transition(_read_records(incidents), "detect")
    assert len(detects) == 1
    d = detects[0]
    assert d["fault_class"] == "dead"
    assert d["exception_repr"] is not None
    assert "FileNotFoundError" in d["exception_repr"]
    # Path scrubbed, raw path never written.
    assert "<PATH>" in d["exception_repr"]
    assert "/home/operator" not in d["exception_repr"]
    assert secret_path not in json.dumps(_read_records(incidents))
    # Shared fields present.
    assert d["module"] == "lingua"
    assert d["incident_id"]
    assert d["ts"].endswith("+00:00")
    # Health metrics present.
    assert "heartbeat_age_s" in d and isinstance(d["heartbeat_age_s"], (int, float))
    assert "tasks_failed" in d and d["tasks_failed"] >= 1
    assert "tasks_total" in d and d["tasks_total"] >= 1
    assert isinstance(d["poll_index"], int) and d["poll_index"] >= 1
    await registry.get("lingua").shutdown()


async def test_hung_module_null_exception_repr(bus, tmp_path):
    # Scenario: Hung module — no exception repr.
    incidents = tmp_path / "incidents"
    mod = _HungMod(bus)
    await mod.initialize()
    registry = ModuleRegistry()
    registry.register(mod)
    fm = ForkManager(tmp_path / "forks")
    spot = _spot(registry, fm, lambda n: None, bus, incidents)
    await spot._incident_log.start()
    stop = asyncio.Event()
    await spot._poll_once(stop)
    await spot._incident_log.stop()

    detects = _by_transition(_read_records(incidents), "detect")
    assert len(detects) == 1
    assert detects[0]["fault_class"] == "hung"
    assert detects[0]["exception_repr"] is None
    await registry.get("soma").shutdown()


# --------------------------------------------------------------------------- #
# Freeze + restart (light recover) + full lifecycle
# --------------------------------------------------------------------------- #


async def test_light_recover_full_lifecycle_shared_incident_id(bus, tmp_path):
    # Scenarios: Successful light restart; freeze record; shared incident_id.
    incidents = tmp_path / "incidents"
    mod = _LightDeadMod(bus)
    await mod.initialize()
    registry = ModuleRegistry()
    registry.register(mod)
    fm = ForkManager(tmp_path / "forks")
    spot = _spot(registry, fm, lambda n: None, bus, incidents)
    await spot._incident_log.start()
    stop = asyncio.Event()
    await spot._poll_once(stop)  # detect -> freeze -> snapshot -> restart (recovered)
    await spot._incident_log.stop()

    records = _read_records(incidents)
    transitions = [r["transition"] for r in records]
    assert "detect" in transitions
    assert "freeze" in transitions
    assert "snapshot" in transitions
    assert "restart" in transitions
    # All records share one incident_id.
    ids = {r["incident_id"] for r in records}
    assert len(ids) == 1

    freeze = _by_transition(records, "freeze")[0]
    assert freeze["source"] == "spot"
    assert freeze["fault_type"] == "dead"
    assert "lingua" in freeze["reason"]

    restart = _by_transition(records, "restart")[0]
    assert restart["path"] == "light"
    assert restart["outcome"] == "recovered"
    assert restart["post_assess"] == "alive"
    assert restart["attempt"] == 1
    assert restart["max_attempts"] == 5
    assert restart["last_good_restored"] is False
    assert isinstance(restart["latency_ms"], (int, float))
    await registry.get("lingua").shutdown()


async def test_new_incident_gets_new_id_after_recovery(bus, tmp_path):
    # A resolved incident clears; a later fault on the same module gets a new id.
    incidents = tmp_path / "incidents"
    mod = _LightDeadMod(bus)
    await mod.initialize()
    registry = ModuleRegistry()
    registry.register(mod)
    fm = ForkManager(tmp_path / "forks")
    spot = _spot(registry, fm, lambda n: None, bus, incidents)
    await spot._incident_log.start()
    stop = asyncio.Event()
    await spot._poll_once(stop)  # incident #1 -> recovered
    first_id = spot._incidents.get("lingua")
    assert first_id is None  # popped on recovery

    # Re-break the module and poll again.
    mod._healthy = False
    await mod.shutdown()
    mod._stopped = asyncio.Event()
    await mod._spawn_crash()
    await spot._poll_once(stop)
    await spot._incident_log.stop()

    detects = _by_transition(_read_records(incidents), "detect")
    assert len(detects) == 2
    assert detects[0]["incident_id"] != detects[1]["incident_id"]
    await registry.get("lingua").shutdown()


# --------------------------------------------------------------------------- #
# Escalation (heavy fail) scenario
# --------------------------------------------------------------------------- #


async def test_escalation_records_heavy_fail_and_halted(bus, tmp_path):
    # Scenarios: Failed heavy restart; escalate record with outcome=halted and
    # final_snapshot_id matching a snapshot record's snapshot_id.
    incidents = tmp_path / "incidents"
    mod = _HeavyDeadMod(bus)
    await mod.initialize()
    registry = ModuleRegistry()
    registry.register(mod)
    fm = ForkManager(tmp_path / "forks")

    def _rebuild(name):
        raise RuntimeError("rebuild keeps failing")

    halted = {"v": False}
    spot = _spot(registry, fm, _rebuild, bus, incidents, max_attempts=3)
    spot._on_halt = lambda: halted.__setitem__("v", True)
    stop = asyncio.Event()
    await spot.run(stop)  # run() drives start/stop of the sink and the loop

    assert spot.escalated is True
    assert halted["v"] is True

    records = _read_records(incidents)
    restarts = _by_transition(records, "restart")
    assert len(restarts) == 3
    for r in restarts:
        assert r["path"] == "heavy"
        assert r["outcome"] == "failed"
        assert r["post_assess"] in ("dead", "hung")

    escs = _by_transition(records, "escalate")
    assert len(escs) == 1
    esc = escs[0]
    assert esc["outcome"] == "halted"
    assert esc["attempts"] == 3
    # final_snapshot_id should match one of the snapshot records' ids.
    snap_ids = {
        s["snapshot_id"]
        for s in _by_transition(records, "snapshot")
        if s["snapshot_id"]
    }
    assert esc["final_snapshot_id"] in snap_ids
    # Shared incident id across the whole incident.
    assert len({r["incident_id"] for r in records}) == 1


# --------------------------------------------------------------------------- #
# Snapshot outcome recording scenarios
# --------------------------------------------------------------------------- #


class _OkMod(BaseModule):
    name = "ok"

    def serialize(self):
        return {"v": 1}


class _BadSerializeMod(BaseModule):
    name = "bad"

    def holds_external_resources(self) -> bool:
        return True

    def serialize(self):
        raise RuntimeError("cannot serialize")


async def test_snapshot_all_ok(bus, tmp_path):
    # Scenario: All modules serialized.
    incidents = tmp_path / "incidents"
    registry = ModuleRegistry()
    registry.register(_OkMod(bus))
    registry.register(_HungMod(bus))
    fm = ForkManager(tmp_path / "forks")
    log = IncidentLog(enabled=True, path=str(incidents))
    await log.start()
    spot = Spot(
        registry=registry,
        fork_manager=fm,
        kaine_config={},
        config=SpotConfig(
            enabled=True,
            incident_log=IncidentLogConfig(enabled=True, path=str(incidents)),
        ),
        rebuild_module=lambda n: None,
        bus=bus,
    )
    await spot._incident_log.start()
    await spot._snapshot("spot-pre-restart:ok", "ok", "iid-1")
    await spot._incident_log.stop()
    await log.stop()

    snaps = _by_transition(_read_records(incidents), "snapshot")
    assert len(snaps) == 1
    s = snaps[0]
    assert s["modules_serialize_errored"] == []
    assert s["modules_serialized_ok"] == 2
    assert s["snapshot_id"]
    assert s["byte_size"] > 0
    assert s["label"] == "spot-pre-restart:ok"
    assert s["encrypted"] is False
    assert isinstance(s["duration_ms"], (int, float))


async def test_snapshot_partial_serialize_error(bus, tmp_path):
    # Scenario: Partial serialization failure.
    incidents = tmp_path / "incidents"
    registry = ModuleRegistry()
    registry.register(_OkMod(bus))
    registry.register(_BadSerializeMod(bus))
    fm = ForkManager(tmp_path / "forks")
    spot = Spot(
        registry=registry,
        fork_manager=fm,
        kaine_config={},
        config=SpotConfig(
            enabled=True,
            incident_log=IncidentLogConfig(enabled=True, path=str(incidents)),
        ),
        rebuild_module=lambda n: None,
        bus=bus,
    )
    await spot._incident_log.start()
    await spot._snapshot("spot-pre-restart:bad", "bad", "iid-2")
    await spot._incident_log.stop()

    s = _by_transition(_read_records(incidents), "snapshot")[0]
    assert s["modules_serialize_errored"] == ["bad"]
    assert s["modules_serialized_ok"] == 1
    assert s["snapshot_id"]  # the bundle still wrote (the bad module is stored as _serialize_error)


async def test_snapshot_whole_failure_writes_null_id(bus, tmp_path):
    # Scenario: Snapshot failure (ForkManager.snapshot raises).
    incidents = tmp_path / "incidents"
    registry = ModuleRegistry()
    registry.register(_OkMod(bus))
    fm = ForkManager(tmp_path / "forks")

    def _boom(*a, **kw):
        raise RuntimeError("disk gone")

    fm.snapshot = _boom  # type: ignore[assignment]
    spot = Spot(
        registry=registry,
        fork_manager=fm,
        kaine_config={},
        config=SpotConfig(
            enabled=True,
            incident_log=IncidentLogConfig(enabled=True, path=str(incidents)),
        ),
        rebuild_module=lambda n: None,
        bus=bus,
    )
    await spot._incident_log.start()
    result = await spot._snapshot("spot-pre-restart:ok", "ok", "iid-3")
    await spot._incident_log.stop()

    assert result is None
    s = _by_transition(_read_records(incidents), "snapshot")[0]
    assert s["snapshot_id"] is None
    assert s["modules_serialize_errored"] == []
    assert s["byte_size"] == 0


# --------------------------------------------------------------------------- #
# Encryption scenarios
# --------------------------------------------------------------------------- #


async def test_encrypted_deployment_records_encrypted_true(bus, tmp_path, monkeypatch):
    # Scenario: Encrypted deployment.
    incidents = tmp_path / "incidents"
    key = base64.b64encode(os.urandom(32)).decode("ascii")
    monkeypatch.setenv("KAINE_STATE_KEY", key)
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=True)))

    registry = ModuleRegistry()
    registry.register(_OkMod(bus))
    fm = ForkManager(tmp_path / "forks")
    spot = Spot(
        registry=registry,
        fork_manager=fm,
        kaine_config={},
        config=SpotConfig(
            enabled=True,
            incident_log=IncidentLogConfig(enabled=True, path=str(incidents)),
        ),
        rebuild_module=lambda n: None,
        bus=bus,
    )
    await spot._incident_log.start()
    await spot._snapshot("spot-pre-restart:ok", "ok", "iid-enc")
    await spot._incident_log.stop()

    # Raw on-disk lines are NOT human-readable JSON.
    f = sorted(incidents.glob("incidents-*.jsonl"))[0]
    raw = f.read_text().splitlines()[0]
    with pytest.raises(Exception):
        json.loads(raw)
    # Decrypted, the snapshot record carries encrypted=true.
    s = _by_transition(_read_records(incidents), "snapshot")[0]
    assert s["encrypted"] is True


async def test_plaintext_deployment_records_encrypted_false(bus, tmp_path):
    # Scenario: Plaintext deployment (the autouse fixture installs a disabled
    # encryptor).
    incidents = tmp_path / "incidents"
    registry = ModuleRegistry()
    registry.register(_OkMod(bus))
    fm = ForkManager(tmp_path / "forks")
    spot = Spot(
        registry=registry,
        fork_manager=fm,
        kaine_config={},
        config=SpotConfig(
            enabled=True,
            incident_log=IncidentLogConfig(enabled=True, path=str(incidents)),
        ),
        rebuild_module=lambda n: None,
        bus=bus,
    )
    await spot._incident_log.start()
    await spot._snapshot("spot-pre-restart:ok", "ok", "iid-plain")
    await spot._incident_log.stop()

    f = sorted(incidents.glob("incidents-*.jsonl"))[0]
    raw = f.read_text().splitlines()[0]
    # Plaintext line is valid JSON.
    parsed = json.loads(raw)
    assert parsed["transition"] == "snapshot"
    assert parsed["encrypted"] is False


# --------------------------------------------------------------------------- #
# Reboot persistence + retention scenarios
# --------------------------------------------------------------------------- #


async def test_log_survives_reboot_and_clear_escalation(bus, tmp_path):
    # Scenarios: Log survives reboot; clear_escalation does not touch it.
    incidents = tmp_path / "incidents"
    mod = _LightDeadMod(bus)
    await mod.initialize()
    registry = ModuleRegistry()
    registry.register(mod)
    fm = ForkManager(tmp_path / "forks")
    spot = _spot(registry, fm, lambda n: None, bus, incidents)
    await spot._incident_log.start()
    stop = asyncio.Event()
    await spot._poll_once(stop)
    await spot._incident_log.stop()
    await registry.get("lingua").shutdown()

    files_before = sorted(p.name for p in incidents.glob("incidents-*.jsonl"))
    records_before = _read_records(incidents)
    assert files_before  # at least one file written

    # Simulate a clean boot's escalation reset.
    clear_escalation()

    # Incident files untouched by the boot reset.
    files_after = sorted(p.name for p in incidents.glob("incidents-*.jsonl"))
    records_after = _read_records(incidents)
    assert files_after == files_before
    assert records_after == records_before

    # A second Spot instance (a new run) appends rather than wiping.
    mod2 = _LightDeadMod(bus)
    await mod2.initialize()
    reg2 = ModuleRegistry()
    reg2.register(mod2)
    spot2 = _spot(reg2, ForkManager(tmp_path / "forks2"), lambda n: None, bus, incidents)
    await spot2._incident_log.start()
    await spot2._poll_once(asyncio.Event())
    await spot2._incident_log.stop()
    await reg2.get("lingua").shutdown()

    records_run2 = _read_records(incidents)
    assert len(records_run2) > len(records_before)


def test_retention_purge_disabled_keeps_old_files(tmp_path):
    # Scenario: Retention purge disabled — no file deleted regardless of age.
    incidents = tmp_path / "incidents"
    log = IncidentLog(enabled=True, path=str(incidents))
    sink = log._sink
    assert sink is not None
    assert sink._retention_days == 0
    incidents.mkdir(parents=True, exist_ok=True)
    ancient_file = incidents / "incidents-2000-01-01.jsonl"
    ancient_file.write_text("{}\n")
    ancient = time.time() - 5000 * 86400
    os.utime(ancient_file, (ancient, ancient))
    # Enforcing retention is a no-op for retention_days == 0.
    sink._enforce_retention()
    assert ancient_file.exists()


def test_disabled_incident_log_builds_no_sink(tmp_path):
    log = IncidentLog(enabled=False, path=str(tmp_path / "incidents"))
    assert log.enabled is False
    assert log._sink is None
