# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Autonomous welfare safety-net monitors (cycle-layer, siblings to the supervisor).

The research phase runs unsupervised. With no human watching, the architecture's
own safeguards must *act*, not merely log. This module holds the two cycle-layer
monitors that carry that duty of care, constructed by ``cycle/__main__.py``
alongside the supervisor and the freeze-watch loop:

* :class:`DivergenceMonitor` — preserves the LIVE entity whenever the shared
  divergence verdict gains a new arm (individuation latch, voice
  distinctiveness, the self-model module's drift or adapters). The arm set is persisted, so a restart with
  unchanged evidence does not re-preserve. Read-only on the entity; never
  deletes; rate-limited.

* :class:`WelfareProtectiveMonitor` — watches the interoception module's interoceptive-distress
  signal (``interoception.report`` ``prediction_error`` on ``interoception.out``) and, on a
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
import json
import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from kaine import legacy_aliases
from kaine.boot.errors import ConfigurationError
from kaine.bus.schema import validate_event
from kaine.bus.streams import AFFECT_STREAM, SLEEP_STREAM
from kaine.config import require_known_keys
from kaine.cycle import control_state
from kaine.cycle.incident_log import IncidentLog, scrub_paths
from kaine.cycle.unfrozen_clock import UnfrozenClock
from kaine.experiment.run_context import get_run_context
from kaine.lifecycle.divergence import (
    VoicePaths,
    assess_divergence,
)
from kaine.lifecycle.manager import ForkManager
from kaine.lifecycle.welfare_indicators import (
    DEPRIVATION_INDICATORS,
    INDICATOR_NAMES,
    REST_FAILED_REASON,
    REST_FAILURES,
    UNAVAILABLE_REASON,
    Evaluation,
    IndicatorEvaluator,
    IndicatorParams,
    indicator_reason,
)
from kaine.lifecycle.welfare_signal import SustainedThresholdTracker, WindowedEventCounter
from kaine.modules.registry import ModuleRegistry
from kaine.state_io import write_json_atomic
from kaine.storage import resolve

log = logging.getLogger(__name__)


def _map_arms(arms: list[Any]) -> frozenset[str]:
    """Apply persisted aliases to stored divergence arm names."""
    return frozenset(legacy_aliases.map_stored_value(str(a)) for a in arms)

_MONITOR_OUT_SALIENCE = 0.5
_INTEROCEPTION_STREAM = "interoception.out"
_WELFARE_STREAM = "welfare.out"
# Most recent distress episodes remembered for counting each once.
_COUNTED_EPISODES_MAX = 256
# While a welfare freeze that could not be written is retried every poll, a
# still-failing retry is logged at error level at most once per this many
# seconds of wall time (the rest go to debug), so a full disk cannot flood the log.
_FREEZE_RETRY_LOG_INTERVAL_S = 60.0
# The indicator response reads the affect and sleep streams itself.
_AFFECT_STREAM = AFFECT_STREAM
_SLEEP_STREAM = SLEEP_STREAM
# Entries read per stream per poll, in batches of _INDICATOR_READ_COUNT.
_INDICATOR_READ_COUNT = 256
_INDICATOR_MAX_BATCHES = 16
# The sleep trigger of the welfare net's requested rest.
WELFARE_REST_TRIGGER = "welfare_rest"
# The event the monitor publishes on its own stream to request that rest.
WELFARE_REST_REQUEST_TYPE = "welfare.rest_request"
# The origin the sleep module answers a welfare rest request with.
WELFARE_REST_ORIGIN = "welfare"
# Used for the developmental completion bound when the sleep module cannot be read.
_DEFAULT_DEVELOPMENTAL_REST_S = 1410.0
# The awake clock (entity time minus frozen and asleep time) never runs
# backwards; reading it takes three clock reads, so successive readings can
# differ by microseconds of jitter while the cycle is frozen or asleep. A
# reading further than this behind the highest one seen is a clock fault.
_AWAKE_CLOCK_REGRESSION_TOLERANCE_S = 0.5
# The welfare monitor bounds its own bus calls. The shared bus client sets no
# socket timeout, so a half-open connection could hang one of the monitor's
# reads while the modules on other pool connections run on; bounded, the hang
# becomes a failed poll, which the cycle's liveness check escalates. Its reads
# never block (block_ms=0) and run on loopback Redis in milliseconds, so 5 s
# is far above a healthy read and well inside the 30 s liveness bound.
_WELFARE_BUS_TIMEOUT_S = 5.0


# Consecutive failed reads of one distress-arm stream (interoception.out or
# welfare.out) that a poll tolerates. One transient error (a reconnect) is
# logged and the stream is read again next poll; the third failure in a row
# fails the poll, so a bus that raises on every read cannot leave the distress
# arm blind while polls count as successful. Three matches the liveness
# check's three failed polls; at the 1 s poll interval the stream has then
# been unread for about 3 s, well inside one 30 s distress window.
_DISTRESS_READ_FAILURES_TO_FAIL_POLL = 3


class WelfareBusReadFailing(Exception):
    """A distress-arm stream could not be read on several polls in a row."""


class WelfareBusTimeout(Exception):
    """One of the welfare monitor's own bus calls did not answer in time.

    Never swallowed as an empty read: it fails the poll, so the cycle's
    liveness check on the welfare monitor sees it.
    """
# Indicator stages.
_STAGE_ARMED = "armed"
_STAGE_RESTING = "resting"
_STAGE_FRESH = "fresh"


@dataclass
class _RestRequest:
    """The indicator response's outstanding rest request."""

    request_id: str
    indicators: tuple[str, ...]
    requested_u: float
    started: bool = False
    standing: bool = False
    started_rest_u: float | None = None
    bound_s: float | None = None


@dataclass(frozen=True)
class _FreezeOutcome:
    """What placing the welfare freeze did.

    ``placed`` is False only when writing the freeze raised; ``error`` then
    carries the scrubbed error and ``exc`` the exception for logging.
    ``unreadable`` is True when the freeze call returned but the control file
    is corrupt, which already reads as a welfare freeze.
    """

    placed: bool
    unreadable: bool = False
    error: str | None = None
    exc: BaseException | None = None


@dataclass
class _PendingFreeze:
    """A protective response whose welfare freeze could not be written yet.

    Only the freeze is retried on later polls; the response's preservation
    bundle, record and caretaker notice were already made.
    """

    freeze_reason: str
    incident_id: str
    crossing_reason: str
    action: str
    attempts: int
    last_logged_at: float


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
    """``[preservation.divergence_monitor]`` — the shared-verdict→preserve trigger.

    Ships ``enabled = false`` (consistent with the all-off first-boot posture).
    The monitor preserves the entity when the shared verdict in
    ``kaine/lifecycle/divergence.py`` gains a divergence arm that was not yet
    observed (individuation latch, voice distinctiveness, self-model drift or
    adapters).
    ``min_interval_s`` rate-limits preservation so a single sustained crossing
    preserves once, not every poll. ``boot_settle_s`` delays the first real
    assessment so entity state can finish loading.
    """

    enabled: bool = False
    poll_interval_s: float = 300.0  # 5 minutes — slow cadence, not per-tick
    min_interval_s: float = 1800.0  # at most one preservation per 30 min
    boot_settle_s: float = 120.0  # wait for state to settle after boot
    state_root: str = "state"
    out_root: str = "backups"
    entity_name: str = "kaine"

    _RETIRED_KEYS = frozenset({
        "individuation_p_value_max",
        "fork_divergence_min",
        "warmup_observations",
        "warmup_lived_time_s",
        "eval_root",
    })

    @classmethod
    def from_section(cls, section: dict[str, Any]) -> "DivergenceMonitorConfig":
        retired = sorted(k for k in section if k in cls._RETIRED_KEYS)
        if retired:
            key = retired[0]
            raise ValueError(
                f"[preservation.divergence_monitor].{key} is retired: "
                "individuation evidence, warm-up and significance now come from "
                "[individuation] and the shared verdict in "
                "kaine/lifecycle/divergence.py"
            )

        allowed = {
            "enabled",
            "poll_interval_s",
            "min_interval_s",
            "boot_settle_s",
            "state_root",
            "out_root",
            "entity_name",
        }
        _check_section_keys(section, allowed, "[preservation.divergence_monitor]")

        return cls(
            enabled=bool(section.get("enabled", False)),
            poll_interval_s=float(section.get("poll_interval_s", 300.0)),
            min_interval_s=float(section.get("min_interval_s", 1800.0)),
            boot_settle_s=float(section.get("boot_settle_s", 120.0)),
            state_root=str(section.get("state_root", "state")),
            out_root=str(section.get("out_root", "backups")),
            entity_name=str(section.get("entity_name", "kaine")),
        )


def _indicator_number(
    section: dict[str, Any], key: str, default: float, *, low: float, high: float | None = None
) -> float:
    """Read one number of ``[preservation.welfare_response.indicators]`` and range-check it.

    The value must be finite, above ``low`` and, when given, at most ``high``.
    """
    raw = section.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(
            f"[preservation.welfare_response.indicators].{key} must be a number, got {raw!r}"
        )
    value = float(raw)
    if not math.isfinite(value) or value <= low or (high is not None and value > high):
        bound = f"({low}, {high}]" if high is not None else f"> {low}"
        raise ValueError(
            f"[preservation.welfare_response.indicators].{key} must be finite and {bound}, got {raw!r}"
        )
    return value


@dataclass(frozen=True)
class WelfareIndicatorConfig:
    """``[preservation.welfare_response.indicators]`` — the response to the A.4 indicators.

    Ships ``enabled = true``, so enabling the welfare response enables it. The
    bars are paper Table A1's provisional ``theta_wf`` and ``q_wf``; they are
    safety bars, not tuning knobs. The three bounds keep the rest stage and a
    silent affect stream from holding the response open: a rest that does not
    start within ``rest_start_timeout_s`` of unfrozen time, or does not
    complete within ``rest_complete_timeout_s`` (``developmental`` and
    ``matured``), escalates to preservation and the freeze, as do indicators
    that stay unavailable for ``unavailable_escalate_s`` of awake time.
    ``rest_complete_developmental_s = None`` means the sleep module's
    ``developmental_rest_s`` plus 300 s.
    """

    enabled: bool = True
    share_bar: float = 0.5
    posterior_bar: float = 0.95
    rest_start_timeout_s: float = 30.0
    rest_complete_developmental_s: float | None = None
    rest_complete_matured_s: float = 3600.0
    unavailable_escalate_s: float = 660.0

    #: Added to ``developmental_rest_s`` for the default developmental bound.
    DEVELOPMENTAL_MARGIN_S = 300.0

    @classmethod
    def from_section(cls, section: dict[str, Any]) -> "WelfareIndicatorConfig":
        if not isinstance(section, dict):
            raise ValueError("[preservation.welfare_response.indicators] must be a table")
        allowed = {
            "enabled",
            "share_bar",
            "posterior_bar",
            "rest_start_timeout_s",
            "rest_complete_timeout_s",
            "unavailable_escalate_s",
        }
        _check_section_keys(section, allowed, "[preservation.welfare_response.indicators]")
        enabled = section.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(
                "[preservation.welfare_response.indicators].enabled must be true or false"
            )
        complete = section.get("rest_complete_timeout_s", {})
        if not isinstance(complete, dict):
            raise ValueError(
                "[preservation.welfare_response.indicators].rest_complete_timeout_s must be "
                "a table with developmental and matured"
            )
        _check_section_keys(
            complete,
            {"developmental", "matured"},
            "[preservation.welfare_response.indicators].rest_complete_timeout_s",
        )
        developmental: float | None = None
        if "developmental" in complete:
            developmental = _indicator_number(
                complete, "developmental", 0.0, low=0.0
            )
        return cls(
            enabled=enabled,
            share_bar=_indicator_number(section, "share_bar", 0.5, low=0.0, high=1.0),
            posterior_bar=_indicator_number(section, "posterior_bar", 0.95, low=0.0, high=1.0),
            rest_start_timeout_s=_indicator_number(section, "rest_start_timeout_s", 30.0, low=0.0),
            rest_complete_developmental_s=developmental,
            rest_complete_matured_s=_indicator_number(complete, "matured", 3600.0, low=0.0),
            unavailable_escalate_s=_indicator_number(section, "unavailable_escalate_s", 660.0, low=0.0),
        )

    def non_default_settings(self) -> dict[str, Any]:
        """The bars and bounds that differ from the shipped defaults, by key."""
        default = type(self)()
        out: dict[str, Any] = {}
        for key in (
            "share_bar",
            "posterior_bar",
            "rest_start_timeout_s",
            "rest_complete_developmental_s",
            "rest_complete_matured_s",
            "unavailable_escalate_s",
        ):
            if getattr(self, key) != getattr(default, key):
                out[key] = getattr(self, key)
        return out

    def rest_complete_bound(self, *, developing: bool, developmental_rest_s: float) -> float:
        """The completion bound for a rest, in unfrozen seconds."""
        if not developing:
            return self.rest_complete_matured_s
        if self.rest_complete_developmental_s is not None:
            return self.rest_complete_developmental_s
        return float(developmental_rest_s) + self.DEVELOPMENTAL_MARGIN_S


@dataclass
class WelfareResponseConfig:
    """``[preservation.welfare_response]`` — the autonomous protective action.

    Ships ``enabled = false``. On a sustained-distress crossing (or repeated
    distress episodes within ``repeat_window_s``) the monitor takes ``action``:
    ``"pause"`` (default — preserve then freeze the cycle, resumable),
    ``"end"`` (preserve then signal the run to stop), or ``"notify"`` (preserve,
    record a flagged event, and continue). ``indicators`` configures the
    response to the A.4 welfare indicators (a rest first, then preservation
    and the freeze on a crossing over a fresh span).
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
    # Ceiling on how long ``interoception.report.warmup_active`` may extend the gating
    # past ``warmup_s`` — MUST exceed the interoception module's own developmental warm-up
    # (``regulation_warmup_min_seconds`` = 1200s), with margin. Bounds trust in
    # a single external flag: if it is ever stuck True (an interoception module bug, or the interoception module
    # going silent right after a True report), the distress net re-arms here
    # rather than staying blind for the whole run.
    warmup_ceiling_s: float = 1800.0
    # M3 — rate limit for the ``notify`` action only: notify continues the run,
    # so a sustained-distress loop would otherwise preserve a full encrypted
    # bundle per distress window until the disk fills. Same mechanism and
    # default as the divergence monitor's ``min_interval_s``.
    min_interval_s: float = 1800.0
    out_root: str = "backups"
    entity_name: str = "kaine"
    # The legacy duplicate sustained-distress keys the operator set in this
    # table. The canonical source is ``[evaluation.welfare]``; see
    # :meth:`adopt_sustained_distress`.
    legacy_distress_keys: frozenset[str] = frozenset()
    indicators: WelfareIndicatorConfig = field(default_factory=WelfareIndicatorConfig)

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
            "warmup_ceiling_s",
            "min_interval_s",
            "out_root",
            "entity_name",
            "indicators",
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
            warmup_ceiling_s=float(section.get("warmup_ceiling_s", 1800.0)),
            min_interval_s=float(section.get("min_interval_s", 1800.0)),
            out_root=str(section.get("out_root", "backups")),
            entity_name=str(section.get("entity_name", "kaine")),
            legacy_distress_keys=frozenset(
                key
                for key in ("distress_threshold", "distress_duration_s")
                if key in section
            ),
            indicators=WelfareIndicatorConfig.from_section(section.get("indicators") or {}),
        )

    def adopt_sustained_distress(self, threshold: float, duration_s: float) -> None:
        """Take the sustained-distress parameters from ``[evaluation.welfare]``.

        The sidecar welfare observer and this monitor detect the same
        sustained distress, so they read one source:
        ``[evaluation.welfare].interoceptive_distress_threshold`` and
        ``interoceptive_distress_duration_s``. The old keys in this table are
        still accepted. A key that agrees with the canonical value logs a
        warning; a key that disagrees raises ``ConfigurationError`` while the
        response is enabled (a disabled response never acts on the value).
        """
        canonical = {
            "distress_threshold": (
                float(threshold),
                "interoceptive_distress_threshold",
            ),
            "distress_duration_s": (
                float(duration_s),
                "interoceptive_distress_duration_s",
            ),
        }
        for key in sorted(self.legacy_distress_keys):
            value, canonical_key = canonical[key]
            if float(getattr(self, key)) != value and self.enabled:
                raise ConfigurationError(
                    f"[preservation.welfare_response].{key} = {getattr(self, key)} "
                    f"disagrees with [evaluation.welfare].{canonical_key} = {value}. "
                    f"Both detectors read [evaluation.welfare].{canonical_key}; "
                    f"remove [preservation.welfare_response].{key}."
                )
            log.warning(
                "[preservation.welfare_response].%s is deprecated; both detectors "
                "now read [evaluation.welfare].%s. Remove it.",
                key,
                canonical_key,
            )
        self.distress_threshold = float(threshold)
        self.distress_duration_s = float(duration_s)


@dataclass
class PreservationRetentionConfig:
    """``[preservation.retention]`` — preservation-bundle retention policy.

    A preserved individual MUST NOT be silently auto-evicted (fork snapshots
    are never evicted either). ``auto_evict`` ships ``false`` and there is
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
        # Liveness of the poll loop, read by the cycle's run loop: consecutive
        # polls that raised, and the clock time of the last poll that returned.
        self.poll_failures = 0
        self.loop_started_at: float | None = None
        self.last_poll_ok_at: float | None = None

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

    #: Consecutive raising polls before the loop can count as failing.
    POLL_FAILURES_TO_ESCALATE = 3

    def poll_loop_failing(self, bound_s: float) -> bool:
        """True when the poll loop keeps raising: at least
        ``POLL_FAILURES_TO_ESCALATE`` polls in a row raised and no poll has
        returned for ``bound_s`` of this monitor's clock."""
        if self.poll_failures < self.POLL_FAILURES_TO_ESCALATE:
            return False
        since = self.last_poll_ok_at if self.last_poll_ok_at is not None else self.loop_started_at
        if since is None:
            return False
        return self._clock() - since >= float(bound_s)

    async def run(self, stop_event: asyncio.Event) -> None:
        try:
            await self._incident_log.start()
        except Exception:
            log.warning("%s incident log failed to start", self.source, exc_info=True)
        self.loop_started_at = self._clock()
        try:
            while not stop_event.is_set():
                try:
                    await self._poll_once(stop_event)
                except Exception:
                    # A safety monitor must not die silently; log loudly and keep
                    # going. A poll loop that keeps raising is seen by
                    # poll_loop_failing(), and the cycle's run loop escalates
                    # it in research and unattended mode.
                    self.poll_failures += 1
                    log.error("%s poll crashed; continuing", self.source, exc_info=True)
                else:
                    self.poll_failures = 0
                    self.last_poll_ok_at = self._clock()
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


def _active_arms(assessment) -> frozenset[str]:
    """Return the set of divergence arms that are active in `assessment`."""
    arms: set[str] = set()
    signals = assessment.signals or {}
    if signals.get("individuation_individuated"):
        arms.add("individuation")
    if signals.get("self_model_drift_signal"):
        arms.add("self_model_drift")
    if signals.get("sleep_adapters_present"):
        arms.add("adapters")
    if signals.get("voice_vote") == "diverged":
        arms.add("voice")
    if assessment.diverged and not arms:
        return frozenset({"diverged"})
    return frozenset(arms)


class DivergenceMonitor(_BaseSafetyMonitor):
    """Preserve the live individual on a rising edge of a divergence arm."""

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
        # When set, preserve_live refuses to write an unencrypted bundle
        # (fail-closed). Threaded from [preservation].require_encryption.
        require_encryption: bool = False,
        distinctiveness_threshold: float = 0.0,
        voice_paths: VoicePaths | None = None,
        adapter_output_dir: Path | None = None,
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
        self._distinctiveness_threshold = float(distinctiveness_threshold)
        self._voice_paths = voice_paths
        self._adapter_output_dir = adapter_output_dir
        # Boot settle: no assessment until boot_settle_s after construction,
        # so state loading can finish.
        self._started_at: float = self._clock()
        # Persisted rising-edge state: the last observed arm set.
        self._last_arms: frozenset[str] | None = None
        self._edge_path = (
            resolve(self._config.state_root) / "preservation" / "divergence_edge.json"
        )
        # Rate limit: monotonic time of the last preservation attempt (None = never).
        self._last_preserve_at: float | None = None

    def _load_edge_arms(self) -> frozenset[str]:
        """Load the persisted arm set, or an empty set on any error."""
        try:
            if not self._edge_path.is_file():
                return frozenset()
            data = json.loads(self._edge_path.read_text(encoding="utf-8"))
            arms = data.get("arms", [])
            if not isinstance(arms, list):
                raise ValueError("arms is not a list")
            return _map_arms(arms)
        except Exception as exc:
            log.warning(
                "divergence monitor: edge state unreadable (%s); treating as empty",
                exc,
            )
            return frozenset()

    def _save_edge_arms(self, arms: frozenset[str]) -> None:
        payload = {
            "arms": sorted(arms),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            write_json_atomic(self._edge_path, payload)
        except OSError as exc:
            # The in-memory state still advances; at worst a restart
            # preserves once more, which errs toward protection.
            log.warning("divergence monitor: could not save edge state: %s", exc)

    def _rate_limited(self, now: float) -> bool:
        if self._last_preserve_at is None:
            return False
        return (now - self._last_preserve_at) < self._config.min_interval_s

    async def _poll_once(self, stop_event: asyncio.Event) -> None:
        self.poll_index += 1
        now = self._clock()
        if now - self._started_at < self._config.boot_settle_s:
            return
        if self._last_arms is None:
            self._last_arms = self._load_edge_arms()
        # assess_divergence does multi-file disk I/O (decrypt+parse of run
        # records); run it off the event loop so the monitor poll never stalls
        # the cycle.
        assessment = await asyncio.to_thread(
            assess_divergence,
            state_root=resolve(self._config.state_root),
            distinctiveness_threshold=self._distinctiveness_threshold,
            adapter_output_dir=self._adapter_output_dir,
            voice_paths=self._voice_paths,
        )
        arms = _active_arms(assessment)
        new_arms = arms - self._last_arms
        if not new_arms:
            if arms != self._last_arms:
                self._save_edge_arms(arms)
                self._last_arms = arms
            return
        if self._rate_limited(now):
            log.info(
                "divergence monitor: %s arm(s) detected but rate-limited "
                "(last preserve %.0fs ago < %.0fs)",
                sorted(new_arms),
                now - (self._last_preserve_at or now),
                self._config.min_interval_s,
            )
            await self._record(
                {
                    "monitor": "divergence",
                    "transition": "crossing_rate_limited",
                    "reason": "+".join(sorted(new_arms)),
                    "run_id": self._run_id(),
                    "poll_index": self.poll_index,
                    "signals": dict(assessment.signals or {}),
                    "new_arms": sorted(new_arms),
                },
                event_type="preservation.skipped",
            )
            return
        ok = await self._preserve(assessment, now, new_arms=new_arms)
        if ok:
            self._save_edge_arms(arms)
            self._last_arms = arms

    async def _preserve(
        self, assessment, now: float, *, new_arms: frozenset[str]
    ) -> bool:
        """Preserve the live entity; the reason names the new arms, sorted and joined with "+"."""
        incident_id = uuid.uuid4().hex[:16]
        reason = "+".join(sorted(new_arms)) if new_arms else "diverged"
        label = f"divergence:{incident_id}"
        try:
            result = await self._fork_manager.preserve_live(
                self._registry,
                reason=reason,
                label=label,
                out_root=resolve(self._config.out_root),
                entity_name=self._config.entity_name,
                require_encryption=self._require_encryption,
            )
        except Exception as exc:
            # Fail loud: a preservation that could not capture the whole
            # individual is recorded as a failure, never a silent partial.
            # A failed preservation must be retried at the next poll, so we do
            # not update _last_preserve_at here; only successes rate-limit.
            log.error("divergence monitor: preservation FAILED", exc_info=True)
            await self._record(
                {
                    "monitor": "divergence",
                    "transition": "preserve_failed",
                    "incident_id": incident_id,
                    "reason": reason,
                    "run_id": self._run_id(),
                    "poll_index": self.poll_index,
                    "error": scrub_paths(f"{type(exc).__name__}: {exc}"),
                    "signals": dict(assessment.signals or {}),
                    "arms": sorted(new_arms),
                },
                event_type="preservation.failed",
            )
            return False
        # Success: rate-limit subsequent preservation attempts.
        self._last_preserve_at = now
        await self._record(
            {
                "monitor": "divergence",
                "transition": "preserved",
                "incident_id": incident_id,
                "reason": reason,
                "run_id": self._run_id(),
                "preservation_id": result.preservation_id,
                "snapshot_id": result.snapshot_id,
                "world_model_captured": result.world_model_captured,
                "poll_index": self.poll_index,
                "signals": dict(assessment.signals or {}),
                "arms": sorted(new_arms),
            },
            event_type="preservation.preserved",
        )
        log.info(
            "divergence monitor: preserved diverging entity "
            "(arms=%s, preservation_id=%s, snapshot=%s)",
            reason,
            result.preservation_id,
            result.snapshot_id,
        )
        return True


# ---------------------------------------------------------------------------
# Autonomous welfare-protective response
# ---------------------------------------------------------------------------


class WelfareProtectiveMonitor(_BaseSafetyMonitor):
    """Preserve-then-act on welfare distress (no human in the loop).

    Two crossing arms, both feeding the same preserve-then-act response:

    * **Sustained interoceptive distress.** Reads ``interoception.report``
      ``prediction_error`` off ``interoception.out`` directly and applies the SAME
      sustained-distress rule as the sidecar welfare observer via the shared
      :class:`SustainedThresholdTracker` — so the cycle-layer action arm never
      imports ``kaine.evaluation`` yet never diverges from it.

    * **Repeated gray-zone events (any of the four categories).** Reads
      ``welfare.gray_zone`` events off ``welfare.out`` (published by the sidecar
      welfare observer — replay_overload, unmaintained_fatigue,
      sustained_extreme_vad, sustained_interoceptive_distress) and feeds EACH into
      the windowed-repeat counter. Previously this arm only saw sustained
      interoceptive distress (read off ``interoception.out``); it now covers all four
      categories, closing the honest limitation noted at merge. The cross-stream
      coupling is bus-only — no ``kaine.evaluation`` import.

    On a crossing it preserves the entity FIRST, then pauses / ends / notifies
    per config.

    Elapsed-time arms (sustained distress, the cold-start warm-up) count
    unfrozen time from :class:`UnfrozenClock`; the repeat window, poll cadence
    and rate limits stay on wall time.
    """

    #: The bound on each of this monitor's own bus calls; the constructor's
    #: ``bus_timeout_s`` overrides it per instance.
    _bus_timeout_s: float = _WELFARE_BUS_TIMEOUT_S
    #: Consecutive failed reads per distress-arm stream (class default so a
    #: monitor built without __init__ still counts).
    _distress_read_failures: dict[str, int] = {}


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
        # Called with the transition of every protective response record
        # ("protective_action", "protective_action_preserve_failed" or
        # "protective_action_freeze_failed"), and once more with
        # "protective_action_freeze_placed" when a freeze that could not be
        # written is finally placed, so an unattended or research run can tell
        # its caretaker whether the entity is paused. Never allowed to break
        # the response itself.
        on_response: Callable[[str], None] | None = None,
        # Clock that discounts time the cycle spends frozen. Time-based arms
        # (sustained distress, warm-up) use this; the repeat window stays on
        # wall time.
        unfrozen_clock: UnfrozenClock | None = None,
        # The A.4 indicator parameters (T_lp, Delta_stall, theta_E, P_Aff from
        # the affect section, the bars from [preservation.welfare_response.indicators]).
        # None takes the evaluator's defaults with the configured bars.
        indicator_params: IndicatorParams | None = None,
        # Awake entity seconds (frozen and asleep time excluded) for the
        # indicator spans. None counts the unfrozen clock, with sleep skipped
        # from the sleep module's events.
        awake_clock: Callable[[], float] | None = None,
        # The entity clock's time scale, for the rest bounds in entity time.
        entity_scale: Callable[[], float] | None = None,
        # True while the entity is in the developmental phase.
        is_developing: Callable[[], bool] | None = None,
        # Called with an indicator caretaker notice kind and the indicator
        # names (from the fixed table). Never allowed to break the response.
        on_notice: Callable[[str, tuple[str, ...]], None] | None = None,
        # Real time of day, the clock event timestamps are stamped with.
        wall_time: Callable[[], float] = time.time,
        # The bound on each of this monitor's own bus calls (see _WELFARE_BUS_TIMEOUT_S).
        bus_timeout_s: float = _WELFARE_BUS_TIMEOUT_S,
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
        self._on_response = on_response
        # The default unfrozen clock reads ``self._clock`` at call time, so it
        # always counts on the monitor's own time base.
        self._unfrozen = unfrozen_clock or UnfrozenClock.for_welfare(
            monotonic=lambda: self._clock()
        )
        self._diag_unknown_seen = 0
        # Cold-start warm-up origin: unfrozen run clock, plus wall clock for
        # the hard ceiling that prevents a freeze from extending warm-up forever.
        self._started_at: float | None = None
        self._started_at_wall: float | None = None
        self._cursor = "0"
        # Separate cursor for the welfare.out gray-zone stream (repeat arm).
        self._welfare_cursor = "0"
        # interoception-module-reported warm-up: the mind's own signal (warmup_active in the
        # latest interoception.report) that gating should continue even past the fixed
        # cold-start window.
        self._interoception_warmup_active = False
        self._distress = SustainedThresholdTracker(
            threshold=config.distress_threshold,
            duration_s=config.distress_duration_s,
        )
        # Repeated distress episodes within a window (the "and/or" arm).
        self._repeat = WindowedEventCounter(
            window_s=config.repeat_window_s, threshold=config.repeat_threshold
        )
        # One sustained-distress episode is seen by two detectors: this monitor's
        # own tracker and the welfare observer's, which publishes it as a
        # welfare.gray_zone event. An episode is identified by the event time of
        # its first at/above-threshold sample, which both detectors read from the
        # same interoception.report, and counts once toward the repeat window
        # whichever detector reports it first.
        self._distress_onset_ts: float | None = None
        self._counted_episodes: dict[float, None] = {}
        # Latch: once a humane action has been taken, do not re-fire (the run is
        # being paused/ended; preserving again every poll would be noise).
        self._acted = False
        # The latch is released again only when this monitor's own pause is
        # lifted (see _maybe_rearm). True while the freeze it placed, or found at
        # its first poll, is the reason for the latch.
        self._pause_placed = False
        # Set when a response's welfare freeze could not be written. The
        # response is latched (no second preservation for the episode) but the
        # pause is not placed; each later poll retries only the freeze.
        self._pending_freeze: _PendingFreeze | None = None
        self._holders_checked = False
        # Reads the freeze holders; None means unreadable.
        self._read_holders = control_state.read_holder_sources
        # M3: rate limit for "notify" responses — at most one notify bundle
        # per min_interval_s, so sustained distress does not fire one bundle
        # per distress cycle.
        self._last_notify_at = float("-inf")
        # --- The response to the A.4 welfare indicators. ---
        self._indicators_cfg = config.indicators
        self._indicators_on = bool(config.indicators.enabled)
        self._indicator_params = indicator_params or IndicatorParams(
            share_bar=config.indicators.share_bar,
            posterior_bar=config.indicators.posterior_bar,
        )
        self._awake_clock = awake_clock
        self._awake_high: float | None = None
        self._entity_scale = entity_scale
        self._is_developing = is_developing
        self._on_notice = on_notice
        self._wall_time = wall_time
        self._bus_timeout_s = float(bus_timeout_s)
        self._ind_eval = IndicatorEvaluator(self._indicator_params)
        self._ind_stage = _STAGE_ARMED
        self._ind_request: _RestRequest | None = None
        self._ind_affect_cursor: str | None = None
        self._ind_sleep_cursor: str | None = None
        # (wall time, awake time) at the previous indicator read.
        self._ind_prev: tuple[float, float] | None = None
        self._ind_unavailable_notified = False
        self._ind_error_since_u: float | None = None
        # Unfrozen entity seconds, for the rest bounds (unfrozen wall time
        # times the entity time scale).
        self._ind_rest_u = 0.0
        self._ind_rest_u_last: float | None = None
        # The boot's welfare exposure (welfare-exposure-report): per indicator
        # the largest value, the crossings, the rests requested and the freezes
        # placed, over the whole boot (this monitor is never restarted).
        self._exposure: dict[str, dict[str, Any]] = {
            name: {"max_value": None, "crossings": 0, "rests_requested": 0, "freezes_placed": 0}
            for name in INDICATOR_NAMES
        }
        self._exposure_rests = 0
        self._exposure_freezes = 0
        self._exposure_responses: dict[str, int] = {}
        # The spans' awake seconds converted to wall seconds, the unit the
        # producer's tally counts in, so the exposure coverage check compares
        # like with like under time dilation. None once a conversion failed.
        self._ind_pos_seen = 0.0
        self._ind_awake_wall: float | None = 0.0
        # Indicator polls (and warm-up accruals) that raised: while one fails
        # the arm counts nothing, so the record cannot show the boot was watched.
        self._exposure_poll_failures = 0

    def _in_warmup(self, u_now: float, wall_now: float) -> bool:
        """True while still inside the cold-start warm-up window.

        The floor is measured in unfrozen time so a freeze does not consume the
        warm-up, but the whole warm-up is bounded by wall time so a long freeze
        can never extend it past ``warmup_ceiling_s``.
        """
        if self._started_at is None or self._started_at_wall is None:
            return self._config.warmup_s > 0.0
        # Hard wall-time bound: a long freeze can never extend warm-up past
        # max(warmup_s, warmup_ceiling_s) of wall time, so it cannot blind the net.
        bound = max(self._config.warmup_s, self._config.warmup_ceiling_s)
        if (wall_now - self._started_at_wall) >= bound:
            return False
        return (u_now - self._started_at) < self._config.warmup_s

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
            (_INTEROCEPTION_STREAM, "_cursor"),
            (_WELFARE_STREAM, "_welfare_cursor"),
        ):
            try:
                entries, last_scanned = await self._bus_read(self._bus.read_entries(
                    stream, last_id=getattr(self, cursor_attr), count=128, block_ms=0
                ))
            except WelfareBusTimeout:
                raise
            except Exception:
                log.warning(
                    "welfare monitor: %s read failed during warm-up",
                    stream,
                    exc_info=True,
                )
                self._distress_read_failed(stream)
                continue
            self._distress_read_ok(stream)
            for entry_id, event in entries:
                setattr(self, cursor_attr, entry_id)
                if stream == _INTEROCEPTION_STREAM and event.type == "interoception.report":
                    # Track the mind's own warm-up signal from every
                    # interoception.report observed during warm-up.
                    self._interoception_warmup_active = bool(
                        (event.payload or {}).get("warmup_active", False)
                    )
                seen += 1
            if last_scanned is not None:
                setattr(self, cursor_attr, last_scanned)
        # Clear any partial onset so warm-up transients never carry over.
        self._distress.reset()
        self._repeat.reset()
        self._counted_episodes.clear()
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
        # Read the unfrozen clock first so an unreadable control state seen on
        # this poll is reported on this poll, not the next one.
        u_now = self._unfrozen.now()
        diag = self._unfrozen.diagnostic()
        if diag["unknown_episodes"] > self._diag_unknown_seen:
            try:
                await self._incident_log.write(
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "kind": "freeze_state_unreadable",
                        "unknown_counts_as": diag["unknown_counts_as"],
                        "unknown_episodes": diag["unknown_episodes"],
                        "run_id": self._run_id(),
                    }
                )
                # Marked seen only once written, so a failed write is retried.
                self._diag_unknown_seen = diag["unknown_episodes"]
            except Exception:
                log.warning("welfare monitor: incident log write failed", exc_info=True)
        if not self._holders_checked:
            self._holders_checked = True
            self._adopt_standing_welfare_freeze()
        if self._acted:
            if self._pending_freeze is not None:
                await self._retry_pending_freeze()
                return
            await self._maybe_rearm()
            return
        now = self._clock()
        if self._started_at is None:
            # First poll: stamp the cold-start origin on both clocks.
            self._started_at = u_now
            self._started_at_wall = now
        # Cold-start warm-up: boot transients are observed + logged but do NOT
        # count toward the repeat threshold or a sustained crossing. After the
        # window, both arms function unchanged; genuine sustained distress
        # re-accrues immediately.
        # Honor the interoception module's own warm-up flag past the fixed floor, but only up to
        # warmup_ceiling_s of wall time, so a stuck/stale flag or a long freeze
        # cannot blind the net forever. A ceiling of 0 means the flag never extends it.
        interoception_gate = (
            self._interoception_warmup_active
            and self._started_at_wall is not None
            and (now - self._started_at_wall) < self._config.warmup_ceiling_s
        )
        if self._in_warmup(u_now, now) or interoception_gate:
            await self._drain_during_warmup(u_now)
            # The indicator spans accrue during warm-up; no indicator response fires.
            if self._indicators_on:
                await self._indicator_accrue(u_now)
            return
        # A read that hangs or keeps failing fails this poll (for the liveness
        # check), but only after every crossing this poll can still find has
        # been answered: no later failure may discard an earlier crossing, and
        # the sustained-distress tracker fires once per episode, so a crossing
        # dropped here would wait a whole new episode or never be answered.
        deferred: Exception | None = None
        # Drain interoception.out, feeding the distress tracker.
        try:
            entries, last_scanned = await self._bus_read(self._bus.read_entries(
                _INTEROCEPTION_STREAM, last_id=self._cursor, count=128, block_ms=0
            ))
        except WelfareBusTimeout as exc:
            deferred = exc
            entries, last_scanned = [], None
        except Exception:
            log.warning("welfare monitor: interoception.out read failed", exc_info=True)
            entries, last_scanned = [], None
            try:
                self._distress_read_failed(_INTEROCEPTION_STREAM)
            except WelfareBusReadFailing as exc:
                deferred = exc
        else:
            self._distress_read_ok(_INTEROCEPTION_STREAM)
        reasons: list[str] = []
        for entry_id, event in entries:
            self._cursor = entry_id
            if event.type != "interoception.report":
                continue
            payload = event.payload or {}
            self._interoception_warmup_active = bool(payload.get("warmup_active", False))
            raw = payload.get("prediction_error", 0.0)
            if raw is None:
                # A reading the interoception module skipped as non-finite has no error: it is no sample,
                # so it neither feeds nor resets the distress episode.
                continue
            magnitude = float(raw)
            u_now = self._unfrozen.now()
            now = self._clock()
            if self._distress.active_since is None:
                self._distress_onset_ts = self._event_ts(event)
            if self._distress.observe(magnitude, u_now, wall_now=now):
                reason = "sustained_distress"
                # A sustained episode also counts toward the repeat window. A
                # windowed-repeat crossing reclassifies as "repeated_distress"
                # (record's side effect — appending this episode to the window —
                # must happen regardless of the resulting classification).
                if self._count_episode(self._distress_onset_ts, now):
                    reason = "repeated_distress"
                reasons.append(reason)
        if last_scanned is not None:
            self._cursor = last_scanned
        # Timer-driven sustained crossing (episode elapses with no new sample).
        if not reasons:
            u_now = self._unfrozen.now()
            now = self._clock()
            if self._distress.check_timeout(u_now):
                reason = "sustained_distress"
                if self._count_episode(self._distress_onset_ts, now):
                    reason = "repeated_distress"
                reasons.append(reason)
        # Repeated gray-zone arm: drain welfare.out for welfare.gray_zone events
        # (ANY of the four categories) and feed each into the windowed-repeat
        # counter. This is the cross-stream coupling that lets the protective
        # response cover all four gray-zone categories, not just sustained
        # interoceptive distress. Drained on every poll so the window stays
        # current even when no sustained-distress crossing fires.
        try:
            reasons.extend(await self._drain_gray_zone())
        except (WelfareBusTimeout, WelfareBusReadFailing) as exc:
            deferred = deferred or exc
        # Pause and end act once, so a second crossing in the same poll must
        # not preserve or freeze again; notify keeps its own rate limit.
        for reason in reasons:
            if self._acted:
                break
            await self._respond(reason)
        # The indicator arm shares the latch: it runs only while unlatched.
        if self._indicators_on and not self._acted:
            try:
                await self._indicator_poll(u_now)
            except WelfareBusTimeout as exc:
                deferred = deferred or exc
        if deferred is not None:
            raise deferred

    def _adopt_standing_welfare_freeze(self) -> None:
        """A welfare freeze left by an earlier process (a restart keeps it)
        latches this monitor as if it had placed the pause itself, so the same
        release re-arms it."""
        try:
            holders = self._read_holders()
        except Exception:
            holders = None
        if holders and "welfare" in holders:
            self._acted = True
            self._pause_placed = True
            log.warning("welfare monitor: a welfare freeze stands from before this start")

    async def _maybe_rearm(self) -> None:
        """Re-arm after the pause this monitor placed has been resolved.

        The rule, from the code's own state: the latch was set by a pause (a
        ``pause``, a ``pause_fallback``, or a welfare freeze found at the first
        poll), and the control file now readably holds no ``welfare`` entry,
        which only a named override (:func:`control_state.override`) removes. An
        enacted ``end`` never re-arms, because it placed no pause. An unreadable
        control file is not a release.

        Re-arming starts a new episode: the sustained-distress tracker and the
        repeat window are emptied and both stream cursors move to the stream
        tail, so neither the distress that caused the pause nor the events
        published while frozen can fire the response again. A condition that
        is still present must accrue a full new sustained duration of unfrozen
        time (or a full new repeat window) before it acts again, and the
        counted-episode memory is kept so one old episode is not counted twice.
        """
        if not self._pause_placed:
            return
        try:
            holders = self._read_holders()
        except Exception:
            holders = None
        if holders is None or "welfare" in holders:
            return
        try:
            interoception_tail = await self._bus_read(self._bus.last_entry_id(_INTEROCEPTION_STREAM))
            welfare_tail = await self._bus_read(self._bus.last_entry_id(_WELFARE_STREAM))
            if self._indicators_on:
                affect_tail = await self._bus_read(self._bus.last_entry_id(_AFFECT_STREAM))
                sleep_tail = await self._bus_read(self._bus.last_entry_id(_SLEEP_STREAM))
        except WelfareBusTimeout:
            raise
        except Exception:
            log.warning("welfare monitor: re-arm deferred, stream tail unreadable", exc_info=True)
            return
        self._cursor = interoception_tail
        self._welfare_cursor = welfare_tail
        if self._indicators_on:
            # Every span restarts and every crossing state resets: the next
            # crossing requests a rest before any freeze.
            self._ind_affect_cursor = affect_tail
            self._ind_sleep_cursor = sleep_tail
            self._indicator_reset(restart_span=True)
        self._distress = SustainedThresholdTracker(
            threshold=self._config.distress_threshold,
            duration_s=self._config.distress_duration_s,
        )
        self._distress_onset_ts = None
        self._repeat = WindowedEventCounter(
            window_s=self._config.repeat_window_s, threshold=self._config.repeat_threshold
        )
        self._acted = False
        self._pause_placed = False
        log.warning("welfare monitor: the welfare freeze was lifted; the response is re-armed")
        try:
            await self._record(
                {
                    "monitor": "welfare",
                    "transition": "rearmed",
                    "run_id": self._run_id(),
                    "poll_index": self.poll_index,
                },
                event_type="welfare.protective_action",
            )
        except Exception:
            log.warning("welfare monitor: re-arm record failed", exc_info=True)

    def _count_episode(self, onset_ts: float | None, now: float) -> bool:
        """Add one distress episode to the repeat window, once per episode.

        ``onset_ts`` identifies the episode. An episode already counted (by the
        other detector) adds nothing and cannot cross the repeat threshold. With
        no onset the report cannot be matched, so it counts as its own episode.
        Returns True when the repeat window crosses its threshold.
        """
        if onset_ts is not None:
            if onset_ts in self._counted_episodes:
                return False
            self._counted_episodes[onset_ts] = None
            # Bounded memory: only the most recent episodes can still be
            # reported by the other detector.
            while len(self._counted_episodes) > _COUNTED_EPISODES_MAX:
                del self._counted_episodes[next(iter(self._counted_episodes))]
        return self._repeat.record(now)

    @staticmethod
    def _event_ts(event: Any) -> float | None:
        ts = getattr(event, "timestamp", None)
        if ts is None:
            return None
        if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.timestamp()

    async def _drain_gray_zone(self) -> list[str]:
        """Drain welfare.gray_zone events; return all crossing reasons.

        Each gray-zone event (any category) counts toward the windowed-repeat
        arm. Returns a ``"repeated_gray_zone"`` entry for each crossing that
        occurs while draining the batch.
        """
        try:
            entries, last_scanned = await self._bus_read(self._bus.read_entries(
                _WELFARE_STREAM, last_id=self._welfare_cursor, count=128, block_ms=0
            ))
        except WelfareBusTimeout:
            raise
        except Exception:
            log.warning("welfare monitor: welfare.out read failed", exc_info=True)
            self._distress_read_failed(_WELFARE_STREAM)
            return []
        self._distress_read_ok(_WELFARE_STREAM)
        reasons: list[str] = []
        for entry_id, event in entries:
            self._welfare_cursor = entry_id
            if event.type != "welfare.gray_zone":
                continue
            now = self._clock()
            payload = event.payload or {}
            onset = None
            if payload.get("gray_zone_event") == "sustained_interoceptive_distress":
                raw_onset = payload.get("episode_onset_ts")
                if isinstance(raw_onset, (int, float)) and not isinstance(raw_onset, bool):
                    onset = float(raw_onset)
                crossed = self._count_episode(onset, now)
            else:
                crossed = self._repeat.record(now)
            if crossed:
                reasons.append("repeated_gray_zone")
        if last_scanned is not None:
            self._welfare_cursor = last_scanned
        return reasons

    @staticmethod
    def _place_welfare_freeze(reason: str) -> _FreezeOutcome:
        """Place the welfare freeze and report what happened; never raises.

        A corrupt control file already reads as a welfare freeze, so the pause
        counts as placed and the latch holds; the caller records the
        ``unreadable`` flag. When writing the freeze itself fails (the disk is
        full, or the control file or its lock file cannot be opened), the
        outcome is not placed and carries the error; the caller logs it and
        keeps the freeze pending.
        """
        try:
            control_state.freeze(reason=reason, source="welfare")
        except Exception as exc:
            return _FreezeOutcome(
                placed=False,
                error=scrub_paths(f"{type(exc).__name__}: {exc}"),
                exc=exc,
            )
        if control_state.control_file_unreadable():
            log.warning(
                "welfare monitor: control file is unreadable; "
                "the cycle is already treated as frozen"
            )
            return _FreezeOutcome(placed=True, unreadable=True)
        return _FreezeOutcome(placed=True)

    async def _retry_pending_freeze(self) -> None:
        """Retry only the welfare freeze of a response that could not write it.

        Nothing else of the response is repeated: no preservation and no record
        per failed attempt. A still-failing retry is logged at error level at
        most once per ``_FREEZE_RETRY_LOG_INTERVAL_S``. When the freeze is
        finally written, the pause counts as placed (so a named override
        re-arms the monitor), one record says so and the caretaker is told.

        Before each retry the freeze holders are read. A ``welfare`` holder
        already in place (a write that landed but reported failure) counts as
        the freeze placed: no second freeze is written, so a later override
        that lifts it is not undone. Unreadable holders fall through to the
        normal retry.
        """
        pending = self._pending_freeze
        if pending is None:
            return
        try:
            holders = self._read_holders()
        except Exception:
            holders = None
        if holders is not None and "welfare" in holders:
            log.warning(
                "welfare monitor: the welfare freeze is already in place after "
                "%d failed attempt(s); the entity is paused",
                pending.attempts,
            )
            await self._freeze_now_placed(
                pending, unreadable=False, found_in_place=True
            )
            return
        pending.attempts += 1
        outcome = self._place_welfare_freeze(pending.freeze_reason)
        if not outcome.placed:
            now = self._clock()
            if now - pending.last_logged_at >= _FREEZE_RETRY_LOG_INTERVAL_S:
                pending.last_logged_at = now
                log.error(
                    "welfare monitor: the welfare freeze still cannot be written "
                    "(attempt %d); the entity is NOT paused, retrying every poll",
                    pending.attempts,
                    exc_info=outcome.exc,
                )
            else:
                log.debug(
                    "welfare monitor: welfare freeze retry %d failed: %s",
                    pending.attempts,
                    outcome.error,
                )
            return
        log.warning(
            "welfare monitor: the welfare freeze was written on attempt %d; "
            "the entity is paused",
            pending.attempts,
        )
        await self._freeze_now_placed(
            pending, unreadable=outcome.unreadable, found_in_place=False
        )

    async def _freeze_now_placed(
        self, pending: _PendingFreeze, *, unreadable: bool, found_in_place: bool
    ) -> None:
        """Latch a pending freeze as a placed pause, record it once, tell the caretaker."""
        self._pending_freeze = None
        self._pause_placed = True
        await self._record(
            {
                "monitor": "welfare",
                "transition": "protective_action_freeze_placed",
                "incident_id": pending.incident_id,
                "reason": pending.crossing_reason,
                "action": pending.action,
                "run_id": self._run_id(),
                "freeze_attempts": pending.attempts,
                "freeze_error": None,
                "freeze_failed_unreadable": unreadable,
                "freeze_found_in_place": found_in_place,
                "poll_index": self.poll_index,
            },
            event_type="welfare.protective_action",
        )
        self._notify_response("protective_action_freeze_placed")

    def _notify_response(self, transition: str) -> None:
        """Tell ``on_response`` the record's transition; a failing callback is only logged."""
        if self._on_response is None:
            return
        try:
            self._on_response(transition)
        except Exception:
            log.warning("welfare monitor: on_response callback failed", exc_info=True)

    async def _respond(
        self,
        crossing_reason: str,
        *,
        indicators: tuple[str, ...] = (),
        stimulus_spent: bool = False,
        indicator_detail: dict[str, Any] | None = None,
    ) -> None:
        # M3 — "notify" continues the run, so sustained distress re-fires the
        # tracker every distress window; without a rate limit that is one full
        # encrypted preservation bundle per window (retention never-delete)
        # until the disk fills and preservation itself breaks. Pause/end act
        # once by construction and are never rate-limited.
        if self._config.action == "notify":
            now = time.monotonic()
            if not _welfare_notify_allowed(
                self._last_notify_at, now, self._config.min_interval_s
            ):
                log.info(
                    "welfare monitor: notify suppressed by min_interval_s rate limit"
                )
                return
            self._last_notify_at = now
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
                out_root=resolve(self._config.out_root),
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
        end_error: str | None = None
        freeze_reason: str | None = None
        if action == "pause":
            freeze_reason = f"welfare: {crossing_reason}"
        elif action == "end":
            if self._on_end is not None:
                try:
                    self._on_end()
                except Exception as exc:
                    # The stop hook failed, so the entity is still running.
                    # Degrade honestly to a pause, as with no hook wired, so it
                    # is not left suffering and the record does not claim an end.
                    end_error = scrub_paths(f"{type(exc).__name__}: {exc}")
                    log.error(
                        "welfare monitor: on_end callback failed; "
                        "falling back to the welfare pause",
                        exc_info=True,
                    )
                    freeze_reason = f"welfare: {crossing_reason} (end failed)"
                    action_taken = "pause_fallback"
            else:
                # No stop hook wired — degrade honestly to a pause so the entity
                # is not left suffering; record that the end could not be enacted.
                freeze_reason = f"welfare: {crossing_reason} (end unavailable)"
                action_taken = "pause_fallback"
        # "notify" preserves + records + continues (no freeze, no end).

        freeze_failed_unreadable = False
        freeze_error: str | None = None
        if freeze_reason is not None:
            outcome = self._place_welfare_freeze(freeze_reason)
            freeze_failed_unreadable = outcome.unreadable
            if not outcome.placed:
                # The freeze could not be written, so the entity is still
                # running. The response is latched (no second preservation for
                # this episode) but the pause is not placed: later polls retry
                # only the freeze until it is written.
                freeze_error = outcome.error
                self._pending_freeze = _PendingFreeze(
                    freeze_reason=freeze_reason,
                    incident_id=incident_id,
                    crossing_reason=crossing_reason,
                    action=action_taken,
                    attempts=1,
                    last_logged_at=self._clock(),
                )
                log.error(
                    "welfare monitor: the welfare freeze could not be written; "
                    "the entity is NOT paused, retrying every poll",
                    exc_info=outcome.exc,
                )

        self._acted = action != "notify"
        self._pause_placed = (
            action_taken in ("pause", "pause_fallback") and freeze_error is None
        )
        # Exposure: every protective response, by its reason label, and the
        # freezes it placed (or is retrying).
        self._exposure_responses[crossing_reason] = (
            self._exposure_responses.get(crossing_reason, 0) + 1
        )
        if action_taken in ("pause", "pause_fallback"):
            self._exposure_freezes += 1
            for name in indicators:
                if name in self._exposure:
                    self._exposure[name]["freezes_placed"] += 1

        if freeze_error is not None:
            transition = "protective_action_freeze_failed"
        elif preserve_error is not None:
            transition = "protective_action_preserve_failed"
        else:
            transition = "protective_action"
        await self._record(
            {
                "monitor": "welfare",
                "transition": transition,
                "incident_id": incident_id,
                "reason": crossing_reason,
                "action": action_taken,
                "run_id": self._run_id(),
                "preservation_id": preservation_id,
                "snapshot_id": snapshot_id,
                "preserve_error": preserve_error,
                "end_error": end_error,
                "freeze_error": freeze_error,
                "freeze_failed_unreadable": freeze_failed_unreadable,
                "distress_threshold": self._config.distress_threshold,
                "distress_duration_s": self._config.distress_duration_s,
                "poll_index": self.poll_index,
                **(indicator_detail or {}),
            },
            event_type="welfare.protective_action",
        )
        log.warning(
            "welfare monitor: %s crossing → preserved (%s) + %s",
            crossing_reason,
            preservation_id or "PRESERVE-FAILED",
            action_taken if freeze_error is None
            else f"{action_taken} (freeze FAILED, retrying)",
        )
        if indicator_detail is not None and self._on_notice is not None:
            # The indicator response's own notice: a freeze that could not be
            # written still says the entity is NOT paused.
            if transition == "protective_action_freeze_failed":
                kind = "welfare_freeze_failed"
            elif stimulus_spent:
                kind = "welfare_stimulus_spent"
            else:
                kind = "welfare_response"
            self._notify(kind, indicators)
        else:
            self._notify_response(transition)


    # ------------------------------------------------------------------
    # The response to the A.4 welfare indicators
    # ------------------------------------------------------------------
    #
    # Three stages share the distress arm's latch: ``armed`` (a first
    # crossing requests a rest), ``resting`` (wait for that rest; every way it
    # could hang escalates) and ``fresh`` (every span restarted at the rest's
    # end; a crossing brings preservation and the freeze). Nothing here
    # imports kaine.evaluation, and the rest request goes out on this
    # monitor's own stream, which the cycle never reads as a candidate.

    def _distress_read_ok(self, stream: str) -> None:
        if self._distress_read_failures.get(stream):
            self._distress_read_failures = {**self._distress_read_failures, stream: 0}

    def _distress_read_failed(self, stream: str) -> None:
        """Count a failed read of a distress-arm stream; fail the poll on the
        ``_DISTRESS_READ_FAILURES_TO_FAIL_POLL``-th in a row."""
        count = self._distress_read_failures.get(stream, 0) + 1
        self._distress_read_failures = {**self._distress_read_failures, stream: count}
        if count >= _DISTRESS_READ_FAILURES_TO_FAIL_POLL:
            raise WelfareBusReadFailing(
                f"welfare monitor: {stream} unreadable on {count} polls in a row"
            )

    async def _bus_read(self, awaitable: Any) -> Any:
        """Await one of this monitor's bus reads, bounded by ``bus_timeout_s``."""
        try:
            return await asyncio.wait_for(awaitable, timeout=self._bus_timeout_s)
        except asyncio.TimeoutError as exc:
            raise WelfareBusTimeout(
                f"welfare monitor: a bus read did not answer within {self._bus_timeout_s} s"
            ) from exc

    async def _publish(self, type_: str, payload: dict[str, Any]) -> None:
        """The base publish, bounded: a hung publish is logged and the poll goes on
        (the durable incident record is written separately)."""
        try:
            await asyncio.wait_for(super()._publish(type_, payload), timeout=self._bus_timeout_s)
        except asyncio.TimeoutError:
            log.error("welfare monitor: publish of %s did not answer in time", type_)

    def _notify(self, kind: str, indicators: tuple[str, ...]) -> None:
        """Tell ``on_notice`` an indicator notice; a failing callback is only logged."""
        if self._on_notice is None:
            return
        try:
            self._on_notice(kind, tuple(indicators))
        except Exception:
            log.warning("welfare monitor: on_notice callback failed", exc_info=True)

    def _awake_now(self, u_now: float) -> float:
        """Awake time for the spans: the injected awake clock, else unfrozen time.

        An awake clock that raises, reads non-finite or runs backwards raises
        here. It is never replaced by another clock: unfrozen time is in other
        units (wall seconds, sleep included), so a switch could leave every
        sample behind the evaluator's last one and freeze the spans and the
        silence count. The raise goes to the indicator arm's error path, which
        retries each poll and escalates as indicators unavailable once the
        fault lasts ``unavailable_escalate_s``.
        """
        if self._awake_clock is None:
            return u_now
        value = float(self._awake_clock())
        if not math.isfinite(value):
            raise ValueError(f"welfare monitor: the awake clock read {value!r}")
        high = self._awake_high
        if high is not None and value < high:
            if high - value > _AWAKE_CLOCK_REGRESSION_TOLERANCE_S:
                raise ValueError(
                    f"welfare monitor: the awake clock ran back {high - value:.3f} s"
                )
            return high  # read jitter while frozen or asleep
        self._awake_high = value
        return value

    def _scale_now(self) -> float:
        """The entity's time scale, for the rest bound counted in entity seconds.

        Without an entity clock (``entity_scale`` not given) the bound runs on
        unfrozen time at scale 1. A scale that raises, reads non-finite or
        reads below zero raises here, never a guess: a guessed scale would
        stretch or shrink a welfare bound. The raise goes to the indicator
        arm's error path, which escalates as indicators unavailable once the
        fault lasts ``unavailable_escalate_s``.
        """
        if self._entity_scale is None:
            return 1.0
        value = float(self._entity_scale())
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(f"welfare monitor: the time scale read {value!r}")
        return value

    def _developing(self) -> bool:
        """The developmental phase; a failing probe counts as developing (the shorter bound)."""
        if self._is_developing is None:
            return False
        try:
            return bool(self._is_developing())
        except Exception:
            return True

    def _sleep_module(self) -> Any | None:
        try:
            if "sleep" not in self._registry:
                return None
            return self._registry.get("sleep")
        except Exception:
            return None

    def _sleep_module_ready(self) -> bool:
        """True when a running sleep module listens for welfare rest requests."""
        module = self._sleep_module()
        if module is None:
            return False
        probe = getattr(module, "welfare_rest_ready", None)
        if not callable(probe):
            return False
        try:
            return bool(probe())
        except Exception:
            return False

    def _developmental_rest_s(self) -> float:
        module = self._sleep_module()
        value = getattr(module, "developmental_rest_s", None) if module is not None else None
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0:
            return float(value)
        return _DEFAULT_DEVELOPMENTAL_REST_S

    def _indicator_reset(self, *, restart_span: bool) -> None:
        """Back to ``armed``: no request outstanding, crossing states reset."""
        if restart_span:
            self._ind_eval.restart()
        self._ind_stage = _STAGE_ARMED
        self._ind_request = None
        self._ind_unavailable_notified = False
        self._ind_error_since_u = None
        self._ind_prev = None

    def _indicator_tick_rest_clock(self, u_now: float) -> None:
        if self._ind_rest_u_last is not None:
            self._ind_rest_u += max(0.0, u_now - self._ind_rest_u_last) * self._scale_now()
        self._ind_rest_u_last = u_now

    async def _indicator_seed_cursors(self) -> bool:
        """Start reading the affect and sleep streams at their tails (this run only)."""
        if self._ind_affect_cursor is not None and self._ind_sleep_cursor is not None:
            return True
        try:
            affect_tail = await self._bus_read(self._bus.last_entry_id(_AFFECT_STREAM))
            sleep_tail = await self._bus_read(self._bus.last_entry_id(_SLEEP_STREAM))
        except WelfareBusTimeout:
            raise
        except Exception:
            log.warning("welfare monitor: indicator stream tails unreadable; retrying", exc_info=True)
            return False
        self._ind_affect_cursor = affect_tail
        self._ind_sleep_cursor = sleep_tail
        return True

    async def _indicator_read(self, stream: str, cursor: str) -> tuple[list[tuple[str, Any]], str]:
        entries_out: list[tuple[str, Any]] = []
        for _ in range(_INDICATOR_MAX_BATCHES):
            entries, last_scanned = await self._bus_read(self._bus.read_entries(
                stream, last_id=cursor, count=_INDICATOR_READ_COUNT, block_ms=0
            ))
            for entry_id, event in entries:
                entries_out.append((entry_id, event))
                cursor = entry_id
            if last_scanned is not None:
                cursor = last_scanned
            if len(entries) < _INDICATOR_READ_COUNT:
                break
        return entries_out, cursor

    async def _indicator_ingest(self, u_now: float) -> list[tuple[str, dict[str, Any]]]:
        """Feed new affect and sleep events to the evaluator, in time order.

        Returns the sleep signals the rest stage acts on. Each event's time on
        the awake clock is interpolated between the previous read and this one
        from its wall timestamp, so samples published within one poll keep
        their spacing. Time always advances, even when a read fails, so a
        silent or unreadable affect stream is seen as silence.
        """
        w_now = float(self._wall_time())
        a_now = self._awake_now(u_now)
        signals: list[tuple[str, dict[str, Any]]] = []
        if await self._indicator_seed_cursors():
            gathered: list[tuple[float, int, str, Any]] = []
            for order, (stream, attr) in enumerate(
                ((_SLEEP_STREAM, "_ind_sleep_cursor"), (_AFFECT_STREAM, "_ind_affect_cursor"))
            ):
                try:
                    entries, cursor = await self._indicator_read(stream, getattr(self, attr))
                except WelfareBusTimeout:
                    raise
                except Exception:
                    log.warning("welfare monitor: %s read failed", stream, exc_info=True)
                    continue
                setattr(self, attr, cursor)
                for _entry_id, event in entries:
                    ts = self._event_ts(event)
                    gathered.append((w_now if ts is None else ts, order, stream, event))
            gathered.sort(key=lambda item: (item[0], item[1]))
            prev = self._ind_prev
            for ts, _order, stream, event in gathered:
                if prev is None or w_now <= prev[0]:
                    t = a_now
                else:
                    frac = min(1.0, max(0.0, (ts - prev[0]) / (w_now - prev[0])))
                    t = prev[1] + frac * (a_now - prev[1])
                payload = event.payload if isinstance(getattr(event, "payload", None), dict) else {}
                if stream == _AFFECT_STREAM:
                    if event.type == "affect.state":
                        self._ind_eval.observe_state(t, payload)
                    continue
                if event.type == "sleep.sleep.started":
                    self._ind_eval.exclude_start("sleep", t)
                    signals.append(("started", payload))
                elif event.type == "sleep.sleep.completed":
                    self._ind_eval.exclude_end("sleep", t)
                    signals.append(("completed", payload))
                elif event.type == "sleep.rest_request":
                    signals.append(("answer", payload))
        self._ind_eval.advance(a_now)
        self._ind_prev = (w_now, a_now)
        self._note_awake_wall()
        return signals

    def _note_awake_wall(self) -> None:
        """Add this poll's new span time, in wall seconds, to the exposure count.

        With an awake entity clock the spans count entity seconds; dividing by
        the time scale gives the wall seconds the producer's tally counts. A
        scale that cannot be read, or reads zero or less while awake time
        accrued, leaves the count unknown (None), so the study runner holds
        the step for incomplete coverage instead of comparing other units.
        """
        pos = float(self._ind_eval.awake_seconds)
        delta = pos - self._ind_pos_seen
        self._ind_pos_seen = pos
        if delta <= 0.0 or self._ind_awake_wall is None:
            return
        if self._awake_clock is None:
            # The spans run on unfrozen time, already in wall seconds.
            self._ind_awake_wall += delta
            return
        scale: float | None = None
        if self._entity_scale is not None:
            try:
                scale = self._scale_now()
            except Exception:
                scale = None
        if scale is None or scale <= 0.0:
            log.error("welfare monitor: the time scale is unreadable; exposure coverage is unknown")
            self._ind_awake_wall = None
            return
        self._ind_awake_wall += delta / scale

    async def _indicator_accrue(self, u_now: float) -> None:
        """Warm-up: the spans accrue; no stage acts and nothing is evaluated."""
        try:
            self._indicator_tick_rest_clock(u_now)
            await self._indicator_ingest(u_now)
        except Exception as exc:
            self._exposure_poll_failures += 1
            if isinstance(exc, WelfareBusTimeout):
                raise
            log.error("welfare monitor: indicator accrual failed during warm-up", exc_info=True)

    def _indicator_detail(
        self, ev: Evaluation | None, indicators: tuple[str, ...]
    ) -> dict[str, Any]:
        """The content-free indicator fields of a record (names from the fixed table)."""
        detail: dict[str, Any] = {
            "indicator_stage": self._ind_stage,
            "indicators": list(indicators),
        }
        if ev is not None:
            detail["indicator_values"] = {r.name: r.value for r in ev.readings}
            detail["indicator_bars"] = {r.name: r.bar for r in ev.readings}
            detail["span_awake_s"] = ev.span_awake_s
        return detail

    async def _indicator_record(
        self, transition: str, ev: Evaluation | None, indicators: tuple[str, ...], **extra: Any
    ) -> None:
        await self._record(
            {
                "monitor": "welfare",
                "transition": transition,
                "run_id": self._run_id(),
                "poll_index": self.poll_index,
                **self._indicator_detail(ev, indicators),
                **extra,
            },
            event_type="welfare.protective_action",
        )

    async def _indicator_escalate(
        self, reason: str, ev: Evaluation | None, indicators: tuple[str, ...]
    ) -> None:
        """Stage 3: preservation first, the configured action, the shared latch."""
        stimulus_spent = (
            reason.startswith("indicator_")
            and reason != REST_FAILED_REASON
            and self._developing()
            and any(name in DEPRIVATION_INDICATORS for name in indicators)
        )
        await self._respond(
            reason,
            indicators=indicators,
            stimulus_spent=stimulus_spent,
            indicator_detail=self._indicator_detail(ev, indicators),
        )
        if not self._acted:
            # "notify" continues the run: start over from a fresh span.
            self._indicator_reset(restart_span=True)

    async def _indicator_rest_failed(
        self, failure: str, ev: Evaluation | None, indicators: tuple[str, ...]
    ) -> None:
        """A rest that cannot start or does not complete: record it, then stage 3."""
        if failure not in REST_FAILURES:
            failure = "refused"
        await self._indicator_record(
            "indicator_rest_failed", ev, indicators, failure=failure
        )
        await self._indicator_escalate(REST_FAILED_REASON, ev, indicators)

    async def _indicator_request_rest(self, ev: Evaluation, u_now: float) -> None:
        """Stage 1: request a rest (no preservation, no freeze)."""
        crossed = ev.crossed
        if not self._sleep_module_ready():
            log.error("welfare monitor: indicator crossed and the sleep module is not running")
            await self._indicator_rest_failed("sleep_module_not_running", ev, crossed)
            return
        request_id = uuid.uuid4().hex[:16]
        try:
            # Bounded: a request that hangs is a request not sent.
            await asyncio.wait_for(
                self._bus.publish(
                    validate_event(
                        source=self.source,
                        type=WELFARE_REST_REQUEST_TYPE,
                        payload={"request_id": request_id, "indicators": list(crossed)},
                        salience=0.0,
                        timestamp=datetime.now(timezone.utc),
                    )
                ),
                timeout=self._bus_timeout_s,
            )
        except Exception:
            log.error("welfare monitor: the welfare rest request could not be sent", exc_info=True)
            await self._indicator_rest_failed("request_not_sent", ev, crossed)
            return
        self._ind_request = _RestRequest(
            request_id=request_id, indicators=tuple(crossed), requested_u=u_now
        )
        self._ind_stage = _STAGE_RESTING
        self._exposure_rests += 1
        for name in crossed:
            self._exposure[name]["rests_requested"] += 1
        await self._indicator_record(
            "indicator_rest_requested", ev, crossed, request_id=request_id
        )
        self._notify("welfare_indicator_rest", crossed)
        log.warning(
            "welfare monitor: welfare indicator crossed (%s); a rest is requested",
            ", ".join(crossed),
        )

    def _indicator_rest_began(self, request: _RestRequest, *, standing: bool) -> None:
        request.started = not standing
        request.standing = standing
        request.started_rest_u = self._ind_rest_u
        request.bound_s = self._indicators_cfg.rest_complete_bound(
            developing=self._developing(),
            developmental_rest_s=self._developmental_rest_s(),
        )

    async def _indicator_rest_signals(
        self, signals: list[tuple[str, dict[str, Any]]], ev: Evaluation | None
    ) -> bool:
        """Apply the sleep module's answers to the outstanding rest; True when it ended.

        A refusal other than ``busy``, an ``aborted`` answer or an aborted
        rest escalates at once. ``busy`` makes the running sleep stand as the
        rest. Its completion restarts every span and moves to ``fresh``.
        """
        request = self._ind_request
        if request is None:
            return False
        for kind, payload in signals:
            if kind == "answer":
                if payload.get("origin") != WELFARE_REST_ORIGIN:
                    continue
                if payload.get("proposal_id") != request.request_id:
                    continue
                if payload.get("accepted") is True:
                    continue
                reason = payload.get("reason")
                if reason == "busy" and not request.started and not request.standing:
                    self._indicator_rest_began(request, standing=True)
                    await self._indicator_record(
                        "indicator_rest_started", ev, request.indicators,
                        request_id=request.request_id, standing=True,
                    )
                    continue
                if reason == "busy":
                    continue
                log.error("welfare monitor: the welfare rest was refused or aborted")
                await self._indicator_rest_failed("refused", ev, request.indicators)
                return True
            if kind == "started":
                if payload.get("trigger") != WELFARE_REST_TRIGGER:
                    continue
                if request.started or request.standing:
                    continue
                self._indicator_rest_began(request, standing=False)
                await self._indicator_record(
                    "indicator_rest_started", ev, request.indicators,
                    request_id=request.request_id, standing=False,
                )
                continue
            if kind == "completed":
                if not (request.started or request.standing):
                    continue
                if request.started and payload.get("trigger") != WELFARE_REST_TRIGGER:
                    continue
                if payload.get("aborted"):
                    log.error("welfare monitor: the welfare rest was aborted")
                    await self._indicator_rest_failed("aborted", ev, request.indicators)
                    return True
                # The rest's affective reset has run: every span restarts at
                # its end, and every crossing state resets.
                self._ind_eval.restart()
                self._ind_stage = _STAGE_FRESH
                self._ind_request = None
                await self._indicator_record(
                    "indicator_rest_completed", None, request.indicators,
                    request_id=request.request_id,
                )
                return True
        return False

    async def _indicator_check_rest_bounds(self, ev: Evaluation, u_now: float) -> bool:
        """Escalate a rest that did not start or did not complete in time."""
        request = self._ind_request
        if request is None:
            return False
        if not self._sleep_module_ready():
            log.error("welfare monitor: the sleep module stopped during a welfare rest")
            await self._indicator_rest_failed("sleep_module_not_running", ev, request.indicators)
            return True
        if not (request.started or request.standing):
            if u_now - request.requested_u >= self._indicators_cfg.rest_start_timeout_s:
                log.error("welfare monitor: the welfare rest did not start in time")
                await self._indicator_rest_failed("start_timeout", ev, request.indicators)
                return True
            return False
        bound = request.bound_s if request.bound_s is not None else self._indicators_cfg.rest_complete_matured_s
        began = request.started_rest_u if request.started_rest_u is not None else self._ind_rest_u
        if self._ind_rest_u - began >= bound:
            log.error("welfare monitor: the welfare rest did not complete in time")
            await self._indicator_rest_failed("complete_timeout", ev, request.indicators)
            return True
        return False

    async def _indicator_availability(self, ev: Evaluation) -> bool:
        """Report a silent affect stream once; escalate when it stays silent."""
        if ev.available:
            self._ind_unavailable_notified = False
            return False
        if not self._ind_unavailable_notified:
            self._ind_unavailable_notified = True
            await self._indicator_record(
                "indicators_unavailable", ev, (),
                silent_awake_s=self._ind_eval.silent_awake_s,
            )
            self._notify("welfare_indicators_unavailable", ())
            log.warning("welfare monitor: no affect.state; the welfare indicators are unavailable")
        if self._ind_eval.silent_awake_s >= self._indicators_cfg.unavailable_escalate_s:
            log.error("welfare monitor: the welfare indicators stayed unavailable; escalating")
            await self._indicator_escalate(UNAVAILABLE_REASON, ev, ())
            return True
        return False

    async def _indicator_poll(self, u_now: float) -> None:
        """One poll of the indicator arm. An error is retried next poll; a
        persistent one escalates as indicators unavailable."""
        try:
            await self._indicator_poll_inner(u_now)
        except WelfareBusTimeout:
            # A hung read fails the whole poll, for the liveness check.
            self._exposure_poll_failures += 1
            raise
        except Exception:
            self._exposure_poll_failures += 1
            log.error("welfare monitor: indicator poll failed; retrying next poll", exc_info=True)
            if self._ind_error_since_u is None:
                self._ind_error_since_u = u_now
            elif (
                u_now - self._ind_error_since_u >= self._indicators_cfg.unavailable_escalate_s
                and not self._acted
            ):
                self._ind_error_since_u = None
                await self._indicator_escalate(UNAVAILABLE_REASON, None, ())
            return
        self._ind_error_since_u = None

    def _note_exposure(self, ev: Evaluation) -> None:
        for reading in ev.readings:
            entry = self._exposure[reading.name]
            if ev.evaluable and reading.value is not None and math.isfinite(reading.value):
                if entry["max_value"] is None or reading.value > entry["max_value"]:
                    entry["max_value"] = float(reading.value)
        for name in ev.crossed:
            self._exposure[name]["crossings"] += 1

    def exposure_summary(self) -> dict[str, Any] | None:
        """The boot's indicator exposure for the exposure record, or None when the arm is off.

        Content-free: numbers keyed by the fixed indicator and reason tables.
        """
        if not self._indicators_on:
            return None
        return {
            "awake_seconds": float(self._ind_eval.awake_seconds),
            "awake_wall_seconds": (
                None if self._ind_awake_wall is None else float(self._ind_awake_wall)
            ),
            "indicator_poll_failures": int(self._exposure_poll_failures),
            # Bars and bounds this boot ran with that differ from the shipped
            # defaults (an operator decision), so a reviewer sees them.
            "non_default_settings": self._indicators_cfg.non_default_settings(),
            "rests_requested": int(self._exposure_rests),
            "freezes_placed": int(self._exposure_freezes),
            "responses": dict(self._exposure_responses),
            "indicators": {name: dict(entry) for name, entry in self._exposure.items()},
        }

    async def _indicator_poll_inner(self, u_now: float) -> None:
        self._indicator_tick_rest_clock(u_now)
        signals = await self._indicator_ingest(u_now)
        if self._ind_stage == _STAGE_RESTING:
            ended = await self._indicator_rest_signals(signals, None)
            if self._acted:
                return
            if not ended:
                ev = self._ind_eval.evaluate()
                self._note_exposure(ev)
                await self._indicator_check_rest_bounds(ev, u_now)
                return
        ev = self._ind_eval.evaluate()
        self._note_exposure(ev)
        if await self._indicator_availability(ev):
            return
        if self._ind_stage == _STAGE_ARMED:
            if ev.crossed:
                await self._indicator_request_rest(ev, u_now)
            return
        if self._ind_stage == _STAGE_FRESH:
            if ev.crossed:
                await self._indicator_escalate(
                    indicator_reason(ev.crossed[0]), ev, ev.crossed
                )
                return
            if ev.span_awake_s >= float(self._indicator_params.span_s):
                # A full fresh span with no crossing: the next one requests a rest.
                self._ind_stage = _STAGE_ARMED
                await self._indicator_record("indicator_rearmed", ev, ())


__all__ = [
    "DivergenceMonitor",
    "WelfareProtectiveMonitor",
    "DivergenceMonitorConfig",
    "WelfareResponseConfig",
    "PreservationRetentionConfig",
    "PreservationConfig",
]




def _welfare_notify_allowed(
    last_notify_at: float, now: float, min_interval_s: float
) -> bool:
    """M3: rate-limit welfare ``notify`` responses.

    Same mechanism as DivergenceMonitor's ``min_interval_s`` rate limit: at
    most one notify bundle per ``min_interval_s``, so a sustained-distress run
    lasting ``duration`` yields at most ``ceil(duration / min_interval_s)``
    bundles, not one per distress cycle.
    """
    return (now - last_notify_at) >= min_interval_s
