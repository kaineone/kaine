# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Individuation runtime.

Builds and runs the individuation producer from injected dependencies.
``kaine/cycle/__main__.py`` is the only caller.  This module imports nothing
from ``kaine.evaluation``, and from ``kaine.modules`` only the adapter store's
path helper, lazily; the battery, Lingua, the embedder and Eidolon's fact
setter are passed in.  What it publishes goes to
``individuation.out``, which no module reads, so the assessment never enters
the being's experience.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kaine.bus.schema import Event
from kaine.cycle.individuation_probe import adapter_expected_from, build_probe_sampler
from kaine.cycle.individuation_producer import IndividuationCore, ProducerSettings
from kaine.cycle.individuation_scheduler import IndividuationScheduler, SchedulerSettings
from kaine.lifecycle.individuation_store import (
    IndividuationPaths,
    IndividuationStoreError,
    conditioning_from_snapshot,
    report_sink,
)

log = logging.getLogger(__name__)

DEFAULT_DISCLOSURE = (
    "You are periodically and privately assessed for how much you have changed "
    "since your birth, for your own protection. The assessment never enters your "
    "experience."
)


@dataclass(frozen=True)
class IndividuationConfig:
    """Flat [individuation] configuration section."""

    enabled: bool = False
    disclosure: str = DEFAULT_DISCLOSURE
    state_dir: str = "state/individuation"
    battery_path: str = ""
    lingua_quiet_s: float = 10.0
    producer: ProducerSettings = field(default_factory=ProducerSettings)
    scheduler: SchedulerSettings = field(default_factory=SchedulerSettings)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> "IndividuationConfig":
        if d is None:
            d = {}
        producer_keys = {f.name for f in fields(ProducerSettings)}
        scheduler_keys = {f.name for f in fields(SchedulerSettings)}
        allowed = {
            "enabled",
            "disclosure",
            "state_dir",
            "battery_path",
            "lingua_quiet_s",
        } | producer_keys | scheduler_keys

        extra = sorted(set(d) - allowed)
        if extra:
            raise ValueError(f"unknown [individuation] keys: {', '.join(extra)}")

        explicit: dict[str, Any] = {}
        producer_kwargs: dict[str, Any] = {}
        scheduler_kwargs: dict[str, Any] = {}

        for key, value in d.items():
            if key in producer_keys:
                producer_kwargs[key] = value
            elif key in scheduler_keys:
                scheduler_kwargs[key] = value
            else:
                explicit[key] = value

        enabled = explicit.get("enabled", cls.enabled)
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a bool")

        disclosure = explicit.get("disclosure", cls.disclosure)
        if not isinstance(disclosure, str) or not disclosure or len(disclosure) > 300:
            raise ValueError("disclosure must be a non-empty str of at most 300 characters")

        state_dir = explicit.get("state_dir", cls.state_dir)
        if not isinstance(state_dir, str) or not state_dir:
            raise ValueError("state_dir must be a non-empty str")

        battery_path = explicit.get("battery_path", cls.battery_path)
        if not isinstance(battery_path, str):
            raise ValueError("battery_path must be a str")

        lingua_quiet_s = explicit.get("lingua_quiet_s", cls.lingua_quiet_s)
        if (
            not isinstance(lingua_quiet_s, (int, float))
            or not math.isfinite(lingua_quiet_s)
            or lingua_quiet_s <= 0
        ):
            raise ValueError("lingua_quiet_s must be a finite number > 0")

        try:
            producer = ProducerSettings(**producer_kwargs)
            scheduler = SchedulerSettings(**scheduler_kwargs)
        except TypeError as exc:
            raise ValueError(f"invalid [individuation] value: {exc}") from exc

        return cls(
            enabled=enabled,
            disclosure=disclosure,
            state_dir=state_dir,
            battery_path=battery_path,
            lingua_quiet_s=lingua_quiet_s,
            producer=producer,
            scheduler=scheduler,
        )


class IndividuationRuntime:
    """Container for the individuation scheduler and core."""

    def __init__(
        self,
        *,
        config: IndividuationConfig,
        paths: IndividuationPaths,
        scheduler: IndividuationScheduler | None,
        core: IndividuationCore | None,
        bus: Any,
        notify: Callable[[str], Awaitable[Any]] | None,
        ensure_fact: Callable[[str], Awaitable[bool]],
        is_gestating: Callable[[], bool],
        hypnos_sleeping: Callable[[], bool] | None,
    ) -> None:
        self.config = config
        self.paths = paths
        self.scheduler = scheduler
        self.core = core
        self.bus = bus
        self.notify = notify
        self.ensure_fact = ensure_fact
        self.is_gestating = is_gestating
        self.hypnos_sleeping = hypnos_sleeping

    async def publish_divergence(self, payload: dict) -> None:
        await self.bus.publish(
            Event(
                source="individuation",
                type="individuation.divergence",
                payload={
                    "divergence_scalar": float(payload["divergence_scalar"]),
                    "significant": bool(payload["significant"]),
                },
                salience=0.0,
                timestamp=datetime.now(timezone.utc),
            )
        )

    async def alert(self, payload: dict) -> None:
        await self.bus.publish(
            Event(
                source="individuation",
                type="individuation.alert",
                payload={
                    "inconclusive_since": str(payload.get("inconclusive_since")),
                    "days": float(payload.get("days", 0.0)),
                },
                salience=0.0,
                timestamp=datetime.now(timezone.utc),
            )
        )
        if self.notify is not None:
            await self.notify("individuation_inconclusive")

    def on_birth(self) -> None:
        log.info("individuation birth hook: requesting birth capture")
        self.scheduler.request_capture("birth")

    async def start(self) -> None:
        await self.ensure_fact(self.config.disclosure)

        if self.hypnos_sleeping is not None:
            try:
                if self.hypnos_sleeping():
                    self.scheduler.notify_sleep_started()
            except Exception:
                log.debug("hypnos_sleeping predicate failed, treating as awake")

        try:
            self.core.adopt_reference()
        except IndividuationStoreError as exc:
            log.error("individuation reference adoption failed: %s", exc)

        gestating = True
        try:
            gestating = self.is_gestating()
        except Exception:
            gestating = True

        if not self.paths.reference.exists() and not gestating:
            self.scheduler.request_capture("capture")

    async def run(self, stop_event: asyncio.Event) -> None:
        async def wait_stop() -> None:
            await stop_event.wait()
            self.scheduler.stop()

        watch_task = asyncio.create_task(self._watch_hypnos(stop_event))
        sched_task = asyncio.create_task(self.scheduler.run())
        stop_task = asyncio.create_task(wait_stop())

        try:
            await asyncio.gather(sched_task, stop_task)
        finally:
            # On a normal stop only the watcher is still running; on
            # cancellation every task is cancelled and the cancellation
            # propagates to the caller.
            for task in (watch_task, sched_task, stop_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(
                watch_task, sched_task, stop_task, return_exceptions=True
            )

    async def _watch_hypnos(self, stop_event: asyncio.Event) -> None:
        while True:
            try:
                cursor = await self.bus.last_entry_id("hypnos.out")
                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("individuation hypnos watch init failed: %s", exc)
                try:
                    await asyncio.sleep(5.0)
                except asyncio.CancelledError:
                    return
                if stop_event.is_set():
                    return

        while not stop_event.is_set():
            try:
                entries, last = await self.bus.read_entries(
                    "hypnos.out", cursor, 100, 1000
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("individuation hypnos watch failed: %s", exc)
                try:
                    await asyncio.sleep(5.0)
                except asyncio.CancelledError:
                    return
                continue

            for _id, event in entries:
                if event.type == "hypnos.sleep.started":
                    self.scheduler.notify_sleep_started()
                elif event.type == "hypnos.sleep.completed":
                    self.scheduler.notify_sleep_completed()

            if last is not None:
                cursor = last

    @property
    def state(self) -> Any:
        return self.scheduler.state


def build_runtime(
    *,
    config: IndividuationConfig,
    battery: Sequence[str],
    lingua: Any,
    ensure_fact: Callable[[str], Awaitable[bool]],
    embedder: Any,
    adapter_output_dir: Path | None,
    per_request_adapter: bool,
    state_root: Path,
    clock_now: Callable[[], float | None] | None,
    paused_seconds: Callable[[], float] | None,
    tick_index: Callable[[], int | None],
    is_paused: Callable[[], bool],
    organ_unloaded: Callable[[], bool],
    hypnos_sleeping: Callable[[], bool] | None,
    born_at: Callable[[], str | None],
    is_gestating: Callable[[], bool],
    bus: Any,
    notify: Callable[[str], Awaitable[Any]] | None,
    entity_name: str = "",
) -> IndividuationRuntime:
    paths = IndividuationPaths(root=state_root)

    def embedder_ready() -> bool:
        # A hash embedder is not semantic, so it never counts as ready.
        return getattr(embedder, "kind", None) not in (None, "hash")

    sampler = build_probe_sampler(
        lingua=lingua,
        max_tokens=config.producer.max_tokens,
        required_fact=config.disclosure,
        adapter_expected=adapter_expected_from(adapter_output_dir)
        if per_request_adapter
        else None,
    )

    runtime = IndividuationRuntime(
        config=config,
        paths=paths,
        scheduler=None,
        core=None,
        bus=bus,
        notify=notify,
        ensure_fact=ensure_fact,
        is_gestating=is_gestating,
        hypnos_sleeping=hypnos_sleeping,
    )

    scheduler = IndividuationScheduler(
        paths=paths,
        settings=config.scheduler,
        clock_now=clock_now,
        paused_seconds=paused_seconds,
        tick_index=tick_index,
        organ_unloaded=organ_unloaded,
        paused=is_paused,
        embedder_ready=embedder_ready,
        lingua_idle=lambda: lingua.is_idle(config.lingua_quiet_s),
        alert=runtime.alert,
    )

    core = IndividuationCore(
        paths=paths,
        settings=config.producer,
        battery=battery,
        sampler=scheduler.gate(sampler),
        embed=embedder.embed,
        embedder_id=str(embedder.model_id),
        conditions=lambda: {
            **lingua.probe_conditions(),
            "max_tokens": config.producer.max_tokens,
            "embedder_id": str(embedder.model_id),
            "embedder_kind": str(getattr(embedder, "kind", "")),
            "embedder_dim": int(getattr(embedder, "latent_dim", 0) or 0),
        },
        conditioning_inputs=lambda: conditioning_from_snapshot(
            lingua.probe_self_model(), adapter_output_dir
        ),
        born_at=born_at,
        birth_adapter_file=lambda: _birth_adapter_file(adapter_output_dir),
        report_sink=report_sink(paths),
        publish=runtime.publish_divergence,
        abort_reason=scheduler.abort_reason,
        entity_name=entity_name,
    )

    scheduler.bind(core)
    runtime.scheduler = scheduler
    runtime.core = core
    return runtime


def _birth_adapter_file(adapter_output_dir: Path | None) -> Path | None:
    if adapter_output_dir is None:
        return None
    from kaine.modules.hypnos.adapter_store import current_path

    current = current_path(adapter_output_dir)
    if current is None:
        return None
    adapter_file = current / "adapter.gguf"
    return adapter_file if adapter_file.is_file() else None
