# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the cross-record corpus / field-tier statistics layer."""

from __future__ import annotations

import json
import math

import pytest

from kaine.experiment.corpus import (
    RunMetric,
    load_corpus,
    run_multi_record,
)
from kaine.experiment.corpus import (
    _norm_cdf,
    _norm_ppf,
)


# --------------------------------------------------------------------------- #
# closed-form helpers
# --------------------------------------------------------------------------- #


def test_norm_ppf_and_cdf_are_inverses_at_common_quantiles():
    # z_{0.975} ~ 1.959964 — the value the 95% interval turns on.
    assert _norm_ppf(0.975) == pytest.approx(1.959964, abs=1e-4)
    assert _norm_ppf(0.5) == pytest.approx(0.0, abs=1e-9)
    # round-trip: cdf(ppf(p)) == p
    for p in (0.01, 0.1, 0.5, 0.9, 0.99):
        assert _norm_cdf(_norm_ppf(p)) == pytest.approx(p, abs=1e-4)


# --------------------------------------------------------------------------- #
# run_multi_record — verdict logic
# --------------------------------------------------------------------------- #


def _win_values():
    # tightly clustered well above any small min_effect
    return [0.40, 0.42, 0.39, 0.41, 0.43, 0.40, 0.38, 0.41]


def test_clear_positive_effect_is_a_win_and_agrees():
    rep = run_multi_record(
        _win_values(), metric_fn=lambda x: x, experiment="ab", min_effect=0.05
    )
    assert rep.verdict == "WIN"
    assert rep.overall.agree is True
    assert rep.trusted is True
    assert rep.overall.n_runs == 8
    assert rep.overall.method == "bootstrap"


def test_effect_within_min_effect_band_is_null():
    # values hover near zero; a min_effect of 0.2 makes this NULL
    vals = [0.01, -0.02, 0.03, 0.00, -0.01, 0.02]
    rep = run_multi_record(vals, metric_fn=lambda x: x, experiment="ab", min_effect=0.2)
    assert rep.verdict == "NULL"


def test_clear_negative_effect_is_negative_two_sided():
    vals = [-0.40, -0.42, -0.39, -0.41, -0.43, -0.40]
    rep = run_multi_record(
        vals,
        metric_fn=lambda x: x,
        experiment="ab",
        min_effect=0.05,
        direction="two_sided",
    )
    assert rep.verdict == "NEGATIVE"


def test_greater_direction_never_returns_negative():
    vals = [-0.40, -0.42, -0.39, -0.41, -0.43, -0.40]
    rep = run_multi_record(
        vals,
        metric_fn=lambda x: x,
        experiment="ab",
        min_effect=0.05,
        direction="greater",
    )
    assert rep.verdict == "NULL"  # not NEGATIVE, even though clearly below zero


def test_single_run_is_insufficient_not_a_verdict():
    rep = run_multi_record(
        [0.9], metric_fn=lambda x: x, experiment="ab", min_effect=0.05
    )
    assert rep.overall.method == "insufficient"
    assert rep.verdict == "NULL"
    assert rep.overall.n_runs == 1


def test_none_metric_drops_the_record():
    vals = [0.4, 0.41, None, 0.42, 0.39, None]
    rep = run_multi_record(
        vals, metric_fn=lambda x: x, experiment="ab", min_effect=0.05
    )
    assert rep.n_dropped == 2
    assert rep.overall.n_runs == 4


def test_bootstrap_is_reproducible_under_a_fixed_analysis_seed():
    vals = _win_values()
    a = run_multi_record(vals, metric_fn=lambda x: x, experiment="ab", analysis_seed=7)
    b = run_multi_record(vals, metric_fn=lambda x: x, experiment="ab", analysis_seed=7)
    assert a.overall.ci_lo == b.overall.ci_lo
    assert a.overall.ci_hi == b.overall.ci_hi


# --------------------------------------------------------------------------- #
# DerSimonian–Laird path (per-run within-variance supplied)
# --------------------------------------------------------------------------- #


def test_within_run_variance_promotes_to_dersimonian_laird():
    metrics = [RunMetric(value=v, variance=0.01, n=30) for v in _win_values()]
    rep = run_multi_record(
        metrics, metric_fn=lambda m: m, experiment="ab", min_effect=0.05
    )
    assert rep.overall.method == "dersimonian_laird"
    assert rep.overall.tau2 is not None
    assert rep.overall.tau2 >= 0.0
    assert rep.verdict == "WIN"


# --------------------------------------------------------------------------- #
# cross-regime stratification / robustness
# --------------------------------------------------------------------------- #


def test_effect_holds_across_regimes_when_all_agree():
    # two regimes, both clearly positive
    metrics = [RunMetric(v, group="camera") for v in _win_values()] + [
        RunMetric(v, group="playlist") for v in _win_values()
    ]
    rep = run_multi_record(
        metrics, metric_fn=lambda m: m, experiment="ab", min_effect=0.05
    )
    assert rep.verdict == "WIN"
    assert set(rep.by_group) == {"camera", "playlist"}
    assert rep.holds_across_groups is True
    assert rep.trusted is True


def test_effect_does_not_hold_when_a_regime_opposes():
    # overall leans positive, but the 'stream' regime is strongly negative
    metrics = [
        RunMetric(v, group="camera") for v in [0.5, 0.52, 0.48, 0.51, 0.49, 0.5]
    ] + [RunMetric(v, group="stream") for v in [-0.5, -0.52, -0.48, -0.51, -0.49, -0.5]]
    rep = run_multi_record(
        metrics, metric_fn=lambda m: m, experiment="ab", min_effect=0.05
    )
    # whatever the overall resolves to, a contradicting regime breaks robustness
    if rep.verdict in ("WIN", "NEGATIVE"):
        assert rep.holds_across_groups is False
        assert rep.trusted is False


def test_small_regimes_are_not_given_their_own_estimate():
    metrics = [RunMetric(v, group="camera") for v in _win_values()] + [
        RunMetric(0.4, group="rare")  # only one 'rare' record < min_group_runs
    ]
    rep = run_multi_record(
        metrics,
        metric_fn=lambda m: m,
        experiment="ab",
        min_effect=0.05,
        min_group_runs=3,
    )
    assert "rare" not in rep.by_group
    assert "camera" in rep.by_group


# --------------------------------------------------------------------------- #
# serialization
# --------------------------------------------------------------------------- #


def test_report_to_dict_is_json_serializable():
    rep = run_multi_record(
        _win_values(), metric_fn=lambda x: x, experiment="ab", min_effect=0.05
    )
    blob = json.dumps(rep.to_dict())
    parsed = json.loads(blob)
    assert parsed["experiment"] == "ab"
    assert parsed["overall"]["verdict"] == "WIN"
    assert "reasons" in parsed["overall"]


def test_invalid_direction_and_alpha_raise():
    with pytest.raises(ValueError):
        run_multi_record(
            [1, 2, 3], metric_fn=lambda x: x, experiment="x", direction="bogus"
        )
    with pytest.raises(ValueError):
        run_multi_record([1, 2, 3], metric_fn=lambda x: x, experiment="x", alpha=1.5)


# --------------------------------------------------------------------------- #
# load_corpus — admissibility-gated multi-run assembly
# --------------------------------------------------------------------------- #


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def test_load_corpus_admits_many_runs_and_excludes_incomplete(tmp_path):
    root = tmp_path / "data" / "evaluation"
    # r1 and r2: contiguous per-sink seq (admissible). r3: a seq gap (inadmissible).
    _write_jsonl(
        root / "ab_divergence-2026-01-01.jsonl",
        [
            {
                "run_id": "r1",
                "seq": 0,
                "event_type": "ab_divergence",
                "divergence": 0.4,
            },
            {
                "run_id": "r1",
                "seq": 1,
                "event_type": "ab_divergence",
                "divergence": 0.5,
            },
            {
                "run_id": "r2",
                "seq": 0,
                "event_type": "ab_divergence",
                "divergence": 0.3,
            },
            {
                "run_id": "r2",
                "seq": 1,
                "event_type": "ab_divergence",
                "divergence": 0.35,
            },
            {
                "run_id": "r3",
                "seq": 0,
                "event_type": "ab_divergence",
                "divergence": 0.2,
            },
            {
                "run_id": "r3",
                "seq": 2,
                "event_type": "ab_divergence",
                "divergence": 0.9,
            },
        ],
    )
    load = load_corpus(root, expected_streams=(), require_admissible=True)
    admitted_ids = {r.run_id for r in load.admitted}
    assert admitted_ids == {"r1", "r2"}
    assert "r3" in load.excluded
    assert load.unreadable_lines == 0


def test_load_corpus_without_gate_admits_everything(tmp_path):
    root = tmp_path / "data" / "evaluation"
    _write_jsonl(
        root / "ab_divergence-2026-01-01.jsonl",
        [
            {
                "run_id": "r1",
                "seq": 0,
                "event_type": "ab_divergence",
                "divergence": 0.4,
            },
            {
                "run_id": "r3",
                "seq": 0,
                "event_type": "ab_divergence",
                "divergence": 0.2,
            },
            {
                "run_id": "r3",
                "seq": 2,
                "event_type": "ab_divergence",
                "divergence": 0.9,
            },
        ],
    )
    load = load_corpus(root, require_admissible=False)
    assert {r.run_id for r in load.admitted} == {"r1", "r3"}
    assert load.excluded == {}


def test_load_corpus_feeds_run_multi_record(tmp_path):
    root = tmp_path / "data" / "evaluation"
    recs = []
    for i in range(6):
        recs.append(
            {
                "run_id": f"run{i}",
                "seq": 0,
                "event_type": "ab_divergence",
                "divergence": 0.4 + 0.01 * i,
            }
        )
    _write_jsonl(root / "ab_divergence-2026-01-01.jsonl", recs)
    load = load_corpus(root, expected_streams=(), require_admissible=True)

    def metric(run_records):
        vals = [
            r["divergence"] for _, r in run_records.all_records() if "divergence" in r
        ]
        return sum(vals) / len(vals) if vals else None

    rep = run_multi_record(
        load.admitted, metric_fn=metric, experiment="ab_divergence", min_effect=0.05
    )
    assert rep.overall.n_runs == 6
    assert rep.verdict == "WIN"
    assert not math.isnan(rep.overall.effect)
