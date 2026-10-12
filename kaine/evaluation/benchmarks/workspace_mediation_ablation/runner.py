# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Two-arm workspace-mediation development harness over REAL Soma and Topos.

The workspace-on arm uses Syneidesis to competitively select a coalition each
tick from the candidate events (Soma's report, Topos's report, and scripted
background events). The pooled arm admits every candidate weighted by its own
salience, with no scoring, selection, access gate, or inhibition.

Both arms use the same seed, the same stimulus, and identically initialized
modules. They diverge only through the snapshots they receive.

The measure is the cross-module broadcast information gain. Soma and Topos
each publish ``context_gain`` on their report payload. IG_j is the mean gain
for processor j over post-warmup reports with finite gains. The headline IG is
the mean of IG_j across processors and is undefined when any IG_j is
undefined. The contrast is dIG = IG(workspace_on) - IG(pooled).

Offline: no entity boot, no network, no live module loops. The modules are
driven by hand (``tick_once`` / ``process_frame`` / ``on_workspace``) so the
run is reproducible.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from kaine.bus.schema import Event
from kaine.entity_clock import EntityClock
from kaine.evaluation.benchmarks import write_jsonl
from kaine.evaluation.benchmarks.oscillatory_ablation.stimulus import ScriptedBus
from kaine.evaluation.benchmarks.workspace_mediation_ablation.measures import (
    headline_gain,
    mean_gain,
)
from kaine.evaluation.benchmarks.workspace_mediation_ablation.pooled import pooled_snapshot
from kaine.evaluation.benchmarks.workspace_mediation_ablation.stimulus import (
    COUPLED_STIMULUS,
    LATENT_DIM,
    MediationStimulus,
    ScriptedMetricsReader,
    StimulusScript,
    VectorEncoder,
)
from kaine.experiment.seeding import set_global_seed
from kaine.experiment.verdict import Outcome, Verdict
from kaine.modules.context import CONTEXT_DIM
from kaine.modules.soma import AlertResult
from kaine.modules.soma.module import Soma
from kaine.modules.topos.forward import LatentForwardModel
from kaine.modules.topos.module import Topos
from kaine.workspace import (
    NoveltyTracker,
    RuleBasedSalience,
    StaticGoalScorer,
    StaticThymosModulator,
    Syneidesis,
)

ARMS: tuple[str, ...] = ("workspace_on", "pooled")
PROCESSORS: tuple[str, ...] = ("soma", "topos")


class _NeverAlertDetector:
    """Interoception anomaly detector that never alerts, so Interoception's published salience is
    driven by its prediction error (the information-gain signal) rather than by
    a threshold alarm."""

    def evaluate(self, metrics: dict[str, float]) -> AlertResult:
        return AlertResult()


@dataclass(frozen=True)
class MediationConfig:
    """Runner parameters (all seeded for reproducibility)."""

    seed: int = 1234
    ticks: int = 160
    warmup_ticks: int = 40
    top_k: int = 2
    access_threshold: float = 0.05
    min_effect: float = 0.05
    n_background: int = 2
    soma_units: int = 16
    topos_units: int = 32
    # The harness raises Vision's learning rate so a short run shows learning;
    # the live module keeps its own default.
    topos_lr: float = 0.02

    def __post_init__(self) -> None:
        if self.top_k <= 0:
            raise ValueError("top_k must be positive")
        if self.warmup_ticks < 0:
            raise ValueError("warmup_ticks must be >= 0")
        if self.ticks <= self.warmup_ticks:
            raise ValueError("ticks must be greater than warmup_ticks")
        if not 0.0 <= self.access_threshold <= 1.0:
            raise ValueError("access_threshold must be in [0.0, 1.0]")
        if self.min_effect < 0:
            raise ValueError("min_effect must be >= 0")
        if self.n_background < 0:
            raise ValueError("n_background must be >= 0")
        if self.topos_lr <= 0:
            raise ValueError("topos_lr must be positive")

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "ticks": self.ticks,
            "warmup_ticks": self.warmup_ticks,
            "top_k": self.top_k,
            "access_threshold": self.access_threshold,
            "min_effect": self.min_effect,
            "n_background": self.n_background,
            "soma_units": self.soma_units,
            "topos_units": self.topos_units,
            "topos_lr": self.topos_lr,
        }


def _build_syneidesis(config: MediationConfig) -> Syneidesis:
    return Syneidesis(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=32),
            goal_scorer=StaticGoalScorer(),
            thymos_modulator=StaticThymosModulator(),
        ),
        top_k=config.top_k,
        publication_threshold=config.access_threshold,
        coherence=None,
    )


def _last_report(bus: ScriptedBus, source: str, etype: str) -> Optional[Event]:
    events = [e for e in bus.published.get(source, []) if e.type == etype]
    return events[-1] if events else None


def _read_float(payload: dict[str, Any], key: str, default: float) -> float:
    val = payload.get(key, default)
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _read_error(payload: dict[str, Any]) -> Optional[float]:
    """A report's prediction error, or None when it has none (a skipped reading)."""
    val = payload.get("prediction_error")
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _read_gain(payload: dict[str, Any]) -> Optional[float]:
    val = payload.get("context_gain")
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


async def _run_arm(
    config: MediationConfig,
    script: StimulusScript,
    arm: str,
) -> dict[str, Any]:
    """Run one arm of the ablation; return its raw gain/error series and summaries."""
    set_global_seed(config.seed)
    clock = [0.0]

    soma_bus = ScriptedBus({})
    soma = Soma(
        soma_bus,
        reader=ScriptedMetricsReader(script.soma_metrics),
        detector=_NeverAlertDetector(),
        forward_model_units=config.soma_units,
        reservoir_seed=config.seed + 1,
        cfc_backend="numpy",
        entity_clock=EntityClock(monotonic=lambda: clock[0]),
    )

    topos_bus = ScriptedBus({})
    encoder = VectorEncoder(LATENT_DIM)
    topos = Topos(
        topos_bus,
        encoder=encoder,
        forward_prediction=True,
        forward_model_units=config.topos_units,
        entity_clock=EntityClock(monotonic=lambda: clock[0]),
    )
    topos._forward_model = LatentForwardModel(
        latent_dim=LATENT_DIM,
        units=config.topos_units,
        lr=config.topos_lr,
        seed=config.seed + 2,
        context_dim=CONTEXT_DIM,
    )

    syn = _build_syneidesis(config) if arm == "workspace_on" else None

    soma_gains: list[Optional[float]] = []
    topos_gains: list[Optional[float]] = []
    soma_errors: list[Optional[float]] = []
    topos_errors: list[Optional[float]] = []
    competing_ticks = 0
    accessed_broadcasts = 0
    coalition_sizes: list[int] = []

    for t in range(config.ticks):
        clock[0] = float(t)

        await soma.tick_once()
        soma_report = _last_report(soma_bus, "soma", "soma.report")
        soma_errors.append(
            _read_error(soma_report.payload)
            if soma_report is not None
            else 0.0
        )

        await topos.process_frame(script.topos_frames[t])
        topos_report = _last_report(topos_bus, "topos", "topos.report")
        topos_errors.append(
            _read_error(topos_report.payload)
            if topos_report is not None
            else 0.0
        )

        candidates: list[tuple[str, Event]] = []
        if soma_report is not None:
            candidates.append((f"{t + 1}-s", soma_report))
        if topos_report is not None:
            candidates.append((f"{t + 1}-t", topos_report))
        for k, ev in enumerate(script.background[t]):
            candidates.append((f"{t + 1}-b{k}", ev))

        if arm == "workspace_on":
            assert syn is not None
            if len(candidates) > config.top_k:
                competing_ticks += 1
            snapshot = await syn.select(candidates, {"tick_index": t})
            if not snapshot.inhibited:
                for entry_id, event in snapshot.selected_events:
                    score = snapshot.salience_scores.get(entry_id, event.salience)
                    if score >= config.access_threshold:
                        accessed_broadcasts += 1
                        break
            coalition_sizes.append(len(snapshot.selected_events))
        else:
            snapshot = pooled_snapshot(t, candidates)
            coalition_sizes.append(len(candidates))

        await soma.on_workspace(snapshot)
        await topos.on_workspace(snapshot)

        soma_gains.append(
            _read_gain(soma_report.payload) if soma_report is not None else None
        )
        topos_gains.append(
            _read_gain(topos_report.payload) if topos_report is not None else None
        )

    included_reports = {
        "soma": sum(
            1
            for i, g in enumerate(soma_gains)
            if i >= config.warmup_ticks and g is not None and math.isfinite(g)
        ),
        "topos": sum(
            1
            for i, g in enumerate(topos_gains)
            if i >= config.warmup_ticks and g is not None and math.isfinite(g)
        ),
    }
    ig_by_processor = {
        "soma": mean_gain(soma_gains, skip=config.warmup_ticks),
        "topos": mean_gain(topos_gains, skip=config.warmup_ticks),
    }
    ig = headline_gain(ig_by_processor)

    return {
        "soma_gain": soma_gains,
        "topos_gain": topos_gains,
        "soma_error": soma_errors,
        "topos_error": topos_errors,
        "competing_ticks": competing_ticks,
        "accessed_broadcasts": accessed_broadcasts,
        "coalition_sizes": coalition_sizes,
        "ig_by_processor": ig_by_processor,
        "ig": ig,
        "included_reports": included_reports,
    }


def _compute_effect(
    config: MediationConfig,
    on: dict[str, Any],
    pooled: dict[str, Any],
) -> dict[str, Any]:
    ig_on = on["ig"]
    ig_pooled = pooled["ig"]
    dig = ig_on - ig_pooled if ig_on is not None and ig_pooled is not None else None

    competing_fraction = on["competing_ticks"] / config.ticks if config.ticks else 0.0

    not_exercised = False
    not_exercised_reason: Optional[str] = None
    if on["competing_ticks"] == 0:
        not_exercised = True
        not_exercised_reason = (
            "competition never operated: the workspace-on arm never had more candidates than top_k"
        )
    elif on["accessed_broadcasts"] == 0:
        not_exercised = True
        not_exercised_reason = "the workspace-on arm had no accessed broadcast"
    elif ig_on is None or ig_pooled is None:
        not_exercised = True
        not_exercised_reason = "information gain undefined in an arm"

    return {
        "ig_on": ig_on,
        "ig_pooled": ig_pooled,
        "ig_on_by_processor": on["ig_by_processor"],
        "ig_pooled_by_processor": pooled["ig_by_processor"],
        "included_reports_on": on["included_reports"],
        "included_reports_pooled": pooled["included_reports"],
        "dig": dig,
        "competing_ticks": on["competing_ticks"],
        "competing_fraction": competing_fraction,
        "accessed_broadcasts": on["accessed_broadcasts"],
        "n_ticks": config.ticks,
        "warmup_ticks": config.warmup_ticks,
        "not_exercised": not_exercised,
        "not_exercised_reason": not_exercised_reason,
    }


_HARNESS_SUFFIX = (
    "Development harness: a reduced pair against a pooled arm only; "
    "it does not test the thesis."
)


def _classify(effect: dict[str, Any], config: MediationConfig) -> Verdict:
    dig = effect["dig"]
    metrics = {
        "dig": dig,
        "ig_on": effect["ig_on"],
        "ig_pooled": effect["ig_pooled"],
        "ig_on_by_processor": effect["ig_on_by_processor"],
        "ig_pooled_by_processor": effect["ig_pooled_by_processor"],
        "competing_fraction": effect["competing_fraction"],
        "accessed_broadcasts": effect["accessed_broadcasts"],
        "min_effect": config.min_effect,
        "not_exercised_reason": effect["not_exercised_reason"],
    }

    if effect["not_exercised"]:
        reason = effect["not_exercised_reason"]
        return Verdict(
            outcome=Outcome.NOT_EXERCISED,
            detail=f"{reason}. {_HARNESS_SUFFIX}",
            metrics=metrics,
        )

    assert dig is not None
    if dig >= config.min_effect:
        return Verdict(
            outcome=Outcome.WIN,
            detail=(
                f"competitive selection gives a higher information gain than pooling "
                f"(dIG {dig:.4f} >= {config.min_effect}). {_HARNESS_SUFFIX}"
            ),
            metrics=metrics,
        )
    if dig <= -config.min_effect:
        return Verdict(
            outcome=Outcome.NEGATIVE,
            detail=(
                f"pooling gives a higher information gain than competitive selection "
                f"(dIG {dig:.4f} <= -{config.min_effect}). {_HARNESS_SUFFIX}"
            ),
            metrics=metrics,
        )
    return Verdict(
        outcome=Outcome.NULL,
        detail=(
            f"competitive selection and pooling give the same information gain within "
            f"the minimum effect (dIG {dig:.4f}, |dIG| < {config.min_effect}). "
            f"{_HARNESS_SUFFIX}"
        ),
        metrics=metrics,
    )


async def run_ablation(
    config: Optional[MediationConfig] = None,
    *,
    stimulus: MediationStimulus = COUPLED_STIMULUS,
) -> dict[str, Any]:
    """Run the two-arm workspace-mediation development harness; return records."""
    config = config or MediationConfig()
    script = stimulus.script(
        config.seed, config.ticks, n_background=config.n_background
    )

    on = await _run_arm(config, script, "workspace_on")
    pooled = await _run_arm(config, script, "pooled")
    effect = _compute_effect(config, on, pooled)
    verdict = _classify(effect, config)
    ts = datetime.now(timezone.utc).isoformat()

    records: list[dict[str, Any]] = [
        {
            "ts": ts,
            "kind": "arm",
            "arm": "workspace_on",
            "stimulus": stimulus.name,
            **on,
        },
        {
            "ts": ts,
            "kind": "arm",
            "arm": "pooled",
            "stimulus": stimulus.name,
            **pooled,
        },
        {
            "ts": ts,
            "kind": "verdict",
            "config": config.as_dict(),
            "stimulus": stimulus.name,
            "effect": effect,
            "verdict": verdict.to_dict(),
        },
    ]
    summary = {
        "ts": ts,
        "kind": "summary",
        "config": config.as_dict(),
        "stimulus": stimulus.name,
        "effect": effect,
        "verdict": verdict.to_dict(),
    }
    records.append(summary)
    return {
        "records": records,
        "summary": summary,
        "verdict": verdict,
        "effect": effect,
    }


def format_summary(result: dict[str, Any]) -> str:
    """Human-readable summary; states WIN/NULL/NEGATIVE plainly."""
    summary = result["summary"]
    eff = summary["effect"]
    v = summary["verdict"]
    cfg = summary["config"]

    def fmt(value: Any) -> str:
        if value is None:
            return "undefined"
        if isinstance(value, float):
            return f"{value:.4f}"
        if isinstance(value, dict):
            return (
                "{"
                + ", ".join(f"{k!r}: {fmt(val)}" for k, val in value.items())
                + "}"
            )
        return str(value)

    lines = [
        "Workspace-mediation development harness: workspace on against pooled",
        "=" * 70,
        f"seed={cfg['seed']} ticks={cfg['ticks']} warmup_ticks={cfg['warmup_ticks']} "
        f"top_k={cfg['top_k']} access_threshold={cfg['access_threshold']}",
        f"stimulus: {summary['stimulus']}",
        f"IG(workspace_on)              = {fmt(eff['ig_on'])}",
        f"IG(pooled)                    = {fmt(eff['ig_pooled'])}",
        f"IG(workspace_on) by processor = {fmt(eff['ig_on_by_processor'])}",
        f"IG(pooled) by processor       = {fmt(eff['ig_pooled_by_processor'])}",
        f"dIG                           = {fmt(eff['dig'])}",
        f"competing_fraction            = {eff['competing_fraction']:.3f}",
        f"accessed_broadcasts           = {eff['accessed_broadcasts']}",
        f"VERDICT: {v['outcome']}: {v['detail']}",
        "This harness is development tooling and does not test the thesis.",
    ]
    return "\n".join(lines)


__all__ = [
    "ARMS",
    "PROCESSORS",
    "MediationConfig",
    "run_ablation",
    "format_summary",
    "write_jsonl",
]
