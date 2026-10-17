# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the KAINE episodic memory associative replay rules."""

from __future__ import annotations

import dataclasses
import math
import uuid

import pytest

from kaine.modules.episodic_memory.associations import (
    LINK_NAMESPACE,
    NODE_NAMESPACE,
    AssociationIndex,
    AssociationParams,
    Link,
    Node,
    cap_links,
    co_replayed_weight,
    link_from_point,
    link_id,
    log_base_for,
    mean_vector,
    node_from_point,
    node_id,
    node_log_base,
    select_pairs,
    split_ref,
    trace_ref,
    weight,
)


def test_co_replayed_weight_halves_distance_from_one():
    w = 0.0
    for expected in (0.5, 0.75, 0.875):
        w = co_replayed_weight(w)
        assert w == pytest.approx(expected)
    with pytest.raises(ValueError):
        co_replayed_weight(-0.1)
    with pytest.raises(ValueError):
        co_replayed_weight(1.1)


def test_weight_and_log_base_roundtrip_and_downscaling():
    gain = -0.3
    lb = log_base_for(0.5, gain)
    assert weight(lb, gain) == pytest.approx(0.5)

    lb_at_zero_gain = log_base_for(0.5, 0.0)
    assert weight(lb_at_zero_gain, math.log(0.8)) == pytest.approx(0.4)
    assert weight(100.0, 0.0) == pytest.approx(1.0)
    assert weight(0.0, 0.0) == pytest.approx(1.0)


def test_link_and_ref_helpers():
    a, b, c = "episodic:aaa", "episodic:bbb", "episodic:ccc"
    assert link_id(a, b) == link_id(b, a)
    assert link_id(a, b) != link_id(a, c)
    with pytest.raises(ValueError):
        link_id(a, a)

    uid = uuid.uuid4()
    hyphenated = str(uid)
    ref = trace_ref("episodic", hyphenated)
    assert ref == f"episodic:{uid.hex}"
    kind, key = split_ref(ref)
    assert kind == "episodic"
    assert key == uid.hex
    with pytest.raises(ValueError):
        split_ref("nocolon")


def test_select_pairs():
    candidates = [
        ("q1", "o1", 0.6),
        ("q1", "o1", 0.7),
        ("q2", "o1", 0.9),
        ("q1", "o2", 0.8),
        ("q1", "o2", 0.85),
    ]
    result = select_pairs(candidates, 2)
    assert result == [("q2", "o1", 0.9), ("q1", "o2", 0.85)]

    with pytest.raises(ValueError):
        select_pairs([], -1)


def test_mean_vector():
    assert mean_vector([[1.0, 0.0], [0.0, 1.0]]) == [0.5, 0.5]
    with pytest.raises(ValueError):
        mean_vector([])
    with pytest.raises(ValueError):
        mean_vector([[1.0, 0.0], [1.0]])


def test_node_log_base():
    gain = -0.2
    lb_half = log_base_for(0.5, gain)
    lb_full = log_base_for(1.0, gain)
    node_lb = node_log_base([lb_half, lb_full], gain)
    assert weight(node_lb, gain) == pytest.approx(0.75)


def test_association_index():
    c = "episodic:center"
    p1, p2, p3 = "episodic:p1", "episodic:p2", "episodic:p3"

    def make_link(a: str, b: str, lb: float, time: float) -> Link:
        a, b = sorted((a, b))
        return Link(
            id=link_id(a, b),
            raw_id=link_id(a, b),
            a=a,
            b=b,
            log_base=lb,
            entity_time=time,
            size_bytes=1,
        )

    idx = AssociationIndex()
    idx.add_link(make_link(c, p1, 0.0, 1.0))
    idx.add_link(make_link(c, p2, -0.7, 2.0))
    idx.add_link(make_link(c, p3, -1.4, 3.0))

    assert idx.degree(c) == 3
    assert idx.partners(c) == [p1, p2, p3]

    # Replacing a link with the same id keeps the degree.
    idx.add_link(make_link(c, p1, -0.1, 4.0))
    assert idx.degree(c) == 3
    assert idx.partners(c) == [p1, p2, p3]

    # Removing a link drops adjacency on both sides.
    removed = idx.remove_link(link_id(c, p1))
    assert removed is not None
    assert idx.degree(c) == 2
    assert idx.degree(p1) == 0

    # Re-add p1 for the cap test.
    idx.add_link(make_link(c, p1, 0.0, 1.0))
    dropped = cap_links(idx, [c], 2)
    assert len(dropped) == 1
    assert dropped[0].other(c) == p3
    assert idx.degree(c) == 2
    assert idx.degree(p3) == 0

    # On equal log_base, the older entity_time goes first.
    idx2 = AssociationIndex()
    idx2.add_link(make_link(c, p1, 1.0, 1.0))
    idx2.add_link(make_link(c, p2, 1.0, 2.0))
    excess = idx2.weakest_excess(c, 1)
    assert len(excess) == 1
    assert excess[0].other(c) == p1


def test_link_from_point_roundtrip_and_validation():
    a, b = "episodic:a", "episodic:b"
    link = Link(
        id=link_id(a, b),
        raw_id=link_id(a, b),
        a=a,
        b=b,
        log_base=log_base_for(0.5, 0.0),
        entity_time=1.0,
        size_bytes=4,
    )
    point = {"id": link.raw_id, "payload": link.payload()}
    assert link_from_point(point) == link

    hyphenated = {"id": str(uuid.UUID(link.id)), "payload": link.payload()}
    # raw_id keeps the form the backend reported; the id is canonical.
    assert link_from_point(hyphenated) == dataclasses.replace(link, raw_id=hyphenated["id"])

    bad_id = {"id": str(uuid.uuid5(LINK_NAMESPACE, "other")), "payload": link.payload()}
    with pytest.raises(ValueError):
        link_from_point(bad_id)

    bad_log_base = {"id": link.raw_id, "payload": {**link.payload(), "log_base": True}}
    with pytest.raises(ValueError):
        link_from_point(bad_log_base)

    missing_size = {"id": link.raw_id, "payload": {k: v for k, v in link.payload().items() if k != "size_bytes"}}
    with pytest.raises(ValueError):
        link_from_point(missing_size)


def test_node_from_point_roundtrip_and_validation():
    center = "episodic:center"
    node = Node(
        id=node_id(center),
        raw_id=node_id(center),
        center=center,
        log_base=log_base_for(0.75, 0.0),
        entity_time=2.0,
        size_bytes=8,
    )
    point = {"id": node.raw_id, "payload": node.payload()}
    assert node_from_point(point) == node

    hyphenated = {"id": str(uuid.UUID(node.id)), "payload": node.payload()}
    assert node_from_point(hyphenated) == dataclasses.replace(node, raw_id=hyphenated["id"])

    bad_id = {"id": str(uuid.uuid5(NODE_NAMESPACE, "other")), "payload": node.payload()}
    with pytest.raises(ValueError):
        node_from_point(bad_id)


def test_association_params():
    defaults = AssociationParams()
    assert defaults.n_pair == 5
    assert defaults.sim_min == 0.5
    assert defaults.sim_dup == 0.95
    assert defaults.n_sch == 3
    assert defaults.n_link == 8

    with pytest.raises(ValueError):
        AssociationParams(n_pair=0)
    with pytest.raises(ValueError):
        AssociationParams(sim_min=0.95, sim_dup=0.5)
    with pytest.raises(ValueError):
        AssociationParams(n_link=True)
