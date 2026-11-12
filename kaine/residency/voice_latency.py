# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Per-turn voice latency breakdown with warm/cold path separation.

Every turn is measured into a breakdown of six timing segments.  Cold-path
turns (where a model load occurred) are recorded separately from warm-path
turns, and persistent misses surface as degradation reports naming the
offending rung.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class VoiceTurnBreakdown:
    """Latency breakdown for a single voice turn."""

    queue_wait_ms: float
    preempt_wait_ms: float
    load_ms: float
    stt_ms: float
    llm_first_token_ms: float
    tts_first_chunk_ms: float
    rung_label: str
    is_cold: bool
    ts: float = field(default_factory=time.monotonic)

    @property
    def total_ms(self) -> float:
        """Sum of all six timing segments."""
        return (
            self.queue_wait_ms
            + self.preempt_wait_ms
            + self.load_ms
            + self.stt_ms
            + self.llm_first_token_ms
            + self.tts_first_chunk_ms
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the full breakdown as a plain dict."""
        return {
            "queue_wait_ms": self.queue_wait_ms,
            "preempt_wait_ms": self.preempt_wait_ms,
            "load_ms": self.load_ms,
            "stt_ms": self.stt_ms,
            "llm_first_token_ms": self.llm_first_token_ms,
            "tts_first_chunk_ms": self.tts_first_chunk_ms,
            "rung_label": self.rung_label,
            "is_cold": self.is_cold,
            "ts": self.ts,
            "total_ms": self.total_ms,
        }


@dataclass(frozen=True)
class PersistentMissReport:
    """A rung that keeps getting evicted and reloaded."""

    rung_label: str
    cold_count: int
    threshold: int
    offending_segment: str


_LOCK = threading.Lock()
_BREAKDOWNS: list[VoiceTurnBreakdown] = []


def record_voice_turn(breakdown: VoiceTurnBreakdown) -> VoiceTurnBreakdown:
    """Append a voice turn breakdown and log a summary."""
    with _LOCK:
        _BREAKDOWNS.append(breakdown)
    path = "cold" if breakdown.is_cold else "warm"
    log.info(
        "voice turn [%s] %s: total=%.1fms (queue=%.1f preempt=%.1f load=%.1f"
        " stt=%.1f llm=%.1f tts=%.1f)",
        path,
        breakdown.rung_label,
        breakdown.total_ms,
        breakdown.queue_wait_ms,
        breakdown.preempt_wait_ms,
        breakdown.load_ms,
        breakdown.stt_ms,
        breakdown.llm_first_token_ms,
        breakdown.tts_first_chunk_ms,
    )
    return breakdown


def voice_turn_breakdowns() -> list[VoiceTurnBreakdown]:
    """Snapshot of all recorded breakdowns."""
    with _LOCK:
        return list(_BREAKDOWNS)


def warm_turns() -> list[VoiceTurnBreakdown]:
    """Breakdowns where the model was already resident."""
    with _LOCK:
        return [b for b in _BREAKDOWNS if not b.is_cold]


def cold_turns() -> list[VoiceTurnBreakdown]:
    """Breakdowns where a model load happened during the turn."""
    with _LOCK:
        return [b for b in _BREAKDOWNS if b.is_cold]


def check_persistent_misses(
    threshold: int = 3,
) -> list[PersistentMissReport]:
    """Detect rungs whose last N consecutive turns are all cold.

    For each rung_label, if the most recent *threshold* or more consecutive
    turns are all cold, emit a :class:`PersistentMissReport`.  The
    ``offending_segment`` is the rung label itself -- it is the model that
    keeps getting evicted and reloaded.
    """
    with _LOCK:
        snapshot = list(_BREAKDOWNS)

    # Group by rung, preserving insertion order.
    by_rung: dict[str, list[VoiceTurnBreakdown]] = defaultdict(list)
    for b in snapshot:
        by_rung[b.rung_label].append(b)

    reports: list[PersistentMissReport] = []
    for rung_label, turns in by_rung.items():
        # Count consecutive cold turns from the tail.
        streak = 0
        for turn in reversed(turns):
            if turn.is_cold:
                streak += 1
            else:
                break
        if streak >= threshold:
            report = PersistentMissReport(
                rung_label=rung_label,
                cold_count=streak,
                threshold=threshold,
                offending_segment=rung_label,
            )
            reports.append(report)
            log.warning(
                "persistent miss: %s has %d consecutive cold turns"
                " (threshold %d)",
                rung_label,
                streak,
                threshold,
            )
    return reports


def clear_voice_turn_breakdowns() -> None:
    """Clear all recorded breakdowns (for tests)."""
    with _LOCK:
        _BREAKDOWNS.clear()
