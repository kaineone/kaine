# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Controlled oscillatory-ablation runner tests (oscillatory-binding).

The runner executes the cognitive cycle twice under identical conditions — same
``set_global_seed(seed)``, same fixed scripted input, ``deterministic=True`` —
differing only in whether the coherence layer is enabled. These tests assert:

- a seeded run reproduces its verdict + effect metrics (run twice, identical);
- a crafted stimulus yields a measurable effect (WIN, effect > 0);
- the disabled arm is bit-for-bit the layer-absent baseline (the only difference
  between the arms is the layer);
- the runner is offline (scripted in-memory bus; no entity, no network).

No live modules, no entity boot, no network.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from kaine.cycle.engine import CognitiveCycle
from kaine.evaluation.benchmarks.oscillatory_ablation.runner import (
    AblationConfig,
    _MonotonicClock,
    _async_noop,
    _build_syneidesis,
    _classify,
    _normalize_broadcast,
    _run_arm,
    format_summary,
    run_ablation,
    write_jsonl,
)
from kaine.evaluation.benchmarks.oscillatory_ablation.stimulus import (
    MISLABELED_STIMULUS,
    NEUTRAL_STIMULUS,
    ScriptedBus,
    ScriptedPhaseRegistry,
    scripted_streams,
)
from kaine.experiment.seeding import set_global_seed
from kaine.experiment.verdict import Outcome
from kaine.workspace.volition import Volition


# --------------------------------------------------------------------------
# Reproducibility: same seed → same verdict + metrics
# (spec scenario: "Enabled-vs-disabled run is reproducible")
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seeded_run_reproduces_verdict_and_metrics():
    """Two invocations with the same config produce identical verdict + effect
    metrics + trajectories (the wall-clock ``ts`` is the only thing that may
    differ, and it is not part of the cognitive result)."""
    cfg = AblationConfig()
    r1 = await run_ablation(cfg)
    r2 = await run_ablation(cfg)

    assert r1["verdict"].to_dict() == r2["verdict"].to_dict()
    assert r1["effect"] == r2["effect"]
    assert r1["enabled_trajectory"] == r2["enabled_trajectory"]
    assert r1["disabled_trajectory"] == r2["disabled_trajectory"]
    # The summary differs only by the wall-clock timestamp.
    s1 = {k: v for k, v in r1["summary"].items() if k != "ts"}
    s2 = {k: v for k, v in r2["summary"].items() if k != "ts"}
    assert s1 == s2


# --------------------------------------------------------------------------
# Measurable effect: a crafted stimulus yields WIN with effect > 0
# (spec scenario: "A non-trivial stimulus yields a measurable effect")
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crafted_stimulus_yields_win_with_positive_effect():
    """On the default crafted stimulus the enabled layer measurably re-ranks
    selection, so the verdict is WIN and the effect size is strictly positive."""
    result = await run_ablation(AblationConfig())
    verdict = result["verdict"]

    assert verdict.outcome is Outcome.WIN
    sel = verdict.metrics["selection_divergence_fraction"]
    assert sel > 0.0, "the layer must measurably change the selected coalition"
    # The ranking divergence (re-ordering below the top entry) is also positive.
    assert verdict.metrics["mean_ranking_divergence"] > 0.0
    assert verdict.metrics["ticks_top_differs"] >= 1


@pytest.mark.asyncio
async def test_top_selection_actually_flips_on_some_tick():
    """Concretely: on at least one tick the enabled arm's top entry differs from
    the disabled arm's — proving the toggle is wired to selection, not just to a
    metadata field."""
    result = await run_ablation(AblationConfig())
    enabled = result["enabled_trajectory"]
    disabled = result["disabled_trajectory"]

    def top_source(tick):
        sel = tick["selected"]
        return sel[0]["source"] if sel else None

    flipped = [
        i
        for i in range(min(len(enabled), len(disabled)))
        if top_source(enabled[i]) != top_source(disabled[i])
    ]
    assert flipped, "expected the top selected source to flip on some tick"
    # The disabled arm always favours the higher-raw-salience drift source; the
    # enabled arm eventually favours a phase-locked source.
    i = flipped[-1]
    assert top_source(disabled[i]) == "drift_a"
    assert top_source(enabled[i]) == "lock_a"


# --------------------------------------------------------------------------
# Disabled arm == layer-absent baseline (bit-for-bit)
# (spec scenario: "The disabled arm matches the layer-absent baseline")
# --------------------------------------------------------------------------


async def _layer_absent_baseline(cfg: AblationConfig) -> list[dict]:
    """Run the cycle with NO coherence layer at all, independently of the runner.

    Built here from scratch (no coherence kwarg, no phase collection) so the
    comparison is against a genuinely layer-absent cycle, not merely the runner's
    own disabled path.
    """
    set_global_seed(cfg.seed)
    bus = ScriptedBus(scripted_streams(cfg.ticks))
    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=_build_syneidesis(cfg, None),
        registry=ScriptedPhaseRegistry(),
        volition=Volition(),
        clock=_MonotonicClock(),
        sleep=_async_noop,
        collect_phases=False,
        deterministic=True,
    )
    for _ in range(cfg.ticks):
        bus.advance()
        await cycle.tick()
    return [_normalize_broadcast(b) for b in bus.workspace_broadcasts]


@pytest.mark.asyncio
async def test_disabled_arm_is_bit_for_bit_layer_absent_baseline():
    """The runner's disabled arm equals an independently-built layer-absent
    cycle, tick by tick — so the only difference between the runner's two arms is
    the coherence layer."""
    cfg = AblationConfig()
    disabled = await _run_arm(cfg, enabled=False)
    baseline = await _layer_absent_baseline(cfg)
    assert disabled == baseline
    # And no coherence metadata leaks into the disabled trajectory (the layer is
    # genuinely absent, not silently active).
    result = await run_ablation(cfg)
    for tick in result["records"]:
        if tick.get("arm") == "disabled":
            for entry in tick["trajectory"]:
                assert "coherence" not in entry


@pytest.mark.asyncio
async def test_enabled_and_disabled_arms_differ_only_by_the_layer():
    """The two arms diverge (else the test stimulus would be vacuous) AND the
    divergence is a genuine selection difference, not a config artefact."""
    cfg = AblationConfig()
    enabled = await _run_arm(cfg, enabled=True)
    disabled = await _run_arm(cfg, enabled=False)
    assert enabled != disabled, "the layer must make a difference on this stimulus"


# --------------------------------------------------------------------------
# Null path: with no precision gain (floor == ceiling == 1.0) → NULL
# (spec scenario: "No measurable difference is reported as null")
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Falsifiability: the runner is NOT wired to always-WIN.
# (spec scenario: "A layer with no meaningful effect resolves to NULL")
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_neutral_battery_yields_null_not_win():
    """On the non-engineered battery (no coherence contrast — all sources equally
    phase-coherent) precision-weighting has no discriminative signal, so the layer
    changes nothing and the verdict is NULL. This proves the runner can return a
    result adverse to a naive 'the layer always helps' expectation: the same
    machinery that WINs on the engineered battery NULLs here."""
    result = await run_ablation(AblationConfig(), stimulus=NEUTRAL_STIMULUS)
    assert result["verdict"].outcome is Outcome.NULL
    assert result["verdict"].metrics["selection_divergence_fraction"] <= (
        AblationConfig().min_effect
    )


@pytest.mark.asyncio
async def test_neutral_disabled_arm_is_bit_for_bit_layer_absent_baseline():
    """The bit-for-bit disabled-arm control still holds on the neutral battery:
    the runner's disabled arm equals an independently-built layer-absent cycle."""
    cfg = AblationConfig()
    disabled = await _run_arm(cfg, enabled=False, stimulus=NEUTRAL_STIMULUS)

    set_global_seed(cfg.seed)
    bus = ScriptedBus(NEUTRAL_STIMULUS.streams(cfg.ticks))
    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=_build_syneidesis(cfg, None),
        registry=NEUTRAL_STIMULUS.registry(),
        volition=Volition(),
        clock=_MonotonicClock(),
        sleep=_async_noop,
        collect_phases=False,
        deterministic=True,
    )
    for _ in range(cfg.ticks):
        bus.advance()
        await cycle.tick()
    baseline = [_normalize_broadcast(b) for b in bus.workspace_broadcasts]
    assert disabled == baseline


@pytest.mark.asyncio
async def test_mislabeled_battery_yields_real_negative_via_pipeline():
    """NEGATIVE is reachable through the REAL measurement pipeline, not just a
    hand-fed classifier input. On the mislabeled/adversarial battery the honest,
    monotone coherence layer promotes the truly-synchronized source (labeled
    coherent=False) over a high-salience non-locked decoy (mislabeled
    coherent=True), so ``run_ablation`` returns Outcome.NEGATIVE with a genuinely
    negative coherence_alignment_delta computed from the two arms' trajectories."""
    result = await run_ablation(AblationConfig(), stimulus=MISLABELED_STIMULUS)
    assert result["verdict"].outcome is Outcome.NEGATIVE
    # The negative direction comes from the real per-tick top-source comparison.
    assert result["effect"]["coherence_alignment_delta"] < 0.0
    assert result["verdict"].metrics["coherence_alignment_delta"] < 0.0
    # And the change is meaningful (above min_effect), else it would be NULL.
    assert (
        result["verdict"].metrics["selection_divergence_fraction"]
        > AblationConfig().min_effect
    )


def test_classifier_can_return_negative_adverse_outcome():
    """The classifier can return NEGATIVE — a meaningful re-ranking AWAY from the
    coherent coalition. This makes an adverse result reachable and reportable
    rather than silently coerced to WIN/NULL (the paper's falsification framing)."""
    cfg = AblationConfig(min_effect=0.10, min_alignment=0.10)
    adverse_effect = {
        "selection_divergence_fraction": 0.5,  # meaningful (> min_effect)
        "mean_ranking_divergence": 0.4,
        "coherence_alignment_delta": -0.4,  # moved AWAY from coherent sources
        "has_coherent_ground_truth": True,
        "ticks_top_differs": 8,
        "n_ticks_compared": 16,
    }
    v = _classify(adverse_effect, cfg)
    assert v.outcome is Outcome.NEGATIVE


def test_classifier_below_min_effect_is_null():
    """A tiny, sub-threshold selection change is NULL, not a WIN."""
    cfg = AblationConfig(min_effect=0.10)
    tiny = {
        "selection_divergence_fraction": 0.05,  # below min_effect
        "mean_ranking_divergence": 0.02,
        "coherence_alignment_delta": 0.05,
        "has_coherent_ground_truth": True,
        "ticks_top_differs": 1,
        "n_ticks_compared": 20,
    }
    assert _classify(tiny, cfg).outcome is Outcome.NULL


@pytest.mark.asyncio
async def test_unit_gain_layer_produces_null_verdict():
    """A coherence layer pinned to a unit multiplier (floor == ceiling == 1.0)
    cannot change any score, so selection is unchanged and the verdict is NULL
    with zero effect — the honest null the classifier must report."""
    cfg = AblationConfig(coherence_floor=1.0, coherence_ceiling=1.0)
    result = await run_ablation(cfg)
    assert result["verdict"].outcome is Outcome.NULL
    assert result["verdict"].metrics["selection_divergence_fraction"] == 0.0
    assert result["verdict"].metrics["mean_ranking_divergence"] == 0.0


def test_degenerate_zero_ceiling_is_rejected():
    """A non-positive coherence_ceiling zeroes every score → a degenerate tie
    whose sort order is an artefact that would masquerade as a false WIN. It must
    be rejected as an invalid config, symmetric with the floor<=ceiling check.
    (The unit-gain null control floor==ceiling==1.0 stays valid — see above.)"""
    import pytest as _pytest

    with _pytest.raises(ValueError, match="ceiling must be > 0"):
        AblationConfig(coherence_floor=0.0, coherence_ceiling=0.0)
    # The scorer rejects it too (defence in depth on the enabled arm).
    from kaine.workspace.coherence import CoherenceScorer

    with _pytest.raises(ValueError, match="ceiling must be > 0"):
        CoherenceScorer(plv_window=12, coherence_floor=0.0, coherence_ceiling=0.0)


# --------------------------------------------------------------------------
# Offline / no-boot
# (spec scenario: "Offline, no entity boot")
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_is_offline_no_network_no_entity(monkeypatch):
    """The runner opens no socket: any attempt to create a network connection
    raises. It still produces a verdict, proving it is genuinely offline."""
    import socket

    def _no_network(*_a, **_k):
        raise AssertionError("oscillatory ablation runner must not open a socket")

    monkeypatch.setattr(socket.socket, "connect", _no_network)
    result = await run_ablation(AblationConfig(ticks=12))
    assert result["verdict"].outcome in (Outcome.WIN, Outcome.NULL)


# --------------------------------------------------------------------------
# JSONL output + summary
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jsonl_output_round_trips_and_contains_verdict(tmp_path):
    result = await run_ablation(AblationConfig(ticks=12))
    out = tmp_path / "ablation.jsonl"
    write_jsonl(result["records"], out)

    lines = out.read_text(encoding="utf-8").strip().splitlines()
    records = [json.loads(ln) for ln in lines]
    kinds = [r["kind"] for r in records]
    assert "arm" in kinds and "verdict" in kinds and "summary" in kinds
    verdict_rec = next(r for r in records if r["kind"] == "verdict")
    assert verdict_rec["verdict"]["outcome"] in ("WIN", "NULL")
    assert "selection_divergence_fraction" in verdict_rec["verdict"]["metrics"]


def test_format_summary_states_verdict_plainly():
    result = asyncio.run(run_ablation(AblationConfig(ticks=12)))
    text = format_summary(result)
    assert "VERDICT:" in text
    assert "selection_divergence_fraction" in text
