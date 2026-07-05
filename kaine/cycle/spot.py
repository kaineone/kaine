# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Spot — KAINE's module supervisor (the watchdog).

Spot is a cycle-layer component, NOT a registry module: it must keep running
precisely when modules fail, so it cannot be subject to its own liveness checks
or torn down by the shutdown it orchestrates. The entrypoint constructs and runs
it alongside ``cycle.run_forever`` and the freeze-watch loop.

Per poll Spot assesses each module (alive | dead | hung), and on a fault it
freezes the cycle (humane suspend) with ``source="spot"``, snapshots last-good
state, and runs the restart ladder (light ``BaseModule.restart`` for pure
modules; heavy rebuild via the injected ``rebuild_module`` closure +
``registry.replace`` + ``rewire_module`` + snapshot restore for modules holding
external resources). One incident is handled per poll. After
``max_restart_attempts`` failures Spot escalates: a final snapshot, shutdown of
every module, ``escalation.json``, a CRITICAL ``spot.status``, and a halt signal
so the entrypoint exits non-zero. Spot never reboots the host — it only asks.

Incident annotation (research log)
----------------------------------
At each lifecycle transition Spot also publishes a structured ``spot.incident``
bus event (source ``"spot"``) IN ADDITION to the ephemeral ``spot.status`` /
``spot.log`` events. The curated research-event observer captures it (privacy-
filtered) into ``data/evaluation/research_events/``, where the run-context sink
stamping stamps it with the active ``run_id`` — so a run whose data was collected
across a Spot freeze carries the annotation, joined to the run by ``run_id`` and
to the incident by ``incident_id``. The event carries a best-effort cycle
position: Spot's ``poll_index`` always, plus the cycle's ``tick_index`` when a
``tick_index_provider`` is wired at construction (no tick is fabricated without
one). Free-text fields are path-scrubbed before publish.

Durable incident log
--------------------
Alongside the ephemeral ``spot.status`` / ``spot.log`` bus events (which Nexus
shows live but which are trimmed away on every publish) and the ``spot.incident``
annotation, Spot writes a durable, append-only JSONL record at each lifecycle
transition (detect, freeze, snapshot, restart, escalate) to
``state/cycle/incidents/`` via ``kaine.cycle.incident_log.IncidentLog``. Every record for one module fault
window shares a generated ``incident_id``. Unlike ``escalation.json`` /
``control.json`` — which hold single-state operational data and are wiped on
every clean boot — the incident log is NEVER cleared at boot, so crash/recovery
evidence accumulates across runs for research and post-mortem review. The log is
governed by ``[spot.incident_log]`` (ships ``enabled = true`` but dormant while
``[spot].enabled = false``) and is encrypted at rest when state encryption is on.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, NamedTuple, Optional

from kaine.bus.schema import validate_event
from kaine.config import require_known_keys
from kaine.cycle import control_state, escalation_state
from kaine.cycle.escalation_state import EscalationRecord
from kaine.cycle.incident_log import IncidentLog, scrub_paths
from kaine.lifecycle.manager import ForkManager
from kaine.modules.base import BaseModule
from kaine.modules.registry import ModuleRegistry
from kaine.security.crypto import get_state_encryptor

log = logging.getLogger(__name__)

_SPOT_OUT_SALIENCE = 0.5


@dataclass
class IncidentLogConfig:
    """``[spot.incident_log]`` — the durable incident-log side-channel.

    Ships ``enabled = true`` so any operator who turns Spot on automatically gets
    the research-value log; it is dormant while ``[spot].enabled = false``. There
    is deliberately NO ``retention_days`` key: the retention purge is
    unconditionally disabled for the incident log (see incident_log.py).
    """

    enabled: bool = True
    path: str = "state/cycle/incidents"

    @classmethod
    def from_section(cls, section: dict[str, Any]) -> "IncidentLogConfig":
        allowed = {"enabled", "path"}
        require_known_keys(section, allowed, "[spot.incident_log]")
        return cls(
            enabled=bool(section.get("enabled", True)),
            path=str(section.get("path", "state/cycle/incidents")),
        )


@dataclass
class SpotConfig:
    enabled: bool = False
    poll_interval_s: float = 2.0
    heartbeat_timeout_s: float = 60.0
    max_restart_attempts: int = 5
    restart_backoff_s: float = 3.0
    per_module_timeout_s: dict[str, float] = field(default_factory=dict)
    incident_log: IncidentLogConfig = field(default_factory=IncidentLogConfig)

    @classmethod
    def from_section(cls, section: dict[str, Any]) -> "SpotConfig":
        allowed = {
            "enabled",
            "poll_interval_s",
            "heartbeat_timeout_s",
            "max_restart_attempts",
            "restart_backoff_s",
            "per_module_timeout_s",
            "incident_log",
        }
        require_known_keys(section, allowed, "[spot]")
        per_module = {
            str(k): float(v)
            for k, v in (section.get("per_module_timeout_s") or {}).items()
        }
        return cls(
            enabled=bool(section.get("enabled", False)),
            poll_interval_s=float(section.get("poll_interval_s", 2.0)),
            heartbeat_timeout_s=float(section.get("heartbeat_timeout_s", 60.0)),
            max_restart_attempts=int(section.get("max_restart_attempts", 5)),
            restart_backoff_s=float(section.get("restart_backoff_s", 3.0)),
            per_module_timeout_s=per_module,
            incident_log=IncidentLogConfig.from_section(
                section.get("incident_log") or {}
            ),
        )


class AssessResult(NamedTuple):
    """Liveness assessment plus the captured crash cause.

    ``exception_repr`` is the repr of the exception that marked a module dead
    (or ``None`` for "hung" / "alive"). It is captured at the point where
    ``Spot.assess`` previously read ``t.exception()`` and discarded it, so it can
    reach the durable ``detect`` incident record. It is NOT yet path-scrubbed —
    scrubbing happens just before write.
    """

    state: str
    exception_repr: Optional[str] = None


@dataclass
class _Incident:
    attempts: int = 0
    last_good: Optional[str] = None
    incident_id: Optional[str] = None


class Spot:
    """The module supervisor. Constructed by the cycle entrypoint."""

    def __init__(
        self,
        *,
        registry: ModuleRegistry,
        fork_manager: ForkManager,
        kaine_config: dict[str, Any],
        config: SpotConfig,
        rebuild_module: Callable[[str], BaseModule],
        bus: Any,
        clock: Callable[[], float] = time.monotonic,
        on_halt: Optional[Callable[[], None]] = None,
        tick_index_provider: Optional[Callable[[], Optional[int]]] = None,
    ) -> None:
        self._registry = registry
        self._fork_manager = fork_manager
        self._kaine_config = kaine_config
        self._config = config
        self._rebuild_module = rebuild_module
        self._bus = bus
        self._clock = clock
        self._on_halt = on_halt
        # Best-effort reader of the cycle's current tick_index for the
        # tick<->poll bridge in spot.incident events. None => events carry
        # poll_index only and never a fabricated tick (honest limitation when
        # the cycle reference is not wired, e.g. in unit tests).
        self._tick_index_provider = tick_index_provider
        self._incidents: dict[str, _Incident] = {}
        self.escalated: bool = False
        self.poll_index: int = 0
        self._incident_log = IncidentLog(
            enabled=config.incident_log.enabled,
            path=config.incident_log.path,
        )

    # --- liveness ---------------------------------------------------------

    def _hypnos_sleeping(self) -> bool:
        try:
            if "hypnos" not in self._registry:
                return False
            hypnos = self._registry.get("hypnos")
            return bool(getattr(hypnos, "is_sleeping", False))
        except Exception:
            return False

    def _timeout_for(self, module: BaseModule) -> float:
        return self._config.per_module_timeout_s.get(
            module.name, self._config.heartbeat_timeout_s
        )

    def assess(self, module: BaseModule) -> AssessResult:
        """Return an ``AssessResult(state, exception_repr)`` for ``module``.

        ``state`` is "alive" | "dead" | "hung". Crash is primary (zero false
        positives): a task that finished with an exception, or returned normally
        while the module is NOT stopping (an organ loop that exited on its own),
        means dead. Hang is secondary and gated: stale heartbeat AND a
        still-running task AND not sleeping.

        ``exception_repr`` carries the repr of the crash exception for a dead
        module (the value previously read from ``t.exception()`` and discarded),
        so the durable ``detect`` incident record can capture the cause. It is
        ``None`` for hung/alive and for a dead module whose deadness is an
        unexpected normal return rather than an exception.
        """
        tasks = list(getattr(module, "_tasks", []) or [])
        stopped = getattr(module, "_stopped", None)
        is_stopping = bool(stopped.is_set()) if stopped is not None else False
        for t in tasks:
            if not t.done() or t.cancelled():
                continue
            try:
                exc = t.exception()
            except Exception:
                continue
            if exc is not None or not is_stopping:
                return AssessResult(
                    "dead", repr(exc) if exc is not None else None
                )
        if not self._hypnos_sleeping():
            stale = module.heartbeat_age() > self._timeout_for(module)
            any_running = any(not t.done() for t in tasks)
            if stale and any_running:
                return AssessResult("hung", None)
        return AssessResult("alive", None)

    # --- side effects -----------------------------------------------------

    async def _publish(self, type_: str, payload: dict[str, Any]) -> None:
        try:
            await self._bus.publish(
                validate_event(
                    source="spot",
                    type=type_,
                    payload=payload,
                    salience=_SPOT_OUT_SALIENCE,
                    timestamp=datetime.now(timezone.utc),
                )
            )
        except Exception:
            log.debug("spot publish failed (%s)", type_, exc_info=True)

    # Operational, non-sensitive incident fields that may ride the bus event
    # into the curated research log. Deliberately an allowlist: anything not
    # named here (e.g. a future free-text field) is never forwarded. Free-text
    # entries are path-scrubbed before publish below.
    _INCIDENT_EVENT_FIELDS: tuple[str, ...] = (
        "incident_id",
        "transition",
        "module",
        "fault_class",
        "fault_type",
        "reason",
        "source",
        "exception_repr",
        "snapshot_id",
        "byte_size",
        "duration_ms",
        "attempt",
        "attempts",
        "max_attempts",
        "path",
        "outcome",
        "latency_ms",
        "last_good_restored",
        "post_assess",
        "final_snapshot_id",
    )
    # Free-text fields scrubbed of operator filesystem paths before publish.
    _INCIDENT_SCRUB_FIELDS: tuple[str, ...] = ("reason", "exception_repr")

    def _current_tick_index(self) -> Optional[int]:
        """Best-effort read of the cycle's current tick_index (or None).

        Guarded so the supervisor never crashes on its own instrumentation and
        so a missing/unwired provider yields no (fabricated) tick.
        """
        if self._tick_index_provider is None:
            return None
        try:
            value = self._tick_index_provider()
        except Exception:
            log.debug("spot tick_index provider raised", exc_info=True)
            return None
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    async def _publish_incident(self, record: dict[str, Any]) -> None:
        """Publish a structured ``spot.incident`` bus event for one transition.

        Copies the allowlisted operational fields from the durable incident
        record, scrubs the free-text fields of operator paths, and stamps the
        cycle position (``poll_index`` always; ``tick_index`` when a provider is
        wired). Published IN ADDITION to the ephemeral ``spot.status`` /
        ``spot.log`` events and the durable incident log — never in place of
        them. Guarded by ``_publish``; a publish failure degrades to a debug log.
        """
        payload: dict[str, Any] = {}
        for key in self._INCIDENT_EVENT_FIELDS:
            if key not in record:
                continue
            value = record[key]
            if key in self._INCIDENT_SCRUB_FIELDS and isinstance(value, str):
                value = scrub_paths(value)
            payload[key] = value
        payload["poll_index"] = self.poll_index
        tick = self._current_tick_index()
        if tick is not None:
            payload["tick_index"] = tick
        await self._publish("spot.incident", payload)

    async def _snapshot(
        self, label: str, module_name: str, incident_id: Optional[str]
    ) -> Optional[str]:
        """Take a snapshot, emit a durable ``snapshot`` incident record, and
        return the snapshot id (or ``None`` if the whole snapshot failed).

        The per-module serialize outcome is read back from the returned
        snapshot bundle: ``ForkManager.snapshot`` stores any module that raised
        in ``serialize()`` as ``{"_serialize_error": ...}`` (manager.py), so the
        errored set is derived by inspecting the returned snapshot's module
        entries rather than reimplementing serialization. If the snapshot call
        itself raises, a record with ``snapshot_id=null`` is still written.
        """
        start = time.monotonic()
        snapshot_id: Optional[str] = None
        byte_size = 0
        modules_serialized_ok = 0
        modules_serialize_errored: list[str] = []
        try:
            snap = self._fork_manager.snapshot(
                self._registry,
                label=label,
                metadata={"module": module_name, "reason": "spot"},
            )
            snapshot_id = snap.id
            for name, state in snap.modules.items():
                if isinstance(state, dict) and "_serialize_error" in state:
                    modules_serialize_errored.append(name)
                else:
                    modules_serialized_ok += 1
            byte_size = self._snapshot_byte_size(snap.id)
        except Exception:
            log.warning("spot snapshot failed (%s)", label, exc_info=True)
        finally:
            duration_ms = (time.monotonic() - start) * 1000.0
            await self._write_incident_record(
                {
                    "incident_id": incident_id,
                    "module": module_name,
                    "transition": "snapshot",
                    "snapshot_id": snapshot_id,
                    "byte_size": byte_size,
                    "modules_serialized_ok": modules_serialized_ok,
                    "modules_serialize_errored": modules_serialize_errored,
                    "encrypted": bool(get_state_encryptor().enabled),
                    "duration_ms": duration_ms,
                    "label": label,
                }
            )
        return snapshot_id

    def _snapshot_byte_size(self, snapshot_id: str) -> int:
        """Total bytes of the completed snapshot bundle on disk (0 if absent)."""
        try:
            from kaine.lifecycle.snapshot import snapshot_path

            path = snapshot_path(self._fork_manager.root, snapshot_id)
            return Path(path).stat().st_size
        except Exception:
            return 0

    async def _write_incident_record(
        self, record: dict[str, Any], *, publish: bool = True
    ) -> None:
        """Durably append one incident transition record AND publish the
        structured ``spot.incident`` bus event for it (both no-op-safe).

        ``ts`` is stamped by IncidentLog if absent. The durable write and the
        bus publish are independently guarded so neither a broken sink nor a
        broken bus can crash the supervisor. The bus event is the curated
        research-log annotation path (run<->incident cross-link); the durable
        log remains the rich isolated provenance. ``publish=False`` suppresses
        only the bus event (the durable write still happens) — reserved for any
        future record that should stay strictly local.
        """
        if publish:
            # Publish the structured annotation IN ADDITION to the durable write
            # and the ephemeral status/log events. Independently guarded.
            await self._publish_incident(record)
        try:
            await self._incident_log.write(record)
        except Exception:
            log.warning("spot incident record write failed", exc_info=True)

    class _RestartResult(NamedTuple):
        ok: bool
        path: str  # "light" | "heavy"
        last_good_restored: bool

    async def _restart_module(self, name: str) -> "Spot._RestartResult":
        module = self._registry.get(name)
        if not module.holds_external_resources():
            try:
                await module.restart()
                return Spot._RestartResult(True, "light", False)
            except Exception:
                log.warning("light restart of %s failed", name, exc_info=True)
                return Spot._RestartResult(False, "light", False)
        # Heavy rebuild path.
        last_good_restored = False
        try:
            await module.shutdown()
            new = self._rebuild_module(name)
            await new.initialize()
            self._registry.replace(name, new)
            from kaine.boot import rewire_module

            rewire_module(self._registry, name, self._kaine_config)
            incident = self._incidents.get(name)
            last_good = incident.last_good if incident else None
            if last_good:
                self._fork_manager.restore(last_good, self._registry)
                last_good_restored = True
            return Spot._RestartResult(True, "heavy", last_good_restored)
        except Exception:
            log.warning("heavy restart of %s failed", name, exc_info=True)
            return Spot._RestartResult(False, "heavy", last_good_restored)

    async def _escalate(
        self,
        name: str,
        attempts: int,
        snapshot_id: Optional[str],
        incident_id: Optional[str] = None,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        message = (
            f"Module '{name}' failed to recover after {attempts} attempts. "
            f"Entity state saved (snapshot {snapshot_id}). Reboot the machine, "
            f"then restart the cycle. Do NOT auto-retry."
        )
        try:
            escalation_state.write_escalation(
                EscalationRecord(
                    escalated=True,
                    module=name,
                    attempts=attempts,
                    snapshot_id=snapshot_id,
                    escalated_at=now_iso,
                    message=message,
                )
            )
        except Exception:
            log.critical("spot failed to write escalation.json", exc_info=True)
        await self._write_incident_record(
            {
                "incident_id": incident_id,
                "module": name,
                "transition": "escalate",
                "attempts": attempts,
                "final_snapshot_id": snapshot_id,
                "outcome": "halted",
            }
        )
        await self._publish(
            "spot.status",
            {
                "state": "critical",
                "module": name,
                "attempts": attempts,
                "snapshot_id": snapshot_id,
                "message": message,
            },
        )
        log.critical(message)
        if self._on_halt is not None:
            try:
                self._on_halt()
            except Exception:
                log.warning("spot on_halt callback failed", exc_info=True)

    async def _shutdown_all(self) -> None:
        for module in list(self._registry.all_modules()):
            try:
                await module.shutdown()
            except Exception:
                log.warning(
                    "spot shutdown of %s failed", module.name, exc_info=True
                )

    # --- recovery (one incident per poll) ---------------------------------

    @staticmethod
    def _health_metrics(module: BaseModule) -> dict[str, Any]:
        """Read ``BaseModule.health()`` for the detect record. ``health()`` is
        documented as pure/never-raises, but Spot must never crash on its own
        instrumentation, so this is guarded and falls back to neutral values."""
        try:
            h = module.health()
            return {
                "heartbeat_age_s": float(h.get("heartbeat_age_s", 0.0)),
                "tasks_failed": int(h.get("tasks_failed", 0)),
                "tasks_total": int(h.get("tasks_total", 0)),
            }
        except Exception:
            log.debug("spot health() read failed for %s", module.name, exc_info=True)
            return {"heartbeat_age_s": 0.0, "tasks_failed": 0, "tasks_total": 0}

    async def _poll_once(self, stop_event: asyncio.Event) -> None:
        if not self._config.enabled:
            return
        self.poll_index += 1
        control = control_state.read_control()
        if control.frozen and control.source == "operator":
            # The operator owns the freeze; Spot stands down this poll.
            return
        for module in list(self._registry.all_modules()):
            result = self.assess(module)
            state = result.state
            name = module.name
            if state == "alive":
                self._incidents.pop(name, None)
                continue
            incident = self._incidents.setdefault(name, _Incident())
            if incident.incident_id is None:
                # First detection of this fault window: mint the id shared by
                # every record from detect through recover/escalate.
                incident.incident_id = str(uuid.uuid4())
            incident_id = incident.incident_id
            health = self._health_metrics(module)
            await self._write_incident_record(
                {
                    "incident_id": incident_id,
                    "module": name,
                    "transition": "detect",
                    "fault_class": state,
                    "exception_repr": scrub_paths(result.exception_repr),
                    "heartbeat_age_s": health["heartbeat_age_s"],
                    "tasks_failed": health["tasks_failed"],
                    "tasks_total": health["tasks_total"],
                    "poll_index": self.poll_index,
                }
            )
            freeze_reason = f"spot: {name} {state}"
            control_state.freeze(reason=freeze_reason, source="spot")
            await self._write_incident_record(
                {
                    "incident_id": incident_id,
                    "module": name,
                    "transition": "freeze",
                    "reason": freeze_reason,
                    "source": "spot",
                    "fault_type": state,
                }
            )
            await self._publish(
                "spot.status",
                {"state": "recovery", "module": name, "fault": state},
            )
            await self._publish(
                "spot.log",
                {
                    "module": name,
                    "message": f"detected {state} module '{name}'; recovering",
                },
            )
            if incident.attempts == 0:
                incident.last_good = await self._snapshot(
                    f"spot-pre-restart:{name}", name, incident_id
                )
            incident.attempts += 1
            restart_start = time.monotonic()
            restart = await self._restart_module(name)
            restart_latency_ms = (time.monotonic() - restart_start) * 1000.0
            post = self.assess(self._registry.get(name)).state
            recovered = restart.ok and post == "alive"
            await self._write_incident_record(
                {
                    "incident_id": incident_id,
                    "module": name,
                    "transition": "restart",
                    "attempt": incident.attempts,
                    "max_attempts": self._config.max_restart_attempts,
                    "path": restart.path,
                    "outcome": "recovered" if recovered else "failed",
                    "latency_ms": restart_latency_ms,
                    "last_good_restored": restart.last_good_restored,
                    "post_assess": post,
                }
            )
            if recovered:
                await self._publish(
                    "spot.log",
                    {
                        "module": name,
                        "message": (
                            f"recovered '{name}' after "
                            f"{incident.attempts} attempt(s)"
                        ),
                    },
                )
                self._incidents.pop(name, None)
                if control_state.read_control().source == "spot":
                    control_state.unfreeze()
                return  # one incident per poll
            if incident.attempts >= self._config.max_restart_attempts:
                final_snap = await self._snapshot(
                    f"spot-escalation:{name}", name, incident_id
                )
                snapshot_id = final_snap or incident.last_good
                await self._shutdown_all()
                await self._escalate(
                    name, incident.attempts, snapshot_id, incident_id
                )
                self.escalated = True
                stop_event.set()
                return
            await self._publish(
                "spot.log",
                {
                    "module": name,
                    "message": (
                        f"restart of '{name}' failed "
                        f"({incident.attempts}/"
                        f"{self._config.max_restart_attempts}); backing off"
                    ),
                },
            )
            await asyncio.sleep(self._config.restart_backoff_s)
            return  # stay frozen; re-poll next cycle

    async def run(self, stop_event: asyncio.Event) -> None:
        if not self._config.enabled:
            return
        try:
            await self._incident_log.start()
        except Exception:
            log.warning("spot incident log failed to start", exc_info=True)
        try:
            while not stop_event.is_set():
                try:
                    await self._poll_once(stop_event)
                except Exception:
                    # Who watches the watchdog: an internal error must halt
                    # loudly, not die silently.
                    log.critical("spot poll crashed; halting", exc_info=True)
                    self.escalated = True
                    if self._on_halt is not None:
                        try:
                            self._on_halt()
                        except Exception:
                            log.warning(
                                "spot on_halt callback failed", exc_info=True
                            )
                    stop_event.set()
                    return
                try:
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=self._config.poll_interval_s
                    )
                except asyncio.TimeoutError:
                    continue
        finally:
            # Flush any buffered incident records on the way out (clean stop or
            # escalation halt alike).
            try:
                await self._incident_log.stop()
            except Exception:
                log.warning("spot incident log failed to stop", exc_info=True)
