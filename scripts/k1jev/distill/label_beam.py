#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Label utterances via beam:cloud through Ollama's /api/generate endpoint.

Sends one prompt per utterance-question pair, using structured JSON output
to force a single-letter classification answer. Runs requests concurrently.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from kaine.decision.schema import (  # noqa: E402
    QUESTIONS,
    SHARED_RULES,
    get_question,
)

LETTERS = "ABCDEFGHIJKLMNOP"


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


def build_prompt(qid: str, utterance: str, context: str | None) -> tuple[str, list[tuple[str, str]]]:
    """Build a classification prompt. Returns (prompt_text, [(letter, key), ...])."""
    q = get_question(qid)
    parts: list[str] = []
    parts.append(f"Question: {q.instructions}")
    if q.definition:
        parts.append(f"Definition: {q.definition}")
    parts.append("")
    parts.append("Rules:")
    for rule in SHARED_RULES:
        parts.append(f"- {rule}")
    parts.append("")
    parts.append(f'The speaker said: "{utterance}"')
    if context is not None and q.context_label is not None:
        label = q.context_label.replace("_", " ").title()
        parts.append(f"{label}: {context}")
    parts.append("")
    parts.append("Options:")
    option_map: list[tuple[str, str]] = []
    for i, opt in enumerate(q.options):
        letter = LETTERS[i]
        desc = f" - {opt.description}" if opt.description else ""
        parts.append(f"  {letter}) {opt.key}{desc}")
        option_map.append((letter, opt.key))
    parts.append("")
    parts.append("Reply with ONLY the letter of the correct option.")
    return "\n".join(parts), option_map


def send_generate(
    base_url: str, model: str, prompt: str, valid_letters: list[str],
    think: str = "budget", retries: int = 3,
) -> str:
    """Send a request to /api/generate and return the chosen letter."""
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string", "enum": valid_letters}},
        "required": ["answer"],
    }
    payload = {
        "model": model,
        "prompt": prompt,
        "format": schema,
        "stream": False,
        "think": think,
        "options": {"num_predict": 256},
    }
    data = json.dumps(payload).encode()
    for attempt in range(retries):
        req = urllib.request.Request(
            base_url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                body = json.loads(resp.read())
                text = body.get("response", "").strip()
                try:
                    return json.loads(text).get("answer", "")
                except json.JSONDecodeError:
                    for ch in text:
                        if ch in valid_letters:
                            return ch
                    return ""
        except Exception as exc:
            if attempt == retries - 1:
                raise
            print(f"  retry {attempt + 1}/{retries}: {exc}", file=sys.stderr)
            time.sleep(2**attempt)
    return ""


def label_one(base_url: str, model: str, think: str, item: dict, qid: str) -> tuple[str, str, dict]:
    """Label one question for one utterance. Returns (item_id, qid, label)."""
    q = get_question(qid)
    prompt, option_map = build_prompt(qid, item["utterance"], item.get("context"))
    valid = [pair[0] for pair in option_map]
    letter = send_generate(base_url, model, prompt, valid, think)
    key_by_letter = dict(option_map)
    answer_key = key_by_letter.get(letter, q.options[0].key)

    label: dict = {"type": q.type, "answer": answer_key}
    if q.type == "noul":
        label["noul"] = 1.0 if answer_key == "true" else 0.0
    elif q.type == "choice":
        label["choice"] = answer_key
    elif q.type == "score":
        label["score"] = float(answer_key)
    return item["id"], qid, label


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", "-i", required=True, help="Input JSONL file")
    ap.add_argument("--output", "-o", required=True, help="Output JSONL file")
    ap.add_argument("--model", "-m", default="beam:cloud")
    ap.add_argument("--base-url", default="http://localhost:11434/api/generate")
    ap.add_argument("--concurrent", type=int, default=5, help="Parallel requests")
    ap.add_argument("--think", default="budget", help="Thinking level (budget|high)")
    args = ap.parse_args()

    with open(args.input) as f:
        items = [json.loads(ln) for ln in f if ln.strip().startswith("{")]

    tasks = []
    for item in items:
        for qid in applicable_questions(item):
            tasks.append((args.base_url, args.model, args.think, item, qid))

    total = len(tasks)
    done = 0
    t0 = time.time()
    results: dict[str, dict[str, dict]] = {}

    with ThreadPoolExecutor(max_workers=args.concurrent) as pool:
        futures = {pool.submit(label_one, *t): t for t in tasks}
        for fut in as_completed(futures):
            item_id, qid, label = fut.result()
            results.setdefault(item_id, {})[qid] = label
            done += 1
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed > 0 else 0
            print(f"\r  [{done}/{total}] {rate:.1f} qs/s", end="", file=sys.stderr)

    with open(args.output, "w") as out:
        for item in items:
            record = {
                "id": item["id"],
                "utterance": item["utterance"],
                "context": item.get("context"),
                "context_label": item.get("context_label"),
                "labels": results.get(item["id"], {}),
                "judge": "beam",
            }
            out.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    elapsed = time.time() - t0
    print(
        f"\nLabeled {len(items)} items ({total} questions) in {elapsed:.1f}s"
        f" with {args.model}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
