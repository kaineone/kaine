# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Deterministic in-memory replay feeds for the audition bake-off.

This module provides a small, dependency-free replay path producing blocks of PCM
bytes that an audition encoder can consume directly (``embed(block, sample_rate)``).
No audio is downloaded, decoded from disk, or written to disk: every feed is
derived from immutable in-memory primitives keyed by ``seed``.

``load_feed_replay(feed_family, *, seed)`` returns an immutable tuple::

    (blocks, labels, metadata)

where ``blocks`` and ``labels`` are tuples of equal length and ``metadata`` carries
the seed, block geometry and the label rule used.
"""

from __future__ import annotations

import hashlib
import math
import struct
from typing import Any

SAMPLE_RATE = 16000
FRAMES_PER_BLOCK = 480
CHANNELS = 1
DEFAULT_BLOCKS = 12
BLOCK_BYTES = FRAMES_PER_BLOCK * CHANNELS * 2

_CANONICAL = {
    "seeded": "seeded_synthetic",
    "seeded_synthetic": "seeded_synthetic",
    "synthetic": "seeded_synthetic",
    "synthetic_seeded": "seeded_synthetic",
    "seededsynthetic": "seeded_synthetic",

    "repeated": "repeated_tone",
    "repeated_tone": "repeated_tone",
    "tone": "repeated_tone",
    "tone_pattern": "repeated_tone",
    "repeated_non_lexical_tone": "repeated_tone",
    "non_lexical_tone": "repeated_tone",
    "nonlexical": "repeated_tone",
    "nonlexical_tone": "repeated_tone",
    "single_tone": "repeated_tone",

    "noise": "pseudo_noise",
    "pseudo_noise": "pseudo_noise",
    "pseudo-noise": "pseudo_noise",
    "pseudonoise": "pseudo_noise",
    "deterministic_noise": "pseudo_noise",
    "pseudo_noise_feed": "pseudo_noise",
}


def _canonical_family(feed_family: str) -> str:
    key = str(feed_family).strip().lower().replace(" ", "_").replace("-", "_")
    # Allow common compound aliases without separators.
    if key not in _CANONICAL:
        # Try removing underscores as a last attempt.
        compact = key.replace("_", "")
        for k, v in _CANONICAL.items():
            if k.replace("_", "") == compact:
                return v
    if key not in _CANONICAL:
        raise ValueError(f"unknown feed_family: {feed_family!r}")
    return _CANONICAL[key]


def _seeded_synthetic(seed: int, n_blocks: int) -> tuple[tuple[bytes, ...], tuple[int, ...], dict[str, Any]]:
    from kaine.modules.audition.feed import SeededAudioSchedule, SeededProceduralAudioStream

    schedule = SeededAudioSchedule(
        seed=int(seed),
        sample_rate=SAMPLE_RATE,
        channels=CHANNELS,
        frames_per_block=FRAMES_PER_BLOCK,
        surprise_interval=4,
        base_strength=0.3,
        surprise_strength=1.0,
    )
    stream = SeededProceduralAudioStream(schedule, callback=lambda _b: None)
    blocks = tuple(stream.pcm_at(i) for i in range(n_blocks))
    surprise = set(stream.surprise_indices(n_blocks))
    labels = tuple(1 if i in surprise else 0 for i in range(n_blocks))
    meta = {
        "feed_family": "seeded_synthetic",
        "family": "seeded_synthetic",
        "seed": int(seed),
        "block_count": int(n_blocks),
        "n_blocks": int(n_blocks),
        "count": int(n_blocks),
        "sample_rate": int(SAMPLE_RATE),
        "frames_per_block": int(FRAMES_PER_BLOCK),
        "block_samples": int(FRAMES_PER_BLOCK),
        "block_size": int(BLOCK_BYTES),
        "channels": int(CHANNELS),
        "label_rule": "surprise_indices",
        "surprise_indices": tuple(int(i) for i in stream.surprise_indices(n_blocks)),
    }
    return blocks, labels, meta


def _repeated_tone(seed: int, n_blocks: int) -> tuple[tuple[bytes, ...], tuple[int, ...], dict[str, Any]]:
    rng_state = hashlib.sha256(f"tone:{seed}".encode()).digest()
    # Derive a stable, non-speech-like frequency in Hz from the seed.
    freq = 110.0 + (int.from_bytes(rng_state[:4], "big") % 330)
    phase0 = (int.from_bytes(rng_state[4:8], "big") / 2 ** 32) * 2.0 * math.pi
    amp = 0.35
    samples = []
    for i in range(FRAMES_PER_BLOCK):
        t = i / float(SAMPLE_RATE)
        val = amp * math.sin(2.0 * math.pi * freq * t + phase0)
        samples.append(int(round(val * 32767.0)))
    packed = struct.pack("<" + "h" * len(samples), *samples)
    assert len(packed) == BLOCK_BYTES
    blocks = tuple(packed for _ in range(n_blocks))
    labels = tuple(0 for _ in range(n_blocks))
    meta = {
        "feed_family": "repeated_tone",
        "family": "repeated_tone",
        "seed": int(seed),
        "block_count": int(n_blocks),
        "n_blocks": int(n_blocks),
        "count": int(n_blocks),
        "sample_rate": int(SAMPLE_RATE),
        "frames_per_block": int(FRAMES_PER_BLOCK),
        "block_samples": int(FRAMES_PER_BLOCK),
        "block_size": int(BLOCK_BYTES),
        "channels": int(CHANNELS),
        "label_rule": "none",
        "tone_frequency_hz": float(freq),
    }
    return blocks, labels, meta


def _pseudo_noise(seed: int, n_blocks: int) -> tuple[tuple[bytes, ...], tuple[int, ...], dict[str, Any]]:
    blocks = []
    for block_index in range(n_blocks):
        out = bytearray()
        counter = 0
        while len(out) < BLOCK_BYTES:
            digest = hashlib.sha256(
                f"pseudo-noise:{seed}:{block_index}:{counter}".encode("ascii")
            ).digest()
            out.extend(digest)
            counter += 1
        blocks.append(bytes(out[:BLOCK_BYTES]))
    blocks_t = tuple(blocks)
    labels = tuple(0 for _ in range(n_blocks))
    meta = {
        "feed_family": "pseudo_noise",
        "family": "pseudo_noise",
        "seed": int(seed),
        "block_count": int(n_blocks),
        "n_blocks": int(n_blocks),
        "count": int(n_blocks),
        "sample_rate": int(SAMPLE_RATE),
        "frames_per_block": int(FRAMES_PER_BLOCK),
        "block_samples": int(FRAMES_PER_BLOCK),
        "block_size": int(BLOCK_BYTES),
        "channels": int(CHANNELS),
        "label_rule": "none",
    }
    return blocks_t, labels, meta


def load_feed_replay(feed_family: str, *, seed: int, n_blocks: int = DEFAULT_BLOCKS) -> tuple[tuple[bytes, ...], tuple[int, ...], dict[str, Any]]:
    family = _canonical_family(feed_family)
    n = int(n_blocks)
    if n <= 0:
        raise ValueError("n_blocks must be positive")
    if family == "seeded_synthetic":
        return _seeded_synthetic(int(seed), n)
    if family == "repeated_tone":
        return _repeated_tone(int(seed), n)
    if family == "pseudo_noise":
        return _pseudo_noise(int(seed), n)
    raise ValueError(f"unsupported feed family: {feed_family!r}")


__all__ = ["load_feed_replay"]
