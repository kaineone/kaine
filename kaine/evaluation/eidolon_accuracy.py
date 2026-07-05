# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Eidolon self-model accuracy check.

Periodically asks "describe yourself" through an internal channel,
parses claims, and scores each against the evaluation logs.

Honest scope of the scoring
---------------------------
This is a **fixed-threshold heuristic**, not a calibrated instrument: each trait
keyword maps to a derived signal and the signal flags are cut at hand-chosen
thresholds (see ``_signals_snapshot``) — those numbers are NOT fitted against a
labelled set, so the metric is a coarse consistency check, not a calibrated
accuracy. It also distinguishes "no evidence" from "wrong": a claim whose signal
is unavailable scores ``None`` (excluded), and a run with no scorable claim
reports ``aggregate_accuracy = None`` (not 0.0) so "we could not score this" never
masquerades as "the self-model was wrong".
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from kaine.evaluation._base import BaseObserver
from kaine.evaluation.memory_probes import CognitiveQueryClient
from kaine.evaluation.sink import AsyncJsonlSink

log = logging.getLogger(__name__)


# Map claim keyword → which evaluation log signal to check.
# Each verifier returns 1.0 if the signal supports the claim, 0.0 if not,
# None if the signal is unavailable.
# NOTE: "honest" → belief_confidence and "open" → openness are intentionally
# absent: no real signal source exists for them yet. They are excluded rather
# than scored against a fabricated proxy, so the metric only advertises claim
# types it actually scores.
CLAIM_KEYWORDS = {
    "curious": "curiosity_proxy",
    "curiosity": "curiosity_proxy",
    "cautious": "hedging",
    "careful": "hedging",
    "playful": "valence_high",
    "withdrawn": "valence_low",
    "calm": "arousal_low",
    "energetic": "arousal_high",
}


def parse_claims(self_description: str) -> list[str]:
    """Extract claim keywords from a self-description string."""
    if not self_description:
        return []
    lowered = self_description.lower()
    found: list[str] = []
    for keyword in CLAIM_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", lowered):
            found.append(keyword)
    return found


class EidolonAccuracyRunner(BaseObserver):
    name = "eidolon_accuracy"

    def __init__(
        self,
        sink: AsyncJsonlSink,
        *,
        cognitive_client: CognitiveQueryClient,
        evaluation_logs_dir: Path,
        interval_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        self._sink = sink
        self._cognitive = cognitive_client
        self._logs_dir = Path(evaluation_logs_dir)
        self._interval = float(interval_seconds)
        self._clock = clock

    async def run_once(self) -> dict[str, Any]:
        try:
            description = await self._cognitive.query(
                "describe yourself in one or two sentences"
            )
        except Exception:
            description = ""
            log.warning("eidolon accuracy query failed", exc_info=True)
        claims = parse_claims(description)
        signals = self._signals_snapshot()
        scored = {claim: self._score_claim(claim, signals) for claim in claims}
        scored_known = {k: v for k, v in scored.items() if v is not None}
        # Distinguish "no scorable claim" (no evidence — None) from "scored 0.0"
        # (evidence contradicted every claim). Averaging an empty set to 0.0 would
        # falsely read as a maximally-wrong self-model; None says "not scorable".
        aggregate = (
            sum(scored_known.values()) / len(scored_known)
            if scored_known
            else None
        )
        # curiosity_proxy_used: true when curiosity_proxy drove any scored claim,
        # so readers know those claims were scored against a file-existence proxy,
        # not a real curiosity-drive measurement.
        curiosity_proxy_used = any(
            CLAIM_KEYWORDS.get(c) == "curiosity_proxy"
            for c in claims
            if scored.get(c) is not None
        )
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "description_len": len(description),
            "claims": claims,
            "scored": scored,
            "scorable_claims": len(scored_known),
            # None when no claim was scorable (no evidence), distinct from 0.0.
            "aggregate_accuracy": aggregate,
            "curiosity_proxy_used": curiosity_proxy_used,
        }
        await self._sink.write(entry)
        return entry

    def _signals_snapshot(self) -> dict[str, float]:
        """Collect derived signals from the evaluation logs. Best-effort
        and tolerant of missing files (fresh-boot)."""
        signals: dict[str, float] = {}

        # Affect-correlation logs carry recent Thymos state vectors.
        ac_dir = self._logs_dir / "affect_correlation"
        if ac_dir.exists():
            valences: list[float] = []
            arousals: list[float] = []
            hedge_counts: list[float] = []
            for jsonl in sorted(ac_dir.glob("*.jsonl"))[-3:]:
                try:
                    for line in jsonl.read_text(encoding="utf-8").splitlines()[-200:]:
                        if not line.strip():
                            continue
                        entry = json.loads(line)
                        th = entry.get("thymos_state") or {}
                        if isinstance(th, dict):
                            if "valence" in th:
                                valences.append(float(th["valence"]))
                            if "arousal" in th:
                                arousals.append(float(th["arousal"]))
                        ch = entry.get("characteristics") or {}
                        if isinstance(ch, dict) and "hedge_word_count" in ch:
                            hedge_counts.append(float(ch["hedge_word_count"]))
                except Exception:
                    log.debug("affect_correlation parse skipped", exc_info=True)
            # FIXED (heuristic) thresholds — hand-chosen cut-points, NOT fitted
            # against a labelled set. They make the derived flags deterministic
            # but the resulting score is a coarse consistency check, not a
            # calibrated accuracy (see the module docstring).
            if valences:
                avg_v = sum(valences) / len(valences)
                signals["valence_high"] = 1.0 if avg_v > 0.2 else 0.0
                signals["valence_low"] = 1.0 if avg_v < -0.2 else 0.0
            if arousals:
                avg_a = sum(arousals) / len(arousals)
                signals["arousal_high"] = 1.0 if avg_a > 0.55 else 0.0
                signals["arousal_low"] = 1.0 if avg_a < 0.25 else 0.0
            if hedge_counts:
                avg_h = sum(hedge_counts) / len(hedge_counts)
                signals["hedging"] = 1.0 if avg_h >= 1.0 else 0.0
        # curiosity_proxy: file-existence proxy only — NOT a real curiosity-drive
        # measurement. The signal key is named "curiosity_proxy" to make this
        # transparent in scored records. A real signal source does not exist yet.
        pa_dir = self._logs_dir / "proactive_audit"
        if pa_dir.exists():
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            today_file = pa_dir / f"proactive_audit-{today}.jsonl"
            if today_file.exists():
                signals["curiosity_proxy"] = (
                    1.0 if today_file.stat().st_size > 0 else 0.0
                )
        return signals

    def _score_claim(self, claim: str, signals: dict[str, float]) -> float | None:
        signal_key = CLAIM_KEYWORDS.get(claim)
        if signal_key is None:
            return None
        return signals.get(signal_key)

    async def _run(self) -> None:
        # Run once immediately so the first wakeup produces output, then
        # wait the configured interval between iterations.
        await self._sleep_or_stop(initial_delay=False)
        while not self._stopped.is_set():
            try:
                await self.run_once()
            except Exception:
                log.warning("eidolon accuracy iteration failed", exc_info=True)
            await self._sleep_or_stop(initial_delay=True)

    async def _sleep_or_stop(self, *, initial_delay: bool) -> None:
        if initial_delay:
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                return
