# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from kaine.evaluation.benchmarks.suite import SuiteConfig, _mediation_aggregate_verdict
from kaine.experiment.verdict import Outcome


def test_strict_alpha_not_win_when_pvalue_equals_alpha():
    """Five positive deltas give sign-test p=1/32 exactly; mean effect clears min."""
    deltas = [0.2, 0.2, 0.2, 0.2, 0.2]
    pvalue = 1 / 32  # == 0.03125
    config = SuiteConfig(alpha=pvalue, mediation_min_effect=0.15)
    verdict = _mediation_aggregate_verdict(deltas, pvalue, config)
    assert verdict.outcome is not Outcome.WIN


def test_strict_alpha_win_when_pvalue_just_below_alpha():
    """Same deltas; a slightly larger alpha makes the strict inequality pass."""
    deltas = [0.2, 0.2, 0.2, 0.2, 0.2]
    pvalue = 1 / 32  # == 0.03125
    config = SuiteConfig(alpha=0.04, mediation_min_effect=0.15)
    verdict = _mediation_aggregate_verdict(deltas, pvalue, config)
    assert verdict.outcome is Outcome.WIN
