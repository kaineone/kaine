# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.lifecycle.strategies import (
    AffectMergeStrategy,
    EpisodicMemoryMergeStrategy,
    PlanningMergeStrategy,
    SelfModelMergeStrategy,
    UnionMergeStrategy,
    default_strategies,
)

# ---- Union (default) ----


def test_union_both_none():
    assert UnionMergeStrategy().merge(None, None) == {}


def test_union_one_none_returns_other():
    s = UnionMergeStrategy()
    assert s.merge({"a": 1}, None) == {"a": 1}
    assert s.merge(None, {"a": 1}) == {"a": 1}


def test_union_last_write_wins_for_scalars():
    s = UnionMergeStrategy()
    assert s.merge({"a": 1, "b": 2}, {"b": 3, "c": 4}) == {"a": 1, "b": 3, "c": 4}


def test_union_recurses_into_dicts():
    s = UnionMergeStrategy()
    out = s.merge({"x": {"a": 1, "b": 2}}, {"x": {"b": 5, "c": 6}})
    assert out == {"x": {"a": 1, "b": 5, "c": 6}}


def test_union_concatenates_lists_dedup_preserving_order():
    s = UnionMergeStrategy()
    out = s.merge({"l": [1, 2, 3]}, {"l": [3, 4, 5]})
    assert out == {"l": [1, 2, 3, 4, 5]}


# ---- Episodic memory ----


def test_episodic_memory_sums_short_term_and_preserves_matching_prefix():
    s = EpisodicMemoryMergeStrategy()
    space = {"model_id": "minilm", "dim": 384, "pooling": "mean", "normalized": True}
    out = s.merge(
        {"short_term_size": 4, "collection_prefix": "episodic_memory_",
         "embedding_space": space},
        {"short_term_size": 7, "collection_prefix": "episodic_memory_",
         "embedding_space": space},
    )
    assert out["short_term_size"] == 11
    assert out["collection_prefix"] == "episodic_memory_"
    assert "metadata" not in out
    assert out["embedding_space"] == space
    assert out["pending_source_tag"] == ["fork-a", "fork-b"]


def test_episodic_memory_flags_prefix_mismatch():
    s = EpisodicMemoryMergeStrategy()
    out = s.merge(
        {"short_term_size": 1, "collection_prefix": "a_"},
        {"short_term_size": 2, "collection_prefix": "b_"},
    )
    assert out["metadata"]["prefix_mismatch"] is True
    assert set(out["metadata"]["parent_prefixes"]) == {"a_", "b_"}


def test_episodic_memory_flags_embedding_space_mismatch():
    s = EpisodicMemoryMergeStrategy()
    out = s.merge(
        {"short_term_size": 1, "collection_prefix": "episodic_memory_",
         "embedding_space": {"model_id": "a", "dim": 384, "pooling": "mean", "normalized": True}},
        {"short_term_size": 2, "collection_prefix": "episodic_memory_",
         "embedding_space": {"model_id": "b", "dim": 384, "pooling": "mean", "normalized": True}},
    )
    assert out["metadata"]["embedding_space_mismatch"] is True
    assert out["embedding_space"]["model_id"] == "a"


def test_episodic_memory_one_parent_missing():
    s = EpisodicMemoryMergeStrategy()
    out = s.merge({"short_term_size": 3, "collection_prefix": "episodic_memory_"}, None)
    assert out == {"short_term_size": 3, "collection_prefix": "episodic_memory_"}


# ---- Planning ----


def test_planning_one_sided_selection_keeps_lower_entropy():
    s = PlanningMergeStrategy()
    # Fork A: a near point-mass posterior (low entropy / high certainty).
    certain = {
        "last_action": "request_think",
        "posterior": [[0.97, 0.01, 0.01, 0.01], [0.9, 0.05, 0.05]],
    }
    # Fork B: a near-uniform posterior (high entropy / low certainty).
    uncertain = {
        "last_action": "no_op",
        "posterior": [[0.25, 0.25, 0.25, 0.25], [0.34, 0.33, 0.33]],
    }
    out = s.merge(uncertain, certain)
    # The more certain fork (B in the call order) is selected.
    assert out["last_action"] == "request_think"
    assert out["selected_fork_entropy"] < out["discarded_fork_entropy"]


def test_planning_merge_warning_set_when_forks_diverge():
    s = PlanningMergeStrategy(warning_threshold=0.2)
    certain = {"posterior": [[0.98, 0.02]]}
    uncertain = {"posterior": [[0.5, 0.5]]}  # entropy 1.0 vs ~0.14
    out = s.merge(certain, uncertain)
    assert out.get("planning.merge_warning") is True


def test_planning_merge_no_warning_when_forks_agree():
    s = PlanningMergeStrategy(warning_threshold=0.2)
    a = {"posterior": [[0.9, 0.1]]}
    b = {"posterior": [[0.88, 0.12]]}
    out = s.merge(a, b)
    assert "planning.merge_warning" not in out


def test_planning_no_restart_or_pending_fields():
    # NARS-era fields are gone.
    s = PlanningMergeStrategy()
    out = s.merge({"posterior": [[1.0, 0.0]]}, {"posterior": [[0.5, 0.5]]})
    assert "restart_count" not in out
    assert "pending_revision" not in out


def test_planning_one_parent_missing():
    s = PlanningMergeStrategy()
    out = s.merge({"posterior": [[1.0, 0.0]]}, None)
    assert out == {"posterior": [[1.0, 0.0]]}


# ---- Self-model ----


def test_self_model_dedups_values_orders_history_and_sums_drift():
    s = SelfModelMergeStrategy()
    out = s.merge(
        {
            "values": ["honesty", "curiosity"],
            "behavioral_norms": ["be kind"],
            "internal_speech_count": 10,
            "identity_history": [{"event": "born"}],
            "drift_count": 1,
            "personality_baseline": {"openness": 0.8},
        },
        {
            "values": ["curiosity", "patience"],
            "behavioral_norms": ["be kind", "be precise"],
            "internal_speech_count": 4,
            "identity_history": [{"event": "first conversation"}],
            "drift_count": 2,
            "personality_baseline": {"openness": 0.4},
        },
    )
    assert out["values"] == ["honesty", "curiosity", "patience"]
    assert out["behavioral_norms"] == ["be kind", "be precise"]
    assert out["internal_speech_count"] == 14
    assert out["drift_count"] == 3
    assert out["personality_baseline"]["openness"] == pytest.approx(0.6)
    assert out["identity_history"][0]["source"] == "fork-a"
    assert out["identity_history"][1]["source"] == "fork-b"


def test_self_model_baseline_one_sided():
    s = SelfModelMergeStrategy()
    out = s.merge(
        {"values": [], "personality_baseline": {"x": 0.9}},
        {"values": []},
    )
    assert out["personality_baseline"] == {"x": 0.9}


# ---- Affect ----


def test_affect_averages_dim_max_drives_unions_goals():
    s = AffectMergeStrategy()
    out = s.merge(
        {
            "dimensional": {"valence": 0.4, "arousal": 0.2},
            "drives": {"curiosity": 0.8, "boredom": 0.1},
            "goals": [{"id": "g1", "priority": 1.0}],
            "emotional_history": [{"emotion": "joy"}],
        },
        {
            "dimensional": {"valence": -0.2, "arousal": 0.6, "dominance": 0.1},
            "drives": {"curiosity": 0.3, "restlessness": 0.5},
            "goals": [{"id": "g1", "priority": 0.5}, {"id": "g2", "priority": 0.9}],
            "emotional_history": [{"emotion": "anger"}],
        },
    )
    assert out["dimensional"]["valence"] == pytest.approx(0.1)
    assert out["dimensional"]["arousal"] == pytest.approx(0.4)
    assert out["dimensional"]["dominance"] == pytest.approx(0.05)
    assert out["drives"]["curiosity"] == 0.8
    assert out["drives"]["boredom"] == 0.1
    assert out["drives"]["restlessness"] == 0.5
    # g1 deduplicated; first occurrence (fork-a) wins
    ids = [g["id"] for g in out["goals"]]
    assert ids == ["g1", "g2"]
    assert out["goals"][0]["source"] == "fork-a"
    assert out["goals"][1]["source"] == "fork-b"
    assert {h["source"] for h in out["emotional_history"]} == {"fork-a", "fork-b"}


# ---- default_strategies ----


def test_default_strategies_present():
    strats = default_strategies()
    assert set(strats) == {"episodic_memory", "planning", "self_model", "affect", "social_cognition"}
