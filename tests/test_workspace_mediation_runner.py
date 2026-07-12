# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Runner-level tests for the workspace-mediation ablation: determinism, the
three-way verdict reachability, and the underpowered flag."""
from __future__ import annotations

import pytest

from kaine.evaluation.benchmarks.workspace_mediation_ablation.runner import (
    MediationConfig,
    _classify,
    run_ablation,
)
from kaine.evaluation.benchmarks.workspace_mediation_ablation.stimulus import (
    DECOUPLED_STIMULUS,
    NEUTRAL_STIMULUS,
    SOMA_SALIENT_STIMULUS,
)
from kaine.experiment.verdict import Outcome


@pytest.mark.asyncio
async def test_same_seed_reproduces_effect_and_verdict():
    cfg = MediationConfig(seed=7, ticks=20)
    r1 = await run_ablation(cfg)
    r2 = await run_ablation(cfg)
    assert r1["effect"] == r2["effect"]
    assert r1["verdict"].to_dict() == r2["verdict"].to_dict()


@pytest.mark.asyncio
async def test_arms_produce_the_expected_records():
    r = await run_ablation(MediationConfig(seed=3, ticks=16))
    kinds = [rec["kind"] for rec in r["records"]]
    assert kinds == ["arm", "arm", "verdict", "summary"]
    on = next(rec for rec in r["records"] if rec.get("arm") == "workspace_on")
    off = next(rec for rec in r["records"] if rec.get("arm") == "workspace_off")
    # Both arms produce a full Chronos error series (fair-null: off is not silenced).
    assert len(on["chronos_error"]) == 16
    assert len(off["chronos_error"]) == 16


@pytest.mark.asyncio
async def test_soma_salient_battery_gives_coverage_and_competition():
    r = await run_ablation(MediationConfig(seed=1, ticks=24), stimulus=SOMA_SALIENT_STIMULUS)
    eff = r["effect"]
    # The coverage battery makes Soma enter the coalition and forces competition.
    assert eff["soma_salient_ticks"] > 0
    assert eff["competing_fraction"] > 0.0
    assert not eff["underpowered"]


# --------------------------- verdict reachability -------------------------- #


def _effect(delta, *, ent_frac=0.6, salient=10, underpowered=False):
    return {
        "coupling_on": (delta or 0.0) + 0.5,
        "coupling_off": 0.5,
        "coupling_delta": delta,
        "coalition_entropy_bits": 0.9,
        "coalition_entropy_fraction": ent_frac,
        "mean_conditioning_divergence": 0.1,
        "soma_salient_ticks": salient,
        "competing_ticks": 8,
        "competing_fraction": 0.5,
        "n_ticks": 20,
        "underpowered": underpowered,
    }


def test_classify_win_reachable():
    v = _classify(_effect(0.30), MediationConfig())
    assert v.outcome is Outcome.WIN


def test_classify_null_on_small_delta():
    v = _classify(_effect(0.05), MediationConfig())
    assert v.outcome is Outcome.NULL
    assert "prompt-assembler" in v.detail


def test_classify_negative_reachable():
    v = _classify(_effect(-0.30), MediationConfig())
    assert v.outcome is Outcome.NEGATIVE


def test_classify_win_requires_nontrivial_selection():
    # A meaningful delta but degenerate selection (entropy fraction at the
    # extreme) is not a WIN — competitive selection must actually be selecting.
    v = _classify(_effect(0.30, ent_frac=1.0), MediationConfig())
    assert v.outcome is not Outcome.WIN


def test_classify_underpowered_flagged_not_clean_null():
    v = _classify(_effect(0.0, salient=0, underpowered=True), MediationConfig())
    assert v.outcome is Outcome.NULL
    assert "UNDERPOWERED" in v.detail
    assert v.metrics["underpowered"] is True


@pytest.mark.asyncio
async def test_batteries_keep_null_reachable_on_neutral():
    # The neutral battery should not be engineered to force a WIN; a NULL (or
    # adverse) result must be reachable there.
    outcomes = set()
    for seed in (7, 42):
        r = await run_ablation(MediationConfig(seed=seed, ticks=24), stimulus=NEUTRAL_STIMULUS)
        outcomes.add(r["verdict"].outcome)
    assert Outcome.WIN not in outcomes or len(outcomes) > 1
