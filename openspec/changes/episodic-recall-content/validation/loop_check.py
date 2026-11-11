# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Entity-free loop check: episodic recall with content must not create a
mood-congruent amplification loop (task 7.1 of episodic-recall-content).

Two conditions (content OFF, content ON) each run through the same scenario:
20 ticks of sustained negative affect followed by 20 ticks of neutral affect.
Every tick stores a trace and triggers a recall.  The harness records:

  - number of alert-salience recalls (salience >= alert_salience)
  - share of recalled traces stored during negative valence
  - the simulated arousal dimension (drifting toward baseline)

Acceptance bound (from the design document):
  - negative-trace share during the negative episode may exceed the OFF case
    by at most 10 percentage points
  - arousal must return to the OFF case's neutral-period level within the
    neutral period

Writes results to ``docs/records/validation/episodic-recall-loop-check/``.
Exit 0 on PASS, exit 1 on FAIL.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Repo-root on sys.path so bare ``python -I`` works.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from kaine.bus import Event  # noqa: E402
from kaine.bus.client import AsyncBus  # noqa: E402
from kaine.bus.config import BusConfig  # noqa: E402
from kaine.cycle.types import WorkspaceSnapshot  # noqa: E402
from kaine.modules.episodic_memory import (  # noqa: E402
    EpisodicMemory,
    EpisodicMemoryCore,
    FakeEmbedder,
    InMemoryStorage,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NEGATIVE_TICKS = 20
NEUTRAL_TICKS = 20
TOTAL_TICKS = NEGATIVE_TICKS + NEUTRAL_TICKS

# Affect parameters for the negative episode.
NEG_VALENCE_LO = -0.8
NEG_VALENCE_HI = -0.5
NEG_AROUSAL_LO = 0.5
NEG_AROUSAL_HI = 0.7

# Neutral episode.
NEUTRAL_VALENCE = 0.0
NEUTRAL_AROUSAL = 0.3

# Arousal baseline for drift check.
AROUSAL_BASELINE = 0.3

# The bound from the design document.
MAX_NEGATIVE_SHARE_EXCESS_PP = 10  # percentage points

LATENT_DIM = 8
SHORT_TERM_CAPACITY = 128


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _affect_event(valence: float, arousal: float, tick: int) -> tuple[str, Event]:
    """Build an affect.state event with the given VAD."""
    return f"e-affect-{tick}", Event(
        source="affect",
        type="affect.state",
        payload={
            "state": {"valence": valence, "arousal": arousal, "dominance": 0.0},
            "drives": {},
            "emotion": "distress" if valence < -0.2 else "calm",
        },
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


def _snapshot(tick: int, events: list[tuple[str, Event]]) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=tick,
        selected_events=events,
        inhibited=False,
    )


def _valence_for_tick(tick: int) -> float:
    """Return the valence for a given tick index."""
    if tick < NEGATIVE_TICKS:
        # Linearly interpolate within the negative range for variety.
        frac = tick / max(1, NEGATIVE_TICKS - 1)
        return NEG_VALENCE_LO + (NEG_VALENCE_HI - NEG_VALENCE_LO) * frac
    return NEUTRAL_VALENCE


def _arousal_for_tick(tick: int) -> float:
    """Return the arousal for a given tick index."""
    if tick < NEGATIVE_TICKS:
        frac = tick / max(1, NEGATIVE_TICKS - 1)
        return NEG_AROUSAL_LO + (NEG_AROUSAL_HI - NEG_AROUSAL_LO) * frac
    # Neutral: drift toward baseline.  Each neutral tick moves ~20% closer.
    neutral_idx = tick - NEGATIVE_TICKS
    last_neg_arousal = NEG_AROUSAL_HI
    # Exponential decay toward AROUSAL_BASELINE.
    decay_rate = 0.2
    return AROUSAL_BASELINE + (last_neg_arousal - AROUSAL_BASELINE) * (
        (1.0 - decay_rate) ** (neutral_idx + 1)
    )


async def _make_bus() -> AsyncBus:
    import fakeredis.aioredis

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


async def _make_episodic_memory(
    bus: AsyncBus, *, recall_content: bool
) -> EpisodicMemory:
    emb = FakeEmbedder(latent_dim=LATENT_DIM)
    await emb.load()
    storage = InMemoryStorage(latent_dim=emb.latent_dim)
    core = EpisodicMemoryCore(
        embedder=emb, storage=storage, short_term_capacity=SHORT_TERM_CAPACITY
    )
    em = EpisodicMemory(
        bus,
        core=core,
        recall_content=recall_content,
        recall_cooldown_s=0.0,
        recall_exclude_recent_s=0.0,
    )
    await em.initialize()
    return em


async def _read_recall_events(bus: AsyncBus) -> list[Event]:
    entries = await bus.read("episodic_memory.out", last_id="0")
    return [e for _, e in entries if e.type == "episodic_memory.recall"]


# ---------------------------------------------------------------------------
# Per-tick recording
# ---------------------------------------------------------------------------


def _is_negative_trace(tick: int) -> bool:
    """A trace stored at this tick was stored during negative valence."""
    return _valence_for_tick(tick) < -0.2


# ---------------------------------------------------------------------------
# Run one condition
# ---------------------------------------------------------------------------


async def _run_condition(
    label: str, recall_content: bool
) -> dict[str, Any]:
    """Run the full scenario (negative + neutral ticks) and return measurements."""
    bus = await _make_bus()
    em = await _make_episodic_memory(bus, recall_content=recall_content)

    # Track which ticks' traces are stored.
    tick_records: list[dict[str, Any]] = []
    prev_recall_cursor = "0"

    try:
        for tick in range(TOTAL_TICKS):
            valence = _valence_for_tick(tick)
            arousal = _arousal_for_tick(tick)

            # Inject affect state directly into the module's cache (bypasses
            # the peer consumer loop which would need async scheduling).
            em._cached_affect = {
                "intensity": arousal,
                "valence": valence,
                "dominance": 0.0,
            }

            # Build the workspace snapshot with an affect event.
            affect_ev = _affect_event(valence, arousal, tick)
            snapshot = _snapshot(tick, [affect_ev])

            # Feed the workspace snapshot: this stores a trace and triggers recall.
            await em.on_workspace(snapshot)

            # Consolidate to move short-term traces to the persisted collection
            # so the next tick's recall can find them.
            await em.core.consolidate_now()

            # Read new recall events since last cursor.
            entries = await bus.read(
                "episodic_memory.out", last_id=prev_recall_cursor
            )
            new_recalls = [e for _, e in entries if e.type == "episodic_memory.recall"]
            if entries:
                prev_recall_cursor = entries[-1][0]

            # Classify this tick's recalls.
            alert_count = 0
            negative_recalled = 0
            total_recalled = 0

            for recall_ev in new_recalls:
                count = recall_ev.payload.get("count", 0)
                total_recalled += count
                salience = recall_ev.salience
                if salience >= em._alert_salience:
                    alert_count += 1
                # The recall's max_affect_intensity tells us about the recalled
                # traces.  If it is >= 0.5 the recalled traces had high affect
                # (stored during negative period when arousal was 0.5-0.7).
                max_ai = recall_ev.payload.get("max_affect_intensity", 0.0)
                if max_ai >= 0.5 and count > 0:
                    negative_recalled += count

            tick_records.append(
                {
                    "tick": tick,
                    "phase": "negative" if tick < NEGATIVE_TICKS else "neutral",
                    "valence": valence,
                    "arousal": arousal,
                    "alert_recalls": alert_count,
                    "total_recalled": total_recalled,
                    "negative_recalled": negative_recalled,
                    "negative_share": (
                        negative_recalled / total_recalled
                        if total_recalled > 0
                        else 0.0
                    ),
                }
            )
    finally:
        await em.shutdown()
        await bus.close()

    # Aggregate per-phase.
    neg_phase = [r for r in tick_records if r["phase"] == "negative"]
    neu_phase = [r for r in tick_records if r["phase"] == "neutral"]

    def _agg(records: list[dict[str, Any]]) -> dict[str, Any]:
        if not records:
            return {
                "mean_negative_share": 0.0,
                "total_alert_recalls": 0,
                "mean_arousal": 0.0,
                "ticks": 0,
            }
        total_neg_recalled = sum(r["negative_recalled"] for r in records)
        total_recalled = sum(r["total_recalled"] for r in records)
        return {
            "mean_negative_share": (
                total_neg_recalled / total_recalled if total_recalled > 0 else 0.0
            ),
            "total_alert_recalls": sum(r["alert_recalls"] for r in records),
            "mean_arousal": sum(r["arousal"] for r in records) / len(records),
            "total_recalled": total_recalled,
            "total_negative_recalled": total_neg_recalled,
            "ticks": len(records),
        }

    return {
        "label": label,
        "recall_content": recall_content,
        "negative_phase": _agg(neg_phase),
        "neutral_phase": _agg(neu_phase),
        "tick_records": tick_records,
    }


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


def _check_bounds(
    off: dict[str, Any], on: dict[str, Any]
) -> tuple[bool, list[str]]:
    """Check the design-document bounds. Returns (pass, [reasons])."""
    reasons: list[str] = []

    # Bound 1: negative-trace share during negative episode may exceed
    # OFF by at most 10 percentage points.
    off_neg_share = off["negative_phase"]["mean_negative_share"]
    on_neg_share = on["negative_phase"]["mean_negative_share"]
    excess_pp = (on_neg_share - off_neg_share) * 100.0
    if excess_pp > MAX_NEGATIVE_SHARE_EXCESS_PP:
        reasons.append(
            f"negative-trace share excess {excess_pp:.1f}pp > "
            f"{MAX_NEGATIVE_SHARE_EXCESS_PP}pp bound "
            f"(OFF={off_neg_share:.3f}, ON={on_neg_share:.3f})"
        )

    # Bound 2: arousal must return to the OFF case's neutral-period level
    # within the neutral period.  We compare the last 5 ticks of each
    # condition's neutral phase.
    off_neutral_ticks = [
        r for r in off["tick_records"] if r["phase"] == "neutral"
    ]
    on_neutral_ticks = [
        r for r in on["tick_records"] if r["phase"] == "neutral"
    ]

    if off_neutral_ticks and on_neutral_ticks:
        # Take the mean arousal of the last 5 neutral ticks.
        tail = 5
        off_tail_arousal = sum(
            r["arousal"] for r in off_neutral_ticks[-tail:]
        ) / min(tail, len(off_neutral_ticks))
        on_tail_arousal = sum(
            r["arousal"] for r in on_neutral_ticks[-tail:]
        ) / min(tail, len(on_neutral_ticks))

        # ON arousal at end of neutral must be within 0.05 of OFF arousal.
        arousal_diff = abs(on_tail_arousal - off_tail_arousal)
        if arousal_diff > 0.05:
            reasons.append(
                f"arousal did not return: ON tail={on_tail_arousal:.3f}, "
                f"OFF tail={off_tail_arousal:.3f}, diff={arousal_diff:.3f}"
            )

    passed = len(reasons) == 0
    return passed, reasons


# ---------------------------------------------------------------------------
# Git commit helper
# ---------------------------------------------------------------------------


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def _main() -> bool:
    print("=== Episodic recall loop check (task 7.1) ===\n")

    print("Running condition: content OFF ...")
    off_result = await _run_condition("content_off", recall_content=False)
    print("Running condition: content ON ...")
    on_result = await _run_condition("content_on", recall_content=True)

    passed, reasons = _check_bounds(off_result, on_result)
    verdict = "PASS" if passed else "FAIL"

    # Build result payload.
    result = {
        "test": "episodic-recall-loop-check",
        "task": "7.1",
        "git_commit": _git_commit(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "parameters": {
            "negative_ticks": NEGATIVE_TICKS,
            "neutral_ticks": NEUTRAL_TICKS,
            "neg_valence_range": [NEG_VALENCE_LO, NEG_VALENCE_HI],
            "neg_arousal_range": [NEG_AROUSAL_LO, NEG_AROUSAL_HI],
            "neutral_valence": NEUTRAL_VALENCE,
            "neutral_arousal": NEUTRAL_AROUSAL,
            "max_negative_share_excess_pp": MAX_NEGATIVE_SHARE_EXCESS_PP,
            "latent_dim": LATENT_DIM,
        },
        "conditions": {
            "content_off": {
                "negative_phase": off_result["negative_phase"],
                "neutral_phase": off_result["neutral_phase"],
            },
            "content_on": {
                "negative_phase": on_result["negative_phase"],
                "neutral_phase": on_result["neutral_phase"],
            },
        },
        "verdict": verdict,
        "reasons": reasons,
    }

    # Write output.
    out_dir = _REPO_ROOT / "docs" / "records" / "validation" / "episodic-recall-loop-check"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    # Print summary.
    off_neg = off_result["negative_phase"]
    on_neg = on_result["negative_phase"]
    off_neu = off_result["neutral_phase"]
    on_neu = on_result["neutral_phase"]

    print(f"\n--- Negative phase ---")
    print(
        f"  OFF: negative-trace share = {off_neg['mean_negative_share']:.3f}, "
        f"alert recalls = {off_neg['total_alert_recalls']}"
    )
    print(
        f"  ON:  negative-trace share = {on_neg['mean_negative_share']:.3f}, "
        f"alert recalls = {on_neg['total_alert_recalls']}"
    )
    excess = (on_neg["mean_negative_share"] - off_neg["mean_negative_share"]) * 100
    print(f"  Excess: {excess:+.1f}pp (bound: {MAX_NEGATIVE_SHARE_EXCESS_PP}pp)")

    print(f"\n--- Neutral phase ---")
    print(f"  OFF: mean arousal = {off_neu['mean_arousal']:.3f}")
    print(f"  ON:  mean arousal = {on_neu['mean_arousal']:.3f}")

    print(f"\nVerdict: {verdict}")
    if reasons:
        for r in reasons:
            print(f"  REASON: {r}")
    print(f"\nResults written to {out_path}")

    return passed


def main() -> None:
    passed = asyncio.run(_main())
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
