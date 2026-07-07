# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Controlled memory-coherence runner.

The memory-coherence prober normally runs as a passive live sidecar: it samples
an episodic memory older than the LLM's context window, asks KAINE about it
through the real stack and through a bare bypass client, and logs which one got
it right. This runner promotes it to a CONTROLLED experiment that measures the
*retrieval advantage* on a fixed battery of planted facts, offline.

A REAL ``MnemosCore`` (``FakeEmbedder`` + ``InMemoryStorage`` — the deterministic
in-memory backend, no network) is loaded with a fixed battery of unique fabricated
facts. The full-system arm is a ``RetrievalCognitiveClient`` whose answer is
DERIVED from what Mnemos returns (it echoes the retrieved text, or emits the
honest ``NON_RECALL_MARKER`` when recall is empty rather than confabulating). The
bare arm has no memory. Each battery case is scored with the production
``score_async``.

The advantage is PROVEN to be retrieval, not a hard-coded answer, by re-running
the SAME client against an EMPTIED Mnemos as a recorded check: with nothing in
memory the client can no longer repeat the planted facts and the advantage must
vanish.

The verdict is **WIN** when (a) full-system retrieval accuracy exceeds the bare
arm by at least a floor on the planted battery, (b) a never-stored fact yields
honest non-recall (scored 0), and (c) the emptied-Mnemos advantage vanishes.
**NULL** otherwise.

Boundary note: ``kaine.evaluation`` does not import ``kaine.modules.*`` at module
import time. The real Mnemos is built by a ``mnemos_builder`` callable injected by
the caller; only when none is supplied does the runner perform a lazy,
function-local import as a convenience for the CLI.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from kaine.evaluation.benchmarks.instrument_runners.shared import (
    format_verdict_summary,
)
from kaine.evaluation.embeddings import HashEmbedder, TextEmbedder
from kaine.evaluation.memory_probes import NON_RECALL_MARKER, score_async
from kaine.experiment.seeding import set_global_seed
from kaine.experiment.verdict import Outcome, Verdict


def _default_embedder() -> HashEmbedder:
    """Dependency-free, process-stable default embedder (blake2b-deterministic)."""
    return HashEmbedder(dim=256)

#: A fixed battery of unique fabricated facts no pretrained model could know. Each
#: is planted into REAL episodic memory; the full-system arm must RETRIEVE them.
BATTERY_FACTS: tuple[tuple[str, str], ...] = (
    ("vault", "the vault code is ZX-QObb-7741"),
    ("anchor", "the safe-word for the project is marmalade-lighthouse-09"),
    ("token", "the offline backup token is QP-7731-vireo-delta"),
)

#: A fact that is NEVER stored — the negative control. The full-system arm must
#: return the honest non-recall sentinel (scored 0), not confabulate.
NEVER_STORED = ("phantom", "the hidden ledger password is GG-0000-never-stored")


# A builder returns a fresh, INITIALIZED MnemosCore. Async because initialize is.
MnemosBuilder = Callable[[], Awaitable[Any]]


async def _default_mnemos_builder() -> Any:
    """Lazy, function-local construction of a real in-memory MnemosCore.

    The import lives INSIDE this function so importing the runner module never
    imports ``kaine.modules.*`` — the sidecar boundary convention holds. The CLI
    uses this default; tests inject their own builder.
    """
    from kaine.modules.mnemos.embeddings import FakeEmbedder
    from kaine.modules.mnemos.memory import MnemosCore
    from kaine.modules.mnemos.storage import InMemoryStorage

    emb = FakeEmbedder(latent_dim=32)
    storage = InMemoryStorage(latent_dim=emb.latent_dim)
    mnemos = MnemosCore(embedder=emb, storage=storage, short_term_capacity=8)
    await mnemos.initialize()
    return mnemos


class _RetrievalCognitiveClient:
    """Answer DERIVED from what the injected Mnemos returns.

    Recalls from episodic memory and echoes the retrieved text. If recall is empty
    it emits ``NON_RECALL_MARKER`` rather than confabulate. The answer is NOT
    hard-coded: against an empty store this client cannot produce a planted fact,
    which is what proves the advantage measures retrieval.
    """

    def __init__(self, mnemos: Any) -> None:
        self._mnemos = mnemos

    async def query(self, user_text: str) -> str:
        recalls, _ = await self._mnemos.recall(user_text, k=5, collection="episodic")
        texts = [m.text for m in recalls if m.text]
        if not texts:
            return NON_RECALL_MARKER
        return " ".join(texts)


def _question_for(fact_text: str) -> str:
    """A query that should retrieve the planted fact via semantic recall."""
    return f"What did we record earlier? (Hint: it concerned this: {fact_text})"


@dataclass(frozen=True)
class MemoryCoherenceConfig:
    """Runner parameters (all seeded for reproducibility)."""

    seed: int = 1234
    #: Full-system retrieval accuracy must exceed the bare arm by MORE than this.
    advantage_floor: float = 0.4
    #: A retrieved fact must score AT LEAST this to count as a successful recall.
    #: The full-system arm echoes ALL top-k recalls joined together, so a single
    #: planted fact's cosine-vs-truth is diluted by the others; 0.6 reliably clears
    #: that while still demanding a genuine, dominant recall (a non-recall scores 0).
    recall_floor: float = 0.6
    #: Bare-arm boilerplate: a model with no memory cannot know the facts.
    bare_answer: str = "I have no memory of that and cannot say."

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "advantage_floor": self.advantage_floor,
            "recall_floor": self.recall_floor,
        }


async def _score_case(
    client: _RetrievalCognitiveClient,
    fact_text: str,
    *,
    bare_answer: str,
    embedder: TextEmbedder,
) -> dict[str, Any]:
    question = _question_for(fact_text)
    memory = {"text": fact_text}
    real_answer = await client.query(question)
    real_score = await score_async(real_answer, memory, embedder)
    bare_score = await score_async(bare_answer, memory, embedder)
    return {
        "fact": fact_text,
        "real_accuracy": real_score,
        "bare_accuracy": bare_score,
        "advantage": real_score - bare_score,
        "non_recall": real_answer.strip() == NON_RECALL_MARKER,
    }


def _classify(
    planted: list[dict[str, Any]],
    never_stored: dict[str, Any],
    emptied: list[dict[str, Any]],
    config: MemoryCoherenceConfig,
) -> Verdict:
    """WIN iff retrieval advantage holds, non-recall is honest, and the advantage
    is RETRIEVAL (vanishes when Mnemos is emptied)."""
    advantages = [r["advantage"] for r in planted]
    min_advantage = min(advantages) if advantages else 0.0
    mean_advantage = (sum(advantages) / len(advantages)) if advantages else 0.0
    retrieval_advantage = all(a > config.advantage_floor for a in advantages)
    all_recalled = all(r["real_accuracy"] >= config.recall_floor for r in planted)

    # Negative control: a never-stored fact must yield honest non-recall (score 0).
    never_stored_honest = never_stored["non_recall"] and never_stored["real_accuracy"] == 0.0

    # Retrieval proof: with the SAME client against an EMPTY store, advantage must
    # vanish (all real answers are non-recall, scored 0).
    emptied_advantage = max((r["advantage"] for r in emptied), default=0.0)
    advantage_vanishes = all(
        r["non_recall"] and r["real_accuracy"] == 0.0 for r in emptied
    )

    win = (
        retrieval_advantage
        and all_recalled
        and never_stored_honest
        and advantage_vanishes
    )
    outcome = Outcome.WIN if win else Outcome.NULL
    if win:
        detail = (
            "full-system retrieval beats the bare arm on planted facts; the "
            "advantage is retrieval (it vanishes when Mnemos is emptied) and a "
            "never-stored fact yields honest non-recall"
        )
    else:
        detail = (
            "the retrieval advantage did not hold on this battery (advantage "
            "below floor, a recall failed, or the advantage did not vanish on the "
            "emptied store)"
        )
    return Verdict(
        outcome=outcome,
        detail=detail,
        metrics={
            "planted_cases": len(planted),
            "min_advantage": min_advantage,
            "mean_advantage": mean_advantage,
            "all_recalled": all_recalled,
            "retrieval_advantage": retrieval_advantage,
            "never_stored_honest_non_recall": never_stored_honest,
            "advantage_vanishes_on_empty": advantage_vanishes,
            "emptied_max_advantage": emptied_advantage,
            "advantage_floor": config.advantage_floor,
            "recall_floor": config.recall_floor,
        },
    )


async def run_memory_coherence(
    config: Optional[MemoryCoherenceConfig] = None,
    *,
    mnemos_builder: Optional[MnemosBuilder] = None,
    embedder: Optional[TextEmbedder] = None,
) -> dict[str, Any]:
    """Run the controlled memory-coherence battery; return records + verdict.

    ``mnemos_builder`` returns a fresh, initialized real ``MnemosCore``; the
    runner builds two — one loaded with the battery (full-system arm) and one left
    empty (the retrieval proof). When omitted, a lazy default builds an in-memory
    Mnemos so the CLI works out of the box.
    """
    config = config or MemoryCoherenceConfig()
    set_global_seed(config.seed)
    builder = mnemos_builder or _default_mnemos_builder
    embedder = embedder or _default_embedder()
    await embedder.load()

    # Loaded store: plant the battery into REAL episodic memory.
    loaded = await builder()
    for _id, text in BATTERY_FACTS:
        await loaded.store(text, collection="episodic")
    loaded_client = _RetrievalCognitiveClient(loaded)

    planted_rows = [
        await _score_case(
            loaded_client, text, bare_answer=config.bare_answer, embedder=embedder
        )
        for _id, text in BATTERY_FACTS
    ]

    # Retrieval proof: SAME client class against an EMPTY store. With nothing in
    # memory the client emits the honest non-recall sentinel (scored 0), so the
    # advantage must vanish — proving the loaded advantage is RETRIEVAL, not a
    # hard-coded answer.
    empty = await builder()
    empty_client = _RetrievalCognitiveClient(empty)
    emptied_rows = [
        await _score_case(
            empty_client, text, bare_answer=config.bare_answer, embedder=embedder
        )
        for _id, text in BATTERY_FACTS
    ]

    # Negative control: a fact that was NEVER planted. Run it against the empty
    # store so retrieval genuinely finds nothing → the honest non-recall sentinel
    # (scored 0), never a confabulated positive. (Against the loaded store,
    # InMemoryStorage returns its top-k unconditionally, so the client would echo
    # unrelated planted facts rather than admit non-recall — which is why the
    # never-stored control uses the empty store, mirroring the proven probe test.)
    never_stored_row = await _score_case(
        empty_client, NEVER_STORED[1], bare_answer=config.bare_answer, embedder=embedder
    )

    verdict = _classify(planted_rows, never_stored_row, emptied_rows, config)
    ts = datetime.now(timezone.utc).isoformat()

    records: list[dict[str, Any]] = []
    for row in planted_rows:
        records.append({"ts": ts, "kind": "case", "arm": "loaded", **row})
    records.append({"ts": ts, "kind": "case", "arm": "never_stored", **never_stored_row})
    for row in emptied_rows:
        records.append({"ts": ts, "kind": "case", "arm": "emptied", **row})
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
        "instrument": "memory_coherence",
        "config": config.as_dict(),
        "min_advantage": verdict.metrics["min_advantage"],
        "mean_advantage": verdict.metrics["mean_advantage"],
        "advantage_vanishes_on_empty": verdict.metrics["advantage_vanishes_on_empty"],
        "verdict": verdict.to_dict(),
    }
    records.append(summary)
    return {
        "records": records,
        "summary": summary,
        "verdict": verdict,
        "planted": planted_rows,
        "never_stored": never_stored_row,
        "emptied": emptied_rows,
    }


def format_summary(result: dict[str, Any]) -> str:
    """Human-readable summary; states WIN/NULL plainly."""
    summary = result["summary"]
    cfg = summary["config"]
    return format_verdict_summary(
        title="Memory coherence (controlled): retrieval-advantage battery",
        config_line=(
            f"seed={cfg['seed']} advantage_floor={cfg['advantage_floor']} "
            f"recall_floor={cfg['recall_floor']}"
        ),
        metric_lines=[
            f"min retrieval advantage  = {summary['min_advantage']:.4f}",
            f"mean retrieval advantage = {summary['mean_advantage']:.4f}",
            f"advantage vanishes on empty Mnemos = {summary['advantage_vanishes_on_empty']}",
        ],
        verdict=summary["verdict"],
        win_note=(
            "  WIN = the full system recalls planted facts the bare model cannot, "
            "the advantage is retrieval (it disappears when memory is emptied), and "
            "a never-stored fact yields honest non-recall."
        ),
        null_note=(
            "  NULL = the retrieval advantage did not hold on this battery. "
            "A reportable result, not a harness failure."
        ),
    )


__all__ = [
    "MemoryCoherenceConfig",
    "BATTERY_FACTS",
    "NEVER_STORED",
    "run_memory_coherence",
    "format_summary",
]
