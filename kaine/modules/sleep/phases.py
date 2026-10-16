# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The five sleep phases (paper §3.5).

Phase ordering (non-negotiable; paper-canonical):
  1. light_consolidation: short-term to episodic transfer (nothing dropped);
     oscillator frequency reduction across all active modules.
  2. deep_consolidation: replay of the consolidated traces inside a replay
     window that the sleep module opens through the episodic memory module, then the downscaling of trace
     strengths that protects the replayed traces (paper A.10).
  3. associative_replay: co-replay of related trace pairs of different periods, recorded as weighted links, then pruning (paper A.10).
  4. voice_alignment: orchestrated by the sleep module directly.
  5. affective_reset: the affect module reset; sleep ends with it. The interoception module's fatigue
     resets on the sleep.sleep.completed event that follows.

Each phase is async, takes its specific collaborator(s), and returns a
`PhaseResult`.  Exceptions are caught inside each phase function so one
failure cannot stop the pipeline: the orchestrator in `module.py` runs
them in order regardless.

Phase 3 (associative_replay) is gated by the
`[sleep.consolidation].associative_replay` config flag and ships disabled
by default; when it is on, phase 2 leaves pruning to phase 3 so that
pruning follows the co-replays, as A.10 orders it.  Voice
alignment (phase 4) is likewise gated by `[sleep.voice_alignment].enabled`
plus the operator-approval env var.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, Sequence

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PhaseResult:
    phase: str
    success: bool
    elapsed_ms: float
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _now_ms() -> float:
    return time.monotonic() * 1000.0


# ---------------------------------------------------------------------------
# Collaborator protocols — duck-typed so tests can supply tiny fakes.
# ---------------------------------------------------------------------------

class _SupportsEpisodicMemory(Protocol):
    """The episodic memory module: memory consolidation, replay, and downscaling of trace strengths.

    deep_consolidation also calls ``open_replay_window()`` and
    ``close_replay_window()`` when the collaborator has them. The real episodic memory module
    does; test fakes need not, so they are not part of this protocol.
    """

    async def consolidate_now(self) -> int: ...

    async def downscale(self, protect: Sequence[Any] = (), *, prune: bool = True) -> dict[str, Any]:
        """Downscale trace strengths, protecting the replayed traces, then prune unless prune is false (paper A.10)."""

    async def replay_now(self) -> list[Any]: ...


class _SupportsAffectiveReset(Protocol):
    async def affective_reset(self) -> None: ...


class _SupportsTimeReset(Protocol):
    """Anything sequence-module-shaped that exposes a reset/recalibrate entry."""

    def reset(self) -> None: ...


# ---------------------------------------------------------------------------
# Phase 1 — Light Consolidation
# ---------------------------------------------------------------------------

async def light_consolidation(
    episodic_memory: Optional[_SupportsEpisodicMemory],
    *,
    active_modules: list[Any] | None = None,
    frequency_scale: float = 0.5,
) -> PhaseResult:
    """Phase 1: short-term to episodic transfer and the oscillator frequency hook.

    Calls ``consolidate_now()``, which moves every short-term entry into
    episodic memory and drops nothing: no trace is deleted in this phase, and
    ``entries_consolidated`` counts the entries moved. The episodic memory module keeps the moved
    traces for this sleep, so phase 2's replay draws on them. Strong traces are
    tagged for deep consolidation (no-op at this stage — tagging is implicit
    in the existing salience scoring).

    The oscillator frequency-reduction hook (``set_frequency(scale)``) is
    invoked on all provided *active_modules*.  When no oscillatory-layer is
    present every module's ``set_frequency`` is a ``BaseModule`` no-op, so
    this is guaranteed safe regardless of oscillatory-layer deployment status.
    """
    start = _now_ms()
    metadata: dict[str, Any] = {}

    # --- Oscillator hook across all active modules (no-op without oscillatory-layer) ---
    called_modules = 0
    for module in (active_modules or []):
        try:
            module.set_frequency(frequency_scale)
            called_modules += 1
        except Exception:
            log.warning(
                "light_consolidation: set_frequency raised on %r",
                getattr(module, "name", module),
                exc_info=True,
            )
    metadata["frequency_scale"] = frequency_scale
    metadata["modules_frequency_called"] = called_modules

    # --- Consolidation (short-term to episodic; nothing is dropped) ---
    if episodic_memory is None:
        metadata["consolidation_skipped"] = "no Episodic memory available"
        return PhaseResult(
            phase="light_consolidation",
            success=True,
            elapsed_ms=_now_ms() - start,
            metadata=metadata,
        )
    try:
        moved = await episodic_memory.consolidate_now()
        metadata["entries_consolidated"] = int(moved)
        return PhaseResult(
            phase="light_consolidation",
            success=True,
            elapsed_ms=_now_ms() - start,
            metadata=metadata,
        )
    except Exception as exc:
        log.exception("light_consolidation phase failed during consolidate_now")
        return PhaseResult(
            phase="light_consolidation",
            success=False,
            elapsed_ms=_now_ms() - start,
            error=f"{type(exc).__name__}: {exc}",
            metadata=metadata,
        )


# ---------------------------------------------------------------------------
# Phase 2 — Deep Consolidation + Downscaling
# ---------------------------------------------------------------------------

async def deep_consolidation(
    episodic_memory: Optional[_SupportsEpisodicMemory],
    *,
    suspend_perception: Any = None,
    restore_perception: Any = None,
    replay_window_s: float = 5.0,
    defer_prune: bool = False,
) -> PhaseResult:
    """Phase 2: replay first, then downscaling of trace strengths.

    Replay of the consolidated traces runs inside a replay window that this
    function opens through the episodic memory module itself (so the window never depends on
    the episodic memory module having seen ``sleep.sleep.started`` on the bus). The window is
    closed once replay is done. Perception is suspended for the duration
    using the provided callables and is always restored afterwards.

    After replay the episodic memory module scales the strength of every persisted trace
    except the replayed ones by one factor that deepens with the number of
    traces the wake stored, and the replayed traces keep theirs (paper
    A.10); vectors are not touched. If replay fails, downscaling and pruning
    are skipped for this sleep so the wake's traces keep their strength and
    can be replayed on the next sleep.

    Args:
        episodic_memory:      the episodic memory module, or None (phase is no-op).
        suspend_perception:   Callable (sync or no-arg async) to suspend external
                              perception; None = skip.
        restore_perception:   Callable (sync or no-arg async) to restore perception;
                              None = skip.
        replay_window_s:      Replay window duration in seconds (informational;
                              actual replay completes synchronously).
        defer_prune:          Leave pruning to phase 3 (true when associative replay is on).
    """
    start = _now_ms()
    metadata: dict[str, Any] = {}

    if episodic_memory is None:
        metadata["skipped"] = "no Episodic memory available"
        return PhaseResult(
            phase="deep_consolidation",
            success=True,
            elapsed_ms=_now_ms() - start,
            metadata=metadata,
        )

    errors: list[str] = []
    replay_events: list[Any] = []
    replay_failed = False

    # --- Step 1: Suspend perception; open the window; replay; close; restore ---
    open_window = getattr(episodic_memory, "open_replay_window", None)
    close_window = getattr(episodic_memory, "close_replay_window", None)
    perception_suspended = False
    try:
        # Suspend external perception (freeze/locus machinery).
        if suspend_perception is not None:
            try:
                result = suspend_perception()
                if asyncio.iscoroutine(result):
                    await result
                perception_suspended = True
                metadata["perception_suspended"] = True
                log.debug("deep_consolidation: external perception suspended")
            except Exception as exc:
                log.warning(
                    "deep_consolidation: perception suspension failed: %s", exc
                )
                errors.append(f"suspend_perception: {type(exc).__name__}: {exc}")

        # Drive replay within the window.
        try:
            if open_window is not None:
                open_window()
            replay_events = await episodic_memory.replay_now()
            metadata["replay_events"] = len(replay_events)
            log.debug(
                "deep_consolidation: replay_now returned %d events", len(replay_events)
            )
        except Exception as exc:
            replay_failed = True
            log.exception("deep_consolidation: replay_now failed")
            errors.append(f"replay_now: {type(exc).__name__}: {exc}")
            metadata["replay_events"] = 0

        metadata["replay_window_s"] = replay_window_s

    finally:
        # Close the replay window once replay is done, before perception
        # returns, so the window is never open while perceiving.
        if close_window is not None:
            try:
                close_window()
            except Exception as exc:
                log.warning(
                    "deep_consolidation: closing the replay window failed: %s", exc
                )
                errors.append(f"close_replay_window: {type(exc).__name__}: {exc}")
        # Always restore perception (even on error): safety invariant.
        if restore_perception is not None:
            try:
                result = restore_perception()
                if asyncio.iscoroutine(result):
                    await result
                if perception_suspended:
                    metadata["perception_restored"] = True
                log.debug("deep_consolidation: external perception restored")
            except Exception as exc:
                log.warning(
                    "deep_consolidation: perception restore failed: %s", exc
                )
                errors.append(f"restore_perception: {type(exc).__name__}: {exc}")

    # --- Step 2: Downscale trace strengths, protecting the replayed traces (paper A.10) ---
    # Skip if replay failed; the wake's traces keep born_sleep == n so the
    # next sleep will count and replay them.
    if replay_failed:
        metadata["downscale_skipped"] = "replay failed"
    else:
        try:
            if defer_prune:
                summary = dict(await episodic_memory.downscale(protect=replay_events, prune=False))
            else:
                summary = dict(await episodic_memory.downscale(protect=replay_events))
            metadata["downscale"] = summary
            if summary.get("blocked"):
                errors.append(f"downscale blocked: {summary['blocked']}")
        except Exception as exc:
            log.exception("deep_consolidation: downscale failed")
            errors.append(f"downscale: {type(exc).__name__}: {exc}")

    success = not errors
    return PhaseResult(
        phase="deep_consolidation",
        success=success,
        elapsed_ms=_now_ms() - start,
        error="; ".join(errors) if errors else None,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Phase 3: Associative Replay (behind feature flag)
# ---------------------------------------------------------------------------

class _SupportsAssociation(Protocol):
    """The episodic memory module's associative replay and pruning (paper A.10)."""

    async def associate(self) -> dict[str, Any]: ...

    async def prune(self) -> dict[str, Any]: ...


async def associative_replay(
    *,
    enabled: bool = False,
    episodic_memory: Optional[_SupportsAssociation] = None,
    publish: Any = None,
) -> PhaseResult:
    """Phase 3: associative replay (paper A.10).

    After downscaling, the episodic memory module co-replays at most n_pair pairs
    of a replayed trace and one stored before the wake, most similar first,
    and records each pair as a weighted link; then it prunes. This phase calls
    ``associate()`` then ``prune()``; pruning runs even if association fails.
    Each ``sleep.association`` event carries only the pair's two point ids and
    its weight. It does not cue the world model module.

    Args:
        enabled:         associative_replay feature flag.
        episodic_memory: the episodic memory module (or None -> phase is skipped).
        publish:         callable taking one payload dict; may be sync or async.
    """
    start = _now_ms()
    if not enabled:
        return PhaseResult(
            phase="associative_replay",
            success=True,
            elapsed_ms=_now_ms() - start,
            metadata={"skipped": "associative_replay feature flag not enabled"},
        )

    if episodic_memory is None:
        return PhaseResult(
            phase="associative_replay",
            success=True,
            elapsed_ms=_now_ms() - start,
            metadata={"skipped": "no Episodic memory available"},
        )

    metadata: dict[str, Any] = {}
    errors: list[str] = []
    pairs: list[dict[str, Any]] = []

    associate = getattr(episodic_memory, "associate", None)
    prune = getattr(episodic_memory, "prune", None)

    try:
        if associate is None:
            metadata["associate_skipped"] = "episodic memory has no associate()"
        else:
            summary = dict(await associate())
            metadata["associate"] = {k: v for k, v in summary.items() if k != "pairs"}
            pairs = list(summary.get("pairs") or [])
            metadata["pairs"] = len(pairs)
    except Exception as exc:
        log.exception("associative_replay: associate() failed")
        errors.append(f"associate: {type(exc).__name__}: {exc}")
    finally:
        if prune is not None:
            try:
                metadata["prune"] = dict(await prune())
            except Exception as exc:
                log.exception("associative_replay: prune() failed")
                errors.append(f"prune: {type(exc).__name__}: {exc}")

    if publish is not None:
        published = 0
        for pair in pairs:
            try:
                payload = {
                    "a": str(pair["a"]),
                    "b": str(pair["b"]),
                    "weight": float(pair["weight"]),
                }
                result = publish(payload)
                if asyncio.iscoroutine(result):
                    await result
                published += 1
            except Exception as exc:
                log.exception("associative_replay: publish failed for pair %r", pair)
                errors.append(f"publish: {type(exc).__name__}: {exc}")
        metadata["associations_published"] = published

    return PhaseResult(
        phase="associative_replay",
        success=not errors,
        elapsed_ms=_now_ms() - start,
        error="; ".join(errors) if errors else None,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Phase 5: Affective Reset (+ the interoception module's fatigue reset); sleep ends with it
# ---------------------------------------------------------------------------

async def affective_reset(
    affect: Optional[_SupportsAffectiveReset],
) -> PhaseResult:
    """Phase 5: the affect module's affective reset, the last phase of every sleep.

    Resets the entity's dimensional affect state (valence/arousal/dominance)
    toward baseline.  The interoception module's fatigue reset is handled separately via the
    existing ``sleep.sleep.completed`` event that the interoception module subscribes to
    (``soma-forward-model-fatigue`` change); the sleep module publishes that event in
    ``_run_pipeline`` after all phases complete, which zeroes
    ``FatigueAccumulator`` without requiring a direct module reference here.
    """
    start = _now_ms()
    if affect is None:
        return PhaseResult(
            phase="affective_reset",
            success=True,
            elapsed_ms=_now_ms() - start,
            metadata={"skipped": "no Affect available"},
        )
    try:
        await affect.affective_reset()
        return PhaseResult(
            phase="affective_reset",
            success=True,
            elapsed_ms=_now_ms() - start,
        )
    except Exception as exc:
        log.exception("affective_reset phase failed")
        return PhaseResult(
            phase="affective_reset",
            success=False,
            elapsed_ms=_now_ms() - start,
            error=f"{type(exc).__name__}: {exc}",
        )


# ---------------------------------------------------------------------------
# Phase 4: Voice Alignment (orchestrated by module.py directly)
# ---------------------------------------------------------------------------
# Voice alignment is complex enough that it is driven by Sleep.module
# rather than a standalone phase function.  The PhaseResult for it is
# constructed in module._run_voice_alignment() and appended to the
# phase_results list directly.  This module contains only the helper
# phases 1, 2, 3 and 5 that phase functions call.


# ---------------------------------------------------------------------------
# Legacy aliases — kept so existing test imports don't break.
# These names are deprecated; prefer the new phase functions above.
# ---------------------------------------------------------------------------

async def consolidate_memory(episodic_memory: Optional[_SupportsEpisodicMemory]) -> PhaseResult:
    """Legacy alias for the pre-restructure memory consolidation step.

    Delegates to ``light_consolidation`` without the oscillator hook,
    producing a ``memory_consolidation`` phase name to maintain backwards
    compatibility with tests that check the old phase name directly.
    """
    start = _now_ms()
    if episodic_memory is None:
        return PhaseResult(
            phase="memory_consolidation",
            success=True,
            elapsed_ms=_now_ms() - start,
            metadata={"skipped": "no Episodic memory available"},
        )
    try:
        moved = await episodic_memory.consolidate_now()
        return PhaseResult(
            phase="memory_consolidation",
            success=True,
            elapsed_ms=_now_ms() - start,
            metadata={"entries_consolidated": int(moved)},
        )
    except Exception as exc:
        log.exception("memory_consolidation phase failed")
        return PhaseResult(
            phase="memory_consolidation",
            success=False,
            elapsed_ms=_now_ms() - start,
            error=f"{type(exc).__name__}: {exc}",
        )


async def reset_affect(affect: Optional[_SupportsAffectiveReset]) -> PhaseResult:
    """Legacy alias — delegates to ``affective_reset``."""
    return await affective_reset(affect)


async def recalibrate_time(sequence_resetters: list[Any]) -> PhaseResult:
    """Reset the sequence module's habituation / rumination trackers via their reset() methods.

    Each item in ``sequence_resetters`` is anything with a ``reset()`` method
    — typically the detectors stashed inside the sequence module. The list
    shape lets callers pass several without an introspection dance.
    """
    start = _now_ms()
    if not sequence_resetters:
        return PhaseResult(
            phase="temporal_recalibration",
            success=True,
            elapsed_ms=_now_ms() - start,
            metadata={"skipped": "no Sequence resetters provided"},
        )
    reset = 0
    errors: list[str] = []
    for r in sequence_resetters:
        try:
            r.reset()
            reset += 1
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
    return PhaseResult(
        phase="temporal_recalibration",
        success=not errors,
        elapsed_ms=_now_ms() - start,
        error="; ".join(errors) if errors else None,
        metadata={"reset_count": reset},
    )
