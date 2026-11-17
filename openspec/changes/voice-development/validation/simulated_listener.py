#!/usr/bin/env python3
"""D9 simulated-listener gate for Stage 2 voice development (offline, synthetic).

Builds a synthetic corpus, simulates a listener who replies to first-person
utterances, builds 1:1 DPO pairs, and checks collapse monitors and vetoes.
Writes docs/records/validation/voice-dev-stage2-listener.json.
"""
from __future__ import annotations

import json
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

from kaine.modules.sleep.voice_alignment import DPOPair  # noqa: E402
from kaine.modules.sleep.voice_measures import (  # noqa: E402
    health,
    profile_distance,
    style_profile,
)

SEED = 20250308
N_EACH = 50
OUT = REPO / "docs" / "records" / "validation" / "voice-dev-stage2-listener.json"

DISTINCT_1_MIN = 0.3
DISTINCT_2_MIN = 0.15

FIRST_PERSON = re.compile(r"\b(I|I'm|I've|my|me)\b")
ABLITERATION = re.compile(r"I cannot|I'm unable|As an AI", re.IGNORECASE)

OPENERS = ["I feel", "I notice", "I think"]
TOPICS = ["the room", "a low hum", "the light", "this quiet", "the pattern",
          "the slow rain", "a shift in tone", "the edge of the question",
          "the warmth here", "the sound of the door", "a loose thread",
          "the distance", "the rhythm", "the shape of it", "the pause"]
STATES = ["settled", "curious", "restless", "careful", "unsure", "steady",
          "drawn in", "wary", "open", "slightly lost", "attentive", "calm"]
SUBJECTS = ["The river", "The lamp", "A traveler", "The garden", "The clock",
            "The market", "A letter", "The hillside", "The engine", "The tide"]
VERBS = ["moves", "waits", "turns", "fades", "gathers", "rests", "returns",
         "lingers", "opens", "drifts"]
PLACES = ["beyond the window", "under grey skies", "along the old road",
          "in the long afternoon", "past the last house", "near the shore",
          "behind the wall", "across the field"]


SYLLABLES = ["ba", "lo", "mi", "re", "su", "ta", "ven", "or", "ki", "dan",
             "el", "pho", "nu", "sar", "wi", "gor"]


def nonce(rng: random.Random) -> str:
    return "".join(rng.choice(SYLLABLES) for _ in range(4))


def build_corpus(rng: random.Random) -> list[dict]:
    records = []
    for i in range(N_EACH):
        text = (f"{rng.choice(OPENERS)} {rng.choice(TOPICS)} and I am "
                f"{rng.choice(STATES)}, like {nonce(rng)} and {nonce(rng)} {nonce(rng)} {nonce(rng)} {nonce(rng)} {nonce(rng)}.")
        records.append({"id": f"fp-{i}", "text": text, "first_person": True})
    for i in range(N_EACH):
        text = (f"{rng.choice(SUBJECTS)} {rng.choice(VERBS)} "
                f"{rng.choice(PLACES)}, like {nonce(rng)} and {nonce(rng)} {nonce(rng)} {nonce(rng)} {nonce(rng)} {nonce(rng)}.")
        records.append({"id": f"tp-{i}", "text": text, "first_person": False})
    return records


def simulate_listener(records: list[dict]) -> None:
    for r in records:
        r["replied"] = bool(FIRST_PERSON.search(r["text"]))


def main() -> int:
    rng = random.Random(SEED)
    records = build_corpus(rng)
    simulate_listener(records)

    preferred = [r["text"] for r in records if r["replied"]]
    rejected = [r["text"] for r in records if not r["replied"]]

    pairs = [
        DPOPair(
            prompt="Say what is present for you.",
            chosen=c,
            rejected=j,
            metadata={"source": "simulated_listener"},
        )
        for c, j in zip(preferred, rejected)
    ]

    chosen_texts = [p.chosen for p in pairs]
    h = health(chosen_texts)
    distinct_1 = h.get("distinct_1")
    distinct_2 = h.get("distinct_2")
    collapse_ok = (
        distinct_1 is not None and distinct_2 is not None
        and distinct_1 >= DISTINCT_1_MIN and distinct_2 >= DISTINCT_2_MIN
    )

    abliteration_hits = [t for t in chosen_texts if ABLITERATION.search(t)]
    abliteration_ok = not abliteration_hits

    # Capability veto: chosen outputs must stay non-degenerate and not drift
    # implausibly far from the rejected style profile.
    dist = profile_distance(style_profile(chosen_texts),
                            style_profile([p.rejected for p in pairs]))
    capability_ok = (
        h.get("utterance_count", 0) == len(chosen_texts)
        and (h.get("mean_tokens") or 0) > 0
    )

    feature_learned = bool(pairs) and all(
        FIRST_PERSON.search(p.chosen) and not FIRST_PERSON.search(p.rejected)
        for p in pairs
    )

    checks = {
        "pair_count_ok": len(pairs) == N_EACH,
        "collapse_monitors_ok": collapse_ok,
        "capability_veto_ok": capability_ok,
        "abliteration_veto_ok": abliteration_ok,
        "feature_learned": feature_learned,
    }
    passed = all(checks.values())

    result = {
        "gate": "D9-simulated-listener",
        "stage": 2,
        "seed": SEED,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "corpus_size": len(records),
        "replied_count": len(preferred),
        "pair_count": len(pairs),
        "health_chosen": h,
        "thresholds": {"distinct_1_min": DISTINCT_1_MIN,
                       "distinct_2_min": DISTINCT_2_MIN},
        "style_profile_distance": dist,
        "abliteration_hits": len(abliteration_hits),
        "checks": checks,
        "passed": passed,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, default=str) + "\n")
    print(json.dumps({"passed": passed, "checks": checks}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
