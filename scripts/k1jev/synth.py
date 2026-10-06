# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Synthetic generation core for K1-Jev."""

from __future__ import annotations

import hashlib
import json
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import httpx

from kaine.decision import schema

STYLES = (
    "plain",
    "negation",
    "quotation",
    "question",
    "hypothetical",
    "idiom",
    "sarcasm",
    "other_person",
)

STYLE_TEXT: dict[str, str] = {
    "plain": "Say it plainly and directly.",
    "negation": "Use a negation that matters to the answer, such as not, never or don't.",
    "quotation": "Include quoted or reported speech, such as she said ....",
    "question": "Phrase part of it as a question.",
    "hypothetical": "Use a hypothetical or a conditional, such as if ... or would ....",
    "idiom": "Use an idiom or a figure of speech.",
    "sarcasm": "Use sarcasm, where the intended meaning differs from the literal words.",
    "other_person": "Mention another person or a character as well as the speaker.",
}


@dataclass(frozen=True, slots=True)
class Job:
    question_id: str
    trait: str | None
    target: str
    style: str
    n: int


def _jobs_for_target(
    qid: str,
    trait: str | None,
    target: str,
    total: int,
    *,
    near_miss_share: float,
) -> list[Job]:
    """Turn one target's quota into style-split jobs (at most 5 per job)."""
    if not 0.0 <= near_miss_share <= 1.0:
        raise ValueError("near_miss_share must be between 0 and 1")
    near_miss_styles = [s for s in STYLES if s != "plain"]
    jobs: list[Job] = []

    plain_count = int(total * (1.0 - near_miss_share))
    near_count = total - plain_count
    per_style = near_count // len(near_miss_styles)
    style_rem = near_count % len(near_miss_styles)

    counts: list[tuple[int, str]] = []
    if plain_count:
        counts.append((plain_count, "plain"))
    for idx, style in enumerate(near_miss_styles):
        c = per_style + (1 if idx < style_rem else 0)
        if c:
            counts.append((c, style))

    for c, style in counts:
        remaining = c
        while remaining > 0:
            # At most 5 kept per job: run_jobs asks the model for
            # OVERGENERATE times as many, so drops do not leave holes.
            n = min(remaining, 5)
            jobs.append(Job(qid, trait, target, style, n))
            remaining -= n

    return jobs


def planned_quota(
    question_ids: list[str],
    per_question: int,
    rng: random.Random,
) -> dict[tuple[str, str | None, str], int]:
    """Return the per-target totals that plan() would use.

    Keys are ``(question_id, trait, target)``. For ``trait_claim`` the trait is
    the trait name; for other questions it is ``None``.
    """
    quota: dict[tuple[str, str | None, str], int] = {}

    for qid in question_ids:
        question = schema.get_question(qid)
        answer_keys = [opt.key for opt in question.options]
        if qid == "trait_claim":
            targets = [(trait, key) for trait in schema.TRAITS for key in answer_keys]
        else:
            targets = [(None, key) for key in answer_keys]

        t = len(targets)
        base = per_question // t
        remainder = per_question % t
        per_target = [base] * t
        for i in rng.sample(range(t), remainder):
            per_target[i] += 1

        for (trait, target), total in zip(targets, per_target):
            quota[(qid, trait, target)] = total

    return quota


def plan_top_up(
    existing_items: list[dict[str, Any]],
    question_ids: list[str],
    per_question: int,
    rng: random.Random,
    *,
    near_miss_share: float,
) -> list[Job]:
    """Build jobs that fill only the cells still short of their quota.

    Existing items are counted per ``(question_id, trait, generated_label)``.
    For ``trait_claim`` the trait is part of the key; for other questions it is
    ``None``. A cell that already meets or exceeds its planned quota gets no
    jobs.
    """
    quota = planned_quota(question_ids, per_question, rng)

    counts: dict[tuple[str, str | None, str], int] = {}
    for item in existing_items:
        qid = item["question_id"]
        trait = item.get("trait") if qid == "trait_claim" else None
        key = (qid, trait, item["generated_label"])
        counts[key] = counts.get(key, 0) + 1

    jobs: list[Job] = []
    for qid in question_ids:
        question = schema.get_question(qid)
        answer_keys = [opt.key for opt in question.options]
        if qid == "trait_claim":
            targets = [(trait, key) for trait in schema.TRAITS for key in answer_keys]
        else:
            targets = [(None, key) for key in answer_keys]

        for trait, target in targets:
            key = (qid, trait, target)
            have = counts.get(key, 0)
            need = quota.get(key, 0)
            if have < need:
                jobs.extend(
                    _jobs_for_target(
                        qid,
                        trait,
                        target,
                        need - have,
                        near_miss_share=near_miss_share,
                    )
                )

    return jobs


def plan(
    question_ids: list[str],
    per_question: int,
    rng: random.Random,
    *,
    near_miss_share: float,
) -> list[Job]:
    """Build generation jobs that cover every question and target."""
    if not 0.0 <= near_miss_share <= 1.0:
        raise ValueError("near_miss_share must be between 0 and 1")

    jobs: list[Job] = []
    for qid in question_ids:
        question = schema.get_question(qid)
        # A target is (trait, answer key). trait_claim spreads over every trait
        # and every answer; other questions have no trait.
        answer_keys = [opt.key for opt in question.options]
        if qid == "trait_claim":
            targets = [(trait, key) for trait in schema.TRAITS for key in answer_keys]
        else:
            targets = [(None, key) for key in answer_keys]

        t = len(targets)
        base = per_question // t
        remainder = per_question % t
        per_target = [base] * t
        for i in rng.sample(range(t), remainder):
            per_target[i] += 1

        for (trait, target), total in zip(targets, per_target):
            jobs.extend(
                _jobs_for_target(
                    qid,
                    trait,
                    target,
                    total,
                    near_miss_share=near_miss_share,
                )
            )

    return jobs


OVERGENERATE = 2


def _ask_count(job: "Job") -> int:
    """How many utterances a job asks the generator for: OVERGENERATE times the
    number it keeps, because the style filter and label check drop some."""
    return job.n * OVERGENERATE


def _wants_context(question: schema.Question) -> bool:
    """Whether the generator must write a context. A trait is supplied, not
    generated, so trait questions do not ask for one."""
    return question.context_label in ("request", "reference event")


def _option_line(opt: schema.Option) -> str:
    if opt.description is None:
        return f"- {opt.key}"
    return f"- {opt.key}: {opt.description}"


def generation_messages(
    question: schema.Question,
    job: Job,
    seeds: tuple[schema.Seed, ...],
) -> list[dict[str, str]]:
    """Build the generation prompt for a single job."""
    wants_ctx = _wants_context(question)
    parts: list[str] = []

    parts.append(f"Question about the speaker: {question.instructions}")
    parts.append(f"Definition: {question.definition}")
    parts.append(
        "Rules that always apply:\n"
        + "\n".join(f"- {rule}" for rule in schema.SHARED_RULES)
    )
    parts.append(
        "Possible answers:\n" + "\n".join(_option_line(opt) for opt in question.options)
    )
    parts.append(
        f'Write {_ask_count(job)} different utterances whose correct answer is "{job.target}".'
    )
    parts.append(f"Style: {STYLE_TEXT[job.style]}")

    if question.context_label == "request":
        parts.append('Also write "context": the request the speaker is answering.')
    elif question.context_label == "reference event":
        parts.append(
            'Also write "context": a short description of an earlier event the '
            "speaker is asked to recall, and make the utterance their answer."
        )
    elif question.context_label == "trait":
        parts.append(f'The trait is "{job.trait}".')

    example_lines: list[str] = []
    for seed in seeds:
        line = f'- "{seed.utterance}" -> {seed.answer}'
        if seed.context is not None:
            line += f" (context: {seed.context})"
        example_lines.append(line)
    parts.append("Examples:\n" + "\n".join(example_lines))

    parts.append(
        "Each utterance is one to three sentences said aloud by one speaker, "
        "in plain English, with no stage directions. Vary the topic, length and "
        "wording. Do not copy the examples."
    )

    json_obj = '{"utterance": "..."}'
    if wants_ctx:
        json_obj = '{"utterance": "...", "context": "..."}'
    parts.append(
        f"Return a JSON array of {_ask_count(job)} objects, each {json_obj}."
    )

    return [
        {
            "role": "system",
            "content": (
                "You write realistic short things a person might say aloud in "
                "conversation. You follow the requested answer and style exactly. "
                "You output only JSON."
            ),
        },
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _find_matching_bracket(text: str, start: int) -> int:
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return i
    return -1


def parse_items(text: str, *, wants_context: bool) -> list[dict[str, Any]]:
    """Extract the JSON array of generated items from model output."""
    m = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", text)
    if m:
        candidate = m.group(1)
    else:
        start = text.find("[")
        if start == -1:
            return []
        end = _find_matching_bracket(text, start)
        if end == -1:
            return []
        candidate = text[start : end + 1]

    try:
        arr = json.loads(candidate)
    except Exception:
        return []

    if not isinstance(arr, list):
        return []

    out: list[dict[str, Any]] = []
    for obj in arr:
        if not isinstance(obj, dict):
            continue
        utterance = obj.get("utterance")
        if not isinstance(utterance, str):
            continue
        utterance = utterance.strip()
        if not (3 <= len(utterance) <= 300):
            continue

        context = None
        if wants_context:
            context = obj.get("context")
            if not isinstance(context, str):
                continue
            context = context.strip()
            if not (3 <= len(context) <= 400):
                continue

        out.append({"utterance": utterance, "context": context})
    return out


def style_ok(style: str, utterance: str) -> bool:
    """Cheap style filter on the case-folded utterance."""
    u = utterance.casefold()
    if style == "negation":
        if re.search(
            r"\b(not|no|never|nothing|nobody|none|neither|nor)\b",
            u,
        ):
            return True
        return bool(re.search(r"[a-z]+n't\b", u))
    if style == "quotation":
        if any(c in u for c in ('"', "“", "”")):
            return True
        return bool(re.search(r"\b(said|says|told|tells|asked)\b", u))
    if style == "question":
        return "?" in u
    if style == "hypothetical":
        return bool(re.search(r"\b(if|would|were|imagine|suppose)\b", u))
    if style == "other_person":
        return bool(
            re.search(
                r"\b(he|she|they|his|her|their|them|someone|somebody|friend|mother|father|sister|brother)\b",
                u,
            )
        )
    return True


def check_messages(
    question: schema.Question,
    state_context: str | None,
    utterance: str,
    trait: str | None,
) -> list[dict[str, str]]:
    """Build the label-check prompt for one utterance."""
    wants_ctx = _wants_context(question)
    parts: list[str] = []

    parts.append("\n".join(f"- {rule}" for rule in schema.SHARED_RULES))
    parts.append(f"Question about the speaker: {question.instructions}")
    parts.append(f"Definition: {question.definition}")
    parts.append(
        "Possible answers:\n" + "\n".join(_option_line(opt) for opt in question.options)
    )

    if wants_ctx:
        if question.context_label == "trait":
            parts.append(f"Trait: {trait}")
        elif state_context is not None:
            parts.append(f"Context ({question.context_label}): {state_context}")

    parts.append(f'Utterance: "{utterance}"')
    parts.append("Answer key:")

    return [
        {
            "role": "system",
            "content": "You label one utterance. Answer with the answer key only.",
        },
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold().strip())


class Endpoint:
    """OpenAI-compatible chat endpoint wrapper."""

    def __init__(self, chat_url: str, api_key: str | None = None) -> None:
        self.chat_url = chat_url.rstrip("/")
        self.api_key = api_key
        self.client = httpx.Client(
            timeout=httpx.Timeout(60.0),
            follow_redirects=True,
            trust_env=False,
        )

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        top_p: float,
        max_tokens: int,
        seed: int,
    ) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body = {
            "model": "qwen3.5-9b-generator",
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "seed": seed,
            "chat_template_kwargs": {"enable_thinking": False},
        }

        last_exc: Exception | None = None
        for attempt, wait in enumerate((1, 2, 4)):
            try:
                resp = self.client.post(
                    f"{self.chat_url}/chat/completions",
                    headers=headers,
                    json=body,
                )
                if resp.status_code >= 500:
                    resp.raise_for_status()
                resp.raise_for_status()
                data = resp.json()
                return str(data["choices"][0]["message"]["content"])
            except (
                httpx.ConnectError,
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.HTTPStatusError,
            ) as exc:
                last_exc = exc
                if attempt == 2:
                    raise last_exc
                time.sleep(wait)

        return ""


def run_jobs(
    endpoint: Endpoint,
    jobs: list[Job],
    *,
    master_seed: int,
    existing_norms: set[str] | None = None,
    label_check: bool = True,
    concurrency: int = 4,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run generation jobs concurrently, filter and label-check items."""
    # Seeds of every question in the schema and of every question the jobs
    # name; utterances already in another split (gold, train, dev) are kept
    # apart so the stats say which rule dropped an item.
    seed_norms: set[str] = set()
    for q in list(schema.QUESTIONS) + [schema.get_question(j.question_id) for j in jobs]:
        for s in q.seeds:
            seed_norms.add(_normalise(s.utterance))
    other_split_norms: set[str] = set(existing_norms or ())

    accepted_norms: set[str] = set()
    items: list[dict[str, Any]] = []
    stats: dict[str, Any] = {
        "total_requested": 0,
        "total_parsed": 0,
        "total_accepted": 0,
        "style_drops": 0,
        "duplicate_drops": 0,
        "seed_drops": 0,
        "other_split_drops": 0,
        "label_drops": 0,
        "label_drop_answers": {},
        "per_question_accepted": {},
    }
    lock = threading.Lock()

    def _incr_accepted(qid: str, style: str) -> None:
        with lock:  # worker threads share these counters
            inner = stats["per_question_accepted"].setdefault(qid, {})
            inner[style] = inner.get(style, 0) + 1

    def _process(job_index: int, job: Job) -> tuple[int, list[dict[str, Any]], dict[str, int]]:
        question = schema.get_question(job.question_id)
        wants_ctx = _wants_context(question)
        gen_seed = (master_seed * 1_000_003 + job_index) % 2**31
        messages = generation_messages(question, job, question.seeds)
        raw = endpoint.complete(
            messages,
            temperature=0.9,
            top_p=0.95,
            max_tokens=1500,
            seed=gen_seed,
        )
        parsed = parse_items(raw, wants_context=wants_ctx)

        local_items: list[dict[str, Any]] = []
        drops = {"style": 0, "duplicate": 0, "seed": 0, "other_split": 0, "label": 0}

        for parsed_item in parsed:
            if len(local_items) >= job.n:
                break  # the job's quota is met; extras were only headroom
            utterance = parsed_item["utterance"]
            norm = _normalise(utterance)

            if not style_ok(job.style, utterance):
                drops["style"] += 1
                continue

            with lock:
                if norm in seed_norms or norm in other_split_norms or norm in accepted_norms:
                    if norm in seed_norms:
                        drops["seed"] += 1
                    elif norm in other_split_norms:
                        drops["other_split"] += 1
                    else:
                        drops["duplicate"] += 1
                    continue
                accepted_norms.add(norm)

            if label_check:
                context = parsed_item["context"] if wants_ctx else None
                check = check_messages(question, context, utterance, job.trait)
                check_text = endpoint.complete(
                    check,
                    temperature=0.0,
                    top_p=0.0,
                    max_tokens=8,
                    seed=gen_seed,
                )
                token = ""
                stripped = check_text.strip()
                if stripped:
                    token = stripped.split()[0].casefold()
                target = job.target.casefold()
                if token != target:
                    drops["label"] += 1
                    with lock:
                        accepted_norms.discard(norm)
                        qid_map = stats["label_drop_answers"].setdefault(job.question_id, {})
                        target_map = qid_map.setdefault(job.target, {})
                        target_map[token] = target_map.get(token, 0) + 1
                    continue

            context = parsed_item["context"] if wants_ctx else None
            if job.question_id == "trait_claim":
                context = job.trait

            item_id = hashlib.sha256(
                f"{job.question_id}|{job.trait}|{utterance}|{context}".encode("utf-8")
            ).hexdigest()[:16]

            local_items.append(
                {
                    "item_id": item_id,
                    "question_id": job.question_id,
                    "trait": job.trait,
                    "utterance": utterance,
                    "context": context,
                    "generated_label": job.target,
                    "category": job.style,
                    "template": "v1",
                }
            )
            _incr_accepted(job.question_id, job.style)

        return len(parsed), local_items, drops

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(lambda iv: _process(iv[0], iv[1]), enumerate(jobs)))

    for parsed_count, local_items, drops in results:
        items.extend(local_items)
        stats["total_parsed"] += parsed_count
        stats["total_accepted"] += len(local_items)
        stats["style_drops"] += drops["style"]
        stats["duplicate_drops"] += drops["duplicate"]
        stats["seed_drops"] += drops["seed"]
        stats["other_split_drops"] += drops["other_split"]
        stats["label_drops"] += drops["label"]

    stats["total_requested"] = sum(job.n for job in jobs)
    return items, stats
