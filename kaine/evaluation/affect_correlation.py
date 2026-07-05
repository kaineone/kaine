# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Affect-output correlation logger + offline batch correlator.

Logs paired (Thymos state, Lingua output characteristics) for every
external speech event. The batch correlator runs during Hypnos sleep
(or on-demand via the Nexus tab) and produces a correlation matrix
across the Thymos dimensions and output features.
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kaine.bus.schema import Event
from kaine.evaluation._base import BusReader, StreamSubscriberObserver
from kaine.evaluation.proactive_audit import LINGUA_EXTERNAL_STREAM
from kaine.evaluation.sink import AsyncJsonlSink

log = logging.getLogger(__name__)


HEDGE_WORDS = frozenset(
    {
        "perhaps",
        "maybe",
        "might",
        "possibly",
        "probably",
        "i think",
        "i suppose",
        "i guess",
        "kind of",
        "sort of",
        "somewhat",
        "seems",
        "appears",
        "likely",
    }
)


def output_characteristics(text: str, *, latency_ms: float | None = None) -> dict[str, Any]:
    """Pure-function feature extraction. Used by the observer at log
    time AND by the batch correlator at analysis time."""
    text = text or ""
    tokens = re.findall(r"\b\w+\b", text.lower())
    length_chars = len(text)
    length_tokens = len(tokens)
    distinct_tokens = len(set(tokens))
    lexical_diversity = (
        distinct_tokens / length_tokens if length_tokens > 0 else 0.0
    )
    lowered = text.lower()
    hedge_count = sum(1 for w in HEDGE_WORDS if w in lowered)
    return {
        "length_chars": length_chars,
        "length_tokens": length_tokens,
        "distinct_tokens": distinct_tokens,
        "lexical_diversity": lexical_diversity,
        "hedge_word_count": hedge_count,
        "latency_ms": latency_ms,
    }


def pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0.0 or dy == 0.0:
        return 0.0
    return num / (dx * dy)


class AffectCorrelationRecorder(StreamSubscriberObserver):
    name = "affect_correlation"
    stream = LINGUA_EXTERNAL_STREAM

    def __init__(
        self,
        bus: BusReader,
        sink: AsyncJsonlSink,
        *,
        thymos_state_provider=None,
    ) -> None:
        super().__init__(bus, poll_interval_s=0.5)
        self._sink = sink
        self._thymos = thymos_state_provider

    async def handle(self, entry_id: str, event: Event) -> None:
        if event.type != "external_speech":
            return
        payload = event.payload or {}
        text = str(payload.get("text") or "")
        latency_ms = payload.get("latency_ms")
        chars = output_characteristics(text, latency_ms=latency_ms)
        thymos_state = None
        if self._thymos is not None:
            try:
                thymos_state = self._thymos()
            except Exception:
                thymos_state = None
        await self._sink.write(
            {
                "entry_id": entry_id,
                "ts": datetime.now(timezone.utc).isoformat(),
                "thymos_state": thymos_state,
                "characteristics": chars,
            }
        )


def correlate_from_log(log_path: Path) -> dict[str, dict[str, float]]:
    """Read every line in `log_path`, compute pearson correlations
    between each Thymos dimension and each output characteristic.
    Returns dict[thymos_key][char_key] = pearson value.
    """
    if not log_path.exists():
        return {}
    paired: list[tuple[dict[str, float], dict[str, float]]] = []
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            thymos = entry.get("thymos_state") or {}
            chars = entry.get("characteristics") or {}
            if not isinstance(thymos, dict) or not chars:
                continue
            paired.append((
                {k: float(v) for k, v in thymos.items() if isinstance(v, (int, float))},
                {k: float(v) for k, v in chars.items() if isinstance(v, (int, float))},
            ))
    if not paired:
        return {}
    thymos_keys = sorted({k for t, _ in paired for k in t})
    char_keys = sorted({k for _, c in paired for k in c})
    matrix: dict[str, dict[str, float]] = {}
    for tk in thymos_keys:
        matrix[tk] = {}
        xs = [t.get(tk, 0.0) for t, _ in paired]
        for ck in char_keys:
            ys = [c.get(ck, 0.0) for _, c in paired]
            matrix[tk][ck] = pearson(xs, ys)
    return matrix
