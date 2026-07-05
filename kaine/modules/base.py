# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC
from datetime import datetime, timezone
from typing import Any, ClassVar, Optional

from kaine.bus.client import AsyncBus
from kaine.bus.schema import Event, validate_event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.oscillator import NEUTRAL_PHASE, OscillatorProtocol

log = logging.getLogger(__name__)


class BaseModule(ABC):
    """Common contract for every KAINE module.

    Subclasses MUST declare a class-level `name` matching their bus
    output stream prefix (e.g. `name = "soma"` publishes to `soma.out`).
    Subclasses override `on_workspace` to react to each global
    broadcast and may override `serialize` and `deserialize` to support
    Phase 7 fork/merge.
    """

    name: ClassVar[str]

    def __init__(self, bus: AsyncBus) -> None:
        self._enforce_name()
        self._bus = bus
        self._tasks: list[asyncio.Task[Any]] = []
        self._stopped = asyncio.Event()
        self._workspace_cursor = "$"
        # Optional oscillatory-binding LIF oscillator (oscillatory-layer).
        # None until attached via attach_oscillator(); modules without one
        # report the neutral phase, so the coherence factor degrades to 1.0.
        self._oscillator: Optional[OscillatorProtocol] = None
        # Centralized liveness heartbeat for the Spot supervisor. Bumped after
        # each successful on_workspace and at the end of publish; the cycle's
        # 10 Hz broadcast refreshes it for every live module regardless of
        # the module's own publishing activity, so "quiet" never reads as "hung."
        # infrastructural: real time, not subjective — the liveness watchdog
        # measures real elapsed seconds and must not dilate with time_scale.
        self._last_heartbeat = time.monotonic()

    def _beat(self) -> None:
        # infrastructural: real time, not subjective (liveness heartbeat).
        self._last_heartbeat = time.monotonic()

    def heartbeat_age(self) -> float:
        """Seconds since the last liveness heartbeat (real monotonic time)."""
        # infrastructural: real time, not subjective.
        return time.monotonic() - self._last_heartbeat

    def health(self) -> dict[str, Any]:
        """Operational liveness snapshot for the Spot supervisor.

        Pure and never raises — every task introspection is guarded by
        done()/cancelled() so a pending or cancelled task can't blow up.
        """
        tasks_total = len(self._tasks)
        tasks_done = 0
        tasks_failed = 0
        for t in self._tasks:
            if not t.done():
                continue
            tasks_done += 1
            if t.cancelled():
                continue
            try:
                if t.exception() is not None:
                    tasks_failed += 1
            except Exception:
                # Defensive: never let introspection raise.
                continue
        return {
            "name": self.name,
            "heartbeat_age_s": self.heartbeat_age(),
            "tasks_total": tasks_total,
            "tasks_done": tasks_done,
            "tasks_failed": tasks_failed,
        }

    async def restart(self) -> None:
        """Light restart: tear down, reset for a fresh start, re-initialize.

        Valid only when construction held no external resources (see
        holds_external_resources). The Spot supervisor uses the heavy rebuild
        path for modules that do.
        """
        await self.shutdown()
        self._stopped = asyncio.Event()
        self._workspace_cursor = "$"
        await self.initialize()

    def holds_external_resources(self) -> bool:
        """Whether this module owns external handles (httpx/Qdrant clients,
        model handles, perception supervisors) that a light restart() cannot
        safely recreate. Modules that do override this to return True so Spot
        rebuilds them via the boot factory instead."""
        return False

    @classmethod
    def _enforce_name(cls) -> None:
        if not getattr(cls, "name", None):
            raise TypeError(
                f"{cls.__name__} must declare a class-level `name: ClassVar[str]`"
            )

    @property
    def bus(self) -> AsyncBus:
        return self._bus

    async def initialize(self) -> None:
        if self._workspace_cursor == "$":
            self._workspace_cursor = await self._bus.current_workspace_id()
        task = asyncio.create_task(self._workspace_loop(), name=f"{self.name}-workspace")
        self._tasks.append(task)

    async def shutdown(self) -> None:
        self._stopped.set()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def publish(
        self,
        type_: str,
        payload: dict[str, Any],
        *,
        salience: float = 0.5,
        causal_parent: Optional[str] = None,
    ) -> str:
        event = validate_event(
            source=self.name,
            type=type_,
            payload=payload,
            salience=salience,
            timestamp=datetime.now(timezone.utc),
            causal_parent=causal_parent,
        )
        # Drive this module's oscillator (if any) from its own activity. v1
        # uses the published salience as a co-activity proxy for the paper's
        # content-relatedness (see design.md). No-op when no oscillator.
        oscillator = getattr(self, "_oscillator", None)
        if oscillator is not None:
            try:
                oscillator.step(float(salience))
            except Exception:
                log.debug("oscillator step failed in module %s", self.name, exc_info=True)
        result = await self._bus.publish(event)
        self._beat()
        return result

    async def on_workspace(self, snapshot: WorkspaceSnapshot) -> None:
        """Override in subclasses to react to each broadcast."""
        return

    def attach_oscillator(self, oscillator: Optional[OscillatorProtocol]) -> None:
        """Attach (or clear) this module's oscillatory-binding oscillator.

        Called by the boot wiring when ``[oscillator].enabled`` is true and a
        live oscillator could be constructed. Passing ``None`` (or never
        calling this) leaves the module reporting the neutral phase.
        """
        self._oscillator = oscillator

    @property
    def oscillator(self) -> Optional[OscillatorProtocol]:
        return getattr(self, "_oscillator", None)

    def phase(self) -> float:
        """Current oscillator phase, or the neutral phase when none is attached.

        A module without an oscillator is indistinguishable, for coherence
        purposes, from every other neutral module — they lock perfectly among
        themselves and so never perturb selection relative to one another.
        """
        oscillator = getattr(self, "_oscillator", None)
        if oscillator is None:
            return NEUTRAL_PHASE
        try:
            return float(oscillator.phase())
        except Exception:
            log.debug("oscillator phase failed in module %s", self.name, exc_info=True)
            return NEUTRAL_PHASE

    def set_frequency(self, scale: float) -> None:
        """Scale this module's LIF oscillator drive frequency by ``scale``.

        Called by ``hypnos-fatigue-phases`` phase 1 to slow oscillators during
        maintenance (e.g. 0.5 = half speed during deep sleep). Delegates to the
        attached oscillator; a true no-op when no oscillator is attached, so
        Hypnos can invoke it unconditionally without error regardless of
        oscillatory-layer deployment status. No-op correctness is exercised by
        ``tests/test_hypnos_oscillator_hook.py``.

        Args:
            scale: Multiplicative frequency scaling factor.
        """
        oscillator = getattr(self, "_oscillator", None)
        if oscillator is None:
            return
        try:
            oscillator.set_frequency(float(scale))
        except Exception:
            log.debug("oscillator set_frequency failed in %s", self.name, exc_info=True)

    def serialize(self) -> dict[str, Any]:
        return {}

    def deserialize(self, state: dict[str, Any]) -> None:
        return

    async def _workspace_loop(self) -> None:
        try:
            async for entry_id, payload in self._bus.subscribe_workspace(
                last_id=self._workspace_cursor
            ):
                if self._stopped.is_set():
                    break
                self._workspace_cursor = entry_id
                try:
                    snapshot = self._snapshot_from_payload(payload)
                    await self.on_workspace(snapshot)
                    self._beat()
                except Exception:
                    log.exception("on_workspace failed in module %s", self.name)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("workspace subscription loop crashed in module %s", self.name)

    def _snapshot_from_payload(self, payload: dict[str, Any]) -> WorkspaceSnapshot:
        selected: list[tuple[str, Event]] = []
        for item in payload.get("selected", []) or []:
            ts = item.get("timestamp")
            if isinstance(ts, str):
                ts_value = datetime.fromisoformat(ts)
            else:
                ts_value = ts
            try:
                event = Event(
                    source=item["source"],
                    type=item["type"],
                    payload=item.get("payload") or {},
                    salience=float(item["salience"]),
                    timestamp=ts_value,
                    causal_parent=item.get("causal_parent") or None,
                )
            except Exception:
                log.warning("dropped malformed broadcast item: %s", item, exc_info=True)
                continue
            selected.append((str(item.get("entry_id", "")), event))
        return WorkspaceSnapshot(
            tick_index=int(payload.get("tick_index", 0)),
            selected_events=selected,
            inhibited=bool(payload.get("inhibited", False)),
            is_experiential=bool(payload.get("is_experiential", False)),
            salience_scores={
                str(k): float(v)
                for k, v in (payload.get("salience_scores") or {}).items()
            },
            metadata=dict(payload.get("metadata") or {}),
        )
