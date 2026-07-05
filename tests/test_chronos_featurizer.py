# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.chronos.featurizer import (
    DEFAULT_FEATURE_DIM,
    DEFAULT_KNOWN_SOURCES,
    SnapshotFeaturizer,
)


def _event(source: str, salience: float, etype: str = "t.x") -> Event:
    return Event(
        source=source,
        type=etype,
        payload={"k": "v"},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _snapshot(events=None, *, inhibited=False, is_experiential=True, tick=0):
    return WorkspaceSnapshot(
        tick_index=tick,
        selected_events=[("e", e) for e in (events or [])],
        inhibited=inhibited,
        is_experiential=is_experiential,
    )


def test_feature_vec_has_documented_dimensionality():
    feat = SnapshotFeaturizer(clock=lambda: 0.0)
    snap = _snapshot([_event("soma", 0.5)])
    vec = feat.featurize(snap)
    assert len(vec) == DEFAULT_FEATURE_DIM == 24


def test_featurizer_is_deterministic_for_same_snapshot():
    snap = _snapshot([_event("soma", 0.5)], inhibited=False)
    feat_a = SnapshotFeaturizer(clock=lambda: 1.0)
    feat_b = SnapshotFeaturizer(clock=lambda: 1.0)
    assert feat_a.featurize(snap) == feat_b.featurize(snap)


def test_inhibited_bit_distinguishes_snapshots():
    feat = SnapshotFeaturizer(clock=lambda: 0.0)
    a = feat.featurize(_snapshot([_event("soma", 0.5)], inhibited=False))
    feat2 = SnapshotFeaturizer(clock=lambda: 0.0)
    b = feat2.featurize(_snapshot([_event("soma", 0.5)], inhibited=True))
    assert a != b
    assert a[21] == 0.0 and b[21] == 1.0


def test_experiential_bit_distinguishes():
    feat = SnapshotFeaturizer(clock=lambda: 0.0)
    a = feat.featurize(_snapshot([_event("soma", 0.5)], is_experiential=True))
    feat2 = SnapshotFeaturizer(clock=lambda: 0.0)
    b = feat2.featurize(_snapshot([_event("soma", 0.5)], is_experiential=False))
    assert a[22] != b[22]


def test_source_onehot_accumulates_salience():
    feat = SnapshotFeaturizer(clock=lambda: 0.0)
    snap = _snapshot(
        [_event("soma", 0.4), _event("soma", 0.3), _event("nous", 0.6)]
    )
    vec = feat.featurize(snap)
    soma_idx = DEFAULT_KNOWN_SOURCES.index("soma")
    nous_idx = DEFAULT_KNOWN_SOURCES.index("nous")
    assert vec[4 + soma_idx] == 0.7
    assert vec[4 + nous_idx] == 0.6


def test_unknown_source_lands_in_overflow_bucket():
    feat = SnapshotFeaturizer(clock=lambda: 0.0)
    snap = _snapshot([_event("strangermod", 0.8)])
    vec = feat.featurize(snap)
    overflow_idx = 4 + 7  # last source bucket
    assert vec[overflow_idx] == 0.8


def test_delta_time_log_scaled():
    times = iter([1000.0, 1001.5, 1031.5])
    feat = SnapshotFeaturizer(clock=lambda: next(times))
    snap = _snapshot([_event("soma", 0.5)])
    vec0 = feat.featurize(snap)
    vec1 = feat.featurize(snap)
    vec2 = feat.featurize(snap)
    # First call has no prior, delta = 0
    assert vec0[20] == 0.0
    # Second call after 1.5s: log1p(1.5) ≈ 0.916
    assert 0.9 < vec1[20] < 1.0
    # Third call after 30s: log1p(30) ≈ 3.43
    assert 3.4 < vec2[20] < 3.5


def test_empty_snapshot_safe():
    feat = SnapshotFeaturizer(clock=lambda: 0.0)
    vec = feat.featurize(_snapshot([], inhibited=True))
    assert len(vec) == DEFAULT_FEATURE_DIM
    assert vec[0] == 0.0
    assert vec[21] == 1.0  # inhibited bit


# ---------------------------------------------------------------------------
# L1: reserved slot [23] — permanently zero (documented cost, not removed)
# ---------------------------------------------------------------------------


def test_reserved_slot_23_is_always_zero():
    """Slot [23] is a permanently-zero reserved slot.

    The CfC and forward-prediction models have been trained with this slot
    always zero; introducing a real feature here requires a full model retrain.
    This test guards that invariant so no accidental population goes unnoticed.
    """
    feat = SnapshotFeaturizer(clock=lambda: 0.0)
    for snap in [
        _snapshot([]),
        _snapshot([_event("soma", 0.5)]),
        _snapshot([_event("nous", 0.9), _event("thymos", 0.3)], inhibited=True),
        _snapshot([_event("chronos", 1.0)], is_experiential=False),
    ]:
        vec = feat.featurize(snap)
        assert vec[23] == 0.0, (
            f"slot [23] must be permanently 0.0 — introducing a real feature "
            f"here requires a model-weight reset (see featurizer.py comment)"
        )


def test_feature_dim_unchanged():
    """Feature dim must remain 24 (no accidental slot removal)."""
    feat = SnapshotFeaturizer(clock=lambda: 0.0)
    vec = feat.featurize(_snapshot([_event("soma", 0.5)]))
    assert len(vec) == 24
    assert DEFAULT_FEATURE_DIM == 24
