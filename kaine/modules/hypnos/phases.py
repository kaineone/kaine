# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The five Hypnos sleep phases (paper §3.3.5).

Phase ordering (non-negotiable; paper-canonical):
  1. light_consolidation  — weak-trace decay; strong-trace tagging; oscillator
                            frequency reduction across all active modules.
  2. deep_consolidation   — global activation downscaling (Tononi & Cirelli 2014)
                            + perception-suspended replay window.
  3. associative_replay   — cross-period trace selection + Phantasia-cued
                            re-injection (hypnos-consolidation).
  4. affective_reset      — Thymos reset + Soma fatigue reset.
  5. voice_alignment      — orchestrated by the Hypnos module directly.

Each phase is async, takes its specific collaborator(s), and returns a
`PhaseResult`.  Exceptions are caught inside each phase function so one
failure cannot stop the pipeline — the orchestrator in `module.py` runs
them in order regardless.

Phase 3 (associative_replay) is fully implemented but gated by the
`[hypnos.consolidation].associative_replay` config flag and ships disabled
by default; it runs as a safe no-op until an operator opts in. Voice
alignment (phase 5) is likewise gated by `[hypnos.voice_alignment].enabled`
plus the operator-approval env var.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

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

class _SupportsMnemos(Protocol):
    """Mnemos module — memory consolidation, downscaling, and replay."""

    async def consolidate_now(self) -> int: ...

    def downscale_activations(self, factor: float) -> int: ...

    async def replay_now(self) -> list[Any]: ...


class _SupportsAffectiveReset(Protocol):
    async def affective_reset(self) -> None: ...


class _SupportsStep(Protocol):
    @property
    def running(self) -> bool: ...

    async def step(self, n: int) -> list[str]: ...


class _SupportsTimeReset(Protocol):
    """Anything Chronos-shaped that exposes a reset/recalibrate entry."""

    def reset(self) -> None: ...


# ---------------------------------------------------------------------------
# Phase 1 — Light Consolidation
# ---------------------------------------------------------------------------

async def light_consolidation(
    mnemos: Optional[_SupportsMnemos],
    *,
    active_modules: list[Any] | None = None,
    frequency_scale: float = 0.5,
) -> PhaseResult:
    """Phase 1: weak-trace decay, strong-trace tagging, oscillator frequency hook.

    Weak traces are pruned via ``consolidate_now()`` (which moves short-term
    to episodic, dropping low-salience items).  Strong traces are tagged for
    deep consolidation (no-op at this stage — tagging is implicit in the
    existing salience scoring).

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

    # --- Consolidation (weak-trace pruning / strong-trace promotion) ---
    if mnemos is None:
        metadata["consolidation_skipped"] = "no Mnemos available"
        return PhaseResult(
            phase="light_consolidation",
            success=True,
            elapsed_ms=_now_ms() - start,
            metadata=metadata,
        )
    try:
        moved = await mnemos.consolidate_now()
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
    mnemos: Optional[_SupportsMnemos],
    *,
    downscale_factor: float = 0.9,
    suspend_perception: Any = None,
    restore_perception: Any = None,
    replay_window_s: float = 5.0,
) -> PhaseResult:
    """Phase 2: global activation downscaling + perception-suspended replay window.

    Implements Tononi & Cirelli (2014) synaptic homeostasis hypothesis:
    scale all memory activation weights by *downscale_factor* preserving
    relative ordering (cosine similarity unchanged; L2 norms shrink).

    A replay window is then opened.  External perception is suspended for
    the duration using the provided callables (reusing the freeze/locus
    machinery from the Hypnos module layer).  The replay window drives
    ``mnemos.replay_now()`` (``ReplayEngine`` path, real on this branch
    since ``mnemos-replay`` has merged).  Perception is always restored after
    the window regardless of replay outcome.

    Args:
        mnemos:              Mnemos module, or None (phase is no-op).
        downscale_factor:    Synaptic scaling factor in (0, 1].
        suspend_perception:  Callable (sync or no-arg async) to suspend external
                             perception; None = skip.
        restore_perception:  Callable (sync or no-arg async) to restore perception;
                             None = skip.
        replay_window_s:     Replay window duration in seconds (informational;
                             actual replay completes synchronously).
    """
    import asyncio

    start = _now_ms()
    metadata: dict[str, Any] = {}

    if mnemos is None:
        metadata["skipped"] = "no Mnemos available"
        return PhaseResult(
            phase="deep_consolidation",
            success=True,
            elapsed_ms=_now_ms() - start,
            metadata=metadata,
        )

    errors: list[str] = []

    # --- Step 1: Downscale activations ---
    try:
        scaled = mnemos.downscale_activations(downscale_factor)
        metadata["vectors_downscaled"] = scaled
        metadata["downscale_factor"] = downscale_factor
    except Exception as exc:
        log.exception("deep_consolidation: downscale_activations failed")
        errors.append(f"downscale: {type(exc).__name__}: {exc}")
        metadata["downscale_factor"] = downscale_factor
        metadata["vectors_downscaled"] = 0

    # --- Step 2: Open replay window; suspend perception; replay; restore ---
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
        replay_events = []
        try:
            replay_events = await mnemos.replay_now()
            metadata["replay_events"] = len(replay_events)
            log.debug(
                "deep_consolidation: replay_now returned %d events", len(replay_events)
            )
        except Exception as exc:
            log.exception("deep_consolidation: replay_now failed")
            errors.append(f"replay_now: {type(exc).__name__}: {exc}")
            metadata["replay_events"] = 0

        metadata["replay_window_s"] = replay_window_s

    finally:
        # Always restore perception (even on error) — safety invariant.
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

    success = not errors
    return PhaseResult(
        phase="deep_consolidation",
        success=success,
        elapsed_ms=_now_ms() - start,
        error="; ".join(errors) if errors else None,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Phase 3 — Associative Replay (stub; behind feature flag)
# ---------------------------------------------------------------------------

class _SupportsCrossPeriod(Protocol):
    """Mnemos-shaped object that can yield traces grouped by memory period.

    Returns a mapping ``{period_name: [trace, ...]}`` where each trace is
    any object carrying at least ``point_id`` and ``text`` attributes (or a
    dict with those keys).  Implementations select from distinct memory
    periods (short-term / episodic / semantic) so a single replay batch can
    span more than one period for novel cross-period association.
    """

    async def select_cross_period_traces(
        self, *, periods: int, per_period: int
    ) -> dict[str, list[Any]]: ...


class _SupportsScenarioCue(Protocol):
    """Phantasia-shaped collaborator that imagines a scenario from a seed."""

    async def generate_scenario(
        self, *, seed_memory_id: str = ""
    ) -> list[dict[str, Any]]: ...


def _trace_id(trace: Any) -> str:
    if isinstance(trace, dict):
        return str(trace.get("point_id") or trace.get("memory_id") or "")
    return str(getattr(trace, "point_id", "") or getattr(trace, "memory_id", ""))


async def associative_replay(
    *,
    enabled: bool = False,
    mnemos: Optional[_SupportsCrossPeriod] = None,
    phantasia: Optional[_SupportsScenarioCue] = None,
    reinject: Any = None,
    periods: int = 2,
    per_period: int = 3,
) -> PhaseResult:
    """Phase 3: associative cross-period replay (hypnos-consolidation).

    Gated by the ``associative_replay`` feature flag in
    ``[hypnos.consolidation]``.  When disabled it returns a successful
    no-op so the pipeline ordering is preserved.

    When enabled it:

    1. Selects traces from at least two DISTINCT memory periods (short-term,
       episodic, semantic) via ``mnemos.select_cross_period_traces`` so a
       single replay batch spans more than one period — the substrate for
       novel cross-period association.
    2. Cues Phantasia (``generate_scenario``) for each cross-period seed and
       consumes the resulting ``phantasia.scenario`` payloads.  When
       Phantasia is disabled/absent the cue degrades to a no-op (no scenarios
       produced) — the phase still succeeds.
    3. Re-injects the novel associations (the consumed scenarios) into the
       workspace via the ``reinject`` callable so Nous (pymdp) and Thymos
       process them through the normal cognitive cycle — there is NO special
       belief-revision burst.

    Args:
        enabled:     associative_replay feature flag.
        mnemos:      cross-period trace source (or None → cross-period skipped).
        phantasia:   scenario cue collaborator (or None → cue no-op).
        reinject:    async/sync callable taking one scenario payload dict;
                     publishes it into the workspace.  None → skip re-injection.
        periods:     number of distinct memory periods to span (>= 2).
        per_period:  traces to pull from each period.
    """
    import asyncio

    start = _now_ms()
    if not enabled:
        return PhaseResult(
            phase="associative_replay",
            success=True,
            elapsed_ms=_now_ms() - start,
            metadata={"skipped": "associative_replay feature flag not enabled"},
        )

    metadata: dict[str, Any] = {}
    errors: list[str] = []

    # --- Step 1: cross-period trace selection -------------------------------
    by_period: dict[str, list[Any]] = {}
    if mnemos is None or not hasattr(mnemos, "select_cross_period_traces"):
        metadata["cross_period_skipped"] = (
            "no Mnemos cross-period surface available"
        )
    else:
        try:
            by_period = await mnemos.select_cross_period_traces(
                periods=max(2, int(periods)), per_period=max(1, int(per_period))
            )
        except Exception as exc:
            log.exception("associative_replay: cross-period selection failed")
            errors.append(f"cross_period: {type(exc).__name__}: {exc}")
            by_period = {}

    populated_periods = [p for p, traces in by_period.items() if traces]
    metadata["periods_selected"] = sorted(populated_periods)
    metadata["distinct_periods"] = len(populated_periods)
    seeds: list[str] = []
    for traces in by_period.values():
        for trace in traces:
            tid = _trace_id(trace)
            if tid:
                seeds.append(tid)
    metadata["cross_period_traces"] = len(seeds)

    # --- Step 2 + 3: cue Phantasia, consume scenarios, re-inject ------------
    scenarios_consumed = 0
    reinjected = 0
    if phantasia is None:
        metadata["phantasia_cue"] = "no-op (Phantasia disabled/absent)"
    else:
        # Cue once per cross-period seed; if no seeds were selected, still
        # issue a single unseeded cue so an enabled Phantasia can extend the
        # accumulated trajectory.
        cue_seeds = seeds or [""]
        for seed in cue_seeds:
            try:
                scenarios = await phantasia.generate_scenario(seed_memory_id=seed)
            except Exception as exc:
                log.exception("associative_replay: Phantasia cue failed")
                errors.append(f"phantasia_cue: {type(exc).__name__}: {exc}")
                continue
            for scenario in scenarios or []:
                scenarios_consumed += 1
                if reinject is None:
                    continue
                try:
                    result = reinject(scenario)
                    if asyncio.iscoroutine(result):
                        await result
                    reinjected += 1
                except Exception as exc:
                    log.exception("associative_replay: re-injection failed")
                    errors.append(f"reinject: {type(exc).__name__}: {exc}")
        metadata["phantasia_cue"] = "cued"

    metadata["scenarios_consumed"] = scenarios_consumed
    metadata["associations_reinjected"] = reinjected

    return PhaseResult(
        phase="associative_replay",
        success=not errors,
        elapsed_ms=_now_ms() - start,
        error="; ".join(errors) if errors else None,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Phase 4 — Affective Reset (+ Soma fatigue reset)
# ---------------------------------------------------------------------------

async def affective_reset(
    thymos: Optional[_SupportsAffectiveReset],
) -> PhaseResult:
    """Phase 4: Thymos affective reset.

    Resets the entity's dimensional affect state (valence/arousal/dominance)
    toward baseline.  The Soma fatigue reset is handled separately via the
    existing ``hypnos.sleep.completed`` event that Soma subscribes to
    (``soma-forward-model-fatigue`` change); Hypnos publishes that event in
    ``_run_pipeline`` after all phases complete, which zeroes
    ``FatigueAccumulator`` without requiring a direct module reference here.
    """
    start = _now_ms()
    if thymos is None:
        return PhaseResult(
            phase="affective_reset",
            success=True,
            elapsed_ms=_now_ms() - start,
            metadata={"skipped": "no Thymos available"},
        )
    try:
        await thymos.affective_reset()
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
# Phase 5 — Voice Alignment (orchestrated by module.py directly)
# ---------------------------------------------------------------------------
# Voice alignment is complex enough that it is driven by Hypnos.module
# rather than a standalone phase function.  The PhaseResult for it is
# constructed in module._run_voice_alignment() and appended to the
# phase_results list directly.  This module contains only the helper
# phases 1–4 that phase functions call.


# ---------------------------------------------------------------------------
# Legacy aliases — kept so existing test imports don't break.
# These names are deprecated; prefer the new phase functions above.
# ---------------------------------------------------------------------------

async def consolidate_memory(mnemos: Optional[_SupportsMnemos]) -> PhaseResult:
    """Legacy alias for the pre-restructure memory consolidation step.

    Delegates to ``light_consolidation`` without the oscillator hook,
    producing a ``memory_consolidation`` phase name to maintain backwards
    compatibility with tests that check the old phase name directly.
    """
    start = _now_ms()
    if mnemos is None:
        return PhaseResult(
            phase="memory_consolidation",
            success=True,
            elapsed_ms=_now_ms() - start,
            metadata={"skipped": "no Mnemos available"},
        )
    try:
        moved = await mnemos.consolidate_now()
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


async def revise_beliefs(
    nous_process: Optional[_SupportsStep],
    *,
    step_burst: int,
) -> PhaseResult:
    """Legacy alias for the belief-revision step.

    Retained for backwards-compat with existing tests (test_hypnos_phases.py).
    The paper's five-phase ordering no longer includes a separate
    belief-revision phase; Nous active-inference now runs continuously and
    is not stepped by Hypnos.
    """
    start = _now_ms()
    if nous_process is None or not getattr(nous_process, "running", False):
        return PhaseResult(
            phase="belief_revision",
            success=True,
            elapsed_ms=_now_ms() - start,
            metadata={"skipped": "no Nous available"},
        )
    try:
        lines = await nous_process.step(int(step_burst))
        return PhaseResult(
            phase="belief_revision",
            success=True,
            elapsed_ms=_now_ms() - start,
            metadata={"step_burst": int(step_burst), "lines_emitted": len(lines)},
        )
    except Exception as exc:
        log.exception("belief_revision phase failed")
        return PhaseResult(
            phase="belief_revision",
            success=False,
            elapsed_ms=_now_ms() - start,
            error=f"{type(exc).__name__}: {exc}",
        )


async def reset_affect(thymos: Optional[_SupportsAffectiveReset]) -> PhaseResult:
    """Legacy alias — delegates to ``affective_reset``."""
    return await affective_reset(thymos)


async def recalibrate_time(chronos_resetters: list[Any]) -> PhaseResult:
    """Reset Chronos's habituation / rumination trackers via their reset() methods.

    Each item in ``chronos_resetters`` is anything with a ``reset()`` method
    — typically the detectors stashed inside the Chronos module. The list
    shape lets callers pass several without an introspection dance.
    """
    start = _now_ms()
    if not chronos_resetters:
        return PhaseResult(
            phase="temporal_recalibration",
            success=True,
            elapsed_ms=_now_ms() - start,
            metadata={"skipped": "no Chronos resetters provided"},
        )
    reset = 0
    errors: list[str] = []
    for r in chronos_resetters:
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
