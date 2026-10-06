# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Pinned public sources and conversion helpers for K1-Jev."""

from __future__ import annotations

import csv
import hashlib
import os
import random
import re
from pathlib import Path
from typing import Any

import httpx

from kaine.decision import schema

PINNED: dict[str, tuple[str, str, int | None, str]] = {
    "banking77/train.csv": (
        "https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/"
        "57ec275d8078af65b7731c2a98be812d844a6d6b/banking_data/train.csv",
        "b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b",
        None,
        "CC-BY-4.0",
    ),
    "banking77/test.csv": (
        "https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/"
        "57ec275d8078af65b7731c2a98be812d844a6d6b/banking_data/test.csv",
        "d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d",
        None,
        "CC-BY-4.0",
    ),
    "multinli/train.parquet": (
        "https://huggingface.co/datasets/nyu-mll/multi_nli/resolve/"
        "da70db2af9d09693783c3320c4249840212ee221/data/train-00000-of-00001.parquet",
        "1c1de03640b168e410aabfca19e7cc2f3dfcd7f0e126e935674e56fb102c4529",
        213_961_663,
        "OANC (fiction genre excluded)",
    ),
    "multinli/validation_matched.parquet": (
        "https://huggingface.co/datasets/nyu-mll/multi_nli/resolve/"
        "da70db2af9d09693783c3320c4249840212ee221/data/validation_matched-00000-of-00001.parquet",
        "350c26950b55f460b50d36c76aef87d64b49c78812d7abf7bf97e5fede10f186",
        4_938_568,
        "OANC (fiction genre excluded)",
    ),
    "generator/Qwen3.5-9B-Q5_K_M.gguf": (
        "https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/"
        "3885219b6810b007914f3a7950a8d1b469d598a5/Qwen3.5-9B-Q5_K_M.gguf",
        "dc2a39aef291f91a9116ad214058da0d86eb648743a124bd8c333787c4b9c91c",
        6_577_841_376,
        "Apache-2.0",
    ),
}


class FetchError(Exception):
    """A download failed verification."""

    def __init__(self, name: str, expected: str, actual: str) -> None:
        super().__init__(f"{name}: verification failed (expected {expected}, got {actual})")
        self.name = name
        self.expected = expected
        self.actual = actual


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def fetch(
    work_root: str | os.PathLike[str],
    names: list[str],
    *,
    client: httpx.Client | None = None,
) -> None:
    """Download pinned files into *work_root*/cache/*name*."""
    root = Path(work_root)
    root.mkdir(parents=True, exist_ok=True)
    own_client = client is None
    if own_client:
        client = httpx.Client(
            timeout=httpx.Timeout(60.0),
            follow_redirects=True,
        )
    try:
        for name in names:
            if name not in PINNED:
                raise FetchError(name, "?", "unknown source name")
            url, expected_hash, expected_size, _ = PINNED[name]
            dest = root / "cache" / name
            dest.parent.mkdir(parents=True, exist_ok=True)

            if dest.exists():
                actual = _sha256_file(dest)
                if actual == expected_hash:
                    continue
                dest.unlink()
                raise FetchError(name, expected_hash, actual)

            part = dest.with_suffix(dest.suffix + ".part")
            hasher = hashlib.sha256()
            with client.stream("GET", url, follow_redirects=True) as resp:
                resp.raise_for_status()
                with part.open("wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            hasher.update(chunk)

            actual = hasher.hexdigest()
            if actual != expected_hash:
                part.unlink(missing_ok=True)
                raise FetchError(name, expected_hash, actual)
            if expected_size is not None and part.stat().st_size != expected_size:
                size = part.stat().st_size
                part.unlink(missing_ok=True)
                raise FetchError(name, f"{expected_size} bytes", f"{size} bytes")

            os.replace(part, dest)
    finally:
        if own_client:
            client.close()


def banking77_examples(
    csv_path: str | os.PathLike[str],
    rng: random.Random,
    *,
    n: int | None = None,
) -> list[dict[str, Any]]:
    """Convert Banking77 CSV rows into choice examples."""
    rows: list[tuple[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append((row["text"], row["category"]))

    raw_categories = sorted({cat for _, cat in rows})
    if n is not None:
        rows = rng.sample(rows, min(n, len(rows)))

    k_choices = (8, 12, 16, 24)
    examples: list[dict[str, Any]] = []
    for text, category in rows:
        true_key = category.replace("_", " ")
        other_raw = [c for c in raw_categories if c != category]
        k = rng.choice(k_choices)
        distractors = rng.sample(other_raw, min(k - 1, len(other_raw)))
        options: list[list[Any]] = [[true_key, None]]
        for d in distractors:
            options.append([d.replace("_", " "), None])
        rng.shuffle(options)

        examples.append(
            {
                "source": "banking77",
                "question_id": "banking77",
                "instructions": "Which banking request does the customer make?",
                "type": "choice",
                "options": options,
                "state": schema.state_text(text),
                "answer": true_key,
            }
        )
    return examples


def multinli_examples(
    parquet_path: str | os.PathLike[str],
    rng: random.Random,
    *,
    n: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Convert MultiNLI parquet rows into NLI examples and kept genre counts."""
    import pandas as pd

    df = pd.read_parquet(parquet_path)
    df = df[df["genre"].str.lower() != "fiction"].copy()
    df = df[df["label"] != -1].copy()
    df = df.reset_index(drop=True)

    kept_counts = df["genre"].value_counts().to_dict()
    kept_counts = {str(k): int(v) for k, v in kept_counts.items()}

    if n < len(df):
        chosen = rng.sample(range(len(df)), n)
        df = df.iloc[chosen].copy()
        df = df.reset_index(drop=True)

    label_to_choice = {0: "entails", 1: "neutral", 2: "contradicts"}
    examples: list[dict[str, Any]] = []

    for _, row in df.iterrows():
        premise = row["premise"]
        hypothesis = row["hypothesis"]
        label = int(row["label"])

        if rng.random() < 0.7:
            options = [
                ["entails", "the statement must be true"],
                ["neutral", "the statement may or may not be true"],
                ["contradicts", "the statement must be false"],
            ]
            answer = label_to_choice[label]
            question_id = "nli"
            instructions = f'Given what the speaker says, is this statement true? "{hypothesis}"'
        else:
            options = [["true", None], ["false", None]]
            answer = "true" if label == 0 else "false"
            question_id = "nli_yesno"
            instructions = f'Does what the speaker says make this statement true? "{hypothesis}"'

        examples.append(
            {
                "source": "multinli",
                "question_id": question_id,
                "instructions": instructions,
                "type": "choice",
                "options": options,
                "state": schema.state_text(premise),
                "answer": answer,
            }
        )

    return examples, kept_counts
