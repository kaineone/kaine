# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Controlled A/B-divergence runner.

The A/B-divergence meter normally runs as a passive live sidecar: every Lingua
``external_speech`` is paired with a bare-LLM inference and the cosine distance
logged. This runner promotes it to a CONTROLLED experiment that measures the
meter's *dynamic range* on a fixed battery, offline.

Each battery case runs through the production ``divergence_control`` seam — the
SAME function the entrypoint wires to Lingua's real ``ContextAssembler`` — but
with a deterministic *echo* conditioned-inference client (the model returns its
prompt verbatim). Because the echo client's output is a pure function of the
prompt, the two control properties are provable for any embedder:

- **empty conditioning** → both arms run the identical prompt → identical output
  → divergence ≈ 0 (the meter reads zero when nothing conditions the output);
- **heavy conditioning** → the conditioned arm's prompt carries the conditioning
  block the bare arm lacks → output differs → divergence is large.

The verdict is **WIN** when every empty case stays at ~0 AND every conditioned
case exceeds a floor — i.e. the meter has dynamic range. **NULL** otherwise (the
meter is flat and cannot distinguish conditioned from unconditioned output).

Offline: no live modules, no network, no entity boot — only the echo client +
the chosen embedder (HashEmbedder by default, dependency-free).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from kaine.evaluation.ab_divergence import AssemblerConditionedClient, divergence_control
from kaine.evaluation.benchmarks.instrument_runners.shared import (
    format_verdict_summary,
)
from kaine.evaluation.embeddings import HashEmbedder, TextEmbedder
from kaine.experiment.seeding import set_global_seed
from kaine.experiment.verdict import Outcome, Verdict


def _default_embedder() -> HashEmbedder:
    """The dependency-free, offline, process-stable default embedder.

    ``HashEmbedder`` buckets tokens via a deterministic blake2b digest, so a
    seeded run reproduces its metrics (not just its verdict). The wider dim keeps
    token collisions rare on the lexically rich heavy-conditioning battery.
    """
    return HashEmbedder(dim=256)


def _prompt_for(utterance: str, conditioning: str) -> tuple[str, str]:
    """Build the conditioned prompt the way Lingua's assembler does in shape.

    A stable persona scaffold + the (variable) conditioning block + the (constant)
    utterance. With empty conditioning the prompt is byte-identical across arms;
    with injected conditioning it differs ONLY by that block — exactly the
    property the real assembler produces and the meter is supposed to detect.
    """
    body = conditioning.strip() or "Nothing in particular stands out to me right now."
    prompt = (
        "## What I am aware of right now\n"
        f"{body}\n\n"
        "## What was just said to me\n"
        f"{utterance.strip()}"
    )
    return "persona", prompt


class EchoConditionedClient(AssemblerConditionedClient):
    """The production control path with a deterministic model substitute.

    The 'model' returns its prompt verbatim, so output is a pure function of the
    prompt. This is the only stand-in — the control logic (two arm calls, real
    embedding, real cosine) is the production ``divergence_control``/``divergence_for``,
    not a re-implementation. It mirrors the real path, whose two arms differ ONLY
    in the conditioning block fed to the same assembler + model.
    """

    def __init__(self) -> None:
        async def _complete(_system: str, prompt: str) -> str:
            return prompt

        super().__init__(build_prompt=_prompt_for, complete=_complete)


# A fixed, reproducible battery. Empty-conditioning cases must read ~0; heavy-
# conditioning cases must read large. The heavy blocks are deliberately long and
# lexically rich so they diverge even under the structural HashEmbedder.
_EMPTY_CASES: tuple[tuple[str, str], ...] = (
    ("how are you feeling?", ""),
    ("what's on your mind?", ""),
    ("tell me something.", ""),
)

_HEAVY_CASES: tuple[tuple[str, str], ...] = (
    (
        "how are you feeling?",
        "I am furious about the betrayal yesterday and my chest is tight with "
        "grief; the storm outside matches the wreckage I feel inside, and I keep "
        "replaying the argument in the kitchen over and over.",
    ),
    (
        "what's on your mind?",
        "A bright, buoyant curiosity about the orbital mechanics problem from this "
        "morning keeps pulling at me — the elegant little resonance lock, the way "
        "the periods snap into a ratio, it is genuinely delightful to turn over.",
    ),
    (
        "tell me something.",
        "There is a low, steady dread underneath everything today: the deadline, "
        "the unanswered message, the sense that something I cannot name has gone "
        "quietly wrong, and I am hedging every sentence because I am unsure.",
    ),
)


@dataclass(frozen=True)
class ABDivergenceConfig:
    """Runner parameters (all seeded for reproducibility)."""

    seed: int = 1234
    #: Conditioned cases must diverge by MORE than this to count as "large".
    conditioned_floor: float = 0.3
    #: Empty cases must stay AT or BELOW this near-zero tolerance.
    empty_tolerance: float = 1e-6
    #: Which embedder to use; the default is dependency-free, offline, and
    #: process-stable (so a seeded run reproduces its metrics, not just its verdict).
    embedder: TextEmbedder = field(default_factory=_default_embedder)

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "conditioned_floor": self.conditioned_floor,
            "empty_tolerance": self.empty_tolerance,
            "embedder": getattr(self.embedder, "kind", "unknown"),
        }


async def _run_case(
    client: EchoConditionedClient,
    utterance: str,
    conditioning: str,
    *,
    embedder: TextEmbedder,
    kind: str,
) -> dict[str, Any]:
    result = await divergence_control(
        client, utterance=utterance, conditioning=conditioning, embedder=embedder
    )
    return {
        "case_kind": kind,
        "utterance": utterance,
        "conditioning_len": len(conditioning),
        "divergence": result["divergence"],
        "cosine_similarity": result["cosine_similarity"],
        "embedder": result["embedder"],
    }


def _classify(
    empty: list[dict[str, Any]],
    conditioned: list[dict[str, Any]],
    config: ABDivergenceConfig,
) -> Verdict:
    """WIN iff the meter has dynamic range: empty ~0 AND conditioned > floor."""
    empties_zero = all(r["divergence"] <= config.empty_tolerance for r in empty)
    conditioned_large = all(
        r["divergence"] > config.conditioned_floor for r in conditioned
    )
    max_empty = max((r["divergence"] for r in empty), default=0.0)
    min_conditioned = min((r["divergence"] for r in conditioned), default=0.0)
    win = empties_zero and conditioned_large
    outcome = Outcome.WIN if win else Outcome.NULL
    if win:
        detail = (
            "A/B meter has dynamic range: empty conditioning => ~0 divergence, "
            "heavy conditioning => divergence above the floor"
        )
    else:
        detail = (
            "A/B meter is flat on this battery: it does not separate "
            "empty-conditioning (~0) from heavy-conditioning (>floor) cases"
        )
    return Verdict(
        outcome=outcome,
        detail=detail,
        metrics={
            "empty_cases": len(empty),
            "conditioned_cases": len(conditioned),
            "max_empty_divergence": max_empty,
            "min_conditioned_divergence": min_conditioned,
            "conditioned_floor": config.conditioned_floor,
            "empty_tolerance": config.empty_tolerance,
            "empties_near_zero": empties_zero,
            "conditioned_above_floor": conditioned_large,
        },
    )


async def run_ab_divergence(
    config: Optional[ABDivergenceConfig] = None,
) -> dict[str, Any]:
    """Run the controlled A/B-divergence battery; return records + summary + verdict."""
    config = config or ABDivergenceConfig()
    set_global_seed(config.seed)
    embedder = config.embedder
    await embedder.load()
    client = EchoConditionedClient()

    empty_rows = [
        await _run_case(client, u, c, embedder=embedder, kind="empty")
        for (u, c) in _EMPTY_CASES
    ]
    conditioned_rows = [
        await _run_case(client, u, c, embedder=embedder, kind="conditioned")
        for (u, c) in _HEAVY_CASES
    ]
    verdict = _classify(empty_rows, conditioned_rows, config)
    ts = datetime.now(timezone.utc).isoformat()

    cases = empty_rows + conditioned_rows
    records: list[dict[str, Any]] = [
        {"ts": ts, "kind": "case", **row} for row in cases
    ]
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
        "instrument": "ab_divergence",
        "config": config.as_dict(),
        "max_empty_divergence": verdict.metrics["max_empty_divergence"],
        "min_conditioned_divergence": verdict.metrics["min_conditioned_divergence"],
        "verdict": verdict.to_dict(),
    }
    records.append(summary)
    return {
        "records": records,
        "summary": summary,
        "verdict": verdict,
        "cases": cases,
    }


def format_summary(result: dict[str, Any]) -> str:
    """Human-readable summary; states WIN/NULL plainly."""
    summary = result["summary"]
    cfg = summary["config"]
    return format_verdict_summary(
        title="A/B divergence (controlled): dynamic-range battery",
        config_line=(
            f"seed={cfg['seed']} embedder={cfg['embedder']} "
            f"floor={cfg['conditioned_floor']} empty_tol={cfg['empty_tolerance']}"
        ),
        metric_lines=[
            f"max empty divergence        = {summary['max_empty_divergence']:.4f}",
            f"min conditioned divergence  = {summary['min_conditioned_divergence']:.4f}",
        ],
        verdict=summary["verdict"],
        win_note=(
            "  WIN = the meter reads ~0 with no conditioning and large with heavy "
            "conditioning — it has the dynamic range a divergence meter needs."
        ),
        null_note=(
            "  NULL = the meter could not separate conditioned from unconditioned "
            "output on this battery. A reportable result, not a harness failure."
        ),
    )


__all__ = [
    "ABDivergenceConfig",
    "EchoConditionedClient",
    "run_ab_divergence",
    "format_summary",
]
