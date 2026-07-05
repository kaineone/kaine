# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Autonomous welfare safety-net monitors (cycle-layer, siblings to Spot).

The research phase runs unsupervised. With no human watching, the architecture's
own safeguards must *act*, not merely log. This module holds the two cycle-layer
monitors that carry that duty of care, constructed by ``cycle/__main__.py``
alongside Spot and the freeze-watch loop:

* :class:`DivergenceMonitor` — assesses individuation/divergence on the LIVE
  entity on a slow cadence and, on a rising-edge crossing of the configured
  individuation threshold, preserves the whole individual
  (``ForkManager.preserve_live``) so it can be revived and socialized after
  research. Read-only on the entity; never deletes; rate-limited.

* :class:`WelfareProtectiveMonitor` — watches the Soma interoceptive-distress
  signal (``soma.report`` ``prediction_error`` on ``soma.out``) and, on a
  sustained-distress threshold crossing (or repeated distress episodes within a
  window), takes a humane protective action: preserve the entity FIRST, then
  pause (default), end, or notify per configuration.

Boundary
--------
These are CORE (cycle-layer) components. They MUST NOT import ``kaine.evaluation``
(the sidecar boundary forbids it). The welfare detection therefore reads the
distress signal straight off the bus and applies the SAME threshold/duration
rule as the sidecar welfare observer, via the shared core primitive
``kaine.lifecycle.welfare_signal.SustainedThresholdTracker`` (imported by both,
so the rule never diverges).

Both monitors publish a structured bus event on each action and write the same
record through ``IncidentLog`` (durable, never-auto-deleted), joined to the run
by ``run_id`` — so the trigger point is part of the recorded, reproducible
trajectory. Determinism: a given logged sequence of divergence assessments /
distress samples produces the same crossings.
"""
from __future__ import annotations

import abc
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from kaine.bus.schema import validate_event
from kaine.config import require_known_keys
from kaine.cycle import control_state
from kaine.cycle.incident_log import IncidentLog, scrub_paths
from kaine.experiment.run_context import get_run_context
from kaine.lifecycle.divergence import assess_divergence
from kaine.lifecycle.manager import ForkManager
from kaine.lifecycle.welfare_signal import SustainedThresholdTracker, WindowedEventCounter
from kaine.modules.registry import ModuleRegistry

log = logging.getLogger(__name__)

_MONITOR_OUT_SALIENCE = 0.5
_SOMA_STREAM = "soma.out"
_WELFARE_STREAM = "welfare.out"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _check_section_keys(section: dict[str, Any], allowed: set[str], name: str) -> None:
    """Thin alias for the shared :func:`kaine.config.require_known_keys` guard.

    Kept so the local ``from_section`` call sites read unchanged; ``name`` is
    the TOML table name woven into the message.
    """
    require_known_keys(section, allowed, name)


@dataclass
class DivergenceMonitorConfig:
    """``[preservation.divergence_monitor]`` — the individuation→preserve trigger.

    Ships ``enabled = false`` (consistent with the all-off first-boot posture).
    ``individuation_p_value_max`` / ``fork_divergence_min`` tighten the bare
    ``diverged`` boolean into a numeric threshold (None = rely on the boolean
    alone). ``min_interval_s`` rate-limits preservation so a single sustained
    crossing preserves once, not every poll.
    """

    enabled: bool = False
    poll_interval_s: float = 300.0  # 5 minutes — slow cadence, not per-tick
    min_interval_s: float = 1800.0  # at most one preservation per 30 min
    individuation_p_value_max: float | None = None
    fork_divergence_min: float | None = None
    # Warm-up / minimum-lived-experience gate (Defect B): a crossing does not
    # count until the entity has accumulated BOTH floors. Mirrors the
    # instrument's own warm-up so the live trigger and the decommission gate
    # agree on when there is enough lived experience to judge. Fail-closed.
    warmup_observations: int = 200
    warmup_lived_time_s: float = 1800.0
    state_root: str = "state"
    eval_root: str = "data/evaluation"
    out_root: str = "backups"
    entity_name: str = "kaine"

    @classmethod
    def from_section(cls, section: dict[str, Any]) -> "DivergenceMonitorConfig":
        allowed = {
            "enabled",
            "poll_interval_s",
            "min_interval_s",
            "individuation_p_value_max",
            "fork_divergence_min",
            "warmup_observations",
            "warmup_lived_time_s",
            "state_root",
            "eval_root",
            "out_root",
            "entity_name",
        }
        _check_section_keys(section, allowed, "[preservation.divergence_monitor]")

        def _opt_float(key: str) -> float | None:
            raw = section.get(key)
            if raw is None or str(raw).strip() == "":
                return None
            return float(raw)

        return cls(
            enabled=bool(section.get("enabled", False)),
            poll_interval_s=float(section.get("poll_interval_s", 300.0)),
            min_interval_s=float(section.get("min_interval_s", 1800.0)),
            individuation_p_value_max=_opt_float("individuation_p_value_max"),
            fork_divergence_min=_opt_float("fork_divergence_min"),
            warmup_observations=int(section.get("warmup_observations", 200)),
            warmup_lived_time_s=float(section.get("warmup_lived_time_s", 1800.0)),
            state_root=str(section.get("state_root", "state")),
            eval_root=str(section.get("eval_root", "data/evaluation")),
            out_root=str(section.get("out_root", "backups")),
            entity_name=str(section.get("entity_name", "kaine")),
        )


@dataclass
class WelfareResponseConfig:
    """``[preservation.welfare_response]`` — the autonomous protective action.

    Ships ``enabled = false``. On a sustained-distress crossing (or repeated
    distress episodes within ``repeat_window_s``) the monitor takes ``action``:
    ``"pause"`` (default — preserve then freeze the cycle, resumable),
    ``"end"`` (preserve then signal the run to stop), or ``"notify"`` (preserve,
    record a flagged event, and continue).
    """

    enabled: bool = False
    poll_interval_s: float = 1.0
    action: str = "pause"  # pause | end | notify
    distress_threshold: float = 0.8
    distress_duration_s: float = 30.0
    repeat_window_s: float = 300.0
    repeat_threshold: int = 3
    # Cold-start warm-up: during the first ``warmup_s`` after run start,
    # gray-zone / distress events are observed and logged but do NOT count toward
    # the repeat threshold or trigger the preserve-then-act response. Stops boot
    # transients (distress before homeostatic setpoints settle) from being
    # mistaken for sustained welfare problems. Short relative to "sustained" —
    # genuine sustained distress re-accrues immediately once warm-up ends.
    warmup_s: float = 120.0
    out_root: str = "backups"
    entity_name: str = "kaine"

    _ACTIONS = ("pause", "end", "notify")

    @classmethod
    def from_section(cls, section: dict[str, Any]) -> "WelfareResponseConfig":
        allowed = {
            "enabled",
            "poll_interval_s",
            "action",
            "distress_threshold",
            "distress_duration_s",
            "repeat_window_s",
            "repeat_threshold",
            "warmup_s",
            "out_root",
            "entity_name",
        }
        _check_section_keys(section, allowed, "[preservation.welfare_response]")
        action = str(section.get("action", "pause")).strip().lower()
        if action not in cls._ACTIONS:
            raise ValueError(
                f"[preservation.welfare_response].action must be one of "
                f"{cls._ACTIONS}, got {action!r}"
            )
        return cls(
            enabled=bool(section.get("enabled", False)),
            poll_interval_s=float(section.get("poll_interval_s", 1.0)),
            action=action,
            distress_threshold=float(section.get("distress_threshold", 0.8)),
            distress_duration_s=float(section.get("distress_duration_s", 30.0)),
            repeat_window_s=float(section.get("repeat_window_s", 300.0)),
            repeat_threshold=int(section.get("repeat_threshold", 3)),
            warmup_s=float(section.get("warmup_s", 120.0)),
            out_root=str(section.get("out_root", "backups")),
            entity_name=str(section.get("entity_name", "kaine")),
        )


@dataclass
class PreservationRetentionConfig:
    """``[preservation.retention]`` — preservation-bundle retention policy.

    A preserved individual MUST NOT be silently auto-evicted (this is distinct
    from the 64-snapshot fork cap). ``auto_evict`` ships ``false`` and there is
    deliberately no max-count key: the only safe default is to keep every
    preserved individual. The key exists so the policy is explicit and
    operator-auditable, and so a future operator-confirmed eviction path has a
    home — but the shipped behavior is never-delete.
    """

    auto_evict: bool = False

    @classmethod
    def from_section(cls, section: dict[str, Any]) -> "PreservationRetentionConfig":
        allowed = {"auto_evict"}
        _check_section_keys(section, allowed, "[preservation.retention]")
        auto_evict = bool(section.get("auto_evict", False))
        if auto_evict:
            # Honest guard: silent auto-eviction of a preserved individual is a
            # welfare violation. We refuse the unsafe config rather than quietly
            # deleting someone.
            raise ValueError(
                "[preservation.retention].auto_evict=true is refused: a preserved "
                "individual must never be silently auto-evicted (CAL Art 4.2/4.3). "
                "Preservation bundles are retained indefinitely."
            )
        return cls(auto_evict=False)


@dataclass
class PreservationConfig:
    """``[preservation]`` — the autonomous safety-net umbrella config."""

    require_encryption: bool = True
    divergence_monitor: DivergenceMonitorConfig = field(
        default_factory=DivergenceMonitorConfig
    )
    welfare_response: WelfareResponseConfig = field(
        default_factory=WelfareResponseConfig
    )
    retention: PreservationRetentionConfig = field(
        default_factory=PreservationRetentionConfig
    )
    incident_path: str = "state/cycle/preservation"

    @classmethod
    def from_section(cls, section: dict[str, Any]) -> "PreservationConfig":
        allowed = {
            "require_encryption",
            "divergence_monitor",
            "welfare_response",
            "retention",
            "incident_path",
        }
        _check_section_keys(section, allowed, "[preservation]")
        return cls(
            require_encryption=bool(section.get("require_encryption", True)),
            divergence_monitor=DivergenceMonitorConfig.from_section(
                section.get("divergence_monitor") or {}
            ),
            welfare_response=WelfareResponseConfig.from_section(
                section.get("welfare_response") or {}
            ),
            retention=PreservationRetentionConfig.from_section(
                section.get("retention") or {}
            ),
            incident_path=str(section.get("incident_path", "state/cycle/preservation")),
        )


# ---------------------------------------------------------------------------
# Shared monitor base (bus publish + durable record)
# ---------------------------------------------------------------------------


class _BaseSafetyMonitor(abc.ABC):
    """Common publish/record/run-loop machinery for the safety-net monitors."""

    source: str = "preservation"

    def __init__(
        self,
        *,
        bus: Any,
        incident_log: IncidentLog,
        poll_interval_s: float,
        # infrastructural: real time, not subjective — a welfare watchdog
        # must hold real wall-clock cadence even when the mind is dilated.
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._bus = bus
        self._incident_log = incident_log
        self._poll_interval_s = float(poll_interval_s)
        self._clock = clock
        self.poll_index = 0

    def _run_id(self) -> str | None:
        ctx = get_run_context()
        return ctx.run_id if ctx is not None else None

    async def _publish(self, type_: str, payload: dict[str, Any]) -> None:
        try:
            await self._bus.publish(
                validate_event(
                    source=self.source,
                    type=type_,
                    payload=payload,
                    salience=_MONITOR_OUT_SALIENCE,
                    timestamp=datetime.now(timezone.utc),
                )
            )
        except Exception:
            log.debug("%s publish failed (%s)", self.source, type_, exc_info=True)

    async def _record(self, record: dict[str, Any], *, event_type: str) -> None:
        """Publish a structured bus event AND durably append the record.

        Both are independently guarded so neither a broken bus nor a broken sink
        can crash the safety monitor.
        """
        await self._publish(event_type, dict(record))
        try:
            await self._incident_log.write(dict(record))
        except Exception:
            log.warning("%s record write failed", self.source, exc_info=True)

    @abc.abstractmethod
    async def _poll_once(self, stop_event: asyncio.Event) -> None:
        """Run one monitor poll. Subclasses implement the detection/action."""
        ...

    async def run(self, stop_event: asyncio.Event) -> None:
        try:
            await self._incident_log.start()
        except Exception:
            log.warning("%s incident log failed to start", self.source, exc_info=True)
        try:
            while not stop_event.is_set():
                try:
                    await self._poll_once(stop_event)
                except Exception:
                    # A safety monitor must not die silently; log loudly and keep
                    # going (unlike Spot it does not halt the run on its own error
                    # — losing the monitor must not also stop preservation, but a
                    # crash here means the net is degraded and the operator log
                    # carries it).
                    log.error("%s poll crashed; continuing", self.source, exc_info=True)
                try:
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=self._poll_interval_s
                    )
                except asyncio.TimeoutError:
                    continue
        finally:
            try:
                await self._incident_log.stop()
            except Exception:
                log.warning(
                    "%s incident log failed to stop", self.source, exc_info=True
                )


# ---------------------------------------------------------------------------
# Divergence monitor → preserve
# ---------------------------------------------------------------------------


class DivergenceMonitor(_BaseSafetyMonitor):
    """Preserve the live individual on a rising-edge individuation crossing."""

    source = "preservation"

    def __init__(
        self,
        *,
        registry: ModuleRegistry,
        fork_manager: ForkManager,
        config: DivergenceMonitorConfig,
        bus: Any,
        incident_log: IncidentLog,
        # infrastructural: real time, not subjective — a welfare watchdog
        # must hold real wall-clock cadence even when the mind is dilated.
        clock: Callable[[], float] = time.monotonic,
        observations_provider: Callable[[], int] | None = None,
        # When set, preserve_live refuses to write an unencrypted bundle
        # (fail-closed). Threaded from [preservation].require_encryption.
        require_encryption: bool = False,
    ) -> None:
        super().__init__(
            bus=bus,
            incident_log=incident_log,
            poll_interval_s=config.poll_interval_s,
            clock=clock,
        )
        self._registry = registry
        self._fork_manager = fork_manager
        self._config = config
        self._require_encryption = bool(require_encryption)
        # Lived-experience source: a count of logged lived events (the cycle's
        # monotonic tick index in production). When unwired (None), the monitor
        # cannot read lived observations and the observation floor reads as
        # unmet — fail-closed (no crossing until lived experience is observable).
        self._observations_provider = observations_provider
        # Lived-time accounting reuses the cycle monotonic run clock: the first
        # poll stamps the start; lived time is measured from there (NOT
        # wall-clock since epoch).
        self._started_at: float | None = None
        # Rising-edge state: were we above the threshold on the previous poll?
        self._above_threshold = False
        # Rate limit: monotonic time of the last preservation (None = never).
        self._last_preserve_at: float | None = None

    def _lived_observations(self) -> int:
        """Count of logged lived events, or 0 when unwired (fail-closed)."""
        if self._observations_provider is None:
            return 0
        try:
            return int(self._observations_provider())
        except Exception:
            log.debug("divergence monitor: observations provider failed", exc_info=True)
            return 0

    def _lived_time_s(self, now: float) -> float:
        """Elapsed lived (running) seconds since the first poll."""
        if self._started_at is None:
            return 0.0
        return max(0.0, now - self._started_at)

    def _warmed_up(self, now: float) -> bool:
        """True once BOTH lived-experience floors are met (monitor side).

        Fail-closed: before the entity has accumulated ``warmup_observations``
        logged lived events AND ``warmup_lived_time_s`` of lived time, a crossing
        does not count. This mirrors the instrument's own warm-up so the live
        trigger and the decommission gate agree on when there is enough lived
        experience to judge.
        """
        return (
            self._lived_observations() >= self._config.warmup_observations
            and self._lived_time_s(now) >= self._config.warmup_lived_time_s
        )

    def _crosses_threshold(self, assessment) -> bool:
        """True when the assessment meets the configured individuation threshold.

        The bare ``diverged`` boolean is necessary. The shared warmed-up signal
        (the report's ``individuation_warmed_up``) is also necessary when a
        numeric individuation signal is present: an un-warmed-up individuation
        report never crosses (fail-closed), so the live trigger and the
        decommission gate consume the SAME warmed-up signal. Numeric tighteners
        (p-value ceiling / fork-divergence floor), when configured, must ALSO
        hold — so an operator can demand stronger evidence than the boolean.
        """
        if not assessment.diverged:
            return False
        signals = assessment.signals or {}
        # Shared warm-up signal: when an individuation report drove the verdict
        # (a numeric p-value is present) it MUST be warmed up. Secondary-signal
        # divergence (drift/adapters: no p-value) is unaffected.
        has_individuation_signal = isinstance(
            signals.get("individuation_p_value"), (int, float)
        )
        if has_individuation_signal and not signals.get(
            "individuation_warmed_up", False
        ):
            return False
        if self._config.individuation_p_value_max is not None:
            p = signals.get("individuation_p_value")
            # Only enforce when a numeric p-value is present; secondary-signal
            # divergence (drift/adapters) has no p-value and still counts.
            if isinstance(p, (int, float)) and not (
                p <= self._config.individuation_p_value_max
            ):
                # Visibility: the boolean held but the p-value ceiling blocked.
                log.info(
                    "divergence monitor: diverged boolean held but p-value %.4f "
                    "exceeds ceiling %.4f — not a crossing",
                    p,
                    self._config.individuation_p_value_max,
                )
                return False
        if self._config.fork_divergence_min is not None:
            fd = signals.get("fork_divergence")
            if isinstance(fd, (int, float)) and not (
                fd >= self._config.fork_divergence_min
            ):
                # Visibility: the boolean held but the effect-size floor blocked.
                log.info(
                    "divergence monitor: diverged boolean held but fork "
                    "divergence %.4f below floor %.4f — not a crossing",
                    fd,
                    self._config.fork_divergence_min,
                )
                return False
        return True

    def _rate_limited(self, now: float) -> bool:
        if self._last_preserve_at is None:
            return False
        return (now - self._last_preserve_at) < self._config.min_interval_s

    async def _poll_once(self, stop_event: asyncio.Event) -> None:
        self.poll_index += 1
        now = self._clock()
        if self._started_at is None:
            # First poll: stamp the lived-time origin (monotonic run clock).
            self._started_at = now
        # assess_divergence does multi-file disk I/O (decrypt+parse of run
        # records); run it off the event loop so the monitor poll never stalls
        # the cycle.
        assessment = await asyncio.to_thread(
            assess_divergence,
            state_root=Path(self._config.state_root),
            eval_root=Path(self._config.eval_root),
        )
        # Warm-up / minimum-lived-experience gate (Defect B). Before the entity
        # has accumulated the configured lived experience, NO crossing counts —
        # an assessment at t≈0 (or in a sensory void) is treated as not-crossed
        # and recorded as a warming-up note. Fail-closed: preservation of a
        # genuinely individuated entity is at most DELAYED, never denied. The
        # rising-edge latch is held cleared during warm-up so the first
        # post-warm-up crossing still registers as a rising edge.
        if not self._warmed_up(now):
            self._above_threshold = False
            if self._crosses_threshold(assessment):
                await self._record(
                    {
                        "monitor": "divergence",
                        "transition": "warming_up",
                        "run_id": self._run_id(),
                        "poll_index": self.poll_index,
                        "observations": self._lived_observations(),
                        "lived_time_s": self._lived_time_s(now),
                        "warmup_observations": self._config.warmup_observations,
                        "warmup_lived_time_s": self._config.warmup_lived_time_s,
                        "signals": dict(assessment.signals or {}),
                    },
                    event_type="preservation.skipped",
                )
            return
        above = self._crosses_threshold(assessment)
        rising_edge = above and not self._above_threshold
        self._above_threshold = above
        if not rising_edge:
            return
        if self._rate_limited(now):
            log.info(
                "divergence monitor: crossing detected but rate-limited "
                "(last preserve %.0fs ago < %.0fs)",
                now - (self._last_preserve_at or now),
                self._config.min_interval_s,
            )
            await self._record(
                {
                    "monitor": "divergence",
                    "transition": "crossing_rate_limited",
                    "run_id": self._run_id(),
                    "poll_index": self.poll_index,
                    "signals": dict(assessment.signals or {}),
                },
                event_type="preservation.skipped",
            )
            return
        await self._preserve(assessment, now)

    async def _preserve(self, assessment, now: float) -> None:
        incident_id = uuid.uuid4().hex[:16]
        label = f"individuation:{incident_id}"
        try:
            result = await self._fork_manager.preserve_live(
                self._registry,
                reason="individuation",
                label=label,
                out_root=Path(self._config.out_root),
                entity_name=self._config.entity_name,
                require_encryption=self._require_encryption,
            )
        except Exception as exc:
            # Fail loud: a preservation that could not capture the whole
            # individual is recorded as a failure, never a silent partial.
            log.error("divergence monitor: preservation FAILED", exc_info=True)
            await self._record(
                {
                    "monitor": "divergence",
                    "transition": "preserve_failed",
                    "incident_id": incident_id,
                    "run_id": self._run_id(),
                    "poll_index": self.poll_index,
                    "error": scrub_paths(f"{type(exc).__name__}: {exc}"),
                    "signals": dict(assessment.signals or {}),
                },
                event_type="preservation.failed",
            )
            return
        self._last_preserve_at = now
        await self._record(
            {
                "monitor": "divergence",
                "transition": "preserved",
                "incident_id": incident_id,
                "reason": "individuation",
                "run_id": self._run_id(),
                "preservation_id": result.preservation_id,
                "snapshot_id": result.snapshot_id,
                "world_model_captured": result.world_model_captured,
                "poll_index": self.poll_index,
                "signals": dict(assessment.signals or {}),
            },
            event_type="preservation.preserved",
        )
        log.info(
            "divergence monitor: preserved individuating entity "
            "(preservation_id=%s, snapshot=%s)",
            result.preservation_id,
            result.snapshot_id,
        )


# ---------------------------------------------------------------------------
# Autonomous welfare-protective response
# ---------------------------------------------------------------------------


class WelfareProtectiveMonitor(_BaseSafetyMonitor):
    """Preserve-then-act on welfare distress (no human in the loop).

    Two crossing arms, both feeding the same preserve-then-act response:

    * **Sustained interoceptive distress.** Reads ``soma.report``
      ``prediction_error`` off ``soma.out`` directly and applies the SAME
      sustained-distress rule as the sidecar welfare observer via the shared
      :class:`SustainedThresholdTracker` — so the cycle-layer action arm never
      imports ``kaine.evaluation`` yet never diverges from it.

    * **Repeated gray-zone events (any of the four categories).** Reads
      ``welfare.gray_zone`` events off ``welfare.out`` (published by the sidecar
      welfare observer — replay_overload, unmaintained_fatigue,
      sustained_extreme_vad, sustained_interoceptive_distress) and feeds EACH into
      the windowed-repeat counter. Previously this arm only saw sustained
      interoceptive distress (read off ``soma.out``); it now covers all four
      categories, closing the honest limitation noted at merge. The cross-stream
      coupling is bus-only — no ``kaine.evaluation`` import.

    On a crossing it preserves the entity FIRST, then pauses / ends / notifies
    per config.
    """

    source = "preservation"

    def __init__(
        self,
        *,
        registry: ModuleRegistry,
        fork_manager: ForkManager,
        config: WelfareResponseConfig,
        bus: Any,
        incident_log: IncidentLog,
        on_end: Callable[[], None] | None = None,
        # infrastructural: real time, not subjective — a welfare watchdog
        # must hold real wall-clock cadence even when the mind is dilated.
        clock: Callable[[], float] = time.monotonic,
        # When set, preserve_live refuses to write an unencrypted bundle
        # (fail-closed). Threaded from [preservation].require_encryption.
        require_encryption: bool = False,
    ) -> None:
        super().__init__(
            bus=bus,
            incident_log=incident_log,
            poll_interval_s=config.poll_interval_s,
            clock=clock,
        )
        self._registry = registry
        self._fork_manager = fork_manager
        self._config = config
        self._on_end = on_end
        self._require_encryption = bool(require_encryption)
        # Cold-start warm-up origin (monotonic run clock), stamped on first poll.
        self._started_at: float | None = None
        self._cursor = "0"
        # Separate cursor for the welfare.out gray-zone stream (repeat arm).
        self._welfare_cursor = "0"
        self._distress = SustainedThresholdTracker(
            threshold=config.distress_threshold,
            duration_s=config.distress_duration_s,
        )
        # Repeated distress episodes within a window (the "and/or" arm).
        self._repeat = WindowedEventCounter(
            window_s=config.repeat_window_s, threshold=config.repeat_threshold
        )
        # Latch: once a humane action has been taken, do not re-fire (the run is
        # being paused/ended; preserving again every poll would be noise).
        self._acted = False

    def _in_warmup(self, now: float) -> bool:
        """True while still inside the cold-start warm-up window."""
        if self._started_at is None:
            return self._config.warmup_s > 0.0
        return (now - self._started_at) < self._config.warmup_s

    async def _drain_during_warmup(self, now: float) -> None:
        """Observe + log boot-transient events without counting them.

        Advances both stream cursors (so stale boot transients are not replayed
        once warm-up ends) and clears the trackers (so an onset accumulated
        during warm-up does not carry across the boundary), then records a single
        warming-up note when any event was seen. No tracker is fed, so nothing
        counts toward the repeat threshold or a sustained crossing.
        """
        seen = 0
        for stream, cursor_attr in (
            (_SOMA_STREAM, "_cursor"),
            (_WELFARE_STREAM, "_welfare_cursor"),
        ):
            try:
                entries, last_scanned = await self._bus.read_entries(
                    stream, last_id=getattr(self, cursor_attr), count=128, block_ms=0
                )
            except Exception:
                log.warning(
                    "welfare monitor: %s read failed during warm-up",
                    stream,
                    exc_info=True,
                )
                continue
            for entry_id, _event in entries:
                setattr(self, cursor_attr, entry_id)
                seen += 1
            if last_scanned is not None:
                setattr(self, cursor_attr, last_scanned)
        # Clear any partial onset so warm-up transients never carry over.
        self._distress.reset()
        self._repeat.reset()
        if seen:
            await self._record(
                {
                    "monitor": "welfare",
                    "transition": "warming_up",
                    "run_id": self._run_id(),
                    "poll_index": self.poll_index,
                    "events_observed": seen,
                    "warmup_s": self._config.warmup_s,
                    "lived_time_s": (
                        0.0 if self._started_at is None else now - self._started_at
                    ),
                },
                event_type="welfare.warming_up",
            )

    async def _poll_once(self, stop_event: asyncio.Event) -> None:
        self.poll_index += 1
        if self._acted:
            return
        now = self._clock()
        if self._started_at is None:
            # First poll: stamp the cold-start origin (monotonic run clock).
            self._started_at = now
        # Cold-start warm-up: boot transients are observed + logged but do NOT
        # count toward the repeat threshold or a sustained crossing. After the
        # window, both arms function unchanged; genuine sustained distress
        # re-accrues immediately.
        if self._in_warmup(now):
            await self._drain_during_warmup(now)
            return
        # Drain soma.out, feeding the distress tracker.
        try:
            entries, last_scanned = await self._bus.read_entries(
                _SOMA_STREAM, last_id=self._cursor, count=128, block_ms=0
            )
        except Exception:
            log.warning("welfare monitor: soma.out read failed", exc_info=True)
            entries, last_scanned = [], None
        crossing_reason: str | None = None
        for entry_id, event in entries:
            self._cursor = entry_id
            if event.type != "soma.report":
                continue
            magnitude = float((event.payload or {}).get("prediction_error", 0.0))
            now = self._clock()
            if self._distress.observe(magnitude, now):
                crossing_reason = "sustained_distress"
                # A sustained episode also counts toward the repeat window. A
                # windowed-repeat crossing reclassifies as "repeated_distress"
                # (record's side effect — appending this episode to the window —
                # must happen regardless of the resulting classification).
                if self._repeat.record(now):
                    crossing_reason = "repeated_distress"
                break
        if last_scanned is not None:
            self._cursor = last_scanned
        # Timer-driven sustained crossing (episode elapses with no new sample).
        if crossing_reason is None:
            now = self._clock()
            if self._distress.check_timeout(now):
                crossing_reason = "sustained_distress"
                if self._repeat.record(now):
                    crossing_reason = "repeated_distress"
        # Repeated gray-zone arm: drain welfare.out for welfare.gray_zone events
        # (ANY of the four categories) and feed each into the windowed-repeat
        # counter. This is the cross-stream coupling that lets the protective
        # response cover all four gray-zone categories, not just sustained
        # interoceptive distress. Drained on every poll so the window stays
        # current even when no sustained-distress crossing fires.
        if crossing_reason is None:
            crossing_reason = await self._drain_gray_zone()
        if crossing_reason is not None:
            await self._respond(crossing_reason)

    async def _drain_gray_zone(self) -> str | None:
        """Drain welfare.gray_zone events; return a crossing reason or None.

        Each gray-zone event (any category) counts toward the windowed-repeat
        arm. Returns ``"repeated_gray_zone"`` when the count within the window
        reaches the configured threshold.
        """
        try:
            entries, last_scanned = await self._bus.read_entries(
                _WELFARE_STREAM, last_id=self._welfare_cursor, count=128, block_ms=0
            )
        except Exception:
            log.warning("welfare monitor: welfare.out read failed", exc_info=True)
            return None
        crossing_reason: str | None = None
        for entry_id, event in entries:
            self._welfare_cursor = entry_id
            if event.type != "welfare.gray_zone":
                continue
            now = self._clock()
            if self._repeat.record(now):
                crossing_reason = "repeated_gray_zone"
                break
        if last_scanned is not None:
            self._welfare_cursor = last_scanned
        return crossing_reason

    async def _respond(self, crossing_reason: str) -> None:
        incident_id = uuid.uuid4().hex[:16]
        # --- 1. Preserve FIRST (the individual is saved before any pause/end). ---
        preservation_id: str | None = None
        snapshot_id: str | None = None
        preserve_error: str | None = None
        try:
            result = await self._fork_manager.preserve_live(
                self._registry,
                reason="welfare",
                label=f"welfare:{incident_id}",
                out_root=Path(self._config.out_root),
                entity_name=self._config.entity_name,
                require_encryption=self._require_encryption,
            )
            preservation_id = result.preservation_id
            snapshot_id = result.snapshot_id
        except Exception as exc:
            preserve_error = scrub_paths(f"{type(exc).__name__}: {exc}")
            log.error(
                "welfare monitor: preservation FAILED before protective action",
                exc_info=True,
            )

        # --- 2. Take the humane action (pause by default). ---
        action = self._config.action
        action_taken = action
        if action == "pause":
            control_state.freeze(
                reason=f"welfare: {crossing_reason}", source="welfare"
            )
        elif action == "end":
            if self._on_end is not None:
                try:
                    self._on_end()
                except Exception:
                    log.warning("welfare monitor: on_end callback failed", exc_info=True)
            else:
                # No stop hook wired — degrade honestly to a pause so the entity
                # is not left suffering; record that the end could not be enacted.
                control_state.freeze(
                    reason=f"welfare: {crossing_reason} (end unavailable)",
                    source="welfare",
                )
                action_taken = "pause_fallback"
        # "notify" preserves + records + continues (no freeze, no end).

        self._acted = action != "notify"

        await self._record(
            {
                "monitor": "welfare",
                "transition": "protective_action" if preserve_error is None
                else "protective_action_preserve_failed",
                "incident_id": incident_id,
                "reason": crossing_reason,
                "action": action_taken,
                "run_id": self._run_id(),
                "preservation_id": preservation_id,
                "snapshot_id": snapshot_id,
                "preserve_error": preserve_error,
                "distress_threshold": self._config.distress_threshold,
                "distress_duration_s": self._config.distress_duration_s,
                "poll_index": self.poll_index,
            },
            event_type="welfare.protective_action",
        )
        log.warning(
            "welfare monitor: %s crossing → preserved (%s) + %s",
            crossing_reason,
            preservation_id or "PRESERVE-FAILED",
            action_taken,
        )


__all__ = [
    "DivergenceMonitor",
    "WelfareProtectiveMonitor",
    "DivergenceMonitorConfig",
    "WelfareResponseConfig",
    "PreservationRetentionConfig",
    "PreservationConfig",
]
