# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Controlled two-arm oscillatory-ablation runner.

Runs the cognitive cycle twice under identical conditions — the same
``set_global_seed(seed)``, the same fixed scripted stimulus, the same
``deterministic=True`` mode — differing in exactly one thing: the **enabled** arm
constructs a real ``CoherenceScorer`` (configurable precision gain); the
**disabled** arm passes ``coherence=None`` (the layer-absent baseline). Because
deterministic mode + the same seed + the same input make a run bit-for-bit
reproducible, the ONLY difference between the arms is the coherence layer, so any
trajectory difference is attributable to precision modulation alone.

Effect metric
-------------
- **selection_divergence_fraction** — fraction of experiential ticks on which the
  top-ranked selected entry (``entry_id``/``source``/``type``) differs between
  arms. Exactly 0 iff the layer never changed the winner.
- **mean_ranking_divergence** — mean normalized Spearman footrule distance between
  the two arms' per-tick salience rankings, capturing re-ordering below the top.
- **coherence_alignment_delta** — the *directional* metric: the fraction of ticks
  on which the enabled arm's top source is phase-coherent (a hypothesized target)
  minus the same fraction for the disabled arm. Positive means enabling the layer
  moved selection TOWARD coherent coalitions (the hypothesized direction);
  negative means it moved AWAY (an adverse result). Requires a battery with a
  ground-truth coherent set; it is 0 (undefined) for the neutral battery.

Verdict (falsifiable — WIN / NULL / NEGATIVE are all reachable)
---------------------------------------------------------------
- **NULL** when ``selection_divergence_fraction <= min_effect`` — the layer makes
  no meaningful change to selection on this stimulus (e.g. the neutral battery,
  which has no coherence structure to exploit). Justifies removing the layer.
- **NEGATIVE** when the change is meaningful (``> min_effect``) but adverse:
  ``coherence_alignment_delta <= -min_alignment`` — the layer re-ranks selection
  AWAY from coherent coalitions, contradicting the hypothesis.
- **WIN** when the change is meaningful AND not adverse (on the engineered
  battery: it promotes the phase-locked coalition).

Because ``min_effect`` is a real non-zero threshold and NEGATIVE is a first-class
outcome, the runner can return a result adverse to the hypothesis — the
falsification test the paper's §6.4 / §9.3 frame, not merely a wiring check. The
disabled arm remains the bit-for-bit layer-absent baseline.

Honest structural note (two-sided falsification)
------------------------------------------------
The coherence layer (``CoherenceScorer.factor_from_plv``) is strictly monotone in
PLV with ``floor <= ceiling``, so with a CORRECTLY-labeled coherent coalition it
can only push more-phase-locked sources UP — a correctly-labeled battery can
therefore only ever return WIN or NULL, never NEGATIVE. NEGATIVE is reachable
through the real pipeline via the ``mislabeled`` battery
(``MISLABELED_STIMULUS``), where the ``coherent=True`` ground-truth label is put
on a high-salience source that is NOT the most phase-locked, while the truly
synchronized source is labeled ``coherent=False``. The honest layer then promotes
the truly-synchronized (labeled-False) source over the labeled-coherent decoy,
yielding a genuinely negative ``coherence_alignment_delta`` from
``_run_arm``/``_compute_effect`` — not a hand-fed classifier input. So NEGATIVE
specifically probes a LABEL/REALITY MISMATCH: the layer tracking a coherence the
ground-truth label disagrees with (e.g. a mis-specified coalition), which is
exactly the "the layer is tracking the wrong thing" failure the paper must be
able to report.

Offline: drives only the engine + Syneidesis + Volition over a scripted in-memory
bus. No live modules, no entity boot, no network.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from kaine.cycle.engine import CognitiveCycle
from kaine.evaluation.benchmarks import write_jsonl
from kaine.evaluation.benchmarks.oscillatory_ablation.stimulus import (
    ENGINEERED_STIMULUS,
    ScriptedBus,
    Stimulus,
)
from kaine.experiment.seeding import set_global_seed
from kaine.experiment.verdict import Outcome, Verdict
from kaine.workspace import (
    NoveltyTracker,
    RuleBasedSalience,
    StaticGoalScorer,
    StaticThymosModulator,
    Syneidesis,
)
from kaine.workspace.coherence import CoherenceScorer
from kaine.workspace.volition import Volition

log = logging.getLogger(__name__)


class _MonotonicClock:
    """Deterministic monotonic float clock (slip is irrelevant offline)."""

    def __init__(self) -> None:
        self._t = 0.0

    def __call__(self) -> float:
        self._t += 0.001
        return self._t


async def _async_noop(_seconds: float) -> None:
    return None


@dataclass(frozen=True)
class AblationConfig:
    """Runner parameters (all seeded for reproducibility)."""

    seed: int = 1234
    # Enough ticks for the PLV sliding windows to fill so the desynchronized
    # sources' coherence factor collapses and the phase-locked coalition can
    # overtake them — the controlled effect the runner measures.
    ticks: int = 16
    plv_window: int = 12
    coherence_floor: float = 0.05
    coherence_ceiling: float = 8.0
    # A change in selection below this fraction is NULL ("no meaningful effect").
    # Non-zero so a layer that barely nudges selection cannot pass as a WIN — the
    # honest falsification threshold the paper's §6.4 / §9.3 promise. Below this,
    # the runner reports NULL and the layer's removal is justified.
    min_effect: float = 0.10
    # A meaningful change (> min_effect) whose directional alignment is at or
    # below -min_alignment is NEGATIVE (adverse): the layer re-ranks AWAY from the
    # coherent coalition. Only defined on a battery with a ground-truth coherent
    # set (the engineered battery); ignored when that set is empty (neutral).
    min_alignment: float = 0.10
    top_k: int = 4
    publication_threshold: float = 0.0

    def __post_init__(self) -> None:
        # Fail fast on an invalid coherence gain, symmetric with CoherenceScorer.
        # A non-positive ceiling collapses every score to 0 → a degenerate tie
        # whose sort order is an artefact (it would masquerade as a false WIN).
        # floor == ceiling > 0 (the unit-gain null control) stays valid.
        if not 0.0 <= self.coherence_floor <= self.coherence_ceiling:
            raise ValueError(
                "require 0.0 <= coherence_floor <= coherence_ceiling, got "
                f"floor={self.coherence_floor}, ceiling={self.coherence_ceiling}"
            )
        if self.coherence_ceiling <= 0.0:
            raise ValueError(
                "coherence_ceiling must be > 0 (a non-positive ceiling zeroes "
                f"every salience score); got ceiling={self.coherence_ceiling}"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "ticks": self.ticks,
            "plv_window": self.plv_window,
            "coherence_floor": self.coherence_floor,
            "coherence_ceiling": self.coherence_ceiling,
            "min_effect": self.min_effect,
            "min_alignment": self.min_alignment,
            "top_k": self.top_k,
            "publication_threshold": self.publication_threshold,
        }


def _build_syneidesis(
    config: AblationConfig, coherence: Optional[CoherenceScorer]
) -> Syneidesis:
    return Syneidesis(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=32),
            goal_scorer=StaticGoalScorer(),
            thymos_modulator=StaticThymosModulator(),
        ),
        top_k=config.top_k,
        publication_threshold=config.publication_threshold,
        coherence=coherence,
    )


async def _run_arm(
    config: AblationConfig,
    *,
    enabled: bool,
    stimulus: Stimulus = ENGINEERED_STIMULUS,
) -> list[dict[str, Any]]:
    """Run one arm for ``ticks`` ticks; return the per-tick trajectory.

    The enabled arm builds a real ``CoherenceScorer`` and collects scripted
    phases; the disabled arm passes ``coherence=None`` and does NOT collect
    phases, so it is bit-for-bit the layer-absent baseline. Both arms re-seed
    with the same global seed and read the same scripted stimulus.
    """
    set_global_seed(config.seed)
    bus = ScriptedBus(stimulus.streams(config.ticks))
    scorer = (
        CoherenceScorer(
            plv_window=config.plv_window,
            coherence_floor=config.coherence_floor,
            coherence_ceiling=config.coherence_ceiling,
        )
        if enabled
        else None
    )
    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=_build_syneidesis(config, scorer),
        registry=stimulus.registry(),
        volition=Volition(),
        clock=_MonotonicClock(),
        sleep=_async_noop,
        collect_phases=enabled,
        deterministic=True,
    )
    for _ in range(config.ticks):
        # Reveal this tick's events (one per source) before the cycle reads,
        # emulating a live stream where future events do not exist yet.
        bus.advance()
        await cycle.tick()
    return [_normalize_broadcast(b) for b in bus.workspace_broadcasts]


def _normalize_broadcast(b: dict[str, Any]) -> dict[str, Any]:
    """Project a workspace broadcast to its determinism-relevant fields.

    Excludes wall-clock latency (never present here) and the coherence metadata
    value, which is by construction only present on the enabled arm — comparing
    it would trivially differ and is not the property under test.
    """
    return {
        "tick_index": b["tick_index"],
        "inhibited": b["inhibited"],
        "is_experiential": b["is_experiential"],
        "salience_scores": dict(b["salience_scores"]),
        "selected": [
            {
                "entry_id": s["entry_id"],
                "source": s["source"],
                "type": s["type"],
                "salience": s["salience"],
            }
            for s in b["selected"]
        ],
    }


def _top_entry_key(tick: dict[str, Any]) -> Optional[tuple[str, str, str]]:
    selected = tick["selected"]
    if not selected:
        return None
    top = selected[0]
    return (top["entry_id"], top["source"], top["type"])


def _top_source(tick: dict[str, Any]) -> Optional[str]:
    selected = tick["selected"]
    return selected[0]["source"] if selected else None


def _ranking(tick: dict[str, Any]) -> list[str]:
    """Entry ids in descending salience order (the arm's selection ranking)."""
    return [s["entry_id"] for s in tick["selected"]]


def _normalized_footrule(rank_a: list[str], rank_b: list[str]) -> float:
    """Normalized Spearman footrule distance between two rankings in [0, 1].

    Items present in only one ranking are placed past the end of the other.
    Returns 0.0 when both rankings are identical (and 0.0 for two empties).
    """
    items = set(rank_a) | set(rank_b)
    n = len(items)
    if n == 0:
        return 0.0
    pos_a = {item: i for i, item in enumerate(rank_a)}
    pos_b = {item: i for i, item in enumerate(rank_b)}
    missing = n  # rank assigned to an item absent from a list
    total = 0
    for item in items:
        total += abs(pos_a.get(item, missing) - pos_b.get(item, missing))
    # Max footrule for n items is floor(n^2 / 2); normalize to [0, 1].
    max_dist = (n * n) // 2
    if max_dist == 0:
        return 0.0
    return total / max_dist


def _compute_effect(
    enabled_traj: list[dict[str, Any]],
    disabled_traj: list[dict[str, Any]],
    coherent_sources: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Effect of precision modulation on selection across the two trajectories.

    ``coherent_sources`` is the ground-truth set of phase-coherent sources (the
    layer's hypothesized targets). When non-empty, ``coherence_alignment_delta``
    scores the DIRECTION of any re-ranking: positive iff enabling the layer moves
    the top selection toward coherent sources. When empty (neutral battery) the
    direction is undefined and the delta is 0.0.
    """
    n = min(len(enabled_traj), len(disabled_traj))
    top_diffs = 0
    footrule_sum = 0.0
    enabled_coherent_top = 0
    disabled_coherent_top = 0
    per_tick: list[dict[str, Any]] = []
    for i in range(n):
        en = enabled_traj[i]
        di = disabled_traj[i]
        top_differs = _top_entry_key(en) != _top_entry_key(di)
        footrule = _normalized_footrule(_ranking(en), _ranking(di))
        if top_differs:
            top_diffs += 1
        footrule_sum += footrule
        en_top_src = _top_source(en)
        di_top_src = _top_source(di)
        if en_top_src in coherent_sources:
            enabled_coherent_top += 1
        if di_top_src in coherent_sources:
            disabled_coherent_top += 1
        per_tick.append(
            {
                "tick_index": en["tick_index"],
                "top_differs": top_differs,
                "ranking_divergence": footrule,
                "enabled_top": _top_entry_key(en),
                "disabled_top": _top_entry_key(di),
            }
        )
    sel_frac = (top_diffs / n) if n else 0.0
    mean_rank_div = (footrule_sum / n) if n else 0.0
    # Directional: fraction of ticks the enabled arm's top is coherent minus the
    # disabled arm's. Only meaningful when a coherent set exists; else 0.0.
    if coherent_sources and n:
        alignment_delta = (enabled_coherent_top - disabled_coherent_top) / n
    else:
        alignment_delta = 0.0
    return {
        "n_ticks_compared": n,
        "ticks_top_differs": top_diffs,
        "selection_divergence_fraction": sel_frac,
        "mean_ranking_divergence": mean_rank_div,
        "coherence_alignment_delta": alignment_delta,
        "enabled_coherent_top_ticks": enabled_coherent_top,
        "disabled_coherent_top_ticks": disabled_coherent_top,
        "has_coherent_ground_truth": bool(coherent_sources),
        "per_tick": per_tick,
    }


def _classify(effect: dict[str, Any], config: AblationConfig) -> Verdict:
    """Classify the layer's effect as WIN / NULL / NEGATIVE.

    - NULL when the selection change is below ``min_effect`` (no meaningful
      effect — the layer's removal is justified);
    - NEGATIVE when the change is meaningful but adverse (re-ranks away from the
      coherent coalition: ``coherence_alignment_delta <= -min_alignment``);
    - WIN otherwise (a meaningful, non-adverse change).

    All three are first-class and reachable, so the runner can return a result
    adverse to the hypothesis rather than being wired to always WIN.
    """
    sel_frac = float(effect["selection_divergence_fraction"])
    alignment = float(effect.get("coherence_alignment_delta", 0.0))
    has_truth = bool(effect.get("has_coherent_ground_truth", False))

    if sel_frac <= config.min_effect:
        outcome = Outcome.NULL
        detail = (
            "coherence layer produces no meaningful change in selection "
            f"(selection divergence {sel_frac:.3f} <= min_effect {config.min_effect})"
        )
    elif has_truth and alignment <= -config.min_alignment:
        outcome = Outcome.NEGATIVE
        detail = (
            "coherence layer meaningfully re-ranks selection AWAY from the "
            f"coherent coalition (alignment {alignment:.3f} <= -{config.min_alignment}) "
            "— adverse to the hypothesis"
        )
    else:
        outcome = Outcome.WIN
        detail = (
            "coherence layer meaningfully changes selection"
            + (
                " toward the coherent coalition"
                if has_truth and alignment > 0.0
                else ""
            )
        )
    return Verdict(
        outcome=outcome,
        detail=detail,
        metrics={
            "selection_divergence_fraction": sel_frac,
            "mean_ranking_divergence": float(effect["mean_ranking_divergence"]),
            "coherence_alignment_delta": alignment,
            "has_coherent_ground_truth": has_truth,
            "ticks_top_differs": int(effect["ticks_top_differs"]),
            "n_ticks_compared": int(effect["n_ticks_compared"]),
            "min_effect": config.min_effect,
            "min_alignment": config.min_alignment,
        },
    )


def _trajectory_digest(traj: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact per-tick digest of an arm's trajectory for the JSONL record."""
    return [
        {
            "tick_index": t["tick_index"],
            "inhibited": t["inhibited"],
            "is_experiential": t["is_experiential"],
            "selected": [
                (s["entry_id"], s["source"], round(s["salience"], 6))
                for s in t["selected"]
            ],
        }
        for t in traj
    ]


async def run_ablation(
    config: Optional[AblationConfig] = None,
    *,
    stimulus: Stimulus = ENGINEERED_STIMULUS,
) -> dict[str, Any]:
    """Run the controlled ablation; return records + summary + verdict.

    The disabled arm is the layer-absent baseline; the enabled arm differs only
    in carrying a real ``CoherenceScorer``. Same seed + same scripted input +
    deterministic mode ⇒ any difference is the layer's effect.

    ``stimulus`` selects the battery: the engineered (positive-control) battery
    by default, or the neutral (non-engineered) battery on which a NULL is
    reachable. The verdict can be WIN, NULL, or NEGATIVE (adverse).
    """
    config = config or AblationConfig()
    enabled_traj = await _run_arm(config, enabled=True, stimulus=stimulus)
    disabled_traj = await _run_arm(config, enabled=False, stimulus=stimulus)
    effect = _compute_effect(enabled_traj, disabled_traj, stimulus.coherent_sources)
    verdict = _classify(effect, config)
    ts = datetime.now(timezone.utc).isoformat()

    records: list[dict[str, Any]] = [
        {
            "ts": ts,
            "kind": "arm",
            "arm": "enabled",
            "stimulus": stimulus.name,
            "trajectory": _trajectory_digest(enabled_traj),
        },
        {
            "ts": ts,
            "kind": "arm",
            "arm": "disabled",
            "stimulus": stimulus.name,
            "trajectory": _trajectory_digest(disabled_traj),
        },
        {
            "ts": ts,
            "kind": "verdict",
            "config": config.as_dict(),
            "stimulus": stimulus.name,
            "effect": {k: v for k, v in effect.items() if k != "per_tick"},
            "per_tick": effect["per_tick"],
            "verdict": verdict.to_dict(),
        },
    ]
    summary = {
        "ts": ts,
        "kind": "summary",
        "config": config.as_dict(),
        "stimulus": stimulus.name,
        "selection_divergence_fraction": effect["selection_divergence_fraction"],
        "mean_ranking_divergence": effect["mean_ranking_divergence"],
        "coherence_alignment_delta": effect["coherence_alignment_delta"],
        "verdict": verdict.to_dict(),
    }
    records.append(summary)
    return {
        "records": records,
        "summary": summary,
        "verdict": verdict,
        "effect": effect,
        "enabled_trajectory": enabled_traj,
        "disabled_trajectory": disabled_traj,
    }


def format_summary(result: dict[str, Any]) -> str:
    """Human-readable summary; states WIN/NULL plainly."""
    summary = result["summary"]
    v = summary["verdict"]
    lines: list[str] = []
    lines.append("Oscillatory ablation: coherence layer ENABLED vs DISABLED")
    lines.append("=" * 60)
    cfg = summary["config"]
    lines.append(
        f"seed={cfg['seed']} ticks={cfg['ticks']} "
        f"gain=[{cfg['coherence_floor']}, {cfg['coherence_ceiling']}] "
        f"plv_window={cfg['plv_window']}"
    )
    lines.append(
        f"selection_divergence_fraction = {summary['selection_divergence_fraction']:.4f}"
    )
    lines.append(
        f"mean_ranking_divergence      = {summary['mean_ranking_divergence']:.4f}"
    )
    lines.append(
        f"coherence_alignment_delta    = {summary['coherence_alignment_delta']:.4f}"
    )
    lines.append(f"stimulus: {summary.get('stimulus', 'engineered_phase_locked')}")
    lines.append(f"VERDICT: {v['outcome']} — {v['detail']}")
    if v["outcome"] == Outcome.WIN.value:
        lines.append(
            "  WIN = the layer is wired to selection AND measurably re-ranks it "
            "under identical seed + input (difference attributable to the layer alone)."
        )
    elif v["outcome"] == Outcome.NEGATIVE.value:
        lines.append(
            "  NEGATIVE = the layer meaningfully re-ranks selection AWAY from the "
            "coherent coalition — a result adverse to the hypothesis, reported "
            "honestly, not a harness failure."
        )
    else:
        lines.append(
            "  NULL = the layer produced no meaningful change in selection on this "
            "stimulus (its removal would be justified). A reportable result, not a "
            "harness failure."
        )
    return "\n".join(lines)


__all__ = [
    "AblationConfig",
    "run_ablation",
    "write_jsonl",
    "format_summary",
]
