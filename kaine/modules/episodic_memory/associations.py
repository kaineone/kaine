# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Rules of associative replay for the KAINE episodic memory module.

This module implements the rules from Appendix A.10 of the KAINE paper.

After downscaling, each sleep co-replays at most ``n_pair`` pairs, most similar
first, of a replayed trace and one stored before the wake, with
``sim_min <= sim < sim_dup`` (cosine similarity). Each co-replay halves the
distance from 1 of the pair's link weight ``w``, which is 0 before the first
co-replay. Downscaling scales ``w`` as it scales a trace's strength. A trace with
at least ``n_sch`` links forms a schema node: the centroid of its own and its
partners' embeddings, with their mean link weight as strength. Each trace keeps
at most ``n_link`` links, the weakest going first.

Default parameter values (Table A1): ``n_pair`` 5, ``sim_min`` 0.5,
``sim_dup`` 0.95, ``n_sch`` 3, ``n_link`` 8.

Strengths and weights are stored as a ``log_base``. The current value is
``exp(min(0, log_base + log_gain))``, where ``log_gain`` is the store's shared
log gain that every downscaling lowers. A downscaling therefore scales every
weight without touching the records.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

LINK_NAMESPACE: uuid.UUID = uuid.UUID("3d6f1b2a-8c4e-4f7a-9b1d-2e5c7a9f0b13")
NODE_NAMESPACE: uuid.UUID = uuid.UUID("9a2e4c6b-1f3d-4b8a-a7c5-6d0e2f4b8c91")


def point_key(point_id: Any) -> str:
    """Return the canonical key for a point identifier.

    If ``str(point_id)`` parses as a UUID, the UUID hex form is returned.
    Otherwise the string form itself is returned.
    """
    s = str(point_id)
    try:
        return uuid.UUID(s).hex
    except ValueError:
        return s


def trace_ref(kind: str, point_id: Any) -> str:
    """Return a trace reference of the form ``kind:point_key``."""
    if not kind or ":" in kind:
        raise ValueError("kind must be non-empty and must not contain ':'")
    key = point_key(point_id)
    if not key:
        raise ValueError("point_key must be non-empty")
    return f"{kind}:{key}"


def split_ref(ref: str) -> tuple[str, str]:
    """Split a trace reference on the first ':' into (kind, key)."""
    if ":" not in ref:
        raise ValueError("ref must contain ':'")
    kind, key = ref.split(":", 1)
    if not kind or not key:
        raise ValueError("kind and key must be non-empty")
    return kind, key


def link_id(ref_a: str, ref_b: str) -> str:
    """Return the deterministic id for a pair of trace refs."""
    if ref_a == ref_b:
        raise ValueError("cannot link a trace to itself")
    joined = "|".join(sorted((ref_a, ref_b)))
    return uuid.uuid5(LINK_NAMESPACE, joined).hex


def node_id(center: str) -> str:
    """Return the deterministic id for a schema node centered on ``center``."""
    return uuid.uuid5(NODE_NAMESPACE, center).hex


def weight(log_base: float, log_gain: float) -> float:
    """Return the current weight value for a stored log base and log gain."""
    x = log_base + log_gain
    if not math.isfinite(x):
        raise ValueError("log_base + log_gain must be finite")
    return math.exp(min(0.0, x))


def log_base_for(value: float, log_gain: float) -> float:
    """Return the log_base that yields ``value`` under the given log_gain."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("value must be a number")
    if not math.isfinite(value) or value <= 0.0 or value > 1.0:
        raise ValueError("value must be finite, greater than 0 and at most 1")
    return math.log(value) - log_gain


def co_replayed_weight(w: float) -> float:
    """Return the new weight after a co-replay halves its distance from 1."""
    if isinstance(w, bool) or not isinstance(w, (int, float)):
        raise ValueError("weight must be a number")
    if w < 0.0 or w > 1.0:
        raise ValueError("weight must be between 0 and 1 inclusive")
    return (1.0 + w) / 2.0


def node_log_base(link_log_bases: Sequence[float], log_gain: float) -> float:
    """Return the log_base for a node from the log bases of its links."""
    if not link_log_bases:
        raise ValueError("link_log_bases must not be empty")
    mean = sum(weight(lb, log_gain) for lb in link_log_bases) / len(link_log_bases)
    return log_base_for(mean, log_gain)


def mean_vector(vectors: Sequence[Sequence[float]]) -> list[float]:
    """Return the elementwise mean of a sequence of equal-length vectors."""
    if not vectors:
        raise ValueError("vectors must not be empty")
    dim = len(vectors[0])
    if any(len(v) != dim for v in vectors):
        raise ValueError("all vectors must have the same length")
    n = len(vectors)
    return [sum(v[i] for v in vectors) / n for i in range(dim)]


def select_pairs(
    candidates: Iterable[tuple[str, str, float]],
    n_pair: int,
) -> list[tuple[str, str, float]]:
    """Select up to ``n_pair`` co-replay pairs from ``candidates``.

    Each candidate is ``(q_ref, old_ref, sim)``. For each unordered pair the
    candidate with the highest similarity is kept. Results are sorted by
    similarity descending, then ``q_ref`` ascending, then ``old_ref`` ascending.
    """
    if n_pair < 0:
        raise ValueError("n_pair must be non-negative")
    best: dict[tuple[str, str], tuple[str, str, float]] = {}
    for q_ref, old_ref, sim in candidates:
        key = tuple(sorted((q_ref, old_ref)))
        current = best.get(key)
        if current is None or sim > current[2]:
            best[key] = (q_ref, old_ref, sim)
    ordered = sorted(best.values(), key=lambda t: (-t[2], t[0], t[1]))
    return ordered[:n_pair]


def _is_int_not_bool(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number_not_bool(value: Any) -> bool:
    return (isinstance(value, (int, float))) and not isinstance(value, bool)


@dataclass(frozen=True)
class AssociationParams:
    """Hyper-parameters for associative replay."""

    n_pair: int = 5
    sim_min: float = 0.5
    sim_dup: float = 0.95
    n_sch: int = 3
    n_link: int = 8

    def __post_init__(self) -> None:
        if not _is_int_not_bool(self.n_pair) or self.n_pair < 1:
            raise ValueError("n_pair must be an int >= 1")
        if not _is_int_not_bool(self.n_sch) or self.n_sch < 1:
            raise ValueError("n_sch must be an int >= 1")
        if not _is_int_not_bool(self.n_link) or self.n_link < 1:
            raise ValueError("n_link must be an int >= 1")

        if not _is_number_not_bool(self.sim_min) or not math.isfinite(self.sim_min):
            raise ValueError("sim_min must be a finite number")
        if not _is_number_not_bool(self.sim_dup) or not math.isfinite(self.sim_dup):
            raise ValueError("sim_dup must be a finite number")
        if not -1.0 <= self.sim_min < self.sim_dup <= 1.0:
            raise ValueError("sim_min and sim_dup must satisfy "
                             "-1.0 <= sim_min < sim_dup <= 1.0")


@dataclass(frozen=True)
class Link:
    """An associative link between two traces."""

    id: str
    raw_id: str
    a: str
    b: str
    log_base: float
    entity_time: float
    size_bytes: int

    def other(self, ref: str) -> str:
        """Return the partner reference opposite ``ref``."""
        if ref == self.a:
            return self.b
        if ref == self.b:
            return self.a
        raise ValueError("ref is not a member of this link")

    def payload(self) -> dict[str, Any]:
        """Return the storage payload for this link."""
        return {
            "a": self.a,
            "b": self.b,
            "log_base": self.log_base,
            "entity_time": self.entity_time,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class Node:
    """A schema node centered on a trace."""

    id: str
    raw_id: str
    center: str
    log_base: float
    entity_time: float
    size_bytes: int

    def payload(self) -> dict[str, Any]:
        """Return the storage payload for this node."""
        return {
            "center": self.center,
            "log_base": self.log_base,
            "entity_time": self.entity_time,
            "size_bytes": self.size_bytes,
        }


def _require_finite_float(value: Any, name: str, point_id: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number in point {point_id!r}")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite in point {point_id!r}")
    return float(value)


def _require_nonnegative_int(value: Any, name: str, point_id: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an int in point {point_id!r}")
    if value < 0:
        raise ValueError(f"{name} must be non-negative in point {point_id!r}")
    return int(value)


def link_from_point(point: dict[str, Any]) -> Link:
    """Build a ``Link`` from a storage point dict."""
    try:
        raw_id = str(point["id"])
        payload = point["payload"]
        a = payload["a"]
        b = payload["b"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Invalid link point: {exc}") from exc

    if not isinstance(a, str) or not isinstance(b, str):
        raise ValueError(f"Link point {raw_id!r} has invalid refs")
    try:
        split_ref(a)
        split_ref(b)
    except ValueError as exc:
        raise ValueError(f"Link point {raw_id!r} has invalid ref: {exc}") from exc
    if a == b:
        raise ValueError(f"Link point {raw_id!r} links a trace to itself")

    try:
        log_base = _require_finite_float(payload["log_base"], "log_base", raw_id)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Link point {raw_id!r} has invalid log_base: {exc}") from exc

    try:
        entity_time = payload.get("entity_time", 0.0)
    except (KeyError, TypeError, AttributeError):
        entity_time = 0.0
    entity_time = _require_finite_float(entity_time, "entity_time", raw_id)

    try:
        size_bytes = _require_nonnegative_int(payload["size_bytes"], "size_bytes", raw_id)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Link point {raw_id!r} has invalid size_bytes: {exc}") from exc

    a, b = sorted((a, b))
    expected_id = link_id(a, b)
    if point_key(point["id"]) != expected_id:
        raise ValueError(
            f"Link point {raw_id!r} id does not match link_id({a!r}, {b!r})"
        )

    return Link(
        id=expected_id,
        raw_id=raw_id,
        a=a,
        b=b,
        log_base=log_base,
        entity_time=entity_time,
        size_bytes=size_bytes,
    )


def node_from_point(point: dict[str, Any]) -> Node:
    """Build a ``Node`` from a storage point dict."""
    try:
        raw_id = str(point["id"])
        payload = point["payload"]
        center = payload["center"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Invalid node point: {exc}") from exc

    if not isinstance(center, str):
        raise ValueError(f"Node point {raw_id!r} has invalid center")
    try:
        split_ref(center)
    except ValueError as exc:
        raise ValueError(f"Node point {raw_id!r} has invalid center: {exc}") from exc

    try:
        log_base = _require_finite_float(payload["log_base"], "log_base", raw_id)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Node point {raw_id!r} has invalid log_base: {exc}") from exc

    try:
        entity_time = payload.get("entity_time", 0.0)
    except (KeyError, TypeError, AttributeError):
        entity_time = 0.0
    entity_time = _require_finite_float(entity_time, "entity_time", raw_id)

    try:
        size_bytes = _require_nonnegative_int(payload["size_bytes"], "size_bytes", raw_id)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Node point {raw_id!r} has invalid size_bytes: {exc}") from exc

    expected_id = node_id(center)
    if point_key(point["id"]) != expected_id:
        raise ValueError(
            f"Node point {raw_id!r} id does not match node_id({center!r})"
        )

    return Node(
        id=expected_id,
        raw_id=raw_id,
        center=center,
        log_base=log_base,
        entity_time=entity_time,
        size_bytes=size_bytes,
    )


class AssociationIndex:
    """In-process index of a store's links and schema nodes."""

    def __init__(self) -> None:
        self.links: dict[str, Link] = {}
        self.nodes: dict[str, Node] = {}
        self._adj: dict[str, set[str]] = {}
        self._node_id_to_center: dict[str, str] = {}

    def __bool__(self) -> bool:
        return bool(self.links) or bool(self.nodes)

    def add_link(self, link: Link) -> None:
        """Add or replace a link in the index."""
        if link.id in self.links:
            self.remove_link(link.id)
        self.links[link.id] = link
        for ref in (link.a, link.b):
            self._adj.setdefault(ref, set()).add(link.id)

    def remove_link(self, link_id: str) -> Link | None:
        """Remove a link and return it, or return None if absent."""
        link = self.links.pop(link_id, None)
        if link is None:
            return None
        for ref in (link.a, link.b):
            adj = self._adj.get(ref)
            if adj is not None:
                adj.discard(link_id)
                if not adj:
                    del self._adj[ref]
        return link

    def links_of(self, ref: str) -> list[Link]:
        """Return all links incident to ``ref``, sorted by link id."""
        link_ids = self._adj.get(ref, ())
        return sorted((self.links[lid] for lid in link_ids), key=lambda link: link.id)

    def degree(self, ref: str) -> int:
        """Return the number of links incident to ``ref``."""
        return len(self._adj.get(ref, ()))

    def partners(self, ref: str) -> list[str]:
        """Return the partner refs of all links incident to ``ref``.

        Ordered by link log_base descending, then entity_time descending, then
        partner ref ascending.
        """
        links = self.links_of(ref)

        def key(link: Link) -> tuple[float, float, str]:
            other = link.other(ref)
            return (-link.log_base, -link.entity_time, other)

        return [link.other(ref) for link in sorted(links, key=key)]

    def weakest_excess(self, ref: str, n_link: int) -> list[Link]:
        """Return the weakest links to drop so that ``ref`` keeps ``n_link``."""
        degree = self.degree(ref)
        excess = max(0, degree - n_link)
        links = self.links_of(ref)
        ordered = sorted(links, key=lambda link: (link.log_base, link.entity_time, link.id))
        return ordered[:excess]

    def set_node(self, node: Node) -> None:
        """Add or replace a node in the index."""
        self.nodes[node.center] = node
        self._node_id_to_center[node.id] = node.center

    def remove_node(self, center: str) -> Node | None:
        """Remove the node centered on ``center`` and return it."""
        node = self.nodes.pop(center, None)
        if node is not None:
            self._node_id_to_center.pop(node.id, None)
        return node

    def node_of(self, center: str) -> Node | None:
        """Return the node centered on ``center``."""
        return self.nodes.get(center)

    def node_by_id(self, node_id: str) -> Node | None:
        """Return the node whose canonical id matches ``node_id``."""
        center = self._node_id_to_center.get(point_key(node_id))
        if center is None:
            return None
        return self.nodes.get(center)

    @classmethod
    def from_points(
        cls,
        link_points: Iterable[dict[str, Any]],
        node_points: Iterable[dict[str, Any]],
    ) -> "AssociationIndex":
        """Build an index from storage point dicts."""
        index = cls()
        for point in link_points:
            index.add_link(link_from_point(point))
        for point in node_points:
            index.set_node(node_from_point(point))
        return index


def cap_links(index: AssociationIndex, refs: Iterable[str], n_link: int) -> list[Link]:
    """Cap each ref in ``refs`` to at most ``n_link`` weakest-first.

    Removed links are returned in the order they were removed. A single pass
    over the refs is sufficient because removing a link only lowers degrees.
    """
    removed: list[Link] = []
    for ref in sorted(set(refs)):
        for link in index.weakest_excess(ref, n_link):
            index.remove_link(link.id)
            removed.append(link)
    return removed
