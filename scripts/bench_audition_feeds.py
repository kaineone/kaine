# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Deterministic benchmark record generator for synthetic seeded auditory feeds."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np

from kaine.modules.audition.acoustic import ACOUSTIC_ENCODERS, cosine_change
from kaine.modules.audition.feed import SeededAudioSchedule, SeededProceduralAudioStream
from kaine.modules.audition.forward import AuditoryForwardModel

FEEDING_VERSION = "1.0"
FEED_FAMILY = "synthetic_seeded"
SEED = 42
SAMPLE_RATE = 16000
DEFAULT_BLOCKS = 300
SURPRISE_INTERVAL = 150
OUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "records"
    / "audition-feed-bench-synthetic.json"
)
ENCODERS = ("spectral",)


def load_feed(
    kind: str,
    config: dict[str, Any],
    n_blocks: int,
) -> tuple[list[bytes], list[int], dict[str, Any]]:
    if kind not in {"synthetic", "seeded"}:
        raise ValueError(f"unsupported feed kind: {kind!r}")

    seed = int(config.get("seed", SEED))
    sample_rate = int(config.get("sample_rate", SAMPLE_RATE))
    channels = int(config.get("channels", 1))
    frames_per_block = int(config.get("frames_per_block", 480))
    surprise_interval = int(config.get("surprise_interval", SURPRISE_INTERVAL))
    base_strength = float(config.get("base_strength", 0.3))
    surprise_strength = float(config.get("surprise_strength", 1.0))

    schedule = SeededAudioSchedule(
        seed=seed,
        sample_rate=sample_rate,
        channels=channels,
        frames_per_block=frames_per_block,
        surprise_interval=surprise_interval,
        base_strength=base_strength,
        surprise_strength=surprise_strength,
    )
    stream = SeededProceduralAudioStream(schedule, callback=lambda _b: None)
    blocks = [stream.pcm_at(i) for i in range(n_blocks)]
    _surprise = set(stream.surprise_indices(n_blocks))
    labels = [1 if i in _surprise else 0 for i in range(n_blocks)]
    meta = {
        "feeding_version": FEEDING_VERSION,
        "feed_family": FEED_FAMILY,
        "seed": seed,
        "block_count": int(n_blocks),
        "block_samples": int(frames_per_block),
        "sample_rate": int(sample_rate),
        "surprise_indices": [int(i) for i in stream.surprise_indices(n_blocks)],
    }
    return blocks, labels, meta


def _block_hash(block: bytes) -> str:
    return hashlib.sha256(block).hexdigest()


def _roc_auc(labels: list[int], scores: list[float]) -> Optional[float]:
    if len(set(labels)) < 2:
        return None
    y = np.asarray(labels)
    s = np.asarray(scores, dtype=float)
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), dtype=float)
    sorted_s = s[order]
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and sorted_s[j + 1] == sorted_s[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    n_pos = int(y.sum())
    n_neg = len(y) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def run_encoder(
    name: str, blocks: list[bytes], labels: list[int], sample_rate: int
) -> dict[str, Any]:
    encoder = ACOUSTIC_ENCODERS[name]()
    encoder.embed(blocks[0], sample_rate)
    encoder = ACOUSTIC_ENCODERS[name]()

    forward = AuditoryForwardModel(feature_dim=encoder.embedding_dim, seed=SEED)
    prev = None
    salience: list[float] = []
    lat_ms: list[float] = []
    for blk in blocks:
        t0 = time.perf_counter()
        emb = encoder.embed(blk, sample_rate)
        change = cosine_change(emb, prev)
        err = forward.step(emb)
        lat_ms.append((time.perf_counter() - t0) * 1000.0)
        salience.append(float(change) + float(err))
        prev = emb

    neg = [s for s, y in zip(salience, labels) if y == 0]
    threshold = float(np.percentile(neg, 95)) if neg else 0.0
    false_alerts = sum(1 for s, y in zip(salience, labels) if y == 0 and s > threshold)
    samples_per_block = len(blocks[0]) // 2
    seconds_per_block = samples_per_block / float(sample_rate)
    minutes = len(blocks) * seconds_per_block / 60.0
    return {
        "embedding_dim": int(encoder.embedding_dim),
        "roc_auc": _roc_auc(labels, salience),
        "false_alerts_per_min": false_alerts / minutes if minutes > 0 else 0.0,
        "p95_threshold": threshold,
    }


def build_record(
    seed: int = SEED,
    n_blocks: int = DEFAULT_BLOCKS,
    surprise_interval: int = SURPRISE_INTERVAL,
    frames_per_block: int = 480,
    sample_rate: int = SAMPLE_RATE,
) -> dict[str, Any]:
    config = {
        "seed": seed,
        "sample_rate": sample_rate,
        "channels": 1,
        "frames_per_block": frames_per_block,
        "surprise_interval": surprise_interval,
        "base_strength": 0.3,
        "surprise_strength": 1.0,
    }
    blocks, labels, meta = load_feed("synthetic", config, n_blocks)

    encoders: dict[str, Any] = {}
    for name in ENCODERS:
        try:
            encoders[name] = run_encoder(name, blocks, labels, sample_rate)
        except Exception as exc:  # noqa: BLE001
            encoders[name] = {"skipped": f"{type(exc).__name__}: {exc}"}

    batas = [_block_hash(b) for b in blocks]

    record = {
        "feeding_version": FEEDING_VERSION,
        "feed_family": FEED_FAMILY,
        "seed": int(seed),
        "block_count": int(n_blocks),
        "block_samples": int(frames_per_block),
        "sample_rate": int(sample_rate),
        "surprise_interval": int(surprise_interval),
        "labels": [int(x) for x in labels],
        "batas": batas,
        "encoder_summary": encoders,
        "encoder": encoders,
        "encoders": encoders,
        "encoder_summaries": encoders,
        "config": config,
        "meta": meta,
    }
    return record


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocks", type=int, default=DEFAULT_BLOCKS)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--surprise-interval", type=int, default=SURPRISE_INTERVAL)
    parser.add_argument("--frames-per-block", type=int, default=480)
    parser.add_argument("--sample-rate", type=int, default=SAMPLE_RATE)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args(argv)

    record = build_record(
        seed=args.seed,
        n_blocks=args.blocks,
        surprise_interval=args.surprise_interval,
        frames_per_block=args.frames_per_block,
        sample_rate=args.sample_rate,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(record, sort_keys=True, indent=2) + "\n"
    args.out.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode()).hexdigest()
    print(f"wrote {args.out} (sha256={digest})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
