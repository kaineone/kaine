# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import hashlib
import json
import os

import pytest

from kaine.modules.hypnos.voice_measures import (
    FUNCTION_WORDS,
    compute_sleep_measures,
    grounding,
    health,
    load_base_profile,
    merge_profiles,
    organ_gguf_sha256,
    profile_distance,
    style_profile,
)


def test_function_words_length_and_distribution_sums_to_one():
    assert len(FUNCTION_WORDS) == 100
    profile = style_profile(["the cat sat on the mat and looked at a door."])
    assert len(profile["function_words"]) == 100
    assert abs(sum(profile["function_words"]) - 1.0) < 1e-9


def test_function_words_all_zeros_when_no_function_word():
    profile = style_profile(["zebra quantum marmalade"])
    assert sum(profile["function_words"]) == 0.0


def test_profile_distance_self_is_zero():
    profile = style_profile(["the quick brown fox jumps over the lazy dog."])
    assert profile_distance(profile, profile) == pytest.approx(0.0, abs=1e-9)


def test_profile_distance_different_styles_is_in_zero_one():
    a = style_profile(["the cat sat on the mat and looked at the door."])
    b = style_profile(["I will be there, if you can come with me!"])
    d = profile_distance(a, b)
    assert 0.0 < d <= 1.0


def test_profile_distance_all_zeros_returns_none():
    a = style_profile(["zebra quantum marmalade"])
    b = style_profile(["xyzzy plugh thx1138"])
    assert profile_distance(a, b) is None


def test_health_known_toy_corpus():
    texts = ["the quick brown fox", "the lazy dog sleeps"]
    h = health(texts)
    assert h == {
        "utterance_count": 2,
        "mean_tokens": 4.0,
        "distinct_1": 0.875,
        "distinct_2": 1.0,
        "max_repeated_trigram_fraction": 0.0,
    }
    looping = health(["go on go on go on go on"])
    # Six trigram occurrences, two distinct: four repeat an earlier one.
    assert looping["max_repeated_trigram_fraction"] == 4 / 6


def test_grounding_counts_shared_content_words():
    records = [
        ("I saw a zebra quantum marmalade today.", "the zebra quantum marmalade was visible."),
        ("the weather is nice", "heard speech"),
    ]
    assert grounding(records) == 0.5


def test_grounding_ignores_function_words_and_placeholder():
    records = [
        ("the a an and heard speech", "the a an and heard speech"),
        ("zebra quantum marmalade", "zebra quantum marmalade"),
    ]
    # The first pair shares only function words and the placeholder, so it is
    # not grounded; the second is.
    assert grounding(records) == 0.5


def test_grounding_no_pairs_returns_none():
    assert grounding([]) is None


def test_digest_cache_reused_and_refreshed_on_mtime(tmp_path, monkeypatch):
    f = tmp_path / "organ.gguf"
    f.write_bytes(b"fake gguf content")
    cache = tmp_path / "digest.json"

    real_sha256 = hashlib.sha256

    class CountingSHA256:
        count = 0

        def __init__(self, *args, **kwargs):
            CountingSHA256.count += 1
            self._h = real_sha256(*args, **kwargs)

        def update(self, *args, **kwargs):
            self._h.update(*args, **kwargs)

        def hexdigest(self, *args, **kwargs):
            return self._h.hexdigest(*args, **kwargs)

    monkeypatch.setattr(hashlib, "sha256", CountingSHA256)

    d1 = organ_gguf_sha256(f, cache)
    assert d1 is not None
    assert CountingSHA256.count == 1

    d2 = organ_gguf_sha256(f, cache)
    assert d2 == d1
    assert CountingSHA256.count == 1  # cache reused

    # Touch the file so the cache is invalidated.
    new_mtime = f.stat().st_mtime_ns + 10_000_000_000
    os.utime(f, ns=(new_mtime, new_mtime))

    d3 = organ_gguf_sha256(f, cache)
    assert d3 == d1
    assert CountingSHA256.count == 2
    cached = json.loads(cache.read_text())
    assert cached["mtime_ns"] == new_mtime


def test_load_base_profile_matches_and_ignores_incomplete(tmp_path, caplog):
    valid = {
        "gguf_sha256": "abc",
        "llama_cpp_build": "b123",
        "sampling": {"seed": 42},
        "prompt_set_sha256": "def",
        "style_profile": style_profile(["the cat sat."]),
    }
    invalid = {
        "gguf_sha256": "abc",
        "llama_cpp_build": "b123",
        "sampling": {"seed": 42},
        "prompt_set_sha256": "def",
        # missing style_profile
    }
    (tmp_path / "valid.json").write_text(json.dumps(valid))
    (tmp_path / "invalid.json").write_text(json.dumps(invalid))

    assert load_base_profile("abc", tmp_path) is not None
    assert load_base_profile("xyz", tmp_path) is None
    assert load_base_profile(None, tmp_path) is None

    with caplog.at_level("WARNING"):
        load_base_profile("abc", tmp_path)
    assert "missing required keys" in caplog.text


def test_sentinel_phrase_never_appears_in_measures_or_profile(tmp_path):
    sentinel = "zebra quantum marmalade"
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(
        json.dumps({"generated_text": f"hello {sentinel} world", "faithful_rendering": "x"})
        + "\n"
    )
    measures, cumulative = compute_sleep_measures(corpus, base_profile=None, cumulative=None)

    assert sentinel not in json.dumps(measures)
    assert sentinel not in json.dumps(cumulative)

    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(cumulative))
    assert sentinel not in profile_path.read_text()

    measures_path = tmp_path / "measures.jsonl"
    measures_path.write_text(json.dumps(measures))
    assert sentinel not in measures_path.read_text()


def test_merge_profiles_token_weighted():
    a = style_profile(["the cat sat."])
    b = style_profile(["a dog ran."])
    merged = merge_profiles(a, b)
    assert merged["n_tokens"] == a["n_tokens"] + b["n_tokens"]
    # Weighted average should lie between the two scalar values.
    assert min(a["mean_word_len"], b["mean_word_len"]) <= merged["mean_word_len"] <= max(
        a["mean_word_len"], b["mean_word_len"]
    )
    assert len(merged["function_words"]) == 100
    assert sum(merged["function_words"]) == pytest.approx(1.0, abs=1e-9)
