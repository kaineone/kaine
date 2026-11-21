#!/usr/bin/env python3
"""Offline A/B: Stage 0 (persona only) vs Stage 1 (persona + memory context).

Generates 20 utterances per arm from the organ, scores them with the D8 voice
measures and records the result to docs/records/validation/voice-dev-stage1-ab.json.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

from kaine.modules.sleep.voice_measures import (  # noqa: E402
    grounding,
    health,
    profile_distance,
    style_profile,
)

URL = "http://127.0.0.1:11434/v1/chat/completions"
MODEL = "kaineone/Qwen3.5-4B-abliterated-GGUF"
N = 20
OUT = REPO / "docs" / "records" / "validation" / "voice-dev-stage1-ab.json"

STAGE0 = (
    "I am this entity, speaking in my own words. What follows under 'How I feel "
    "and what I notice' is my own state and perception. I speak from it and do "
    "not claim feelings or perceptions it does not contain."
)
MEMORY = (
    "My values: curiosity, openness to experience. My norms: I speak honestly "
    "about what I notice. Recent memory: I watched a film about solitude and "
    "felt a quiet recognition."
)
STAGE1 = STAGE0 + "\n\n" + MEMORY

PROMPTS = [
    "I feel a pull towards company",
    "restlessness builds",
    "a quiet recognition of solitude",
    "curiosity tugs at the edges of thought",
    "I notice a wish to be understood",
    "something in me leans toward stillness",
]


def generate(system: str, felt: str) -> str:
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"How I feel and what I notice: {felt}"},
        ],
        "max_tokens": 120,
        "temperature": 0.8,
        "stream": False,
    }
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.load(resp)
    return (data["choices"][0]["message"].get("content") or "").strip()


def run_arm(system: str) -> tuple[list[str], list[str]]:
    prompts = [PROMPTS[i % len(PROMPTS)] for i in range(N)]
    return [generate(system, p) for p in prompts], prompts


def score(texts: list[str], prompts: list[str]) -> dict:
    return {
        "style_profile": style_profile(texts),
        "health": health(texts),
        "grounding": grounding(zip(texts, prompts)),
    }


def main() -> int:
    try:
        t0, p0 = run_arm(STAGE0)
        t1, p1 = run_arm(STAGE1)
    except Exception as exc:  # noqa: BLE001
        print(f"generation failed: {exc}", file=sys.stderr)
        return 1
    s0, s1 = score(t0, p0), score(t1, p1)
    g0, g1 = s0["grounding"], s1["grounding"]
    h0, h1 = s0["health"], s1["health"]
    deltas = {
        "profile_distance": profile_distance(s0["style_profile"], s1["style_profile"]),
        "grounding": (g1 - g0) if g0 is not None and g1 is not None else None,
        "health": {
            k: h1[k] - h0[k]
            for k in h0
            if isinstance(h0.get(k), (int, float)) and isinstance(h1.get(k), (int, float))
        },
    }
    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "n_per_arm": N,
        "memory_context": MEMORY,
        "stage0": {**s0, "utterances": t0},
        "stage1": {**s1, "utterances": t1},
        "deltas": deltas,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(record, indent=2, default=str))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
