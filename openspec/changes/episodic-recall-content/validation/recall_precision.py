# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Entity-free recall-precision check on a synthetic film broadcast sequence
(task 7.2 of episodic-recall-content).

Drives the episodic memory module through 12 synthetic film items (8 ticks
each, 96 total) using the real MiniLM text embedder on CPU.  For each recall,
checks whether the top recalled trace came from the same film position
(``item_order``) as the cue.  Reports the share of position-matching recalls
(precision) overall and per item.

This is a measurement, not a pass/fail gate: the verdict is always RECORDED.
Writes results to ``docs/records/validation/episodic-recall-precision-check/``.
"""

from __future__ import annotations

import asyncio
import json
import random
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Repo-root on sys.path so bare ``python -I`` works.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import os  # noqa: E402

os.environ.setdefault("HF_HUB_OFFLINE", "1")

import fakeredis.aioredis  # noqa: E402

from kaine.bus import Event  # noqa: E402
from kaine.bus.client import AsyncBus  # noqa: E402
from kaine.bus.config import BusConfig  # noqa: E402
from kaine.cycle.types import WorkspaceSnapshot  # noqa: E402
from kaine.modules.episodic_memory import (  # noqa: E402
    EpisodicMemory,
    EpisodicMemoryCore,
    InMemoryStorage,
    SentenceTransformerEmbedder,
)
from kaine.modules.episodic_memory.storage import RecalledMemory  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

N_ITEMS = 12
TICKS_PER_ITEM = 8
TOTAL_TICKS = N_ITEMS * TICKS_PER_ITEM
SEED = 42
RECALL_EXCLUDE_RECENT_S = 5.0
SHORT_TERM_CAPACITY = 128
NOISE_STD = 0.05


# ---------------------------------------------------------------------------
# Instrumented module: captures recall results
# ---------------------------------------------------------------------------


class _InstrumentedEpisodicMemory(EpisodicMemory):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.last_recall_results: list[RecalledMemory] = []

    async def recall(
        self,
        query_text: str,
        *,
        k: int | None = None,
        collection: str = "episodic",
        exclude_recent_s: float = 0.0,
    ) -> list[RecalledMemory]:
        results = await super().recall(
            query_text,
            k=k,
            collection=collection,
            exclude_recent_s=exclude_recent_s,
        )
        self.last_recall_results = list(results)
        return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


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
# Build events for one tick
# ---------------------------------------------------------------------------


def _build_events(
    tick: int,
    item: int,
    rng: random.Random,
    vision_bases: list[tuple[float, float]],
    audition_bases: list[tuple[float, float]],
) -> list[tuple[str, Event]]:
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=tick)

    v_change = _clamp(vision_bases[item][0] + rng.gauss(0.0, NOISE_STD))
    v_norm = _clamp(vision_bases[item][1] + rng.gauss(0.0, NOISE_STD))
    v_habit = _clamp(1.0 - v_change)
    v_pred = v_norm * 1.2

    a_change = _clamp(audition_bases[item][0] + rng.gauss(0.0, NOISE_STD))
    a_norm = _clamp(audition_bases[item][1] + rng.gauss(0.0, NOISE_STD))
    a_pred = a_norm * 1.2

    return [
        (
            f"vision-{tick}",
            Event(
                source="vision",
                type="vision.report",
                payload={
                    "change_score": round(v_change, 4),
                    "habituation_score": round(v_habit, 4),
                    "normalised_error": round(v_norm, 4),
                    "prediction_error": round(v_pred, 4),
                    "item_order": item,
                    "encoder_model_id": "dinov2-vits14-reg",
                },
                salience=0.5,
                timestamp=ts,
            ),
        ),
        (
            f"audition-{tick}",
            Event(
                source="audition",
                type="audition.perception",
                payload={
                    "change_score": round(a_change, 4),
                    "normalised_error": round(a_norm, 4),
                    "prediction_error": round(a_pred, 4),
                    "item_order": item,
                    "encoder_model_id": "whisper-medium.en",
                },
                salience=0.5,
                timestamp=ts,
            ),
        ),
        (
            f"affect-{tick}",
            Event(
                source="affect",
                type="affect.state",
                payload={
                    "state": {"valence": 0.0, "arousal": 0.3, "dominance": 0.0},
                    "drives": {},
                    "emotion": "calm",
                },
                salience=0.5,
                timestamp=ts,
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def _main() -> None:
    print("=== Episodic recall precision check (task 7.2) ===\n")

    rng = random.Random(SEED)

    vision_bases = [
        (rng.uniform(0.1, 0.9), rng.uniform(0.1, 0.9)) for _ in range(N_ITEMS)
    ]
    audition_bases = [
        (rng.uniform(0.1, 0.9), rng.uniform(0.1, 0.9)) for _ in range(N_ITEMS)
    ]

    # --- infrastructure ---
    print("Loading MiniLM embedder ...")
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)

    emb = SentenceTransformerEmbedder()
    await emb.load()

    storage = InMemoryStorage(latent_dim=emb.latent_dim)
    core = EpisodicMemoryCore(
        embedder=emb, storage=storage, short_term_capacity=SHORT_TERM_CAPACITY
    )
    em = _InstrumentedEpisodicMemory(
        bus,
        core=core,
        recall_content=True,
        recall_cooldown_s=0.0,
        recall_exclude_recent_s=RECALL_EXCLUDE_RECENT_S,
    )
    await em.initialize()

    print(f"Running {TOTAL_TICKS} ticks ({N_ITEMS} items x {TICKS_PER_ITEM} ticks) ...")

    # --- tracking ---
    per_item: list[dict[str, Any]] = [
        {"item_order": i, "recalls": 0, "matches": 0, "precision": 0.0}
        for i in range(N_ITEMS)
    ]
    total_recalls = 0
    position_matches = 0

    try:
        for tick in range(TOTAL_TICKS):
            item = tick // TICKS_PER_ITEM

            em._cached_affect = {
                "intensity": 0.3,
                "valence": 0.0,
                "dominance": 0.0,
            }

            events = _build_events(tick, item, rng, vision_bases, audition_bases)
            snapshot = WorkspaceSnapshot(
                tick_index=tick,
                selected_events=events,
                inhibited=False,
            )

            em.last_recall_results = []
            await em.on_workspace(snapshot)
            await em.core.consolidate_now()

            results = em.last_recall_results
            if results:
                total_recalls += 1
                top = results[0]
                recalled_tick = top.payload.get("tick_index")
                if recalled_tick is not None:
                    recalled_item = recalled_tick // TICKS_PER_ITEM
                    match = recalled_item == item
                else:
                    match = False
                if match:
                    position_matches += 1
                per_item[item]["recalls"] += 1
                if match:
                    per_item[item]["matches"] += 1

            if tick % 24 == 23:
                print(f"  tick {tick + 1}/{TOTAL_TICKS} done")

    finally:
        await em.shutdown()
        await bus.close()

    # --- compute precision ---
    for p in per_item:
        r = p["recalls"]
        m = p["matches"]
        p["precision"] = round(m / r, 4) if r > 0 else 0.0

    overall_precision = (
        round(position_matches / total_recalls, 4) if total_recalls > 0 else 0.0
    )

    # --- write results ---
    result = {
        "test": "episodic-recall-precision-check",
        "task": "7.2",
        "git_commit": _git_commit(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "parameters": {
            "n_items": N_ITEMS,
            "ticks_per_item": TICKS_PER_ITEM,
            "total_ticks": TOTAL_TICKS,
            "recall_exclude_recent_s": RECALL_EXCLUDE_RECENT_S,
            "embedder": "sentence-transformers/all-MiniLM-L6-v2",
            "seed": SEED,
        },
        "results": {
            "total_recalls": total_recalls,
            "position_matches": position_matches,
            "overall_precision": overall_precision,
            "per_item": per_item,
        },
        "verdict": "RECORDED",
    }

    out_dir = (
        _REPO_ROOT / "docs" / "records" / "validation"
        / "episodic-recall-precision-check"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    # --- summary ---
    print(f"\n--- Results ---")
    print(f"  Total recalls: {total_recalls}")
    print(f"  Position matches: {position_matches}")
    print(f"  Overall precision: {overall_precision}")
    print()
    for p in per_item:
        print(
            f"  item {p['item_order']:2d}: "
            f"recalls={p['recalls']:3d}  matches={p['matches']:3d}  "
            f"precision={p['precision']:.4f}"
        )
    print(f"\nResults written to {out_path}")


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
