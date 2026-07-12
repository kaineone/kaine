# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Shared-seed suite orchestrator tests (experiment-foundation).

The orchestrator runs all seven experiments from one master seed, threading a
SeedSequence-derived child seed into each (including the active-inference
benchmark), and emits a combined report carrying every experiment's raw verdict
plus a Holm-Bonferroni family-wise-corrected view over the p-value experiments.

These use the reduced ``SuiteConfig.fast`` (tiny active-inference benchmark,
exploitation task only) so the smoke run is quick and offline. No entity boot, no
network.
"""
from __future__ import annotations

import numpy as np

from kaine.evaluation.benchmarks.suite import (
    EXPERIMENT_NAMES,
    SuiteConfig,
    format_suite_report,
    run_suite,
)


def test_suite_runs_all_experiments_and_reports_verdicts_and_holm():
    """One seed drives the whole suite; the report carries every experiment's
    raw verdict AND a Holm-corrected family-wise view (spec scenario: 'One seed
    drives the whole suite')."""
    report = run_suite(SuiteConfig.fast(seed=1234))

    # Every experiment produced a verdict.
    for name in EXPERIMENT_NAMES:
        assert name in report["experiments"], f"missing experiment {name}"
        assert "outcome" in report["experiments"][name]

    # The workspace-mediation ablation (the paper's primary experiment) is present
    # and contributes a p-value to the Holm family alongside active-inference.
    assert "workspace_mediation" in report["experiments"]
    fw_names = {c["name"] for c in report["family_wise"]["comparisons"]}
    assert "workspace_mediation" in fw_names

    # The active-inference benchmark was seeded from the master seed (its derived
    # child seed is recorded), proving it is threaded, not independently seeded.
    assert "active_inference" in report["derived_seeds"]
    assert report["master_seed"] == 1234

    # Family-wise correction is present and uses Holm-Bonferroni over the p-value
    # producer(s) — at least the active-inference task(s).
    fw = report["family_wise"]
    assert fw["method"] == "holm-bonferroni"
    assert fw["n"] >= 1
    assert any(
        c["name"].startswith("active_inference:") for c in fw["comparisons"]
    )
    for c in fw["comparisons"]:
        assert 0.0 <= c["raw_p"] <= 1.0
        assert 0.0 <= c["holm_p"] <= 1.0
        assert isinstance(c["reject"], bool)

    # The human-readable report renders both sections.
    text = format_suite_report(report)
    assert "eight experiments under one shared seed" in text
    assert "Family-wise correction" in text


def test_suite_derived_seeds_are_reproducible_function_of_master():
    """The per-experiment child seeds are a pure function of the master seed
    (SeedSequence.spawn), so two runs derive the same seeds."""
    r1 = run_suite(SuiteConfig.fast(seed=99))
    r2 = run_suite(SuiteConfig.fast(seed=99))
    assert r1["derived_seeds"] == r2["derived_seeds"]

    # And they match an independent SeedSequence.spawn recomputation.
    root = np.random.SeedSequence(99)
    children = root.spawn(len(EXPERIMENT_NAMES))
    expected = {
        name: int(child.generate_state(1, dtype=np.uint32)[0])
        for name, child in zip(EXPERIMENT_NAMES, children)
    }
    assert r1["derived_seeds"] == expected


def test_suite_active_inference_verdict_reproduces_under_master_seed():
    """Threading the master seed makes the active-inference verdict reproducible
    across runs (same seed -> same verdict)."""
    r1 = run_suite(SuiteConfig.fast(seed=7))
    r2 = run_suite(SuiteConfig.fast(seed=7))
    assert (
        r1["experiments"]["active_inference"]
        == r2["experiments"]["active_inference"]
    )


def test_suite_master_seed_moves_active_inference_pvalues():
    """Two different master seeds actually MOVE the active-inference p-values —
    proving the master seed genuinely perturbs results (env/RL stochasticity),
    not just metadata. If the threading were cosmetic the p-values would be
    identical across seeds."""
    def ai_pvalues(seed: int) -> dict:
        rep = run_suite(SuiteConfig.fast(seed=seed))
        return {
            c["name"]: c["raw_p"]
            for c in rep["family_wise"]["comparisons"]
            if c["name"].startswith("active_inference:")
        }

    p1 = ai_pvalues(1)
    p2 = ai_pvalues(2)
    assert p1 and p2  # at least one active-inference task produced a p-value
    assert p1 != p2, f"master seed did not move the p-values: {p1} == {p2}"


def test_suite_folds_individuation_pvalue_into_holm_family():
    """An individuation result folded into the suite contributes its permutation
    p-value to the family-wise correction (active-inference + individuation).

    Sync test: ``run_suite`` drives its async experiments via ``asyncio.run``
    internally, so it must be called from a non-async context. The individuation
    result is built with ``asyncio.run`` up front, then folded in.
    """
    import asyncio

    from kaine.evaluation.benchmarks.individuation_runner import (
        IndividuationRunConfig,
        run_individuation,
    )

    battery = ["What do you enjoy?", "Describe your day.", "What matters?"]

    async def parent_sampler(prompt: str, seed: int) -> str:
        return f"response to {prompt} noise {seed % 3}"

    async def fork_sampler(prompt: str, seed: int) -> str:
        return "Quantum lattice topological eigenvalue divergence completely different."

    reference = [f"response to {p} noise 0" for p in battery]

    ind = asyncio.run(
        run_individuation(
            IndividuationRunConfig(
                null_samples=15, min_observations=0, min_lived_time_s=0.0
            ),
            parent_sampler=parent_sampler,
            fork_sampler=fork_sampler,
            observations=100,
            lived_time_s=100.0,
            battery=battery,
            reference=reference,
        )
    )

    report = run_suite(SuiteConfig.fast(seed=1234), individuation=ind)
    fw_names = {c["name"] for c in report["family_wise"]["comparisons"]}
    assert "individuation" in fw_names
    assert "individuation" in report["experiments"]
    # Family now has the active-inference task(s) AND individuation.
    assert report["family_wise"]["n"] >= 2
