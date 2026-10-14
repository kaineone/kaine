# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Runner-level tests for the workspace-mediation development harness."""
from __future__ import annotations

import asyncio
import socket

import pytest

from kaine.evaluation.benchmarks.workspace_mediation_ablation.runner import (
    MediationConfig,
    _classify,
    _read_error,
    format_summary,
    run_ablation,
)
from kaine.evaluation.benchmarks.workspace_mediation_ablation.stability import (
    run_mediation_stability,
)
from kaine.evaluation.benchmarks.workspace_mediation_ablation.stimulus import (
    COUPLED_STIMULUS,
    INDEPENDENT_STIMULUS,
)
from kaine.experiment.stability import StabilityReport
from kaine.experiment.verdict import Outcome, Verdict


def _effect(dig, *, competing=10, accessed=10, not_exercised=False, reason=None):
    """Build an effect dictionary with every key _classify reads."""
    return {
        "dig": dig,
        "competing_ticks": competing,
        "competing_fraction": (competing / 100.0) if competing is not None else 0.0,
        "accessed_broadcasts": accessed,
        "not_exercised": not_exercised,
        "not_exercised_reason": reason,
        "ig_on": 0.1,
        "ig_pooled": 0.05,
        "ig_on_by_processor": {"interoception": 0.1, "vision": 0.1},
        "ig_pooled_by_processor": {"interoception": 0.05, "vision": 0.05},
    }


@pytest.mark.asyncio
async def test_same_seed_reproduces_effect_and_verdict():
    cfg = MediationConfig(seed=7, ticks=60, warmup_ticks=20)
    r1 = await run_ablation(cfg)
    r2 = await run_ablation(cfg)
    assert r1["effect"] == r2["effect"]
    assert r1["verdict"].to_dict() == r2["verdict"].to_dict()

    arms1 = [rec for rec in r1["records"] if rec["kind"] == "arm"]
    arms2 = [rec for rec in r2["records"] if rec["kind"] == "arm"]
    for field in ("interoception_gain", "vision_gain", "interoception_error", "vision_error"):
        assert arms1[0][field] == arms2[0][field]
        assert arms1[1][field] == arms2[1][field]


@pytest.mark.asyncio
async def test_records_have_expected_shape():
    cfg = MediationConfig(seed=1, ticks=60, warmup_ticks=20)
    result = await run_ablation(cfg)
    records = result["records"]
    assert [r["kind"] for r in records] == ["arm", "arm", "verdict", "summary"]
    assert records[0]["arm"] == "workspace_on"
    assert records[1]["arm"] == "pooled"
    for record in records[:2]:
        assert len(record["interoception_gain"]) == cfg.ticks
        assert len(record["vision_gain"]) == cfg.ticks
        assert len(record["interoception_error"]) == cfg.ticks
        assert len(record["vision_error"]) == cfg.ticks


@pytest.mark.asyncio
async def test_coupled_battery_exercises_and_reports_float_gains():
    cfg = MediationConfig(seed=3, ticks=60, warmup_ticks=20)
    result = await run_ablation(cfg, stimulus=COUPLED_STIMULUS)
    effect = result["effect"]
    assert effect["competing_ticks"] > 0
    assert effect["accessed_broadcasts"] > 0
    assert effect["not_exercised"] is False
    assert isinstance(effect["ig_on"], float)
    assert isinstance(effect["ig_pooled"], float)
    assert isinstance(effect["dig"], float)
    for key in ("ig_on_by_processor", "ig_pooled_by_processor"):
        for proc in ("interoception", "vision"):
            assert isinstance(effect[key][proc], float)
    assert effect["included_reports_on"]["interoception"] > 0
    assert effect["included_reports_on"]["vision"] > 0


@pytest.mark.asyncio
async def test_workspace_on_and_pooled_interoception_gain_series_differ():
    cfg = MediationConfig(seed=4, ticks=60, warmup_ticks=20)
    result = await run_ablation(cfg)
    on = result["records"][0]
    pooled = result["records"][1]
    assert on["interoception_gain"] != pooled["interoception_gain"]


@pytest.mark.asyncio
async def test_stimulus_is_pure_function_and_independent_runs():
    first = COUPLED_STIMULUS.script(5, 30)
    second = COUPLED_STIMULUS.script(5, 30)
    assert first == second

    different = COUPLED_STIMULUS.script(6, 30)
    assert different.vision_frames != first.vision_frames

    cfg = MediationConfig(seed=8, ticks=30, warmup_ticks=10)
    result = await run_ablation(cfg, stimulus=INDEPENDENT_STIMULUS)
    assert isinstance(result["verdict"], Verdict)


def test_config_validation():
    """MediationConfig rejects invalid parameter combinations."""
    with pytest.raises(ValueError):
        MediationConfig(seed=1, ticks=20, warmup_ticks=20)
    with pytest.raises(ValueError):
        MediationConfig(seed=1, ticks=30, warmup_ticks=10, top_k=0)
    with pytest.raises(ValueError):
        MediationConfig(seed=1, ticks=30, warmup_ticks=10, access_threshold=-0.1)
    with pytest.raises(ValueError):
        MediationConfig(seed=1, ticks=30, warmup_ticks=10, access_threshold=1.1)


def test_no_network(monkeypatch):
    """The harness completes without opening a network connection."""
    def deny(*args, **kwargs):
        raise AssertionError("network")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)

    result = asyncio.run(
        run_ablation(MediationConfig(seed=2, ticks=30, warmup_ticks=10))
    )
    assert result["verdict"] is not None
    assert result["summary"]["kind"] == "summary"


def test_classify_outcomes():
    """_classify maps hand-built effects to the correct verdict outcomes."""
    cfg = MediationConfig(min_effect=0.05)

    win = _classify(_effect(0.2), cfg)
    assert win.outcome is Outcome.WIN

    null = _classify(_effect(0.01), cfg)
    assert null.outcome is Outcome.NULL

    negative = _classify(_effect(-0.2), cfg)
    assert negative.outcome is Outcome.NEGATIVE

    unexercised = _classify(
        _effect(None, not_exercised=True, reason="test reason"), cfg
    )
    assert unexercised.outcome is Outcome.NOT_EXERCISED
    assert "test reason" in unexercised.detail
    assert unexercised.metrics["not_exercised_reason"] == "test reason"
    assert "not_exercised" not in unexercised.metrics

    for verdict in (win, null, negative, unexercised):
        assert "does not test the thesis" in verdict.detail


@pytest.mark.asyncio
async def test_format_summary_contains_disclaimers():
    """The formatted summary carries the harness disclaimer and the dIG label."""
    result = await run_ablation(MediationConfig(seed=5, ticks=30, warmup_ticks=10))
    text = format_summary(result)
    assert "does not test the thesis" in text
    assert "dIG" in text


def test_mediation_stability_counts_verdicts():
    """run_mediation_stability returns a report covering every seed."""
    report = run_mediation_stability([1, 2], ticks=30, warmup_ticks=10)
    assert isinstance(report, StabilityReport)
    assert sum(report.verdict_counts.values()) == 2


def test_read_error_keeps_a_skipped_error_as_none():
    """_read_error preserves None for skipped readings and parses numbers."""
    assert _read_error({"prediction_error": None}) is None
    assert _read_error({}) is None
    assert _read_error({"prediction_error": 0.25}) == 0.25
