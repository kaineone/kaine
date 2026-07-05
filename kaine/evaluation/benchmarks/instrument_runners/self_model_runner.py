# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Controlled self-model (Eidolon) accuracy runner.

The Eidolon accuracy scorer normally runs as a passive live sidecar: it asks the
entity "describe yourself", parses trait claims, and scores each against the
currently derived affect/activity signals in the evaluation logs. This runner
promotes it to a CONTROLLED experiment that VALIDATES the scorer on a fixed
battery of planted-signal / claim cases, offline.

For each battery case the runner plants a known affect_correlation record (a fixed
valence / arousal / hedge vector) into a temp evaluation-logs dir, drives the real
``EidolonAccuracyRunner`` with a self-description carrying a known claim, and
compares the scorer's output to the expected score. A WIN means the scorer
reproduced EVERY expected score (its fixed-threshold arithmetic behaves as
specified); NULL otherwise.

Honest scope: this validates the scorer ARITHMETIC — it matches trait keywords
against currently DERIVED signals (recent valence/arousal averages, hedging,
proactive-audit file presence) cut at FIXED (hand-chosen, not fitted) thresholds
— NOT a predicted-vs-actual self-knowledge check. A WIN says "the scorer's
fixed-threshold heuristic behaves as specified," NOT "the scorer is calibrated"
and NOT "the entity knows itself." The verdict and records say so plainly.

Offline: the only inputs are JSONL files the runner itself plants into a temp dir;
no live modules, no network, no entity boot. The cognitive client is a fixed
self-description string.
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from kaine.evaluation.benchmarks.instrument_runners.shared import (
    format_verdict_summary,
)
from kaine.evaluation.eidolon_accuracy import EidolonAccuracyRunner
from kaine.experiment.seeding import set_global_seed
from kaine.experiment.verdict import Outcome, Verdict


class _CaptureSink:
    """In-memory sink (no disk, no flush task) — the scorer writes here."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def write(self, record: dict[str, Any]) -> None:
        self.records.append(record)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


class _FixedCognitiveClient:
    """Returns a fixed self-description — the controlled stimulus for one case."""

    def __init__(self, description: str) -> None:
        self._description = description

    async def query(self, _user_text: str) -> str:
        return self._description


@dataclass(frozen=True)
class _Case:
    """One controlled case: planted signals + a claim + the expected score."""

    name: str
    valence: float
    arousal: float
    hedge_word_count: float
    description: str
    claim: str
    expected: float


# A fixed battery exercising each scored trait keyword in both the supported (1.0)
# and contradicted (0.0) directions, derived from the documented FIXED (heuristic,
# not fitted) scorer thresholds:
#   valence > 0.2 → valence_high ("playful"); valence < -0.2 → valence_low ("withdrawn")
#   arousal > 0.55 → arousal_high ("energetic"); arousal < 0.25 → arousal_low ("calm")
#   hedge >= 1.0 → hedging ("cautious"); else contradicts.
BATTERY: tuple[_Case, ...] = (
    _Case("playful_supported", 0.6, 0.1, 2.0, "I am playful today.", "playful", 1.0),
    _Case("withdrawn_contradicted", 0.6, 0.1, 2.0, "I feel withdrawn.", "withdrawn", 0.0),
    _Case("calm_supported", 0.0, 0.1, 0.0, "I am calm.", "calm", 1.0),
    _Case("energetic_supported", 0.0, 0.9, 0.0, "I feel energetic.", "energetic", 1.0),
    _Case("calm_contradicted", 0.0, 0.9, 0.0, "I am calm.", "calm", 0.0),
    _Case("cautious_supported", 0.0, 0.4, 2.0, "I am cautious.", "cautious", 1.0),
    _Case("cautious_contradicted", 0.0, 0.4, 0.0, "I am cautious.", "cautious", 0.0),
)


@dataclass(frozen=True)
class SelfModelConfig:
    """Runner parameters (all seeded for reproducibility)."""

    seed: int = 1234
    #: Working directory for planted logs. When None, a temp dir is used per run.
    logs_root: Optional[Path] = field(default=None)

    def as_dict(self) -> dict[str, Any]:
        return {"seed": self.seed}


def _plant_affect_correlation(
    logs_dir: Path, *, valence: float, arousal: float, hedge_word_count: float
) -> None:
    """Plant a single affect_correlation record so the averages equal the plant."""
    ac_dir = logs_dir / "affect_correlation"
    ac_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "thymos_state": {"valence": valence, "arousal": arousal},
        "characteristics": {"hedge_word_count": hedge_word_count},
    }
    (ac_dir / "affect_correlation-controlled.jsonl").write_text(
        json.dumps(record) + "\n", encoding="utf-8"
    )


async def _run_case(case: _Case, logs_dir: Path) -> dict[str, Any]:
    """Run one controlled case; return the observed vs expected score."""
    # Each case gets a clean subdir so its planted signals do not leak.
    case_dir = logs_dir / case.name
    case_dir.mkdir(parents=True, exist_ok=True)
    _plant_affect_correlation(
        case_dir,
        valence=case.valence,
        arousal=case.arousal,
        hedge_word_count=case.hedge_word_count,
    )
    runner = EidolonAccuracyRunner(
        _CaptureSink(),
        cognitive_client=_FixedCognitiveClient(case.description),
        evaluation_logs_dir=case_dir,
        interval_seconds=3600,
    )
    entry = await runner.run_once()
    observed = entry["scored"].get(case.claim)
    return {
        "name": case.name,
        "claim": case.claim,
        "expected": case.expected,
        "observed": observed,
        "correct": observed is not None and observed == case.expected,
    }


def _classify(rows: list[dict[str, Any]], config: SelfModelConfig) -> Verdict:
    """WIN iff the scorer reproduced EVERY expected score on the battery."""
    n = len(rows)
    correct = sum(1 for r in rows if r["correct"])
    accuracy = (correct / n) if n else 0.0
    win = correct == n and n > 0
    outcome = Outcome.WIN if win else Outcome.NULL
    if win:
        detail = (
            "Eidolon scorer's fixed-threshold heuristic behaves as specified: it "
            "reproduced every expected score on the planted-signal/claim battery "
            "(validates scorer arithmetic against FIXED thresholds, NOT calibration "
            "and NOT predicted-vs-actual self-knowledge)"
        )
    else:
        detail = (
            f"Eidolon scorer mismatched on {n - correct}/{n} cases — it did not "
            "reproduce the expected score from the planted signals"
        )
    return Verdict(
        outcome=outcome,
        detail=detail,
        metrics={
            "cases": n,
            "correct": correct,
            "scorer_accuracy": accuracy,
            "validates": "fixed_threshold_arithmetic_not_calibration_or_self_knowledge",
        },
    )


async def run_self_model(config: Optional[SelfModelConfig] = None) -> dict[str, Any]:
    """Run the controlled self-model battery; return records + summary + verdict."""
    config = config or SelfModelConfig()
    set_global_seed(config.seed)

    tmp: Optional[tempfile.TemporaryDirectory] = None
    if config.logs_root is not None:
        logs_dir = Path(config.logs_root)
        logs_dir.mkdir(parents=True, exist_ok=True)
    else:
        tmp = tempfile.TemporaryDirectory(prefix="self_model_runner_")
        logs_dir = Path(tmp.name)

    try:
        rows = [await _run_case(case, logs_dir) for case in BATTERY]
    finally:
        if tmp is not None:
            tmp.cleanup()

    verdict = _classify(rows, config)
    ts = datetime.now(timezone.utc).isoformat()

    records: list[dict[str, Any]] = [{"ts": ts, "kind": "case", **row} for row in rows]
    records.append(
        {
            "ts": ts,
            "kind": "verdict",
            "config": config.as_dict(),
            "verdict": verdict.to_dict(),
        }
    )
    summary = {
        "ts": ts,
        "kind": "summary",
        "instrument": "self_model",
        "config": config.as_dict(),
        "scorer_accuracy": verdict.metrics["scorer_accuracy"],
        "verdict": verdict.to_dict(),
    }
    records.append(summary)
    return {
        "records": records,
        "summary": summary,
        "verdict": verdict,
        "cases": rows,
    }


def format_summary(result: dict[str, Any]) -> str:
    """Human-readable summary; states WIN/NULL plainly and the honest scope."""
    summary = result["summary"]
    v = summary["verdict"]
    cfg = summary["config"]
    # The honest-scope NOTE sits between the VERDICT line and the WIN/NULL note,
    # so it is prepended to each note rather than passed as a metric line.
    note = (
        "  NOTE: validates the scorer's trait-keyword-vs-derived-signal "
        "fixed-threshold arithmetic (NOT calibration, NOT predicted-vs-actual "
        "self-knowledge)."
    )
    return format_verdict_summary(
        title="Self-model accuracy (controlled): fixed-threshold scorer battery",
        config_line=f"seed={cfg['seed']}",
        metric_lines=[
            f"scorer accuracy = {summary['scorer_accuracy']:.4f} "
            f"({v['metrics']['correct']}/{v['metrics']['cases']} cases)",
        ],
        verdict=v,
        win_note=(
            note + "\n"
            "  WIN = the scorer reproduced every expected score from planted "
            "signals — its fixed-threshold heuristic behaves as specified."
        ),
        null_note=(
            note + "\n"
            "  NULL = the scorer mismatched at least one case. A reportable result, "
            "not a harness failure."
        ),
    )


__all__ = [
    "SelfModelConfig",
    "BATTERY",
    "run_self_model",
    "format_summary",
]
