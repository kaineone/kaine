# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Mnemos replay engine.

During an active Hypnos maintenance window, the replay engine selects
stored memory traces and publishes them as `mnemos.replay` events for
re-processing by the workspace (Nous re-evaluates, Thymos re-appraises,
Eidolon observes, Phantasia extends).

Selection policy: `affect_weight × intensity + recency_weight × recency`
where `recency` is normalised to [0, 1] across the candidate pool.

Guard: `replay()` MUST be called from inside an active Hypnos maintenance
window (tracked via `is_window_active` flag).  Calling it outside raises
`ReplayWindowError` and emits nothing — this is a load-bearing safety
invariant (paper §3.3.5 — external perception suspended during replay).

Redaction: each `mnemos.replay` event carries a full-content payload
(`text` present) for re-injection into the cognitive loop.  A separate
*observer* payload is produced with `text` stripped when `redact_content`
is true, keeping memory content out of operational logs / sidecar streams.
Callers (the owning Mnemos module) receive both so they can publish the
loop-facing event and hand the redacted view to any sidecar observer.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


class ReplayWindowError(RuntimeError):
    """Raised when replay() is called outside an active Hypnos window."""


@dataclass
class ReplayEntry:
    """A single candidate memory trace for replay selection."""

    point_id: str
    text: str
    affect_intensity: float      # [0, 1]  cached from stored affect
    timestamp: float             # wall-clock seconds (float); used for recency
    payload: dict[str, Any] = field(default_factory=dict)
    affect: dict[str, Any] | None = None


@dataclass
class ReplayEvent:
    """Pair of payloads produced for one replayed trace.

    loop_payload   — carries full text; published as mnemos.replay on the
                     workspace bus for cognitive re-processing.
    observer_payload — text may be stripped if redact_content is True;
                       delivered to the sidecar replay observer.
    """

    point_id: str
    loop_payload: dict[str, Any]
    observer_payload: dict[str, Any]


def select_traces(
    candidates: list[ReplayEntry],
    *,
    affect_weight: float,
    recency_weight: float,
    top_k: int,
) -> list[ReplayEntry]:
    """Rank candidates by affect/recency score and return top-k.

    Score = affect_weight × intensity + recency_weight × recency_norm.
    `recency_norm` is 1.0 for the most recent candidate and 0.0 for the
    oldest, scaled linearly across the pool.  Ties in score are broken by
    higher intensity first, then by more recent timestamp.

    Returns at most `top_k` entries.  Returns an empty list if `candidates`
    is empty.
    """
    if not candidates:
        return []

    # Normalise recency: newer = higher score.
    ts_values = [c.timestamp for c in candidates]
    ts_min = min(ts_values)
    ts_max = max(ts_values)
    ts_span = ts_max - ts_min

    def _score(entry: ReplayEntry) -> float:
        recency = (
            (entry.timestamp - ts_min) / ts_span if ts_span > 0.0 else 1.0
        )
        return affect_weight * entry.affect_intensity + recency_weight * recency

    ranked = sorted(
        candidates,
        key=lambda e: (_score(e), e.affect_intensity, e.timestamp),
        reverse=True,
    )
    return ranked[:max(0, int(top_k))]


def build_replay_events(
    selected: list[ReplayEntry],
    *,
    redact_content: bool,
    replayed_at: float | None = None,
) -> list[ReplayEvent]:
    """Produce ReplayEvent pairs for each selected trace.

    Args:
        selected:        Ordered list of traces to replay (from select_traces).
        redact_content:  When True the observer_payload omits `text`.
        replayed_at:     Wall-clock timestamp for the replay batch (defaults
                         to now).  Included in both payloads so observers can
                         correlate across the batch.
    """
    ts = replayed_at if replayed_at is not None else time.time()
    events: list[ReplayEvent] = []
    for entry in selected:
        loop_payload: dict[str, Any] = {
            "memory_id": entry.point_id,
            "text": entry.text,
            "affect": entry.affect,
            "affect_intensity": entry.affect_intensity,
            "source_timestamp": entry.timestamp,
            "replayed_at": ts,
        }
        if redact_content:
            observer_payload = {
                k: v
                for k, v in loop_payload.items()
                if k != "text"
            }
        else:
            observer_payload = dict(loop_payload)
        events.append(
            ReplayEvent(
                point_id=entry.point_id,
                loop_payload=loop_payload,
                observer_payload=observer_payload,
            )
        )
    return events


class ReplayEngine:
    """Stateful engine owned by the Mnemos module.

    Tracks whether a Hypnos maintenance window is currently active and,
    when asked to replay, selects traces from the short-term buffer /
    storage and publishes `mnemos.replay` events.

    The window flag is toggled by the Mnemos module's event handler when
    it observes `hypnos.sleep.started` (window opens) and
    `hypnos.sleep.completed` (window closes).
    """

    def __init__(
        self,
        *,
        selection_top_k: int = 5,
        affect_weight: float = 0.7,
        recency_weight: float = 0.3,
        redact_content: bool = True,
    ) -> None:
        if selection_top_k <= 0:
            raise ValueError("selection_top_k must be positive")
        if affect_weight < 0.0 or recency_weight < 0.0:
            raise ValueError("weights must be non-negative")
        self._top_k = int(selection_top_k)
        self._affect_weight = float(affect_weight)
        self._recency_weight = float(recency_weight)
        self._redact_content = bool(redact_content)
        self._window_active: bool = False

    # ------------------------------------------------------------------
    # Window lifecycle (called by Mnemos when it sees hypnos bus events)
    # ------------------------------------------------------------------

    def open_window(self) -> None:
        """Signal that a Hypnos maintenance replay window has started."""
        self._window_active = True

    def close_window(self) -> None:
        """Signal that the Hypnos maintenance window has ended."""
        self._window_active = False

    @property
    def window_active(self) -> bool:
        return self._window_active

    @property
    def redact_content(self) -> bool:
        return self._redact_content

    # ------------------------------------------------------------------
    # Core replay API
    # ------------------------------------------------------------------

    def replay(self, candidates: list[ReplayEntry]) -> list[ReplayEvent]:
        """Select and package traces for replay.

        MUST be called inside an active Hypnos maintenance window.
        Raises `ReplayWindowError` if called while awake.

        Returns a list of `ReplayEvent` objects (one per selected trace).
        The caller is responsible for publishing `loop_payload` on the bus
        and forwarding `observer_payload` to any sidecar.
        """
        if not self._window_active:
            raise ReplayWindowError(
                "replay() called outside an active Hypnos maintenance window; "
                "replay events are never published while awake"
            )
        selected = select_traces(
            candidates,
            affect_weight=self._affect_weight,
            recency_weight=self._recency_weight,
            top_k=self._top_k,
        )
        return build_replay_events(
            selected,
            redact_content=self._redact_content,
        )
