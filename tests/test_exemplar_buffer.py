# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for ExemplarBuffer and the perceptual identity fields on AgentModel."""
from __future__ import annotations

import math

import pytest

from kaine.modules.social_cognition.agent import EMOTION_CATEGORIES, AgentModel
from kaine.modules.social_cognition.exemplar_buffer import ExemplarBuffer

DIM = 16


def _vec(dim: int, seed: float = 1.0) -> list[float]:
    raw = [math.sin(seed * (i + 1)) for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw] if norm > 0 else raw


def _basis(dim: int, k: int) -> list[float]:
    v = [0.0] * dim
    v[k] = 1.0
    return v


def _diverse_buffer(**kw) -> ExemplarBuffer:
    buf = ExemplarBuffer(DIM, **kw)
    for s in (1.0, 2.3, 3.7, 5.1, 7.9):
        buf.add(_vec(DIM, s))
    return buf


# ---------------------------------------------------------------------------
# ExemplarBuffer
# ---------------------------------------------------------------------------


def test_empty_buffer_returns_zero_match():
    buf = ExemplarBuffer(DIM)
    assert buf.match(_vec(DIM, 1.0)) == 0.0
    assert buf.count == 0
    assert buf.centroid is None


def test_add_increments_count():
    buf = ExemplarBuffer(DIM)
    for i in range(3):
        buf.add(_vec(DIM, 1.0 + i))
        assert buf.count == i + 1


def test_buffer_respects_max_size():
    buf = ExemplarBuffer(DIM, max_size=4)
    for i in range(10):
        buf.add(_vec(DIM, 1.0 + i * 0.7))
    assert buf.count == 4


def test_match_finds_exact_embedding():
    buf = ExemplarBuffer(DIM)
    v = _vec(DIM, 2.0)
    buf.add(v)
    assert buf.match(v) == pytest.approx(1.0)


def test_not_consolidated_below_threshold():
    buf = ExemplarBuffer(DIM, consolidation_threshold=5)
    for s in (1.0, 2.3, 3.7, 5.1):
        buf.add(_vec(DIM, s))
    assert not buf.consolidated


def test_consolidation_triggers_on_threshold():
    buf = _diverse_buffer(consolidation_threshold=5)
    assert buf.consolidated


def test_consolidation_needs_diversity():
    buf = ExemplarBuffer(DIM, consolidation_threshold=5, diversity_floor=0.01)
    v = _vec(DIM, 1.0)
    for _ in range(8):
        buf.add(v)
    assert not buf.consolidated


def test_match_uses_centroid_after_consolidation():
    buf = _diverse_buffer()
    assert buf.consolidated
    c = buf.centroid
    assert c is not None
    # Centroid matches itself perfectly, which no single exemplar would.
    assert buf.match(c) == pytest.approx(1.0)
    best_single = max(
        buf.match(e) for e in [_vec(DIM, s) for s in (1.0, 2.3, 3.7, 5.1, 7.9)]
    )
    assert best_single <= 1.0 + 1e-9


def test_eviction_removes_most_redundant():
    buf = ExemplarBuffer(DIM, max_size=3, consolidation_threshold=100)
    e0, e1 = _basis(DIM, 0), _basis(DIM, 1)
    buf.add(e0)
    buf.add(e0)
    buf.add(e1)
    buf.add(_basis(DIM, 2))
    assert buf.count == 3
    stored = [item["embedding"] for item in buf.to_dict()["exemplars"]]
    # One of the duplicate e0 copies (closest to the mean) was evicted.
    assert stored.count(e0) == 1
    assert e1 in stored
    assert _basis(DIM, 2) in stored


def test_reliability_floor_below_two_exemplars():
    buf = ExemplarBuffer(DIM, reliability_floor=0.3)
    assert buf.reliability() == 0.3
    buf.add(_vec(DIM, 1.0))
    assert buf.reliability() == 0.3


def test_reliability_increases_with_clustering():
    tight = ExemplarBuffer(DIM, consolidation_threshold=100)
    base = _vec(DIM, 1.0)
    for k in range(4):
        v = list(base)
        v[k] += 0.01
        tight.add(v)
    loose = ExemplarBuffer(DIM, consolidation_threshold=100)
    for s in (1.0, 2.3, 3.7, 5.1):
        loose.add(_vec(DIM, s))
    assert tight.reliability() > loose.reliability()


def test_reliability_bounded_zero_one():
    for seeds in [(1.0, 1.0), (1.0, 2.3, 3.7), (1.0, 9.9, 4.4, 0.3)]:
        buf = ExemplarBuffer(DIM, consolidation_threshold=100)
        for s in seeds:
            buf.add(_vec(DIM, s))
        assert 0.0 <= buf.reliability() <= 1.0


def test_to_dict_from_dict_roundtrip():
    buf = ExemplarBuffer(DIM, max_size=7, consolidation_threshold=3)
    for i, s in enumerate((1.0, 2.3, 3.7)):
        buf.add(_vec(DIM, s), timestamp=100.0 + i)
    d = buf.to_dict()
    restored = ExemplarBuffer.from_dict(d)
    assert restored.to_dict() == d
    assert restored.count == buf.count
    assert restored.max_size == 7
    assert restored.match(_vec(DIM, 2.3)) == pytest.approx(buf.match(_vec(DIM, 2.3)))


def test_from_dict_preserves_consolidation_state():
    buf = _diverse_buffer()
    assert buf.consolidated
    restored = ExemplarBuffer.from_dict(buf.to_dict())
    assert restored.consolidated
    assert restored.centroid == pytest.approx(buf.centroid)

    fresh = ExemplarBuffer.from_dict(ExemplarBuffer(DIM).to_dict())
    assert not fresh.consolidated


# ---------------------------------------------------------------------------
# AgentModel identity fields
# ---------------------------------------------------------------------------


def test_agent_model_identity_fields_default_none():
    m = AgentModel(id="a", label="a")
    assert m.voice_centroid is None
    assert m.face_centroid is None
    assert m.voice_exemplars == []
    assert m.face_exemplars == []
    assert m.voice_sample_count == 0
    assert m.face_sample_count == 0
    assert m.binding_state == "unbound"
    assert m.binding_confidence is None
    assert m.voice_reliability is None
    assert m.face_reliability is None
    assert m.voice_acoustic_embedding is None


def test_agent_model_familiarity_unchanged_without_perceptual():
    from kaine.modules.social_cognition import agent as agent_mod

    m = AgentModel(id="a", label="a")
    m.interaction_count = 7
    m.emotion_histogram[EMOTION_CATEGORIES[0]] = 2.0
    count_score = 1.0 - math.exp(-7 / agent_mod._COUNT_SCALE)
    coverage = 1 / len(EMOTION_CATEGORIES)
    assert m.familiarity() == (count_score + coverage) / 2.0


def test_agent_model_familiarity_higher_with_perceptual():
    base = AgentModel(id="a", label="a")
    base.interaction_count = 3
    withp = AgentModel(id="b", label="b")
    withp.interaction_count = 3
    withp.voice_centroid = _vec(8, 1.0)
    withp.voice_sample_count = 20
    withp.voice_reliability = 0.95
    assert withp.familiarity() > base.familiarity()


def test_agent_model_serialization_roundtrip_with_identity():
    m = AgentModel(id="a", label="a")
    m.voice_centroid = _vec(8, 1.0)
    m.face_centroid = _vec(8, 2.0)
    m.voice_exemplars = [{"embedding": _vec(8, 1.0), "timestamp": 1.0}]
    m.face_exemplars = [{"embedding": _vec(8, 2.0), "timestamp": 2.0}]
    m.voice_sample_count = 4
    m.face_sample_count = 5
    m.binding_state = "bound"
    m.binding_confidence = 0.8
    m.voice_reliability = 0.7
    m.face_reliability = 0.6
    m.voice_acoustic_embedding = [0.1, 0.2]
    r = AgentModel.from_dict(m.to_dict())
    assert r.to_dict() == m.to_dict()
    assert r.binding_state == "bound"
    assert r.binding_confidence == 0.8
    assert r.voice_sample_count == 4


def test_agent_model_backwards_compat_deserialization():
    legacy = {
        "id": "old",
        "interaction_count": 3,
        "first_seen": 1.0,
        "last_seen": 2.0,
    }
    m = AgentModel.from_dict(legacy)
    assert m.id == "old"
    assert m.voice_centroid is None
    assert m.face_centroid is None
    assert m.voice_exemplars == []
    assert m.binding_state == "unbound"
    assert m.binding_confidence is None
    assert m.voice_reliability is None
