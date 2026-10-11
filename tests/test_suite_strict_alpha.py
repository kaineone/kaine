# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Suite-level strict-alpha tests for the mediation aggregate verdict."""
from __future__ import annotations

from kaine.evaluation.benchmarks.suite import SuiteConfig, _mediation_aggregate_verdict
from kaine.experiment.verdict import Outcome


def test_strict_alpha_not_win_when_pvalue_equals_alpha():
    """Five positive dIG values give a sign-test p-value of exactly 1/32."""
    digs = [0.2, 0.2, 0.2, 0.2, 0.2]
    config = SuiteConfig(alpha=1 / 32, mediation_min_effect=0.15)
    verdict = _mediation_aggregate_verdict(digs, config)
    assert verdict.outcome is not Outcome.WIN


def test_strict_alpha_win_when_pvalue_below_alpha():
    """A slightly larger alpha makes the strict inequality pass."""
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


def test_all_none_is_null_not_exercised():
    """Missing dIG values mean the comparison was not exercised."""
    config = SuiteConfig(alpha=0.04, mediation_min_effect=0.15)
    verdict = _mediation_aggregate_verdict([None, None, None, None, None], config)
    assert verdict.outcome is Outcome.NULL
    assert verdict.metrics["not_exercised"] is True


def test_mixed_dig_values_are_null():
    """Mixed positive and negative dIG values do not favor either side."""
    digs = [0.2, -0.2, 0.2, -0.2, 0.0]
    config = SuiteConfig(alpha=0.04, mediation_min_effect=0.15)
    verdict = _mediation_aggregate_verdict(digs, config)
    assert verdict.outcome is Outcome.NULL
