# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Deterministic audition feed replay loader."""

from __future__ import annotations

from kaine.modules.audition.feed_replay import load_feed_replay


def test_seeded_synthetic_returns_immutable_tuple_with_matching_lengths():
    blocks, labels, meta = load_feed_replay("seeded_synthetic", seed=7)
    assert isinstance(blocks, tuple) and isinstance(labels, tuple)
    assert len(blocks) == len(labels) == 12
    assert all(isinstance(b, (bytes, bytearray)) for b in blocks)
    assert meta["seed"] == 7
    assert meta["feed_family"] == "seeded_synthetic"


def test_seeded_synthetic_is_deterministic():
    a = load_feed_replay("seeded_synthetic", seed=9, n_blocks=6)
    b = load_feed_replay("seeded_synthetic", seed=9, n_blocks=6)
    assert a == b


def test_repeated_tone_is_single_block_repeated():
    blocks, labels, meta = load_feed_replay("repeated_tone", seed=3, n_blocks=5)
    assert len(blocks) == len(labels) == 5
    assert all(b == blocks[0] for b in blocks)
    assert all(x == 0 for x in labels)
    assert meta["label_rule"] == "none"


def test_pseudo_noise_is_deterministic_and_distinct_blocks():
    a = load_feed_replay("pseudo_noise", seed=1, n_blocks=4)
    b = load_feed_replay("pseudo_noise", seed=1, n_blocks=4)
    assert a == b
    blocks, labels, meta = a
    assert len(set(blocks)) == len(blocks)
    assert all(x == 0 for x in labels)


def test_unknown_family_raises():
    try:
        load_feed_replay("totally-unknown", seed=1)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_seeded_synthetic_has_surprise_labels():
    blocks, labels, meta = load_feed_replay("seeded", seed=42, n_blocks=20)
    assert 1 in labels
    assert len(meta["surprise_indices"]) > 0
