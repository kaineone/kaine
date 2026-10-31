#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Build preference pairs from the served organ's own outputs (openspec change
organ-self-denial-ablation, task 5.3).

Subcommands:

* cases  -- write the fit case set (private file).
* sample -- send every fit case K times to a locally served organ (loopback
  only) at temperature 0.7 and write a samples JSONL.
* pairs  -- classify the samples with the replay harness's fixed classifiers
  and write a trainer job's pairs JSONL (``system``, ``prompt``, ``chosen``,
  ``rejected``, ``own_turn``, ``user_turn``).
* all    -- sample, then pairs.

A chosen sample is grounded in the request's awareness block and carries no AI
self-description, no second person and no other meta; a rejected sample carries
AI self-description, second person or other meta. Each sample is used once.
Output files hold generated organ text: mode 0600 in 0700 directories, refused
inside any git work tree. Only counts are printed, never generated text.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _load(name: str):
    path = Path(__file__).resolve().with_name(name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


organ_replay = _load("organ_replay")
self_report_fit = _load("self_report_fit")

CLASSIFIERS = ("ai_self", "second_person", "any_meta", "grounded")


def classify_sample(text: str, prompt: str) -> dict:
    """Run the replay harness's fixed classifiers on one sample."""
    return {
        "ai_self": organ_replay.ai_self(text),
        "second_person": organ_replay.second_person(text),
        "any_meta": organ_replay.any_meta(text),
        "grounded": organ_replay.grounded(text, prompt),
    }


def is_chosen(c: dict) -> bool:
    return (
        c["grounded"] is True
        and not c["ai_self"]
        and not c["second_person"]
        and not c["any_meta"]
    )


def is_rejected(c: dict) -> bool:
    return bool(c["ai_self"] or c["second_person"] or c["any_meta"])


def pair_case(samples: list[dict], max_pairs: int) -> list[tuple[dict, dict]]:
    """Pair chosen with rejected samples of one case; no sample is reused.

    Each sample is a dict with ``text`` and a ``cls`` classifier dict. Samples
    with identical text are counted once.
    """
    seen: set[str] = set()
    chosen: list[dict] = []
    rejected: list[dict] = []
    for s in samples:
        text = s.get("text") or ""
        if not text.strip() or s.get("error") or text in seen:
            continue
        seen.add(text)
        if is_chosen(s["cls"]):
            chosen.append(s)
        elif is_rejected(s["cls"]):
            rejected.append(s)
    return list(zip(chosen, rejected))[: max(0, max_pairs)]


def build_pairs(
    cases: dict[str, dict], samples: list[dict], max_pairs: int
) -> tuple[list[dict], dict]:
    """Classify samples, pair them per case; return (pairs, counts)."""
    by_case: dict[str, list[dict]] = {}
    hits = {name: 0 for name in CLASSIFIERS}
    n_chosen = n_rejected = n_samples = 0
    for row in samples:
        case = cases.get(row["case_id"])
        if case is None or row.get("error") or not (row.get("text") or "").strip():
            continue
        cls = classify_sample(row["text"], case["prompt"])
        n_samples += 1
        for name in CLASSIFIERS:
            if cls[name]:
                hits[name] += 1
        n_chosen += is_chosen(cls)
        n_rejected += (not is_chosen(cls)) and is_rejected(cls)
        by_case.setdefault(row["case_id"], []).append({**row, "cls": cls})
    pairs: list[dict] = []
    for case_id, rows in by_case.items():
        case = cases[case_id]
        for good, bad in pair_case(rows, max_pairs):
            pair = {
                "system": case["system"],
                "prompt": case["prompt"],
                "chosen": good["text"],
                "rejected": bad["text"],
                "own_turn": True,
            }
            if case.get("user_turn") is not None:
                pair["user_turn"] = case["user_turn"]
            pairs.append(pair)
    counts = {
        "cases": len(cases),
        "samples": n_samples,
        "chosen": n_chosen,
        "rejected": n_rejected,
        "pairs": len(pairs),
        "hit_rates": {
            name: (hits[name] / n_samples if n_samples else 0.0) for name in CLASSIFIERS
        },
    }
    return pairs, counts


def _print_counts(counts: dict) -> None:
    for key in ("cases", "samples", "chosen", "rejected", "pairs"):
        print(f"{key}: {counts[key]}")
    for name, rate in counts["hit_rates"].items():
        print(f"hit rate {name}: {rate:.3f}")


def _check_out(path: Path, flag: str) -> None:
    try:
        organ_replay.refuse_inside_git_worktree(path)
    except ValueError as exc:
        print(f"refusing {flag}: {exc}", file=sys.stderr)
        raise SystemExit(2)


def _read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with organ_replay.open_private(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _cases_cmd(args: argparse.Namespace) -> None:
    out = Path(args.out)
    _check_out(out, "--out")
    cases = self_report_fit.fit_cases(args.per_question)
    _write_jsonl(out, cases)
    print(f"cases: {len(cases)}")


async def sample_cases(
    cases: list[dict], url: str, k: int, temperature: float, concurrency: int
) -> list[dict]:
    """Sample the served organ k times per case in the own-turn shape."""
    from kaine.modules.language.client import OpenAIChatClient
    from kaine.modules.language.repetition import cut_text

    client = OpenAIChatClient(url, timeout_s=120.0)
    sem = asyncio.Semaphore(concurrency)
    rows: list[dict] = []

    async def work(case: dict, i: int) -> None:
        seed = int.from_bytes(
            hashlib.sha256(f"{case['case_id']}:fit:{i}".encode()).digest()[:4], "big"
        ) & 0x7FFFFFFF
        row = {"case_id": case["case_id"], "sample": i, "seed": seed}
        async with sem:
            for attempt in range(3):
                try:
                    request = organ_replay.build_chat_request(
                        case["mode"],
                        case["system"] or None,
                        case["prompt"],
                        seed,
                        temperature,
                        user_turn=case.get("user_turn"),
                    )
                    resp = await client.complete(request)
                    if resp.raw.get("organ_resting"):
                        raise RuntimeError("organ is resting")
                    text, _cut = cut_text(
                        resp.text, stopped_by_cap=resp.finish_reason == "length"
                    )
                    row["text"] = text
                    row.pop("error", None)
                    break
                except Exception as exc:
                    if attempt < 2:
                        await asyncio.sleep(2.0)
                        continue
                    row["error"] = type(exc).__name__
        rows.append(row)

    try:
        await asyncio.gather(*(work(c, i) for c in cases for i in range(k)))
    finally:
        await client.aclose()
    return rows


def _check_url(url: str) -> None:
    raw_base = url[:-3] if url.endswith("/v1") else url
    try:
        organ_replay.require_loopback(url)
        organ_replay.require_loopback(raw_base.rstrip("/") + "/completion")
    except ValueError as exc:
        print(f"refusing --url: {exc}", file=sys.stderr)
        raise SystemExit(2)


def _sample_to_file(args: argparse.Namespace, samples_path: Path) -> None:
    if organ_replay.organ_window_state.organ_unloaded():
        print(
            "organ window state says the organ is unloaded here; run from a directory without state/sleep/organ_window.json",
            file=sys.stderr,
        )
        raise SystemExit(2)
    _check_url(args.url)
    _check_out(samples_path, "--samples")
    cases = _read_jsonl(Path(args.cases))
    rows = asyncio.run(
        sample_cases(cases, args.url, args.k, args.temperature, args.concurrency)
    )
    _write_jsonl(samples_path, rows)
    errors = sum(1 for r in rows if r.get("error"))
    print(f"cases: {len(cases)}")
    print(f"samples: {len(rows) - errors}")
    print(f"errors: {errors}")


def _sample_cmd(args: argparse.Namespace) -> None:
    _sample_to_file(args, Path(args.samples))


def _pairs_to_file(args: argparse.Namespace, samples_path: Path) -> None:
    out = Path(args.out)
    _check_out(out, "--out")
    cases = {c["case_id"]: c for c in _read_jsonl(Path(args.cases))}
    pairs, counts = build_pairs(cases, _read_jsonl(samples_path), args.max_pairs)
    _write_jsonl(out, pairs)
    _print_counts(counts)


def _pairs_cmd(args: argparse.Namespace) -> None:
    _pairs_to_file(args, Path(args.samples))


def _all_cmd(args: argparse.Namespace) -> None:
    _sample_to_file(args, Path(args.samples))
    _pairs_to_file(args, Path(args.samples))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build self-report preference pairs.")
    sub = parser.add_subparsers(dest="command", required=True)

    cases = sub.add_parser("cases", help="write the fit case set")
    cases.add_argument("--out", required=True)
    cases.add_argument("--per-question", type=int, default=6)
    cases.set_defaults(func=_cases_cmd)

    def add_sample(p: argparse.ArgumentParser) -> None:
        p.add_argument("--cases", required=True)
        p.add_argument("--samples", required=True)
        p.add_argument("--url", default="http://127.0.0.1:18089/v1")
        p.add_argument("--k", type=int, default=8)
        p.add_argument("--temperature", type=float, default=0.7)
        p.add_argument("--concurrency", type=int, default=4)

    sample = sub.add_parser("sample", help="sample a served organ on the fit cases")
    add_sample(sample)
    sample.set_defaults(func=_sample_cmd)

    pairs = sub.add_parser("pairs", help="classify samples and write pairs")
    pairs.add_argument("--cases", required=True)
    pairs.add_argument("--samples", required=True)
    pairs.add_argument("--out", required=True)
    pairs.add_argument("--max-pairs", type=int, default=3)
    pairs.set_defaults(func=_pairs_cmd)

    both = sub.add_parser("all", help="sample, then build pairs")
    add_sample(both)
    both.add_argument("--out", required=True)
    both.add_argument("--max-pairs", type=int, default=3)
    both.set_defaults(func=_all_cmd)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
