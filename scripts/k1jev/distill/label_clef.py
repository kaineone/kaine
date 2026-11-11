#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Label utterances via the clef decision model's /v1/systemone endpoint.

Reads a JSONL file of utterances, groups applicable questions by context
requirement, sends batched requests to the systemone endpoint, and writes
labeled JSONL with per-question probabilities.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from kaine.decision.schema import (  # noqa: E402
    QUESTIONS,
    get_question,
    state_text,
    systemone_questions,
)


def applicable_questions(item: dict) -> list[str]:
    """Return question IDs applicable to this item."""
    if item.get("questions"):
        return item["questions"]
    ctx_label = item.get("context_label")
    return [
        q.id
        for q in QUESTIONS
        if q.context_label is None or q.context_label == ctx_label
    ]


def send_request(
    base_url: str, model: str, state: str, questions: dict, retries: int = 3,
) -> dict:
    """Send a batched request to /v1/systemone and return the answers dict."""
    payload = {"model": model, "state": state, "questions": questions}
    data = json.dumps(payload).encode()
    for attempt in range(retries):
        req = urllib.request.Request(
            base_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer local",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                body = json.loads(resp.read())
                return body.get("answers", {})
        except Exception as exc:
            if attempt == retries - 1:
                raise
            wait = 2**attempt
            print(f"  retry {attempt + 1}/{retries}: {exc}", file=sys.stderr)
            time.sleep(wait)
    return {}


def parse_answer(qid: str, raw: dict) -> dict:
    """Convert a raw systemone answer into the output label format."""
    q = get_question(qid)
    if q.type == "noul":
        noul = raw.get("noul", 0.0)
        return {"type": "noul", "noul": noul, "answer": "true" if noul >= 0.5 else "false"}
    if q.type == "choice":
        probs = raw.get("probabilities", {})
        best = max(probs, key=probs.get) if probs else q.options[0].key
        return {"type": "choice", "choice": best, "probabilities": probs, "answer": best}
    if q.type == "score":
        score = raw.get("score", 0.0)
        return {"type": "score", "score": score, "answer": str(round(score))}
    return raw


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", "-i", required=True, help="Input JSONL file")
    ap.add_argument("--output", "-o", required=True, help="Output JSONL file")
    ap.add_argument("--model", "-m", default="clef", help="Decision model tag")
    ap.add_argument("--base-url", default="http://localhost:11434/v1/systemone")
    ap.add_argument("--batch-size", type=int, default=14, help="Max questions per request")
    args = ap.parse_args()

    with open(args.input) as f:
        items = [json.loads(ln) for ln in f if ln.strip().startswith("{")]

    total = len(items)
    done = 0
    t0 = time.time()

    with open(args.output, "w") as out:
        for item in items:
            q_ids = applicable_questions(item)
            utterance = item["utterance"]
            context = item.get("context")

            # Group questions by context_label so each group shares one state.
            groups: dict[str | None, list[str]] = defaultdict(list)
            for qid in q_ids:
                groups[get_question(qid).context_label].append(qid)

            labels: dict[str, dict] = {}
            for ctx_label, group_qids in groups.items():
                st = state_text(utterance, role=ctx_label, value=context) if ctx_label is not None else state_text(utterance)
                for start in range(0, len(group_qids), args.batch_size):
                    batch = group_qids[start : start + args.batch_size]
                    questions = systemone_questions(batch)
                    answers = send_request(args.base_url, args.model, st, questions)
                    for qid in batch:
                        labels[qid] = parse_answer(qid, answers.get(qid, {}))

            record = {
                "id": item["id"],
                "utterance": utterance,
                "context": context,
                "context_label": item.get("context_label"),
                "labels": labels,
                "judge": "clef",
            }
            out.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            done += 1
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed > 0 else 0
            print(f"\r  [{done}/{total}] {rate:.1f} items/s", end="", file=sys.stderr)

    elapsed = time.time() - t0
    print(f"\nLabeled {done} items in {elapsed:.1f}s with {args.model}", file=sys.stderr)


if __name__ == "__main__":
    main()
