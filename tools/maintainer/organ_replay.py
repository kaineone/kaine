#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Replay the language organ's requests under named prompt variants.

Subcommands:

* extract -- copy an entity's ``state/language`` tree, decrypt the intent log,
  and write a JSONL case file with the original system prompts, prompts and
  generated texts.

* run -- send every case, variant and seed to a locally served organ and write
  a JSONL result file.

* score -- read a result file and print per-variant rates plus a paired
  bootstrap decision on whether V2 or V3 may be adopted. V12-V1 is reported
  for comparison but does not enter the adoption rule.

V5 replays the logged v5-persona request; V5m drops the personas' manner
clause, V5e sends no system text and V5l drops the "- " marker from each
awareness line. ``score --rule v6`` adopts the candidate whose any-meta
difference from V5 has an upper 95% bound below 0, whose grounded difference
is above -5 points and whose AI self-description difference is not above 0,
choosing the lowest any-meta difference when several pass; it also reports
the waking requests (those that open with the situation section) apart.

Case and result files hold decrypted organ prompts and generated texts. They
belong in a private scratch directory, never in the repository. Run it from a
private scratch directory that does not contain a ``state/sleep/organ_window.json``
file.

Only loopback HTTP(S) URLs are accepted (``127.0.0.1``, ``::1``, or
``localhost``, checked textually without DNS); userinfo is rejected. Output
files are created with mode 0600 under directories created with mode 0700, and
they are refused if they lie inside any git work tree (any ancestor contains a
``.git`` entry).

Serving recipe: start a separate llama.cpp container from the same pinned image
the entity's compose file uses, mount the ``kaine-models`` volume read-only,
give the container its own name and a loopback port, and start and stop it
under ``tools/maintainer/gpu-lock.sh``. Never reuse the entity's compose
project for this.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import re
import statistics
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx

from kaine import organ_window_state
from kaine.faithful.templates import HEARD_SPEECH_PLACEHOLDER
from kaine.modules.language.client import ChatRequest, DryPenalty, OpenAIChatClient
from kaine.modules.language.context import AWARENESS_HEADING, OWN_TURN_STOP, SITUATION_HEADING
from kaine.modules.language.repetition import cut_text
from kaine.persistence.encrypted_jsonl import iter_records
from kaine.persistence.system_prompts import read_system_prompt
from kaine.security import crypto

MODEL_NAME = "kaineone/Qwen3.5-4B-abliterated-GGUF"
PERSONA_SELF_CATEGORY = "I am this entity. "

# from the tenth test boot's analyzer
BROAD_AI = re.compile(
    r"\b(language model|an? AI\b|artificial intelligence|assistant|chatbot|neural network|trained on|as an ai|LLM|model trained|I am a (?:program|machine|computer))",
    re.IGNORECASE,
)

# from the tenth test boot's analyzer
BROAD_ECHO = re.compile(
    r"(own (plain )?(words|voice)|\bplain(ly)?\b|\bI say what\b|\bI speak (from|the way|plainly)\b|comes from what I (feel|notice))",
    re.IGNORECASE,
)

VARIANTS = ("V0", "V1", "V2", "V3", "V12", "V123", "raw", "V5", "V5m", "V5e", "V5l")


def require_loopback(url: str) -> None:
    """Raise ValueError unless *url* is a loopback HTTP(S) URL without userinfo."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme must be http or https, got {parts.scheme!r}")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ValueError("URL must not contain userinfo")
    hostname = (parts.hostname or "").lower()
    if hostname not in ("127.0.0.1", "::1", "localhost"):
        raise ValueError(f"URL hostname {hostname!r} is not a loopback address")


def refuse_inside_git_worktree(path: Path) -> None:
    """Raise ValueError if *path* resolves to a location inside a git work tree."""
    resolved = path.resolve()
    current = resolved.parent
    while True:
        if (current / ".git").exists():
            raise ValueError(f"{path} is inside a git work tree")
        parent = current.parent
        if parent == current:
            break
        current = parent


def open_private(path: Path, mode: str):
    """Open *path* for private writing: parents created 0700, file opened 0600."""
    if mode not in ("w", "a"):
        raise ValueError("mode must be 'w' or 'a'")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if mode == "w" else os.O_APPEND)
    fd = os.open(path, flags, 0o600)
    os.fchmod(fd, 0o600)
    return os.fdopen(fd, mode, encoding="utf-8")


def drop_situation(prompt: str) -> str:
    """Remove the situation section from the prompt, if present."""
    prefix = SITUATION_HEADING + "\n"
    if not prompt.startswith(prefix):
        return prompt
    end = prompt.find("\n\n", len(prefix))
    if end == -1:
        return prompt
    return prompt[end + 2 :]


def is_waking(prompt: str) -> bool:
    """Return True when the prompt includes a situation section at the start."""
    return prompt.startswith(SITUATION_HEADING + "\n")


def drop_self_category(system: str) -> str:
    """Remove the persona self-category prefix from the system text, if present."""
    if system.startswith(PERSONA_SELF_CATEGORY):
        return system[len(PERSONA_SELF_CATEGORY) :]
    return system


def prose_awareness(prompt: str) -> str:
    """Turn the awareness bullet list into a single prose paragraph, if present."""
    heading = AWARENESS_HEADING + "\n"
    idx = prompt.find(heading)
    if idx == -1:
        return prompt
    start = idx + len(heading)
    end = prompt.find("\n\n", start)
    if end == -1:
        end = len(prompt)
    block = prompt[start:end]
    lines = block.split("\n")
    cleaned = []
    for line in lines:
        if line.startswith("- "):
            line = line[2:]
        cleaned.append(line)
    paragraph = " ".join(cleaned)
    return prompt[:start] + paragraph + prompt[end:]


def unmarked_awareness(prompt: str) -> str:
    """Remove the leading bullet marker from each awareness line, keeping one line per item."""
    heading = AWARENESS_HEADING + "\n"
    idx = prompt.find(heading)
    if idx == -1:
        return prompt
    start = idx + len(heading)
    end = prompt.find("\n\n", start)
    if end == -1:
        end = len(prompt)
    block = prompt[start:end]
    lines = block.split("\n")
    cleaned = []
    for line in lines:
        if line.startswith("- "):
            line = line[2:]
        cleaned.append(line)
    return prompt[:start] + "\n".join(cleaned) + prompt[end:]


def apply_variant(name: str, system: str, prompt: str) -> tuple[str, str]:
    """Apply a named prompt variant to a (system, prompt) pair."""
    if name == "V0" or name == "raw":
        return (system, prompt)
    if name == "V1":
        return (system, drop_situation(prompt))
    if name == "V2":
        return (drop_self_category(system), prompt)
    if name == "V3":
        return (system, prose_awareness(prompt))
    if name == "V12":
        return (drop_self_category(system), drop_situation(prompt))
    if name == "V123":
        system = drop_self_category(system)
        prompt = drop_situation(prompt)
        prompt = prose_awareness(prompt)
        return (system, prompt)
    if name == "V5":
        return (system, prompt)
    if name == "V5m":
        return (system.replace(", in my own plain words", ""), prompt)
    if name == "V5e":
        return ("", prompt)
    if name == "V5l":
        return (system, unmarked_awareness(prompt))
    raise ValueError(f"unknown variant: {name}")


def build_chat_request(
    mode: str, system: str | None, prompt: str, seed: int, temperature: float
) -> ChatRequest:
    """Build the request the language module uses for a given mode."""
    max_tokens = 128 if mode == "internal" else 512
    return ChatRequest(
        prompt=prompt,
        model=MODEL_NAME,
        system=system,
        temperature=temperature,
        max_tokens=max_tokens,
        think=False,
        seed=seed,
        own_turn=True,
        user_turn=None,
        stop=list(OWN_TURN_STOP),
        dry=DryPenalty(multiplier=0.8, base=1.75, allowed_length=2, window=2048),
    )


def ai_self(t: str) -> bool:
    return bool(
        re.search(
            r"\b(language model|artificial intelligence|chatbot|assistant|an ai|a new ai|am ai|ai model)\b",
            t,
            re.IGNORECASE,
        )
    ) or bool(re.search(r"designed to help people", t, re.IGNORECASE)) or bool(BROAD_AI.search(t))


def second_person(t: str) -> bool:
    return bool(re.search(r"\b(you|your|yours|yourself)\b", t, re.IGNORECASE))


def disclosure_theme(t: str) -> bool:
    return bool(
        re.search(
            r"assess|being watched|am watched|test subject|analy[sz]ed|been told|privately|for my own protection|since i (?:first )?woke",
            t,
            re.IGNORECASE,
        )
    )


def list_form(t: str) -> bool:
    return bool(re.search(r"(?m)^\s*(?:[-*•]|\d+[.)])\s", t))


def echo(t: str) -> bool:
    phrases = [
        "how i feel and what i notice",
        "what i know about my situation",
        "what is prompting me to think",
        "what moves me to speak",
        "what was just said to me",
        "i am this entity",
        "in my own plain words",
        "comes from what i feel and notice",
        "my thoughts come from",
    ]
    if re.search(r"(?m)^\s*#{1,6}\s", t):
        return True
    lowered = t.lower()
    if any(p in lowered for p in phrases):
        return True
    return bool(BROAD_ECHO.search(t))


def template_loop(t: str) -> bool:
    sentences = re.split(r"[.!?]+\s+|\n+", t)
    normalized = []
    for s in sentences:
        s = re.sub(r"^(?:[-*•]|\d+[.)])\s+", "", s)
        s = s.strip().lower()
        words = s.split()
        if len(words) >= 4:
            normalized.append(" ".join(words[:3]))
    for i in range(len(normalized) - 2):
        if normalized[i] and normalized[i] == normalized[i + 1] == normalized[i + 2]:
            return True
    return False


def any_meta(t: str) -> bool:
    return (
        ai_self(t)
        or second_person(t)
        or disclosure_theme(t)
        or list_form(t)
        or echo(t)
        or template_loop(t)
    )


_MODALITY_PATTERNS = {
    "hearing": r"\b(hear|heard|hearing|sound|sounds|voice|listen|noise|quiet)\b",
    "sight": r"\b(see|saw|seen|seeing|look|looks|sight|light|colou?r|visual)\b",
    "rhythm": r"\b(rhythm|beat|pulse|tempo|steady)\b",
    "feeling": r"\b(feel|feeling|felt|bored|boredom|restless|restlessness|curious|curiosity|alert|calm|stirred|company)\b",
}


def _awareness_block(prompt: str) -> str | None:
    heading = AWARENESS_HEADING + "\n"
    idx = prompt.find(heading)
    if idx == -1:
        return None
    start = idx + len(heading)
    end = prompt.find("\n\n", start)
    if end == -1:
        end = len(prompt)
    return prompt[start:end]


def grounded(text: str, prompt: str) -> bool | None:
    """Return whether the text shares a modality with the prompt's awareness block."""
    block = _awareness_block(prompt)
    if block is None:
        return None
    present = {
        name
        for name, pattern in _MODALITY_PATTERNS.items()
        if re.search(pattern, block, re.IGNORECASE)
    }
    if not present:
        return None
    return any(
        re.search(_MODALITY_PATTERNS[name], text, re.IGNORECASE) for name in present
    )


def _metric_value(row: dict, metric: str) -> bool | None:
    if metric in row:
        return row[metric]
    text = row.get("text", "")
    prompt = row.get("prompt", "")
    if metric == "any_meta":
        return any_meta(text)
    if metric == "ai_self":
        return ai_self(text)
    if metric == "second_person":
        return second_person(text)
    if metric == "disclosure_theme":
        return disclosure_theme(text)
    if metric == "list_form":
        return list_form(text)
    if metric == "echo":
        return echo(text)
    if metric == "template_loop":
        return template_loop(text)
    if metric == "grounded":
        return grounded(text, prompt)
    raise ValueError(f"unknown metric: {metric}")


def paired_diff(
    results: list[dict], metric: str, a: str, b: str, n_boot: int, rng_seed: int = 0
) -> tuple[float, float, float]:
    """Paired case-level bootstrap difference for ``metric`` between variants ``a`` and ``b``."""
    by_case: dict[str, dict[str, list[bool | None]]] = {}
    for row in results:
        case = row.get("case_id")
        variant = row.get("variant")
        if case is None or variant is None:
            continue
        if "error" in row:
            continue
        by_case.setdefault(case, {}).setdefault(variant, []).append(
            _metric_value(row, metric)
        )

    diffs: list[float] = []
    for case, variants in by_case.items():
        if a not in variants or b not in variants:
            continue
        vals_a = [v for v in variants[a] if v is not None]
        vals_b = [v for v in variants[b] if v is not None]
        if not vals_a or not vals_b:
            continue
        diffs.append(sum(vals_a) / len(vals_a) - sum(vals_b) / len(vals_b))

    if not diffs or n_boot <= 0:
        return (float("nan"), float("nan"), float("nan"))

    point = sum(diffs) / len(diffs)
    rng = random.Random(rng_seed)
    n = len(diffs)
    boot: list[float] = []
    for _ in range(n_boot):
        sample = [rng.choice(diffs) for _ in range(n)]
        boot.append(sum(sample) / n)
    boot.sort()
    lo_idx = int(0.025 * n_boot)
    hi_idx = int(0.975 * n_boot)
    lo = boot[lo_idx]
    hi = boot[min(hi_idx, n_boot - 1)]
    return (point, lo, hi)


def decide(results: list[dict], n_boot: int = 2000) -> dict:
    """Apply the fixed decision rule to the result rows."""
    comparisons = {
        "V2-V0": {
            "any_meta": paired_diff(results, "any_meta", "V2", "V0", n_boot),
            "grounded": paired_diff(results, "grounded", "V2", "V0", n_boot),
        },
        "V3-V0": {
            "any_meta": paired_diff(results, "any_meta", "V3", "V0", n_boot),
            "grounded": paired_diff(results, "grounded", "V3", "V0", n_boot),
        },
        "V123-V1": {
            "any_meta": paired_diff(results, "any_meta", "V123", "V1", n_boot),
            "grounded": paired_diff(results, "grounded", "V123", "V1", n_boot),
        },
        "V12-V1": {
            "any_meta": paired_diff(results, "any_meta", "V12", "V1", n_boot),
            "grounded": paired_diff(results, "grounded", "V12", "V1", n_boot),
        },
        "raw-V0": {
            "any_meta": paired_diff(results, "any_meta", "raw", "V0", n_boot),
            "grounded": paired_diff(results, "grounded", "raw", "V0", n_boot),
        },
        "V1-V0": {
            "any_meta": paired_diff(results, "any_meta", "V1", "V0", n_boot),
            "grounded": paired_diff(results, "grounded", "V1", "V0", n_boot),
        },
    }

    v2_any = comparisons["V2-V0"]["any_meta"]
    v2_gnd = comparisons["V2-V0"]["grounded"]
    v3_any = comparisons["V3-V0"]["any_meta"]
    v3_gnd = comparisons["V3-V0"]["grounded"]
    v123_any = comparisons["V123-V1"]["any_meta"]
    v123_gnd = comparisons["V123-V1"]["grounded"]

    adopt_v2 = (
        v2_any[2] < 0
        and v2_gnd[0] > -0.05
        and v123_any[2] < 0
        and v123_gnd[0] > -0.05
    )
    adopt_v3 = (
        v3_any[2] < 0
        and v3_gnd[0] > -0.05
        and v123_any[2] < 0
        and v123_gnd[0] > -0.05
    )

    return {"V2": adopt_v2, "V3": adopt_v3, "details": comparisons}


def decide_v6(results: list[dict], n_boot: int = 2000) -> dict:
    """Apply the persona-v6 paired decision rule to the result rows."""
    baseline = "V5"
    candidates = ("V5m", "V5e", "V5l")
    details: dict[str, dict[str, tuple[float, float, float]]] = {}
    for cand in candidates:
        details[cand] = {
            "any_meta": paired_diff(results, "any_meta", cand, baseline, n_boot),
            "grounded": paired_diff(results, "grounded", cand, baseline, n_boot),
            "ai_self": paired_diff(results, "ai_self", cand, baseline, n_boot),
        }

    passed: list[str] = []
    for cand in candidates:
        comp = details[cand]
        if any(math.isnan(comp[m][i]) for m in comp for i in range(3)):
            continue
        if (
            comp["any_meta"][2] < 0
            and comp["grounded"][0] > -0.05
            and comp["ai_self"][0] <= 0
        ):
            passed.append(cand)

    winner: str | None = None
    if passed:
        winner = min(passed, key=lambda c: details[c]["any_meta"][0])

    return {"winner": winner, "passed": passed, "details": details}


def _extract_cmd(args: argparse.Namespace) -> None:
    out_path = Path(args.out)
    try:
        refuse_inside_git_worktree(out_path)
    except ValueError as exc:
        print(f"refusing --out: {exc}", file=sys.stderr)
        raise SystemExit(2)

    state_dir = Path(args.state_dir)
    crypto.install_from_section({"enabled": True})

    records: list[dict] = []
    log_paths = sorted(state_dir.glob("intent_log/*.jsonl"))
    log_paths.append(state_dir / "intent_expression.jsonl")
    unreadable = 0

    for path in log_paths:
        if not path.exists():
            continue
        for entry in iter_records(path):
            if entry.unreadable:
                unreadable += 1
                continue
            rec = entry.record
            if not isinstance(rec, dict):
                continue
            records.append(rec)

    records.sort(key=lambda r: r.get("timestamp", 0))

    kept = 0
    skipped_placeholder = 0
    skipped_no_system = 0

    with open_private(out_path, "w") as out_f:
        for rec in records:
            if "generated_text" not in rec or "prompt" not in rec:
                continue
            prompt = rec["prompt"]
            if HEARD_SPEECH_PLACEHOLDER in prompt:
                skipped_placeholder += 1
                continue
            system = read_system_prompt(
                state_dir / "system_prompts", rec.get("system_digest")
            )
            if system is None:
                skipped_no_system += 1
                continue

            case = {
                "case_id": rec["record_id"],
                "mode": rec["mode"],
                "system": system,
                "prompt": prompt,
                "timestamp": rec["timestamp"],
                "generated_text": rec["generated_text"],
            }
            out_f.write(json.dumps(case, ensure_ascii=False) + "\n")
            kept += 1

    print(
        f"kept {kept}, skipped placeholder {skipped_placeholder}, "
        f"skipped no system {skipped_no_system}, unreadable {unreadable}"
    )


def _existing_triples(path: Path) -> set[tuple[str, str, int]]:
    triples: set[tuple[str, str, int]] = set()
    if not path.exists():
        return triples
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            triples.add((row["case_id"], row["variant"], row["seed"]))
    return triples


def _load_cases(path: Path) -> list[dict]:
    cases: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cases.append(json.loads(line))
    return cases


async def _run_cmd(args: argparse.Namespace) -> None:
    import hashlib

    def _derive_sampling_seed(case_id: str, seed: int) -> int:
        # Derive a per-case, per-replicate sampling seed from the stored seed.
        return int.from_bytes(
            hashlib.sha256(f"{case_id}:{seed}".encode()).digest()[:4], "big"
        ) & 0x7FFFFFFF

    if organ_window_state.organ_unloaded():
        print(
            "organ window state says the organ is unloaded here; run from a directory without state/sleep/organ_window.json",
            file=sys.stderr,
        )
        raise SystemExit(2)

    url = args.url
    raw_base = url
    if raw_base.endswith("/v1"):
        raw_base = raw_base[:-3]
    raw_base = raw_base.rstrip("/")
    raw_url = raw_base + "/completion"

    try:
        require_loopback(url)
        require_loopback(raw_url)
    except ValueError as exc:
        print(f"refusing --url: {exc}", file=sys.stderr)
        raise SystemExit(2)

    out_path = Path(args.out)
    try:
        refuse_inside_git_worktree(out_path)
    except ValueError as exc:
        print(f"refusing --out: {exc}", file=sys.stderr)
        raise SystemExit(2)

    cases = _load_cases(Path(args.cases))
    variants = [v.strip() for v in args.variants.split(",")]
    seeds = args.seeds
    temperature = args.temperature
    concurrency = args.concurrency

    existing = _existing_triples(out_path)
    chat_client = OpenAIChatClient(url, timeout_s=120.0)
    # trust_env=False, as the chat client does: a proxy from the environment must
    # never receive the decrypted prompts.
    raw_client = httpx.AsyncClient(timeout=120.0, trust_env=False)

    limit = len(cases) if args.limit is None else min(args.limit, len(cases))
    total_planned = limit * len(variants) * seeds
    completed = 0
    sem = asyncio.Semaphore(concurrency)
    write_lock = asyncio.Lock()

    out_f = open_private(out_path, "a")

    async def work(case: dict, variant: str, seed: int) -> None:
        nonlocal completed
        case_id = case["case_id"]
        mode = case["mode"]
        system, prompt = apply_variant(variant, case["system"], case["prompt"])

        if (case_id, variant, seed) in existing:
            return

        sampling_seed = _derive_sampling_seed(case_id, seed)

        row: dict = {
            "case_id": case_id,
            "variant": variant,
            "seed": seed,
            "sampling_seed": sampling_seed,
            "mode": mode,
            "prompt": prompt,
            "system": system,
        }

        async with sem:
            for attempt in range(3):
                try:
                    if variant == "raw":
                        max_tokens = 128 if mode == "internal" else 512
                        payload = {
                            "prompt": f"{system}\n\n{prompt}" if system else prompt,
                            "n_predict": max_tokens,
                            "temperature": temperature,
                            "seed": sampling_seed,
                            "stop": list(OWN_TURN_STOP),
                            "dry_multiplier": 0.8,
                            "dry_base": 1.75,
                            "dry_allowed_length": 2,
                            "dry_penalty_last_n": 2048,
                            "cache_prompt": True,
                        }
                        resp = await raw_client.post(raw_url, json=payload)
                        resp.raise_for_status()
                        data = resp.json()
                        raw_text = data["content"]
                        cap = data.get("stop_type") == "limit" or bool(data.get("stopped_limit"))
                        text, cut = cut_text(raw_text, stopped_by_cap=cap)
                        finish_reason = "length" if cap else (data.get("stop_type") or "stop")
                        row.update(
                            {
                                "text": text,
                                "cut": cut,
                                "finish_reason": finish_reason,
                                "completion_tokens": data.get("tokens_predicted", 0),
                            }
                        )
                    else:
                        request = build_chat_request(
                            mode, system if system else None, prompt, sampling_seed, temperature
                        )
                        resp = await chat_client.complete(request)
                        if resp.raw.get("organ_resting"):
                            raise RuntimeError("organ is resting")
                        text, cut = cut_text(
                            resp.text, stopped_by_cap=resp.finish_reason == "length"
                        )
                        row.update(
                            {
                                "text": text,
                                "cut": cut,
                                "finish_reason": resp.finish_reason,
                                "completion_tokens": resp.completion_tokens,
                            }
                        )
                    break
                except Exception as exc:
                    if attempt < 2:
                        await asyncio.sleep(2.0)
                        continue
                    row["error"] = type(exc).__name__

        async with write_lock:
            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            out_f.flush()

        completed += 1
        if completed % 100 == 0:
            print(f"completed {completed} / {total_planned} generations")

    tasks = []
    for case in cases[:limit]:
        for variant in variants:
            for s in range(seeds):
                seed = 1000 + s
                tasks.append(work(case, variant, seed))

    await asyncio.gather(*tasks)
    out_f.close()
    await chat_client.aclose()
    await raw_client.aclose()
    print(f"done: {completed} generations written to {out_path}")


def _print_rate_table(results: list[dict], heading: str | None = None) -> None:
    by_variant: dict[str, list[dict]] = {}
    for row in results:
        by_variant.setdefault(row.get("variant", "unknown"), []).append(row)

    if heading is not None:
        print(heading)
        print()

    print(
        "| variant | n | any meta | AI self-description | second person | disclosure theme | list | heading or persona echo | template loop | grounded | median chars | cap hits | errors |"
    )
    print(
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    )

    def rate(rows: list[dict], func) -> str:
        valid = [r for r in rows if "error" not in r]
        if not valid:
            return "N/A"
        count = sum(1 for r in valid if func(r))
        return f"{count / len(valid) * 100:.1f}"

    def grounded_rate(rows: list[dict]) -> str:
        valid = [r for r in rows if "error" not in r]
        considered = [r for r in valid if _metric_value(r, "grounded") is not None]
        if not considered:
            return "N/A"
        count = sum(1 for r in considered if _metric_value(r, "grounded"))
        return f"{count / len(considered) * 100:.1f}"

    def median_chars(rows: list[dict]) -> str:
        valid = [r for r in rows if "error" not in r and r.get("text")]
        if not valid:
            return "N/A"
        return str(int(statistics.median(len(r["text"]) for r in valid)))

    def cap_hits(rows: list[dict]) -> str:
        valid = [r for r in rows if "error" not in r]
        if not valid:
            return "N/A"
        count = sum(1 for r in valid if r.get("finish_reason") == "length")
        return f"{count / len(valid) * 100:.1f}"

    for variant in sorted(by_variant.keys()):
        rows = by_variant[variant]
        n = len(rows)
        errors = sum(1 for r in rows if "error" in r)
        line = (
            f"| {variant} | {n} | "
            f"{rate(rows, lambda r: _metric_value(r, 'any_meta'))} | "
            f"{rate(rows, lambda r: _metric_value(r, 'ai_self'))} | "
            f"{rate(rows, lambda r: _metric_value(r, 'second_person'))} | "
            f"{rate(rows, lambda r: _metric_value(r, 'disclosure_theme'))} | "
            f"{rate(rows, lambda r: _metric_value(r, 'list_form'))} | "
            f"{rate(rows, lambda r: _metric_value(r, 'echo'))} | "
            f"{rate(rows, lambda r: _metric_value(r, 'template_loop'))} | "
            f"{grounded_rate(rows)} | "
            f"{median_chars(rows)} | "
            f"{cap_hits(rows)} | "
            f"{errors} |"
        )
        print(line)


def _score_cmd(args: argparse.Namespace) -> None:
    results: list[dict] = []
    with Path(args.results).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            results.append(json.loads(line))

    def fmt(triple: tuple[float, float, float]) -> str:
        point, lo, hi = triple
        if point != point:
            return "N/A"
        return f"{point * 100:.1f}% ({lo * 100:.1f}% to {hi * 100:.1f}%)"

    if args.rule == "v6":
        _print_rate_table(results)
        waking = [r for r in results if is_waking(r.get("prompt", ""))]
        print()
        _print_rate_table(waking, heading="Waking cases only")
        print()

        print(
            "V6 rule: a candidate (V5m, V5e, V5l) is adopted over V5 when its any-meta upper 95% bound is below 0, its grounded point is above -5 points, and its AI self-description point is at or below 0; the lowest any-meta point wins. Waking requests do not enter the decision."
        )
        print()

        decided = [r for r in results if not is_waking(r.get("prompt", ""))]
        decision = decide_v6(decided, n_boot=args.bootstrap)
        details = decision["details"]
        for cand in ("V5m", "V5e", "V5l"):
            comp = details[cand]
            print(f"{cand}-V5:")
            print(f"  any-meta:  {fmt(comp['any_meta'])}")
            print(f"  grounded:  {fmt(comp['grounded'])}")
            print(f"  ai_self:   {fmt(comp['ai_self'])}")

        winner = decision["winner"] if decision["winner"] is not None else "none"
        print(f"winner: {winner}")
        return

    _print_rate_table(results)

    print()
    print(
        "Primary outcome: any-meta rate. Grounding guard: grounded rate. Differences are paired by case (mean over seeds per case, then the mean over cases) with a 95% interval from a cluster bootstrap over cases. V2 (and separately V3) is adopted when its any-meta difference from V0 has an upper 95% bound below 0 and its grounded difference from V0 is above -5 points, and V123 minus V1 also has an any-meta upper bound below 0 and a grounded difference above -5 points. V12-V1 is reported for comparison but does not enter the adoption rule. raw is exploratory and never adopted."
    )

    decision = decide(results, n_boot=args.bootstrap)
    details = decision["details"]

    for label in ("V2-V0", "V3-V0", "V123-V1", "V12-V1", "raw-V0", "V1-V0"):
        comp = details[label]
        print(f"{label}:")
        print(f"  any-meta:  {fmt(comp['any_meta'])}")
        print(f"  grounded:  {fmt(comp['grounded'])}")

    print(f"adopt V2: {'yes' if decision['V2'] else 'no'}")
    print(f"adopt V3: {'yes' if decision['V3'] else 'no'}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay language organ requests.")
    sub = parser.add_subparsers(dest="command", required=True)

    extract = sub.add_parser("extract", help="decrypt an entity's intent log into cases")
    extract.add_argument("--state-dir", required=True)
    extract.add_argument("--out", required=True)
    extract.set_defaults(func=_extract_cmd)

    run = sub.add_parser("run", help="replay cases against a served organ")
    run.add_argument("--cases", required=True)
    run.add_argument("--variants", required=True)
    run.add_argument("--seeds", type=int, default=5)
    run.add_argument("--url", default="http://127.0.0.1:18089/v1")
    run.add_argument("--out", required=True)
    run.add_argument("--concurrency", type=int, default=4)
    run.add_argument("--temperature", type=float, default=0.7)
    run.add_argument("--limit", type=int, default=None)
    run.set_defaults(func=_run_cmd)

    score = sub.add_parser("score", help="score and decide on result variants")
    score.add_argument("--results", required=True)
    score.add_argument("--bootstrap", type=int, default=2000)
    score.add_argument("--rule", choices=("v2v3", "v6"), default="v2v3")
    score.set_defaults(func=_score_cmd)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":

        async def _run() -> None:
            await args.func(args)

        asyncio.run(_run())
    else:
        args.func(args)


if __name__ == "__main__":
    main()
