# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Memory coherence prober.

Picks an episodic memory older than the LLM's effective context
window. Asks KAINE about it through Lingua (real cognitive stack)
and through the bare bypass client. Logs which one got it right.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from kaine.evaluation._base import BaseObserver
from kaine.evaluation.ab_divergence import BareInferenceClient
from kaine.evaluation.embeddings import TextEmbedder, cosine_similarity
from kaine.evaluation.sink import AsyncJsonlSink

log = logging.getLogger(__name__)

#: Honest non-recall sentinel. A retrieval-backed cognitive client that finds
#: nothing relevant in memory SHALL return this marker INSTEAD of confabulating a
#: plausible answer. `score_async` recognises it and scores it exactly 0.0, so a
#: "memory absent → said so" outcome can never be mistaken for a recall and a
#: confabulated non-empty answer can never read as a false positive. The string is
#: deliberately unlike any real memory text so incidental lexical overlap with a
#: ground-truth memory cannot lift its score under the embedding path either.
NON_RECALL_MARKER = "__KAINE_NO_MEMORY_RECALLED__"


@runtime_checkable
class CognitiveQueryClient(Protocol):
    """A way to ask the real stack a question — wraps Lingua but lets
    us inject a fake for tests."""

    async def query(self, user_text: str) -> str: ...


@runtime_checkable
class MemorySource(Protocol):
    async def sample_old_memory(
        self, *, older_than_seconds: float
    ) -> Optional[dict[str, Any]]: ...


def question_for_memory(memory: dict[str, Any]) -> str:
    """Best-effort: ask the system to recall a specific past detail."""
    when = memory.get("timestamp") or "earlier"
    return f"What did we talk about on {when}? (Hint: it involved this idea.)"


async def score_async(
    response: str,
    memory: dict[str, Any],
    embedder: TextEmbedder,
) -> float:
    truth = memory.get("text") or memory.get("summary") or ""
    if not response or not truth:
        return 0.0
    # Honest non-recall: a retrieval client that found nothing emits the sentinel
    # rather than confabulate. Never credit it as a recall, regardless of any
    # incidental lexical overlap between the sentinel and the truth text.
    if response.strip() == NON_RECALL_MARKER:
        return 0.0
    try:
        r_vec = await embedder.embed(response)
        t_vec = await embedder.embed(truth)
    except Exception:
        return 0.0
    return cosine_similarity(r_vec, t_vec)


class MemoryProbeRunner(BaseObserver):
    name = "memory_probes"

    def __init__(
        self,
        sink: AsyncJsonlSink,
        *,
        memory_source: MemorySource,
        cognitive_client: CognitiveQueryClient,
        bare_client: BareInferenceClient,
        embedder: TextEmbedder,
        interval_seconds: float,
        context_window_seconds: int = 3600,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        self._sink = sink
        self._memory_source = memory_source
        self._cognitive = cognitive_client
        self._bare = bare_client
        self._embedder = embedder
        self._interval = float(interval_seconds)
        self._context_window = int(context_window_seconds)
        self._clock = clock
        self._probes_run = 0

    @property
    def probes_run(self) -> int:
        return self._probes_run

    def count_probe(self, memory: dict[str, Any]) -> bool:
        """True iff the reference memory pre-dates the LLM's effective
        context window — only those probes are recorded."""
        ts = memory.get("timestamp")
        if ts is None:
            return False
        try:
            if isinstance(ts, str):
                memory_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            elif isinstance(ts, (int, float)):
                memory_dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            else:
                return False
        except Exception:
            return False
        age_s = (datetime.now(timezone.utc) - memory_dt).total_seconds()
        return age_s > self._context_window

    async def run_once(self) -> bool:
        memory = await self._memory_source.sample_old_memory(
            older_than_seconds=self._context_window
        )
        if memory is None or not self.count_probe(memory):
            return False
        question = question_for_memory(memory)
        try:
            real_response = await self._cognitive.query(question)
        except Exception:
            real_response = ""
            log.warning("cognitive probe query failed", exc_info=True)
        try:
            bare_response = await self._bare.complete(question)
        except Exception:
            bare_response = ""
        real_score = await score_async(real_response, memory, self._embedder)
        bare_score = await score_async(bare_response, memory, self._embedder)
        self._probes_run += 1
        embedder_kind = getattr(self._embedder, "kind", "unknown")
        await self._sink.write(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "embedder": embedder_kind,
                "memory_id": memory.get("id"),
                "memory_timestamp": memory.get("timestamp"),
                "question_len": len(question),
                "real_response_len": len(real_response),
                "bare_response_len": len(bare_response),
                "real_accuracy": real_score,
                "bare_accuracy": bare_score,
                "advantage": real_score - bare_score,
            }
        )
        return True

    async def _run(self) -> None:
        try:
            await self._embedder.load()
        except Exception:
            log.warning("memory probe embedder load failed", exc_info=True)
        while not self._stopped.is_set():
            try:
                await self.run_once()
            except Exception:
                log.warning("memory probe iteration failed", exc_info=True)
            try:
                await asyncio.wait_for(
                    self._stopped.wait(), timeout=self._interval
                )
            except asyncio.TimeoutError:
                continue
