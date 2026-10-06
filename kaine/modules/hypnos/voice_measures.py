# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Content-free voice measures for the distinctiveness arm (D13).

All computations are pure, use only numpy + stdlib, and are guarded so that bad
input never raises.  No text from the being's corpus is ever stored in the
measure files; only numbers and the fixed ``FUNCTION_WORDS`` identities
(implied by vector position) are persisted.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np

log = logging.getLogger(__name__)

FUNCTION_WORDS: tuple[str, ...] = (
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "if",
    "then",
    "else",
    "when",
    "where",
    "why",
    "how",
    "all",
    "any",
    "both",
    "each",
    "every",
    "few",
    "more",
    "most",
    "other",
    "some",
    "such",
    "no",
    "nor",
    "not",
    "only",
    "own",
    "same",
    "so",
    "than",
    "too",
    "very",
    "just",
    "now",
    "once",
    "again",
    "also",
    "I",
    "me",
    "my",
    "mine",
    "we",
    "our",
    "ours",
    "you",
    "your",
    "yours",
    "he",
    "him",
    "his",
    "she",
    "her",
    "hers",
    "it",
    "its",
    "they",
    "them",
    "their",
    "theirs",
    "what",
    "which",
    "who",
    "whom",
    "whose",
    "this",
    "that",
    "these",
    "those",
    "am",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "can",
    "could",
    "will",
    "would",
    "shall",
    "should",
    "may",
    "might",
    "must",
    "of",
    "in",
    "to",
    "for",
    "with",
    "on",
    "at",
)

_FUNCTION_INDEX = {w: i for i, w in enumerate(FUNCTION_WORDS)}
_WORD_RE = re.compile(r"\b\w+\b", re.UNICODE)
_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+")
_PUNCT_KEYS = (".", ",", "!", "?")


def _safe_list(value: Any) -> list[str]:
    try:
        return list(value) if value is not None else []
    except Exception:
        return []


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def style_profile(texts: list[str]) -> dict[str, Any]:
    """Return a content-free stylometric profile of ``texts``.

    The returned dict contains:

    * ``function_words``: length-100 distribution over ``FUNCTION_WORDS``
      summing to 1, or all zeros when no function word occurs;
    * ``mean_sentence_len``: average number of word tokens per sentence;
    * ``mean_word_len``: average token length;
    * ``type_token_ratio``: unique lower-case tokens / total tokens;
    * ``punct_rate``: per-token counts of ``.``, ``,``, ``!``, ``?``;
    * ``n_tokens``: total word tokens.
    """
    texts = _safe_list(texts)
    function_counts = np.zeros(len(FUNCTION_WORDS), dtype=np.float64)
    sentence_lengths: list[int] = []
    token_lengths_sum = 0
    all_tokens: list[str] = []
    punct_counts = {k: 0 for k in _PUNCT_KEYS}

    for text in texts:
        if not isinstance(text, str):
            continue
        # Per-token punctuation counts.
        for ch in text:
            if ch in punct_counts:
                punct_counts[ch] += 1
        tokens = _tokens(text)
        n = len(tokens)
        if n:
            all_tokens.extend(tokens)
            token_lengths_sum += sum(len(t) for t in tokens)
            for t in tokens:
                idx = _FUNCTION_INDEX.get(t)
                if idx is not None:
                    function_counts[idx] += 1
            # Sentence-level token counts.
            sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
            for sent in sentences:
                sent_toks = _tokens(sent)
                if sent_toks:
                    sentence_lengths.append(len(sent_toks))
            if not sentences:
                # A single block of text with no terminal punctuation counts as
                # one sentence for length purposes.
                sentence_lengths.append(n)

    total_tokens = len(all_tokens)
    function_total = float(function_counts.sum())

    if function_total > 0:
        function_dist = (function_counts / function_total).tolist()
    else:
        function_dist = function_counts.tolist()

    mean_sentence_len = (
        float(sum(sentence_lengths) / len(sentence_lengths)) if sentence_lengths else 0.0
    )
    mean_word_len = (
        float(token_lengths_sum / total_tokens) if total_tokens else 0.0
    )
    type_token_ratio = (
        float(len(set(all_tokens)) / total_tokens) if total_tokens else 0.0
    )

    punct_rate = {
        k: (float(v) / total_tokens if total_tokens else 0.0)
        for k, v in punct_counts.items()
    }

    return {
        "function_words": function_dist,
        "mean_sentence_len": mean_sentence_len,
        "mean_word_len": mean_word_len,
        "type_token_ratio": type_token_ratio,
        "punct_rate": punct_rate,
        "n_tokens": total_tokens,
    }


def _kl2(p: np.ndarray, q: np.ndarray) -> float:
    """KL divergence D(p||q) with base-2 logs, 0 * log 0 := 0."""
    mask = p > 0
    if not np.any(mask):
        return 0.0
    return float(np.sum(p[mask] * np.log2(p[mask] / q[mask])))


def profile_distance(a: dict[str, Any], b: dict[str, Any]) -> float | None:
    """Jensen–Shannon distance + bounded scalar term between two profiles.

    Formula::

        d = 0.5 * sqrt(JS_div_2(p, q))
            + 0.5 * mean_{scalars}( |x - y| / (|x| + |y| + 1e-9) )

    where ``JS_div_2`` is the Jensen–Shannon divergence using base-2 logs, and
    the scalar term averages over ``mean_sentence_len``, ``mean_word_len``,
    ``type_token_ratio`` and the four punctuation rates.

    Returns ``None`` if either function-word distribution is all zeros.
    """
    try:
        p = np.asarray(a.get("function_words", []), dtype=np.float64)
        q = np.asarray(b.get("function_words", []), dtype=np.float64)
    except Exception:
        return None

    if p.size != len(FUNCTION_WORDS) or q.size != len(FUNCTION_WORDS):
        return None
    if float(np.sum(p)) == 0.0 or float(np.sum(q)) == 0.0:
        return None

    p = p / float(np.sum(p))
    q = q / float(np.sum(q))
    m = (p + q) / 2.0
    js_div = 0.5 * (_kl2(p, m) + _kl2(q, m))
    js_div = max(0.0, min(1.0, js_div))
    js_dist = math.sqrt(js_div)

    scalar_diffs: list[float] = []
    scalar_keys = ("mean_sentence_len", "mean_word_len", "type_token_ratio")
    for k in scalar_keys:
        x = float(a.get(k, 0.0) or 0.0)
        y = float(b.get(k, 0.0) or 0.0)
        scalar_diffs.append(abs(x - y) / (abs(x) + abs(y) + 1e-9))

    pa = a.get("punct_rate", {}) or {}
    pb = b.get("punct_rate", {}) or {}
    for k in _PUNCT_KEYS:
        x = float(pa.get(k, 0.0) or 0.0)
        y = float(pb.get(k, 0.0) or 0.0)
        scalar_diffs.append(abs(x - y) / (abs(x) + abs(y) + 1e-9))

    scalar_term = float(np.mean(scalar_diffs)) if scalar_diffs else 0.0
    return 0.5 * js_dist + 0.5 * scalar_term


def merge_profiles(cumulative: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    """Token-weighted merge of two style profiles.

    The returned profile is a new dict; ``function_words``, scalar fields and
    punctuation rates are weighted by ``n_tokens``.  When ``cumulative`` is
    ``None`` or empty, a copy of ``new`` is returned.
    """
    if not cumulative or not isinstance(cumulative, dict):
        return dict(new) if isinstance(new, dict) else new

    n_old = int(cumulative.get("n_tokens", 0) or 0)
    n_new = int(new.get("n_tokens", 0) or 0)
    total = n_old + n_new

    old_arr = np.asarray(
        cumulative.get("function_words", np.zeros(len(FUNCTION_WORDS))),
        dtype=np.float64,
    )
    new_arr = np.asarray(
        new.get("function_words", np.zeros(len(FUNCTION_WORDS))),
        dtype=np.float64,
    )

    out: dict[str, Any] = {}

    if total > 0:
        out["function_words"] = ((old_arr * n_old + new_arr * n_new) / total).tolist()
    else:
        out["function_words"] = old_arr.tolist()

    scalar_keys = ("mean_sentence_len", "mean_word_len", "type_token_ratio")
    for k in scalar_keys:
        old_v = float(cumulative.get(k, 0.0) or 0.0)
        new_v = float(new.get(k, 0.0) or 0.0)
        out[k] = (
            (old_v * n_old + new_v * n_new) / total if total > 0 else old_v
        )

    old_p = cumulative.get("punct_rate", {}) or {}
    new_p = new.get("punct_rate", {}) or {}
    out["punct_rate"] = {}
    for k in _PUNCT_KEYS:
        old_v = float(old_p.get(k, 0.0) or 0.0)
        new_v = float(new_p.get(k, 0.0) or 0.0)
        out["punct_rate"][k] = (
            (old_v * n_old + new_v * n_new) / total if total > 0 else old_v
        )

    out["n_tokens"] = total
    return out


def health(texts: list[str]) -> dict[str, Any]:
    """Return corpus-health diagnostics.

    * ``utterance_count``: number of texts;
    * ``mean_tokens``: average tokens per text;
    * ``distinct_1``: unique unigrams / total unigrams;
    * ``distinct_2``: unique bigrams across the whole corpus / total bigrams.
      A bigram is formed only within one text, never across two utterances;
    * ``max_repeated_trigram_fraction``: the largest, over texts, share of a
      text's trigram occurrences that repeat an earlier trigram of that text
      (0 when nothing repeats; a degeneration signal).
    """
    texts = _safe_list(texts)

    token_counts: list[int] = []
    all_tokens: list[str] = []
    bigrams: set[tuple[str, ...]] = set()
    total_bigrams = 0
    max_trigram_fraction = 0.0

    for text in texts:
        if not isinstance(text, str):
            token_counts.append(0)
            continue
        tokens = _tokens(text)
        n = len(tokens)
        token_counts.append(n)
        all_tokens.extend(tokens)
        for i in range(n - 1):
            bigrams.add((tokens[i], tokens[i + 1]))
        total_bigrams += max(0, n - 1)
        trigram_count = n - 2
        if trigram_count > 0:
            counts: dict[tuple[str, ...], int] = {}
            for i in range(trigram_count):
                tri = (tokens[i], tokens[i + 1], tokens[i + 2])
                counts[tri] = counts.get(tri, 0) + 1
            repeated = trigram_count - len(counts)
            fraction = repeated / trigram_count
            if fraction > max_trigram_fraction:
                max_trigram_fraction = fraction

    total = len(all_tokens)
    return {
        "utterance_count": len(texts),
        "mean_tokens": float(sum(token_counts) / len(token_counts)) if token_counts else 0.0,
        "distinct_1": float(len(set(all_tokens)) / total) if total else 0.0,
        "distinct_2": float(len(bigrams) / total_bigrams) if total_bigrams else 0.0,
        "max_repeated_trigram_fraction": max_trigram_fraction,
    }


def grounding(records: Iterable[tuple[str, str]]) -> float | None:
    """Fraction of generated/faithful pairs sharing a content word.

    A content word is a token of 4+ letters, not in ``FUNCTION_WORDS`` and not
    the redaction placeholder words ``heard`` or ``speech``.  Only pairs with a
    non-empty ``faithful_rendering`` are evaluated.  Returns ``None`` when no
    such pair exists.
    """
    pairs: list[tuple[str, str]] = []
    for rec in records:
        if (
            isinstance(rec, (list, tuple))
            and len(rec) == 2
            and isinstance(rec[1], str)
            and rec[1].strip()
        ):
            pairs.append((rec[0] if isinstance(rec[0], str) else "", rec[1]))

    if not pairs:
        return None

    def content_words(text: str) -> set[str]:
        return {
            t
            for t in _tokens(text)
            if len(t) >= 4 and t not in _FUNCTION_INDEX and t not in ("heard", "speech")
        }

    matches = 0
    for generated, rendering in pairs:
        if content_words(generated) & content_words(rendering):
            matches += 1
    return matches / len(pairs)


def organ_gguf_sha256(gguf_path: Path, cache_path: Path) -> str | None:
    """SHA-256 of the organ GGUF, cached against path, size and mtime.

    The cache file stores ``{"path", "size", "mtime_ns", "sha256"}`` and is
    reused when all three file attributes match.  The file is hashed in 1 MiB
    blocks.  Returns ``None`` if the file is missing or unreadable.
    """
    try:
        path = Path(gguf_path)
        if not path.is_file():
            return None
        stat = path.stat()
        cache = Path(cache_path)

        if cache.is_file():
            try:
                data = json.loads(cache.read_text(encoding="utf-8"))
                if (
                    isinstance(data, dict)
                    and data.get("path") == str(path)
                    and data.get("size") == stat.st_size
                    and data.get("mtime_ns") == stat.st_mtime_ns
                    and isinstance(data.get("sha256"), str)
                ):
                    return data["sha256"]
            except Exception:
                # An unreadable cache only costs a re-hash below.
                log.debug("organ digest cache unreadable; re-hashing", exc_info=True)

        hasher = hashlib.sha256()
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(1 << 20)
                if not chunk:
                    break
                hasher.update(chunk)
        digest = hasher.hexdigest()

        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(cache.suffix + ".tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "path": str(path),
                        "size": stat.st_size,
                        "mtime_ns": stat.st_mtime_ns,
                        "sha256": digest,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            os.replace(tmp, cache)
        except Exception:
            # The digest is still correct; only the cache could not be saved.
            log.debug("organ digest cache not written", exc_info=True)
        return digest
    except Exception:
        log.debug("organ_gguf_sha256 failed", exc_info=True)
        return None


def load_base_profile(
    gguf_sha256: str | None,
    profiles_dir: Path,
) -> dict[str, Any] | None:
    """Return the base voice profile whose ``gguf_sha256`` matches ``digest``.

    Scans ``profiles_dir/*.json`` and validates required keys.  Files missing
    any required key are ignored with a warning.  Returns ``None`` for a
    ``None`` digest, a missing directory, no match, or unreadable files.
    """
    if gguf_sha256 is None:
        return None
    required = {
        "gguf_sha256",
        "llama_cpp_build",
        "sampling",
        "prompt_set_sha256",
        "style_profile",
    }
    try:
        directory = Path(profiles_dir)
        if not directory.is_dir():
            return None
        for path in sorted(directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if data.get("gguf_sha256") != gguf_sha256:
                continue
            missing = required - data.keys()
            if missing:
                log.warning(
                    "load_base_profile: %s missing required keys %s; ignoring",
                    path,
                    sorted(missing),
                )
                continue
            return data
    except Exception:
        log.debug("load_base_profile: scan failed", exc_info=True)
    return None


def compute_sleep_measures(
    corpus_file: Path,
    *,
    base_profile: dict[str, Any] | None = None,
    cumulative: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compute the four voice measures from a rotated corpus file.

    Reads JSONL from ``corpus_file``, skipping ``event: "preempted"`` and
    malformed lines.  Uses ``generated_text`` for style/health and the pair
    ``(generated_text, faithful_rendering)`` for grounding.

    Returns ``(measures, new_cumulative)`` where ``measures`` contains
    ``utterance_count``, ``distinctiveness``, ``self_consistency``,
    ``grounding``, ``health``, ``base_profile_digest`` and ``ts``.
    """
    texts: list[str] = []
    pairs: list[tuple[str, str]] = []

    try:
        path = Path(corpus_file)
        if path.is_file():
            with path.open("r", encoding="utf-8") as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(rec, dict) or rec.get("event") == "preempted":
                        continue
                    generated = rec.get("generated_text")
                    if not isinstance(generated, str):
                        continue
                    texts.append(generated)
                    pairs.append((generated, rec.get("faithful_rendering")))
    except Exception:
        log.debug("compute_sleep_measures: corpus read failed", exc_info=True)

    this_profile = style_profile(texts)
    health_dict = health(texts)
    grounding_score = grounding(pairs)

    distinctiveness: float | None = None
    base_digest: str | None = None
    if isinstance(base_profile, dict):
        base_digest = base_profile.get("gguf_sha256")
        try:
            distinctiveness = profile_distance(
                this_profile, base_profile.get("style_profile", {}) or {}
            )
        except Exception:
            distinctiveness = None

    self_consistency: float | None = None
    if cumulative is not None and isinstance(cumulative, dict):
        try:
            self_consistency = profile_distance(this_profile, cumulative)
        except Exception:
            self_consistency = None

    measures = {
        "utterance_count": health_dict["utterance_count"],
        "distinctiveness": distinctiveness,
        "self_consistency": self_consistency,
        "grounding": grounding_score,
        "health": health_dict,
        "base_profile_digest": base_digest,
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    new_cumulative = merge_profiles(cumulative, this_profile)
    return measures, new_cumulative
