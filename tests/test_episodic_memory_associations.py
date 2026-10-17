# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Associative replay for sleep, paper A.10."""

from __future__ import annotations

import math
import uuid
from pathlib import Path
from typing import Any

import pytest

from kaine.modules.episodic_memory import (
    EpisodicMemoryCore,
    FakeEmbedder,
    InMemoryStorage,
)
from kaine.modules.episodic_memory.associations import (
    AssociationParams,
    trace_ref,
)
from kaine.modules.episodic_memory.storage import (
    QdrantStorage,
    SqliteVecStorage,
)

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect")

DIM = 8


class _Clock:
    """Settable entity clock for tests."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = float(t)

    def __call__(self) -> float:
        return self.t


class _TableEmbedder(FakeEmbedder):
    """Fake embedder that looks up vectors from a table."""

    def __init__(self, table: dict[str, list[float]] | None = None) -> None:
        super().__init__(latent_dim=DIM)
        self.table: dict[str, list[float]] = dict(table or {})

    async def encode(self, text: str) -> list[float]:
        if text in self.table:
            return list(self.table[text])
        return await super().encode(text)


BACKENDS = ["inmemory", "sqlite_vec", "qdrant"]


async def _open_storage(kind: str, path: Path) -> Any:
    """Build and initialize one storage backend."""
    if kind == "inmemory":
        s = InMemoryStorage(latent_dim=DIM)
    elif kind == "sqlite_vec":
        pytest.importorskip("sqlite_vec")
        s = SqliteVecStorage(latent_dim=DIM, db_path=str(path / "m.db"))
    elif kind == "qdrant":
        qc = pytest.importorskip("qdrant_client")
        s = QdrantStorage(latent_dim=DIM, api_key="test")
        s._client = qc.AsyncQdrantClient(location=":memory:")
    else:
        raise ValueError(f"unknown backend {kind!r}")
    await s.initialize()
    return s


@pytest.fixture(params=BACKENDS)
async def storage(request, tmp_path):
    """Parametrized storage backend."""
    s = await _open_storage(request.param, tmp_path)
    yield s
    await s.shutdown()


async def _core(storage, *, embedder=None, clock=None, **kw) -> EpisodicMemoryCore:
    """Create and initialize a EpisodicMemoryCore over the given storage."""
    core = EpisodicMemoryCore(
        embedder or _TableEmbedder(),
        storage,
        entity_clock=clock or _Clock(),
        **kw,
    )
    await core.initialize()
    return core


def _flat(exported: dict) -> list:
    """Every exported point of every collection, in one list."""
    out = []
    for collection, points in exported.items():
        for p in points:
            p2 = dict(p)
            p2["collection"] = collection
            out.append(p2)
    return out


def _key(pid: Any) -> str:
    """Normalize a point id for comparison across backends."""
    try:
        return uuid.UUID(str(pid)).hex
    except ValueError:
        return str(pid)


async def _protect(core: EpisodicMemoryCore, texts: list[str]) -> list[tuple[str, str, float]]:
    """Build protect triples for the current wake matching the given texts."""
    pool = await core.wake_pool()
    return [
        (p["collection"], _key(p["id"]), float(p["payload"]["log_base"]))
        for p in pool
        if p["text"] in texts
    ]


def _unit(first: float, axis: int) -> list[float]:
    """Return a unit vector whose cosine with e0 is ``first``."""
    v = [0.0] * DIM
    v[0] = float(first)
    if axis != 0:
        v[axis] = math.sqrt(max(0.0, 1.0 - first * first))
    return v


def _mean(vectors: list[list[float]]) -> list[float]:
    """Elementwise mean of equal-length vectors."""
    if not vectors:
        return []
    dim = len(vectors[0])
    n = len(vectors)
    return [sum(v[i] for v in vectors) / n for i in range(dim)]


def _normalize(v: list[float]) -> list[float]:
    """Scale a vector to unit length."""
    norm = math.sqrt(sum(x * x for x in v))
    if norm == 0.0:
        return list(v)
    return [x / norm for x in v]


async def _protect_point(core: EpisodicMemoryCore, point_id: Any) -> tuple[str, str, float]:
    """Build a protect triple for one existing episodic point."""
    coll = core.collection_name("episodic")
    pts = await core.storage.get_points(coll, [point_id])
    assert len(pts) == 1
    return (coll, str(pts[0]["id"]), float(pts[0]["payload"]["log_base"]))


async def _point_payload(core: EpisodicMemoryCore, point_id: Any) -> dict[str, Any]:
    """Return the payload of one existing episodic point."""
    coll = core.collection_name("episodic")
    pts = await core.storage.get_points(coll, [point_id])
    assert len(pts) == 1
    return pts[0]["payload"]


async def test_replayed_and_older_at_08_linked(storage):
    """A replayed trace and an older trace at cosine 0.8 are linked with weight 0.5."""
    q, old = "q", "old_80"
    table = {q: _unit(1.0, 0), old: _unit(0.8, 1)}
    core = await _core(storage, embedder=_TableEmbedder(table))

    oid = await core.store(old, collection="episodic")
    await core.downscale([])

    qid = await core.store(q, collection="episodic")
    protect = await _protect(core, [q])
    await core.downscale(protect, prune=False)

    result = await core.associate()
    assert len(result["pairs"]) == 1
    pair = result["pairs"][0]
    assert set(pair.keys()) == {"a", "b", "weight"}
    assert pair["a"] == _key(qid)
    assert pair["b"] == _key(oid)
    assert pair["weight"] == pytest.approx(0.5, rel=1e-5)
    assert len(core.association_index.links) == 1

    await core.prune()


async def test_near_duplicates_and_unrelated_not_linked(storage):
    """Near-duplicates and unrelated traces are not linked."""
    q, old_dup, old_unrelated = "q", "old_97", "old_30"
    table = {
        q: _unit(1.0, 0),
        old_dup: _unit(0.97, 1),
        old_unrelated: _unit(0.3, 2),
    }
    core = await _core(storage, embedder=_TableEmbedder(table))

    await core.store(old_dup, collection="episodic")
    await core.store(old_unrelated, collection="episodic")
    await core.downscale([])

    await core.store(q, collection="episodic")
    protect = await _protect(core, [q])
    await core.downscale(protect, prune=False)

    result = await core.associate()
    assert result["pairs"] == []
    assert not core.association_index.links

    exported = await core.storage.export(core.association_collection_names())
    # No association collection was created.
    assert exported == {}

    await core.prune()


async def test_same_wake_not_linked(storage):
    """Traces of the same wake are not linked even if cosine is in band."""
    q, old = "q", "old_80"
    table = {q: _unit(1.0, 0), old: _unit(0.8, 1)}
    core = await _core(storage, embedder=_TableEmbedder(table))

    await core.store(old, collection="episodic")
    await core.store(q, collection="episodic")
    protect = await _protect(core, [q])
    await core.downscale(protect, prune=False)

    result = await core.associate()
    assert result["pairs"] == []
    await core.prune()


async def test_n_pair_most_similar_first(storage):
    """At most n_pair pairs are reported, most similar first."""
    q = "q"
    cosines = [0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6]
    old_texts = [f"old_{i}" for i in range(len(cosines))]
    table = {q: _unit(1.0, 0)}
    for c, axis, t in zip(cosines, range(1, 8), old_texts):
        table[t] = _unit(c, axis)

    core = await _core(storage, embedder=_TableEmbedder(table))

    old_ids: dict[str, Any] = {}
    for t in old_texts:
        old_ids[t] = await core.store(t, collection="episodic")
    await core.downscale([])

    await core.store(q, collection="episodic")
    protect = await _protect(core, [q])
    await core.downscale(protect, prune=False)

    result = await core.associate()
    assert len(result["pairs"]) == 5

    reported_b = [p["b"] for p in result["pairs"]]
    expected = [_key(old_ids[t]) for t in old_texts[:5]]
    assert reported_b == expected
    await core.prune()


async def test_second_co_replay_halves_remaining_distance(storage):
    """A second co-replay of the same pair raises weight from 0.5 to 0.75."""
    q, old = "q", "old_80"
    table = {q: _unit(1.0, 0), old: _unit(0.8, 1)}
    core = await _core(storage, embedder=_TableEmbedder(table))

    oid = await core.store(old, collection="episodic")
    await core.downscale([])

    qid = await core.store(q, collection="episodic")
    protect = await _protect(core, [q])
    await core.downscale(protect, prune=False)
    first = await core.associate()
    assert first["pairs"][0]["weight"] == pytest.approx(0.5, rel=1e-5)
    await core.prune()

    q_triple = await _protect_point(core, qid)
    await core.downscale([q_triple], prune=False)
    second = await core.associate()
    assert len(second["pairs"]) == 1
    assert second["pairs"][0]["weight"] == pytest.approx(0.75, rel=1e-5)
    assert second["pairs"][0]["a"] == _key(qid)
    assert second["pairs"][0]["b"] == _key(oid)

    await core.prune()


async def test_downscaling_scales_link_like_trace(storage):
    """Downscaling scales a link weight just like a trace strength."""
    q, old, r = "q", "old_80", "r"
    table = {
        q: _unit(1.0, 0),
        old: _unit(0.8, 1),
        r: _unit(0.0, 2),
    }
    core = await _core(storage, embedder=_TableEmbedder(table), traces_per_day=1.0)

    oid = await core.store(old, collection="episodic")
    await core.downscale([])

    await core.store(q, collection="episodic")
    protect = await _protect(core, [q])
    await core.downscale(protect, prune=False)
    await core.associate()
    await core.prune()

    link_before = list(core.association_index.links.values())[0]
    w_before = core.link_weight(link_before)
    o_strength_before = core.strength_of(await _point_payload(core, oid))

    await core.store(r, collection="episodic")
    protect_r = await _protect(core, [r])
    await core.downscale(protect_r, prune=False)
    await core.associate()
    await core.prune()

    link = list(core.association_index.links.values())[0]
    assert w_before == pytest.approx(0.5)
    assert core.link_weight(link) == pytest.approx(w_before * 0.82, rel=1e-5)
    assert core.strength_of(await _point_payload(core, oid)) == pytest.approx(
        o_strength_before * 0.82, rel=1e-5
    )


async def test_n_link_caps_weakest_first(storage):
    """Per-trace link count is capped to n_link, weakest first."""
    q = "q"
    old_texts = ["o1", "o2", "o3"]
    table = {q: _unit(1.0, 0)}
    for axis, t in zip(range(1, 4), old_texts):
        table[t] = _unit(0.8, axis)

    core = await _core(
        storage,
        embedder=_TableEmbedder(table),
        association=AssociationParams(n_link=2),
    )

    for t in old_texts:
        await core.store(t, collection="episodic")
    await core.downscale([])

    qid = await core.store(q, collection="episodic")
    protect = await _protect(core, [q])
    await core.downscale(protect, prune=False)

    result = await core.associate()
    assert result["links_dropped"] == 1
    assert core.association_index.degree(trace_ref("episodic", qid)) == 2

    await core.prune()


async def test_schema_node_forms_at_n_sch(storage):
    """A trace with n_sch links becomes a schema node with centroid and mean weight."""
    q = "q"
    old_texts = ["o1", "o2", "o3"]
    table = {q: _unit(1.0, 0)}
    vectors = [table[q]]
    for c, axis, t in zip([0.9, 0.8, 0.7], range(1, 4), old_texts):
        table[t] = _unit(c, axis)
        vectors.append(table[t])
    table["cue_centroid"] = _normalize(_mean(vectors))

    core = await _core(storage, embedder=_TableEmbedder(table))

    for t in old_texts:
        await core.store(t, collection="episodic")
    await core.downscale([])

    qid = await core.store(q, collection="episodic")
    protect = await _protect(core, [q])
    await core.downscale(protect, prune=False)
    await core.associate()
    await core.prune()

    q_ref = trace_ref("episodic", qid)
    node = core.association_index.node_of(q_ref)
    assert node is not None
    assert core.node_strength(node) == pytest.approx(0.5, rel=1e-5)

    results, _ = await core.recall("cue_centroid", k=10, collection="episodic")
    schema = next(r for r in results if r.payload.get("schema_node"))
    assert schema.text == q
    assert schema.strength == pytest.approx(0.5, rel=1e-5)
    assert schema.similarity == pytest.approx(1.0, rel=1e-4)


async def test_recall_of_member_returns_partner(storage):
    """Recall of either linked trace also returns the other."""
    q, old, cue_q, cue_o = "q", "old_80", "cue_q", "cue_o"
    table = {
        q: _unit(1.0, 0),
        old: _unit(0.8, 1),
        cue_q: _unit(1.0, 0),
        cue_o: _unit(0.8, 1),
    }
    core = await _core(storage, embedder=_TableEmbedder(table))

    oid = await core.store(old, collection="episodic")
    await core.downscale([])

    qid = await core.store(q, collection="episodic")
    protect = await _protect(core, [q])
    await core.downscale(protect, prune=False)
    await core.associate()
    await core.prune()

    results, _ = await core.recall(cue_q, k=1, collection="episodic")
    assert [_key(r.point_id) for r in results] == [_key(qid), _key(oid)]

    results2, _ = await core.recall(cue_o, k=1, collection="episodic")
    assert [_key(r.point_id) for r in results2] == [_key(oid), _key(qid)]


async def test_deleted_trace_takes_its_links(storage):
    """A trace deleted at the floor cascades to its links."""
    q, old = "q", "old_80"
    fillers = ["f1", "f2", "f3"]
    table = {
        q: _unit(1.0, 0),
        old: _unit(0.8, 1),
    }
    for axis, t in zip(range(2, 5), fillers):
        table[t] = _unit(0.0, axis)

    core = await _core(
        storage,
        embedder=_TableEmbedder(table),
        traces_per_day=1.0,
        prune_floor=0.5,
    )

    await core.store(old, collection="episodic")
    await core.downscale([])

    await core.store(q, collection="episodic")
    for t in fillers:
        await core.store(t, collection="episodic")
    protect = await _protect(core, [q])
    await core.downscale(protect, prune=False)
    await core.associate()
    pruned = await core.prune()

    assert pruned["links_pruned"] >= 1
    assert not core.association_index.links

    scan = await core.storage.scan_store(
        core.persisted_collection_names() + core.association_collection_names()
    )
    assert core.store_bytes == scan["bytes"]


async def test_link_below_floor_pruned_keeps_traces(storage):
    """A link below the floor is pruned while both traces survive."""
    q, old = "q", "old_80"
    fillers = ["u1", "u2", "u3"]
    table = {
        q: _unit(1.0, 0),
        old: _unit(0.8, 1),
    }
    for axis, t in zip(range(2, 5), fillers):
        table[t] = _unit(0.0, axis)

    core = await _core(
        storage,
        embedder=_TableEmbedder(table),
        traces_per_day=1.0,
        prune_floor=0.3,
    )

    oid = await core.store(old, collection="episodic")
    await core.downscale([])

    qid = await core.store(q, collection="episodic")
    protect = await _protect(core, [q])
    await core.downscale(protect, prune=False)
    await core.associate()
    await core.prune()

    for u in fillers:
        await core.store(u, collection="episodic")
        protect_u = await _protect(core, [u])
        summary = await core.downscale(protect_u)
        if u == "u3":
            assert summary.get("links_pruned") == 1

    coll = core.collection_name("episodic")
    pts = await core.storage.get_points(coll, [oid, qid])
    assert len(pts) == 2
    assert not core.association_index.links


async def test_link_counts_toward_budget(storage):
    """Link records are pruned to the byte budget before protected traces."""
    q, old = "q", "old_80"
    table = {q: _unit(1.0, 0), old: _unit(0.8, 1)}
    core = await _core(storage, embedder=_TableEmbedder(table))

    oid = await core.store(old, collection="episodic")
    await core.downscale([])

    qid = await core.store(q, collection="episodic")
    protect = await _protect(core, [q])
    await core.downscale(protect, prune=False)
    await core.associate()
    await core.prune()

    q_triple = await _protect_point(core, qid)
    await core.downscale([q_triple], prune=False)
    result = await core.associate()
    assert len(result["pairs"]) == 1
    assert result["pairs"][0]["weight"] == pytest.approx(0.75, rel=1e-5)

    # The re-written link changes S by a few bytes, so the budget is set after it.
    core._budget_bytes = core.store_bytes - 1

    await core.prune()
    assert core.store_bytes <= core._budget_bytes
    assert not core.association_index.links

    coll = core.collection_name("episodic")
    pts = await core.storage.get_points(coll, [qid, oid])
    assert len(pts) == 2


async def test_links_nodes_survive_revive(storage, request, tmp_path):
    """Links and schema nodes survive an export/import revive."""
    q = "q"
    old_texts = ["o1", "o2", "o3"]
    table = {q: _unit(1.0, 0), "cue_q": _unit(1.0, 0)}
    for c, axis, t in zip([0.9, 0.8, 0.7], range(1, 4), old_texts):
        table[t] = _unit(c, axis)

    core = await _core(storage, embedder=_TableEmbedder(table))

    old_ids: dict[str, Any] = {}
    for t in old_texts:
        old_ids[t] = await core.store(t, collection="episodic")
    await core.downscale([])

    qid = await core.store(q, collection="episodic")
    protect = await _protect(core, [q])
    await core.downscale(protect, prune=False)
    await core.associate()
    await core.prune()

    state = await core.export_state()

    kind = request.node.callspec.params["storage"]
    storage2 = await _open_storage(kind, tmp_path / "revive")
    try:
        core2 = await _core(storage2, embedder=_TableEmbedder(table))
        await core2.import_state(state)

        assert set(core2.association_index.links.keys()) == set(
            core.association_index.links.keys()
        )
        for lid in core.association_index.links:
            l1 = core.association_index.links[lid]
            l2 = core2.association_index.links[lid]
            assert core2.link_weight(l2) == pytest.approx(core.link_weight(l1), rel=1e-5)

        q_ref = trace_ref("episodic", qid)
        node1 = core.association_index.node_of(q_ref)
        node2 = core2.association_index.node_of(q_ref)
        assert node1 is not None
        assert node2 is not None
        assert core2.node_strength(node2) == pytest.approx(
            core.node_strength(node1), rel=1e-5
        )

        results, _ = await core2.recall("cue_q", k=1, collection="episodic")
        assert results
        assert _key(results[0].point_id) == _key(qid)
        partner_keys = {_key(old_ids[t]) for t in old_texts}
        assert {_key(r.point_id) for r in results[1:]} == partner_keys
    finally:
        await storage2.shutdown()


async def test_store_without_coreplay_exports_no_association_collections(storage):
    """A store that never co-replayed has no links/schemas in its export."""
    table = {"a": _unit(1.0, 0), "b": _unit(0.8, 1)}
    core = await _core(storage, embedder=_TableEmbedder(table))

    await core.store("a", collection="episodic")
    protect_a = await _protect(core, ["a"])
    s1 = await core.downscale(protect_a)

    await core.store("b", collection="episodic")
    protect_b = await _protect(core, ["b"])
    s2 = await core.downscale(protect_b)

    expected = {
        "n_new",
        "factor",
        "protected",
        "total_before",
        "total_after",
        "pruned_floor",
        "pruned_budget",
        "store_bytes",
        "blocked",
        "blocked_sleeps",
        "persist_refusals",
    }
    assert set(s1.keys()) == expected
    assert set(s2.keys()) == expected

    persisted = (await core.export_state())["persisted"]
    for name in persisted:
        assert not (name.endswith("links") or name.endswith("schemas"))


async def test_deferred_pruning_equals_immediate_without_links():
    """Deferred pruning matches immediate pruning on a store without links."""

    table = {
        "a": _unit(1.0, 0),
        "b": _unit(0.8, 1),
        "c": _unit(0.6, 2),
        "d": _unit(0.4, 3),
    }

    core_i = await _core(
        InMemoryStorage(latent_dim=DIM),
        embedder=_TableEmbedder(table),
        traces_per_day=1.0,
        prune_floor=0.5,
    )
    core_d = await _core(
        InMemoryStorage(latent_dim=DIM),
        embedder=_TableEmbedder(table),
        traces_per_day=1.0,
        prune_floor=0.5,
    )

    for t in table:
        await core_i.store(t, collection="episodic")
        await core_d.store(t, collection="episodic")

    protect_i = await _protect(core_i, ["a", "b"])
    protect_d = await _protect(core_d, ["a", "b"])

    s_i = await core_i.downscale(protect_i)
    await core_d.downscale(protect_d, prune=False)
    s_d2 = await core_d.prune()

    # The two stores draw different point ids, so the survivors compare by text.
    keys_i = {p["text"] for p in _flat(await core_i.storage.export(core_i.persisted_collection_names()))}
    keys_d = {p["text"] for p in _flat(await core_d.storage.export(core_d.persisted_collection_names()))}
    assert keys_i and keys_i != set(table)
    assert keys_i == keys_d
    # Record sizes differ by their wall-clock timestamps, so each store's S is
    # checked against its own scan.
    for c in (core_i, core_d):
        assert c.store_bytes == (await c.storage.scan_store(c.persisted_collection_names()))["bytes"]
    assert (s_i["pruned_floor"], s_i["pruned_budget"]) == (
        s_d2["pruned_floor"],
        s_d2["pruned_budget"],
    )


async def test_associate_prune_skipped_without_deferred_downscale(storage):
    """associate() and prune() skip when no deferred downscaling is pending."""
    core = await _core(storage)

    assert await core.associate() == {"skipped": "no downscaling awaits pruning"}
    assert await core.prune() == {"skipped": "no downscaling awaits pruning"}

    await core.store("q", collection="episodic")
    protect = await _protect(core, ["q"])
    await core.downscale(protect)

    assert await core.associate() == {"skipped": "no downscaling awaits pruning"}
    assert await core.prune() == {"skipped": "no downscaling awaits pruning"}


async def test_restart_reloads_links(storage):
    """A new core over the same storage reloads saved links."""
    q, old = "q", "old_80"
    table = {q: _unit(1.0, 0), old: _unit(0.8, 1)}
    embedder = _TableEmbedder(table)
    core = await _core(storage, embedder=embedder)

    await core.store(old, collection="episodic")
    await core.downscale([])

    await core.store(q, collection="episodic")
    protect = await _protect(core, [q])
    await core.downscale(protect, prune=False)
    await core.associate()
    await core.prune()

    link_ids = set(core.association_index.links)
    bytes1 = core.store_bytes

    core2 = await _core(storage, embedder=embedder)
    assert set(core2.association_index.links) == link_ids
    assert core2.store_bytes == bytes1
