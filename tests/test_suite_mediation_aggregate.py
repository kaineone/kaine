# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Suite-level tests for the mediation aggregate verdict and the family-wise view."""
from __future__ import annotations

import pytest

from kaine.evaluation.benchmarks import suite
from kaine.evaluation.benchmarks.suite import (
    SuiteConfig,
    _mediation_aggregate_verdict,
    format_suite_report,
)
from kaine.experiment.verdict import Outcome


def test_win_when_pvalue_equals_alpha():
    """Five positive dIG values give a sign-test p-value of exactly 1/32.

    That is a WIN at alpha = 1/32, because the rule is p <= alpha.
    """
    digs = [0.2, 0.2, 0.2, 0.2, 0.2]
    config = SuiteConfig(alpha=1 / 32, mediation_min_effect=0.15)
    verdict = _mediation_aggregate_verdict(digs, config)
    assert verdict.outcome is Outcome.WIN


def test_win_when_pvalue_below_alpha():
    """A p-value below alpha is a WIN."""
    digs = [0.2, 0.2, 0.2, 0.2, 0.2]
    config = SuiteConfig(alpha=0.04, mediation_min_effect=0.15)
    verdict = _mediation_aggregate_verdict(digs, config)
    assert verdict.outcome is Outcome.WIN
    assert "does not test the thesis" in verdict.detail


def test_negative_dig_is_negative_verdict():
    """Five negative dIG values pass the negative one-sided sign test."""
    digs = [-0.2, -0.2, -0.2, -0.2, -0.2]
    config = SuiteConfig(alpha=0.04, mediation_min_effect=0.15)
    verdict = _mediation_aggregate_verdict(digs, config)
    assert verdict.outcome is Outcome.NEGATIVE


def test_negative_when_pvalue_equals_alpha():
    """Five negative dIG values at alpha = 1/32 (p equals alpha) are NEGATIVE."""
    digs = [-0.2, -0.2, -0.2, -0.2, -0.2]
    config = SuiteConfig(alpha=1 / 32, mediation_min_effect=0.15)
    verdict = _mediation_aggregate_verdict(digs, config)
    assert verdict.outcome is Outcome.NEGATIVE


def test_all_none_is_not_exercised():
    """Missing dIG values mean the comparison was not exercised."""
    config = SuiteConfig(alpha=0.04, mediation_min_effect=0.15)
    verdict = _mediation_aggregate_verdict([None, None, None, None, None], config)
    assert verdict.outcome is Outcome.NOT_EXERCISED
    assert verdict.metrics["pvalue"] is None
    assert verdict.metrics["n_exercised"] == 0


def test_win_not_reached_just_below_the_pvalue():
    """Five positive dIG values with alpha just below 1/32 are not a WIN."""
    digs = [0.2, 0.2, 0.2, 0.2, 0.2]
    config = SuiteConfig(alpha=0.03, mediation_min_effect=0.15)
    verdict = _mediation_aggregate_verdict(digs, config)
    assert verdict.outcome is not Outcome.WIN


def test_unexercised_seeds_are_left_out_of_the_sign_tests():
    """None entries are not evidence and do not enter the sign tests."""
    digs = [0.2, 0.2, 0.2, 0.2, 0.2, None, None]
    config = SuiteConfig(alpha=0.04, mediation_min_effect=0.15)
    verdict = _mediation_aggregate_verdict(digs, config)
    assert verdict.outcome is Outcome.WIN
    assert verdict.metrics["n_exercised"] == 5
    assert verdict.metrics["n_not_exercised"] == 2


def test_mixed_dig_values_are_null():
    """Mixed positive and negative dIG values do not favor either side."""
    digs = [0.2, -0.2, 0.2, -0.2, 0.0]
    config = SuiteConfig(alpha=0.04, mediation_min_effect=0.15)
    verdict = _mediation_aggregate_verdict(digs, config)
    assert verdict.outcome is Outcome.NULL


def test_run_workspace_mediation_drops_unexercised_seed_with_defined_dig(monkeypatch):
    """A seed with not_exercised=True contributes None even if dIG is defined."""

    async def fake(config, *, stimulus):
        if config.seed % 2 == 0:
            return {
                "effect": {
                    "dig": 0.2,
                    "not_exercised": False,
                    "not_exercised_reason": None,
                }
            }
        return {
            "effect": {
                "dig": 0.9,
                "not_exercised": True,
                "not_exercised_reason": "competition never operated",
            }
        }

    monkeypatch.setattr("kaine.evaluation.benchmarks.suite.run_workspace_mediation", fake)

    cfg = SuiteConfig(
        alpha=0.04,
        mediation_min_effect=0.15,
        mediation_seeds=(0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    )
    result = suite._run_workspace_mediation(cfg, 0)

    assert result["digs"] == [0.2, None, 0.2, None, 0.2, None, 0.2, None, 0.2, None]
    assert result["verdict"]["metrics"]["n_exercised"] == 5
    assert result["verdict"]["metrics"]["n_not_exercised"] == 5
    assert result["verdict"]["outcome"] == "WIN"


def test_run_workspace_mediation_all_unexercised_has_no_pvalue(monkeypatch):
    """When every seed is unexercised the family contribution is None."""

    async def fake(config, *, stimulus):
        return {
            "effect": {
                "dig": 0.2,
                "not_exercised": True,
                "not_exercised_reason": "no competition",
            }
        }

    monkeypatch.setattr("kaine.evaluation.benchmarks.suite.run_workspace_mediation", fake)

    cfg = SuiteConfig(
        alpha=0.04,
        mediation_min_effect=0.15,
        mediation_seeds=(1, 3, 5, 7, 9),
    )
    result = suite._run_workspace_mediation(cfg, 0)

    assert result["pvalue"] is None
    assert result["verdict"]["outcome"] == "NOT_EXERCISED"


def test_family_wise_keeps_unexercised_experiment_at_p_one():
    """NOT_EXERCISED members stay in the Holm family at p = 1."""
    report = suite._family_wise(
        {"active_inference:a": 0.01, "active_inference:b": 0.04, "workspace_mediation": None},
        0.05,
    )
    assert report["n"] == 3
    names = {c["name"] for c in report["comparisons"]}
    assert names == {"active_inference:a", "active_inference:b", "workspace_mediation"}
    wm = next(c for c in report["comparisons"] if c["name"] == "workspace_mediation")
    assert wm["raw_p"] == 1.0
    assert wm["reject"] is False
    assert wm["not_exercised"] is True
    for name in ("active_inference:a", "active_inference:b"):
        c = next(cmp for cmp in report["comparisons"] if cmp["name"] == name)
        assert c["not_exercised"] is False
    assert report["not_exercised"] == ["workspace_mediation"]
    a = next(c for c in report["comparisons"] if c["name"] == "active_inference:a")
    assert a["holm_p"] == pytest.approx(0.03)


def test_family_wise_without_unexercised_members():
    """When every member has a p-value the not_exercised list is empty."""
    report = suite._family_wise({"x": 0.01}, 0.05)
    assert report["not_exercised"] == []
    for c in report["comparisons"]:
        assert c["not_exercised"] is False


def test_format_suite_report_names_unexercised_experiment():
    """The formatted report names a NOT_EXERCISED experiment separately."""
    minimal_report = {
        "master_seed": 1,
        "alpha": 0.05,
        "deterministic": True,
        "experiments": {
            "workspace_mediation": {
                "outcome": "NOT_EXERCISED",
                "detail": "no seed was exercised.",
            }
        },
        "family_wise": suite._family_wise({"workspace_mediation": None}, 0.05),
    }
    output = format_suite_report(minimal_report)
    assert "NOT EXERCISED" in output
    assert "NOT_EXERCISED" in output
    assert "in the family at p = 1" in output
