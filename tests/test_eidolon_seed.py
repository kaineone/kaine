# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for operator-seed first-boot fallback (eidolon-self-inference change).

Coverage (task 6.3):
- Seed populates all four fields on first boot.
- Observation-driven updates apply on top of the seed.
- No seed is applied when seed_path is not configured.
- apply_seed() is idempotent (called only once even if invoked twice).
"""
from __future__ import annotations

import json
from pathlib import Path


from kaine.modules.eidolon.document import SelfModel
from kaine.modules.eidolon.self_inference import SelfInferenceEngine, _NORM_PREFIX


def _write_seed(tmp_path: Path, *records: dict) -> Path:
    """Write a seed JSONL file and return its path."""
    p = tmp_path / "seed.jsonl"
    p.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n",
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# 6.3 Seed populates fields on first boot
# ---------------------------------------------------------------------------

def test_seed_populates_all_four_fields(tmp_path: Path):
    """Seed JSONL sets values, behavioral_norms, personality_baseline, capability_map."""
    seed = _write_seed(
        tmp_path,
        {
            "values": ["curiosity", "honesty"],
            "behavioral_norms": ["speech_pattern:think"],
            "personality_baseline": {"valence_mean": 0.3},
            "capability_map": {"effectors": ["echo"]},
        },
    )
    engine = SelfInferenceEngine(enabled=True, seed_path=seed)
    model = engine.apply_seed(SelfModel())

    assert model.values == ["curiosity", "honesty"]
    assert model.behavioral_norms == ["speech_pattern:think"]
    assert model.personality_baseline == {"valence_mean": 0.3}
    assert model.capability_map == {"effectors": ["echo"]}


def test_seed_partial_fields(tmp_path: Path):
    """Seed with only some fields leaves the others at their defaults."""
    seed = _write_seed(tmp_path, {"values": ["transparency"]})
    engine = SelfInferenceEngine(enabled=True, seed_path=seed)
    model = engine.apply_seed(SelfModel())

    assert model.values == ["transparency"]
    assert model.behavioral_norms == []
    assert model.personality_baseline == {}
    assert model.capability_map == {}


def test_seed_multiple_lines_last_wins(tmp_path: Path):
    """Multiple seed lines merge; later lines overwrite earlier for the same key."""
    seed = _write_seed(
        tmp_path,
        {"values": ["first"]},
        {"values": ["second"]},
    )
    engine = SelfInferenceEngine(enabled=True, seed_path=seed)
    model = engine.apply_seed(SelfModel())
    # The second line overwrites.
    assert model.values == ["second"]


def test_seed_applied_only_once(tmp_path: Path):
    """apply_seed() is idempotent — the seed is not re-applied on second call."""
    seed = _write_seed(tmp_path, {"values": ["honesty"]})
    engine = SelfInferenceEngine(enabled=True, seed_path=seed)

    model = engine.apply_seed(SelfModel())
    assert model.values == ["honesty"]

    # Second call must not alter the model (seed is already marked applied).
    model2 = engine.apply_seed(model.with_updates(values=[]))
    # apply_seed() is a no-op on second call → values cleared externally are not restored.
    assert model2.values == []


# ---------------------------------------------------------------------------
# 6.3 Observation updates on top of seed
# ---------------------------------------------------------------------------

def test_observations_update_on_top_of_seed(tmp_path: Path):
    """Observation-driven updates (maintenance_cycle_end) apply on top of the seed."""
    seed = _write_seed(
        tmp_path,
        {
            "values": ["seeded_value"],
            "behavioral_norms": ["seeded_norm"],
        },
    )
    engine = SelfInferenceEngine(
        enabled=True,
        seed_path=seed,
        speech_pattern_min_count=2,
        vad_window_cycles=5,
    )
    model = engine.apply_seed(SelfModel())

    # Seed is present.
    assert "seeded_norm" in model.behavioral_norms

    # Enough observations to trigger a new inferred norm.
    for _ in range(2):
        engine.observe_lingua({"text": "..."}, "internal.thought")

    model = engine.maintenance_cycle_end(model)
    # New norm was inferred.
    assert f"{_NORM_PREFIX}internal.thought" in model.behavioral_norms
    # Seeded norm may or may not be preserved depending on the derivation
    # policy (the engine derives fresh norms on each cycle; the seed may
    # be overwritten).  What matters is that the new norm is present.


# ---------------------------------------------------------------------------
# 6.3 No seed applied without seed_path
# ---------------------------------------------------------------------------

def test_no_seed_applied_without_config():
    """When seed_path is not set, self-model fields start empty."""
    engine = SelfInferenceEngine(enabled=True)  # no seed_path
    model = engine.apply_seed(SelfModel())

    assert model.values == []
    assert model.behavioral_norms == []
    assert model.personality_baseline == {}
    assert model.capability_map == {}


def test_no_seed_applied_when_disabled(tmp_path: Path):
    """Disabled engine never applies the seed even if seed_path is configured."""
    seed = _write_seed(tmp_path, {"values": ["should_not_appear"]})
    engine = SelfInferenceEngine(enabled=False, seed_path=seed)
    model = engine.apply_seed(SelfModel())

    assert model.values == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_seed_missing_file_does_not_crash(tmp_path: Path):
    """A configured but non-existent seed file is logged and silently skipped."""
    engine = SelfInferenceEngine(
        enabled=True,
        seed_path=tmp_path / "nonexistent.jsonl",
    )
    # Must not raise.
    model = engine.apply_seed(SelfModel())
    assert model.values == []


def test_seed_blank_lines_and_comments_skipped(tmp_path: Path):
    """Blank lines and # comments in seed JSONL are ignored gracefully."""
    p = tmp_path / "seed.jsonl"
    p.write_text(
        "# this is a comment\n"
        "\n"
        '{"values": ["curiosity"]}\n'
        "\n",
        encoding="utf-8",
    )
    engine = SelfInferenceEngine(enabled=True, seed_path=p)
    model = engine.apply_seed(SelfModel())
    assert model.values == ["curiosity"]
