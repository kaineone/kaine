# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the multi-seed stability harness (longitudinal-stability change).

Spec-scenario coverage (openspec/changes/longitudinal-stability/specs/
experiment-foundation/spec.md):

* "Stable experiment across seeds"   -> test_low_variance_run_fn_is_stable
* "Unstable metric reported unstable"-> test_high_variance_run_fn_is_unstable
* "Verdict unanimity captured"       -> test_unanimous_verdicts_counted,
                                        test_disagreeing_verdicts_are_unstable
* boundary-neutral (no kaine.evaluation import)
                                     -> test_stability_module_does_not_import_evaluation
"""
from __future__ import annotations

import ast
import math
import subprocess
from pathlib import Path

import pytest

from kaine.experiment.stability import (
    StabilityError,
    StabilityReport,
    assert_stable,
    run_multi_seed,
)
from kaine.experiment.verdict import Outcome, Verdict


# --------------------------------------------------------------------------- #
# Summary statistics + stable case
# --------------------------------------------------------------------------- #


def test_low_variance_run_fn_is_stable():
    """A run_fn whose metric is identical across seeds -> stable, exact stats."""

    def run_fn(seed: int) -> dict:
        return {"metric": 0.5, "verdict": Verdict(outcome=Outcome.WIN)}

    report = run_multi_seed(
        run_fn,
        [0, 1, 2, 3, 4],
        metric_fn=lambda r: r["metric"],
        tolerance=0.0,
    )
    assert isinstance(report, StabilityReport)
    assert report.seeds == (0, 1, 2, 3, 4)
    assert report.values == (0.5, 0.5, 0.5, 0.5, 0.5)
    assert report.mean == pytest.approx(0.5)
    assert report.std == pytest.approx(0.0)
    assert report.cv == pytest.approx(0.0)
    assert report.verdict_counts == {"WIN": 5}
    assert report.verdict_unanimous is True
    assert report.stable is True
    # reasons() always explains both factors.
    reasons = report.reasons()
    assert any("stable across seeds" in r for r in reasons)
    assert any("unanimous" in r for r in reasons)


def test_small_variance_within_tolerance_is_stable():
    """A small but non-zero spread is stable when CV is within tolerance."""
    values = {0: 1.00, 1: 1.01, 2: 0.99}

    def run_fn(seed: int) -> dict:
        return {"metric": values[seed]}

    report = run_multi_seed(
        run_fn, [0, 1, 2], metric_fn=lambda r: r["metric"], tolerance=0.05
    )
    # std of {1.00,1.01,0.99} ~ 0.00816; mean ~1.0 -> cv ~0.0082 < 0.05
    assert report.cv < 0.05
    assert report.stable is True
    # No verdicts -> vacuously unanimous, empty counts.
    assert report.verdict_counts == {}
    assert report.verdict_unanimous is True
    assert any("metric-only" in r for r in report.reasons())


# --------------------------------------------------------------------------- #
# Unstable metric
# --------------------------------------------------------------------------- #


def test_high_variance_run_fn_is_unstable():
    """A run_fn whose metric swings widely -> unstable, with a clear reason."""
    values = {0: 0.1, 1: 0.9, 2: 0.2, 3: 0.95, 4: 0.05}

    def run_fn(seed: int) -> dict:
        return {"metric": values[seed]}

    report = run_multi_seed(
        run_fn,
        [0, 1, 2, 3, 4],
        metric_fn=lambda r: r["metric"],
        tolerance=0.05,
    )
    assert report.std > 0.0
    assert report.cv > 0.05
    assert report.stable is False
    assert any("varies too much" in r for r in report.reasons())


def test_nonzero_spread_around_zero_mean_is_infinite_cv_unstable():
    """Spread around a zero mean -> infinite CV -> unstable (never within tolerance)."""
    values = {0: -1.0, 1: 1.0}  # mean == 0, std > 0

    def run_fn(seed: int) -> dict:
        return {"metric": values[seed]}

    report = run_multi_seed(
        run_fn, [0, 1], metric_fn=lambda r: r["metric"], tolerance=1e9
    )
    assert report.mean == pytest.approx(0.0)
    assert math.isinf(report.cv)
    assert report.stable is False
    assert any("infinite" in r for r in report.reasons())
    # Serialization replaces inf with None + a flag (JSON-safe).
    d = report.to_dict()
    assert d["cv"] is None
    assert d["cv_is_infinite"] is True


def test_all_zero_ensemble_is_stable():
    """All-zero metric -> CV defined as 0.0 (degenerate but perfectly stable)."""

    def run_fn(seed: int) -> dict:
        return {"metric": 0.0}

    report = run_multi_seed(
        run_fn, [0, 1, 2], metric_fn=lambda r: r["metric"], tolerance=0.0
    )
    assert report.mean == 0.0
    assert report.std == 0.0
    assert report.cv == 0.0
    assert report.stable is True


# --------------------------------------------------------------------------- #
# Verdict unanimity
# --------------------------------------------------------------------------- #


def test_unanimous_verdicts_counted():
    """Verdict distribution is captured and unanimity recognized."""

    def run_fn(seed: int) -> dict:
        return {"metric": 0.5, "verdict": Verdict(outcome=Outcome.WIN)}

    report = run_multi_seed(
        run_fn, [0, 1, 2], metric_fn=lambda r: r["metric"], tolerance=0.0
    )
    assert report.verdict_counts == {"WIN": 3}
    assert report.verdict_unanimous is True
    assert report.stable is True


def test_disagreeing_verdicts_are_unstable():
    """A stable metric but flipped verdict -> NOT unanimous -> unstable."""
    verdicts = {0: Outcome.WIN, 1: Outcome.WIN, 2: Outcome.NULL}

    def run_fn(seed: int) -> dict:
        # Metric identical across seeds (CV == 0) but the verdict flips.
        return {"metric": 0.5, "verdict": Verdict(outcome=verdicts[seed])}

    report = run_multi_seed(
        run_fn, [0, 1, 2], metric_fn=lambda r: r["metric"], tolerance=0.0
    )
    assert report.cv == pytest.approx(0.0)  # metric itself is perfectly stable
    assert report.verdict_counts == {"WIN": 2, "NULL": 1}
    assert report.verdict_unanimous is False
    # Disagreement alone makes the ensemble unstable.
    assert report.stable is False
    assert any("disagree" in r for r in report.reasons())


def test_verdict_extracted_from_object_result():
    """A result object exposing .verdict (not a dict) is still recognized."""

    class _Result:
        def __init__(self, metric: float, verdict: Verdict) -> None:
            self.metric = metric
            self.verdict = verdict

    def run_fn(seed: int) -> _Result:
        return _Result(0.5, Verdict(outcome=Outcome.WIN))

    report = run_multi_seed(
        run_fn, [0, 1], metric_fn=lambda r: r.metric, tolerance=0.0
    )
    assert report.verdict_counts == {"WIN": 2}


# --------------------------------------------------------------------------- #
# assert_stable + validation
# --------------------------------------------------------------------------- #


def test_assert_stable_returns_report_when_stable():
    report = assert_stable(
        lambda seed: {"metric": 1.0},
        [0, 1, 2],
        metric_fn=lambda r: r["metric"],
        tolerance=0.0,
    )
    assert report.stable is True


def test_assert_stable_raises_with_reasons_when_unstable():
    values = {0: 0.1, 1: 0.9}
    with pytest.raises(StabilityError) as ei:
        assert_stable(
            lambda seed: {"metric": values[seed]},
            [0, 1],
            metric_fn=lambda r: r["metric"],
            tolerance=0.01,
        )
    # The error message carries the reasons (honest, self-explaining failure).
    assert "not stable" in str(ei.value)
    assert ei.value.report.stable is False


def test_empty_seeds_rejected():
    with pytest.raises(ValueError):
        run_multi_seed(lambda s: {"metric": 0.0}, [], metric_fn=lambda r: r["metric"])


def test_negative_tolerance_rejected():
    with pytest.raises(ValueError):
        run_multi_seed(
            lambda s: {"metric": 0.0},
            [0],
            metric_fn=lambda r: r["metric"],
            tolerance=-0.1,
        )


def test_global_seed_pinned_before_run_fn():
    """When pin_global_seed=True the numpy global RNG is pinned per seed."""
    import numpy as np

    observed: dict[int, float] = {}

    def run_fn(seed: int) -> dict:
        # If the global seed was pinned to `seed`, this draw is deterministic
        # per seed; record it to compare across two independent runs.
        observed[seed] = float(np.random.random())
        return {"metric": 0.0}

    run_multi_seed(run_fn, [7, 8, 9], metric_fn=lambda r: r["metric"])
    first = dict(observed)
    observed.clear()
    run_multi_seed(run_fn, [7, 8, 9], metric_fn=lambda r: r["metric"])
    # Same seeds -> same global-RNG draws across the two ensembles.
    assert observed == first


# --------------------------------------------------------------------------- #
# Boundary: the harness must not import kaine.evaluation
# --------------------------------------------------------------------------- #


def _imports_of(module_path: Path) -> set[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_stability_module_does_not_import_evaluation():
    """The harness lives in kaine.experiment and must stay boundary-neutral:
    it must NOT import kaine.evaluation (so core may use it too)."""
    repo = Path(__file__).parent.parent
    mod = repo / "kaine" / "experiment" / "stability.py"
    imports = _imports_of(mod)
    offenders = {name for name in imports if name.startswith("kaine.evaluation")}
    assert offenders == set(), (
        f"kaine/experiment/stability.py imports {offenders}; the experiment "
        f"foundation must not import kaine.evaluation (sidecar boundary)."
    )


def test_no_core_module_imports_kaine_evaluation_via_stability():
    """git-grep guard: the new harness did not introduce a core->evaluation import."""
    repo = Path(__file__).parent.parent
    proc = subprocess.run(
        ["git", "grep", "-l", "from kaine.evaluation", "--", "kaine/experiment/"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    matches = [line for line in proc.stdout.strip().splitlines() if line]
    assert matches == [], (
        f"kaine/experiment/ must not import kaine.evaluation; found in {matches}."
    )
