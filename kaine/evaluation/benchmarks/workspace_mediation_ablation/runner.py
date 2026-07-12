# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Two-arm workspace-mediation ablation over the REAL Soma and Chronos modules.

The system as built (workspace-on) is run against a matched fan-in prompt-
assembler control (workspace-off), differing ONLY in how the modules and the
language organ are conditioned:

* **workspace-on** — each tick, Syneidesis competitively selects a coalition from
  the candidate events (Soma's report, injected utterances, the previous tick's
  Chronos report) above ``top_k``; Chronos predicts that coalition; the coalition
  is what conditions the organ.
* **workspace-off** — the same candidates are handed to the organ (and to
  Chronos) as a FLAT snapshot: no scoring, no top-k, no inhibition, no
  competition. Same information, no structure.

Determinism: Soma runs against a scripted ``MetricsReader`` and an injected
clock; both Chronos arms are built from the same seeds, so they start identical
and diverge only because they receive different snapshots. Soma does not read the
broadcast, so its error series is arm-independent — it is run once and shared.

Measures (primary = trajectory structure; secondary = output divergence):
* **coupling_delta** — mean sliding-window Pearson correlation between Soma's and
  Chronos's error series, workspace-on MINUS workspace-off. The thesis predicts a
  positive delta: competitive selection concentrates the salient signal into the
  coalition Chronos predicts, coupling the two modules more than flat fan-in does.
* **coalition entropy** — Shannon entropy of the on-arm selected-source sequence;
  a non-trivial workspace selects different sources as state changes.
* **conditioning divergence** — cosine distance between the two arms' rendered
  workspace content (the deterministic offline proxy for greedy-decoded organ
  output divergence: with a greedy organ, output is a function of conditioning).

Verdict: WIN (positive coupling_delta above ``min_effect`` with non-trivial
selection), NULL (delta within ``min_effect`` — the fan-in prompt-assembler
outcome), or NEGATIVE (delta at or below ``-min_effect`` — competitive mediation
adverse to the thesis). A run where Soma never enters the coalition, or where the
correlation is undefined, is flagged UNDERPOWERED rather than reported as a clean
NULL.

Offline: no entity boot, no network, no live modules' async loops — the modules
are driven by hand (``tick_once`` / ``on_workspace``) so the run is reproducible.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.entity_clock import EntityClock
from kaine.evaluation.benchmarks import write_jsonl
from kaine.evaluation.benchmarks.oscillatory_ablation.stimulus import ScriptedBus
from kaine.evaluation.benchmarks.workspace_mediation_ablation.conditioning import (
    flat_fan_in_snapshot,
)
from kaine.evaluation.benchmarks.workspace_mediation_ablation.measures import (
    entropy_fraction,
    mean_windowed_correlation,
    shannon_entropy,
)
from kaine.evaluation.benchmarks.workspace_mediation_ablation.stimulus import (
    SOMA_SALIENT_STIMULUS,
    MediationStimulus,
    ScriptedMetricsReader,
)
from kaine.experiment.seeding import set_global_seed
from kaine.experiment.verdict import Outcome, Verdict
from kaine.faithful.renderer import FaithfulRenderer
from kaine.modules.chronos.featurizer import SnapshotFeaturizer
from kaine.modules.chronos.module import Chronos
from kaine.modules.chronos.network import CfCNetwork, ForwardPredictionHead
from kaine.modules.soma import AlertResult
from kaine.modules.soma.module import Soma
from kaine.text_embedding import HashEmbedder, cosine_similarity
from kaine.workspace import (
    NoveltyTracker,
    RuleBasedSalience,
    StaticGoalScorer,
    StaticThymosModulator,
    Syneidesis,
)


class _NeverAlertDetector:
    """Soma anomaly detector that never alerts, so Soma's published salience is
    driven by its prediction error (the coupling signal) rather than by a
    threshold alarm."""

    def evaluate(self, metrics: dict[str, float]) -> AlertResult:
        return AlertResult()


@dataclass(frozen=True)
class MediationConfig:
    """Runner parameters (all seeded for reproducibility)."""

    seed: int = 1234
    ticks: int = 24
    # Low top_k so competitive selection actually EXCLUDES on the minimal set
    # (Soma + prev-Chronos + injected utterances typically exceed 2). At the
    # shipped default top_k=5 nothing is excluded and competition is untested.
    top_k: int = 2
    publication_threshold: float = 0.0
    # Sliding window for the cross-module error correlation.
    window: int = 6
    # Minimum coupling_delta magnitude for a meaningful (non-NULL) result.
    min_effect: float = 0.15
    soma_units: int = 16
    chronos_units: int = 16
    max_events: int = 8
    char_budget: int = 2000

    def __post_init__(self) -> None:
        if self.top_k <= 0:
            raise ValueError("top_k must be positive")
        if self.window < 2:
            raise ValueError("window must be >= 2")
        if self.ticks < self.window:
            raise ValueError("ticks must be >= window")

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "ticks": self.ticks,
            "top_k": self.top_k,
            "publication_threshold": self.publication_threshold,
            "window": self.window,
            "min_effect": self.min_effect,
            "soma_units": self.soma_units,
            "chronos_units": self.chronos_units,
            "max_events": self.max_events,
            "char_budget": self.char_budget,
        }


def _build_syneidesis(config: MediationConfig) -> Syneidesis:
    return Syneidesis(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=32),
            goal_scorer=StaticGoalScorer(),
            thymos_modulator=StaticThymosModulator(),
        ),
        top_k=config.top_k,
        publication_threshold=config.publication_threshold,
        coherence=None,
    )


def _build_chronos(config: MediationConfig, clock_holder: list[float]) -> Chronos:
    """Build a real Chronos with seeded, deterministic forward models.

    Two arms call this with the same config, so their networks and heads start
    from identical weights; they diverge only through the snapshots they receive.
    ``initialize()`` is never called (it needs a live bus); the network and
    prediction head are injected/set directly, exactly as the unit tests do.
    """
    featurizer = SnapshotFeaturizer(clock=lambda: clock_holder[0])
    network = CfCNetwork(
        input_size=featurizer.feature_dim,
        units=config.chronos_units,
        seed=config.seed + 1,
    )
    chronos = Chronos(
        ScriptedBus({}),
        featurizer=featurizer,
        network=network,
        forward_prediction=True,
        clock=lambda: clock_holder[0],
    )
    chronos._pred_head = ForwardPredictionHead(
        input_size=featurizer.feature_dim,
        units=config.chronos_units,
        seed=config.seed + 2,
    )
    return chronos


def _last_report(bus: ScriptedBus, source: str, etype: str) -> Optional[Event]:
    events = [e for e in bus.published.get(source, []) if e.type == etype]
    return events[-1] if events else None


async def run_ablation(
    config: Optional[MediationConfig] = None,
    *,
    stimulus: MediationStimulus = SOMA_SALIENT_STIMULUS,
) -> dict[str, Any]:
    """Run the two-arm workspace-mediation ablation; return records + verdict."""
    config = config or MediationConfig()

    # Pinned construction order after seeding so the ambient-RNG draws (Soma's
    # forward model) are reproducible; Chronos passes its own seeds.
    set_global_seed(config.seed)
    clock_holder = [0.0]
    soma_bus = ScriptedBus({})
    soma = Soma(
        soma_bus,
        reader=ScriptedMetricsReader(stimulus.metrics_series(config.ticks)),
        detector=_NeverAlertDetector(),
        forward_model_units=config.soma_units,
        entity_clock=EntityClock(monotonic=lambda: clock_holder[0]),
    )
    chronos_on = _build_chronos(config, clock_holder)
    chronos_off = _build_chronos(config, clock_holder)
    syn_on = _build_syneidesis(config)
    renderer = FaithfulRenderer()
    embedder = HashEmbedder()

    soma_errors: list[float] = []
    on_errors: list[float] = []
    off_errors: list[float] = []
    on_sources: list[str] = []
    divergences: list[float] = []
    soma_salient_ticks = 0
    competing_ticks = 0
    prev_on: Optional[Event] = None
    prev_off: Optional[Event] = None

    for i in range(config.ticks):
        clock_holder[0] = float(i)

        await soma.tick_once()
        soma_report = _last_report(soma_bus, "soma", "soma.report")
        soma_err = (
            float(soma_report.payload.get("prediction_error", 0.0))
            if soma_report is not None
            else 0.0
        )
        soma_errors.append(soma_err)

        extras = stimulus.extra_candidates_at(i)

        # --- workspace-on: competitive selection --------------------------- #
        cands_on: list[tuple[str, Event]] = []
        if soma_report is not None:
            cands_on.append((f"{i + 1}-s", soma_report))
        for k, ev in enumerate(extras):
            cands_on.append((f"{i + 1}-u{k}", ev))
        if prev_on is not None:
            cands_on.append((f"{i + 1}-c", prev_on))
        if len(cands_on) > config.top_k:
            competing_ticks += 1

        snap_on = await syn_on.select(cands_on, {"tick_index": i})
        await chronos_on.on_workspace(snap_on)
        on_report = _last_report(chronos_on._bus, "chronos", "chronos.report")
        on_errors.append(
            float(on_report.payload.get("temporal_prediction_error", 0.0))
            if on_report is not None
            else 0.0
        )
        prev_on = on_report
        selected_sources = [ev.source for _, ev in snap_on.selected_events]
        if selected_sources:
            on_sources.append(selected_sources[0])
        if "soma" in selected_sources:
            soma_salient_ticks += 1
        on_wm = renderer.render_snapshot_bounded(
            snap_on, max_events=config.max_events, char_budget=config.char_budget
        )

        # --- workspace-off: flat fan-in ------------------------------------ #
        cands_off: list[tuple[str, Event]] = []
        if soma_report is not None:
            cands_off.append((f"{i + 1}-s", soma_report))
        for k, ev in enumerate(extras):
            cands_off.append((f"{i + 1}-u{k}", ev))
        if prev_off is not None:
            cands_off.append((f"{i + 1}-c", prev_off))
        snap_off = flat_fan_in_snapshot(i, cands_off)
        await chronos_off.on_workspace(snap_off)
        off_report = _last_report(chronos_off._bus, "chronos", "chronos.report")
        off_errors.append(
            float(off_report.payload.get("temporal_prediction_error", 0.0))
            if off_report is not None
            else 0.0
        )
        prev_off = off_report
        off_wm = renderer.render_snapshot_bounded(
            snap_off, max_events=config.max_events, char_budget=config.char_budget
        )

        # --- secondary: conditioning (≈ greedy output) divergence ---------- #
        on_vec = await embedder.embed(on_wm)
        off_vec = await embedder.embed(off_wm)
        divergences.append(1.0 - cosine_similarity(on_vec, off_vec))

    effect = _compute_effect(
        config,
        soma_errors=soma_errors,
        on_errors=on_errors,
        off_errors=off_errors,
        on_sources=on_sources,
        divergences=divergences,
        soma_salient_ticks=soma_salient_ticks,
        competing_ticks=competing_ticks,
    )
    verdict = _classify(effect, config)
    ts = datetime.now(timezone.utc).isoformat()

    records: list[dict[str, Any]] = [
        {
            "ts": ts,
            "kind": "arm",
            "arm": "workspace_on",
            "stimulus": stimulus.name,
            "chronos_error": on_errors,
            "coalition_sources": on_sources,
        },
        {
            "ts": ts,
            "kind": "arm",
            "arm": "workspace_off",
            "stimulus": stimulus.name,
            "chronos_error": off_errors,
        },
        {
            "ts": ts,
            "kind": "verdict",
            "config": config.as_dict(),
            "stimulus": stimulus.name,
            "soma_error": soma_errors,
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


def _compute_effect(
    config: MediationConfig,
    *,
    soma_errors: list[float],
    on_errors: list[float],
    off_errors: list[float],
    on_sources: list[str],
    divergences: list[float],
    soma_salient_ticks: int,
    competing_ticks: int,
) -> dict[str, Any]:
    coupling_on = mean_windowed_correlation(soma_errors, on_errors, window=config.window)
    coupling_off = mean_windowed_correlation(
        soma_errors, off_errors, window=config.window
    )
    coupling_delta = (
        coupling_on - coupling_off
        if coupling_on is not None and coupling_off is not None
        else None
    )
    ent = shannon_entropy(on_sources)
    ent_frac = entropy_fraction(on_sources)
    mean_div = sum(divergences) / len(divergences) if divergences else 0.0
    competing_fraction = competing_ticks / config.ticks if config.ticks else 0.0
    # Underpowered: the coupling measure is undefined, or Soma never entered the
    # coalition so the coupling path was never exercised. Either way the run
    # cannot support a NULL claim.
    underpowered = (
        coupling_delta is None or soma_salient_ticks == 0
    )
    return {
        "coupling_on": coupling_on,
        "coupling_off": coupling_off,
        "coupling_delta": coupling_delta,
        "coalition_entropy_bits": ent,
        "coalition_entropy_fraction": ent_frac,
        "mean_conditioning_divergence": mean_div,
        "soma_salient_ticks": soma_salient_ticks,
        "competing_ticks": competing_ticks,
        "competing_fraction": competing_fraction,
        "n_ticks": config.ticks,
        "underpowered": underpowered,
    }


def _classify(effect: dict[str, Any], config: MediationConfig) -> Verdict:
    """WIN / NULL / NEGATIVE on the primary coupling measure.

    - UNDERPOWERED (reported as NULL with an explicit flag) when the coupling is
      undefined or Soma never entered the coalition — NOT a clean NULL.
    - NEGATIVE when competitive mediation meaningfully REDUCES coupling
      (coupling_delta <= -min_effect) — adverse to the thesis.
    - NULL when |coupling_delta| < min_effect — the fan-in prompt-assembler
      outcome (competitive mediation makes no meaningful difference).
    - WIN when coupling_delta >= min_effect AND selection is non-trivial (the
      coalition source entropy is strictly between degenerate and uniform).
    """
    delta = effect["coupling_delta"]
    ent_frac = effect["coalition_entropy_fraction"]
    non_trivial_selection = ent_frac is not None and 0.0 < ent_frac < 1.0
    metrics = {
        "coupling_delta": delta,
        "coupling_on": effect["coupling_on"],
        "coupling_off": effect["coupling_off"],
        "coalition_entropy_fraction": ent_frac,
        "mean_conditioning_divergence": effect["mean_conditioning_divergence"],
        "competing_fraction": effect["competing_fraction"],
        "soma_salient_ticks": effect["soma_salient_ticks"],
        "min_effect": config.min_effect,
        "underpowered": effect["underpowered"],
    }

    if effect["underpowered"]:
        return Verdict(
            outcome=Outcome.NULL,
            detail=(
                "UNDERPOWERED — coupling undefined or Soma never entered the "
                f"coalition ({effect['soma_salient_ticks']} salient ticks); not a "
                "clean NULL. Use a battery that makes Soma salient."
            ),
            metrics=metrics,
        )
    if delta <= -config.min_effect:
        return Verdict(
            outcome=Outcome.NEGATIVE,
            detail=(
                f"competitive mediation REDUCES cross-module coupling "
                f"(delta {delta:.3f} <= -{config.min_effect}) — adverse to the thesis"
            ),
            metrics=metrics,
        )
    if delta >= config.min_effect and non_trivial_selection:
        return Verdict(
            outcome=Outcome.WIN,
            detail=(
                f"competitive mediation increases cross-module coupling "
                f"(delta {delta:.3f} >= {config.min_effect}) with non-trivial "
                f"selection (entropy fraction {ent_frac:.3f}) — does work flat "
                "fan-in does not. WIN = does work, NOT that it is more coherent "
                "or beats every aggregation."
            ),
            metrics=metrics,
        )
    return Verdict(
        outcome=Outcome.NULL,
        detail=(
            f"competitive mediation makes no meaningful change to coupling "
            f"(delta {delta:.3f}, |delta| < {config.min_effect}) — the fan-in "
            "prompt-assembler outcome"
        ),
        metrics=metrics,
    )


def format_summary(result: dict[str, Any]) -> str:
    """Human-readable summary; states WIN/NULL/NEGATIVE plainly."""
    summary = result["summary"]
    eff = summary["effect"]
    v = summary["verdict"]
    cfg = summary["config"]
    lines = [
        "Workspace-mediation ablation: competitive workspace vs flat fan-in",
        "=" * 66,
        f"seed={cfg['seed']} ticks={cfg['ticks']} top_k={cfg['top_k']} "
        f"window={cfg['window']}",
        f"stimulus: {summary['stimulus']}",
        f"coupling_on           = {eff['coupling_on']}",
        f"coupling_off          = {eff['coupling_off']}",
        f"coupling_delta        = {eff['coupling_delta']}  (primary measure 1)",
        f"coalition_entropy_frac= {eff['coalition_entropy_fraction']}  (primary measure 2)",
        f"mean_divergence       = {eff['mean_conditioning_divergence']:.4f}  (secondary)",
        f"competing_fraction    = {eff['competing_fraction']:.3f}  "
        f"(ticks where candidates > top_k)",
        f"soma_salient_ticks    = {eff['soma_salient_ticks']}",
        f"VERDICT: {v['outcome']} — {v['detail']}",
    ]
    if eff["competing_fraction"] == 0.0:
        lines.append(
            "  NOTE: candidates never exceeded top_k — this run tests broadcast "
            "mediation + gating, NOT competitive exclusion. Lower top_k or raise "
            "candidate count to test competition."
        )
    return "\n".join(lines)


__all__ = [
    "MediationConfig",
    "run_ablation",
    "format_summary",
    "write_jsonl",
]
