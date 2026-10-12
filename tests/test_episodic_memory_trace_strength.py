# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Trace-strength downscaling for sleep, paper A.10."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import random
import struct
import uuid
from pathlib import Path
from typing import Any

import pytest

from kaine.boot.errors import ConfigurationError
from kaine.boot.factories.episodic_memory import make_episodic_memory
from kaine.boot.factories.sleep import make_sleep
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.episodic_memory import (
    EpisodicMemory,
    EpisodicMemoryCore,
    FakeEmbedder,
    InMemoryStorage,
)
from kaine.modules.episodic_memory.memory import recover_interrupted_import
from kaine.modules.episodic_memory.replay import ReplayEvent
from kaine.modules.episodic_memory.storage import (
    QdrantStorage,
    SqliteVecStorage,
    StorageError,
)
from kaine.modules.sleep.phases import deep_consolidation

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


async def _strengths(core: EpisodicMemoryCore) -> dict[str, float]:
    """Map normalized point id to current strength for persisted points."""
    points = _flat(await core.storage.export(core.persisted_collection_names()))
    return {_key(p["id"]): core.strength_of(p["payload"]) for p in points}


async def _protect(core: EpisodicMemoryCore, texts: list[str]) -> list[tuple[str, str, float]]:
    """Build protect triples for the current wake matching the given texts."""
    pool = await core.wake_pool()
    return [
        (p["collection"], _key(p["id"]), float(p["payload"]["log_base"]))
        for p in pool
        if p["text"] in texts
    ]


def _unit(v: list[float]) -> list[float]:
    """Return the unit vector."""
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


def _cos(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    ua = _unit(a)
    ub = _unit(b)
    return sum(x * y for x, y in zip(ua, ub))


# ------------------------------------------------------------------
# Basic strength semantics
# ------------------------------------------------------------------


async def test_persist_sets_strength_keys(storage):
    """Persist overwrites reserved strength keys and stamps entity time."""
    clock = _Clock(42.0)
    core = await _core(storage, clock=clock)
    pid = await core.store(
        "a",
        payload={"log_base": 5.0, "born_sleep": 9, "entity_time": -1.0, "x": 1},
        collection="episodic",
    )
    points = _flat(await core.storage.export(core.persisted_collection_names()))
    found = next(p for p in points if _key(p["id"]) == _key(pid))
    payload = found["payload"]
    assert payload["log_base"] == 0.0
    assert payload["born_sleep"] == 0
    assert payload["entity_time"] == 42.0
    assert payload["x"] == 1
    assert "timestamp" in payload
    assert core.strength_of(payload) == pytest.approx(1.0, abs=1e-12)


async def test_factor_follows_new_trace_count(storage):
    """Downscale factor deepens with the number of new traces."""
    core = await _core(storage, traces_per_day=4.0)
    for _ in range(4):
        await core.store("x", collection="episodic")
    s1 = await core.downscale()
    assert s1["n_new"] == 4
    assert s1["factor"] == pytest.approx(0.82, rel=1e-12)
    strengths = await _strengths(core)
    assert all(v == pytest.approx(0.82, rel=1e-12) for v in strengths.values())

    for _ in range(2):
        await core.store("y", collection="episodic")
    s2 = await core.downscale()
    assert s2["n_new"] == 2
    assert s2["factor"] == pytest.approx(math.sqrt(0.82), rel=1e-12)
    strengths = await _strengths(core)
    old = [v for k, v in strengths.items() if k in await _key_ids_from_texts(core, ["x"])]
    new = [v for k, v in strengths.items() if k in await _key_ids_from_texts(core, ["y"])]
    assert all(v == pytest.approx(0.82 * math.sqrt(0.82), rel=1e-12) for v in old)
    assert all(v == pytest.approx(math.sqrt(0.82), rel=1e-12) for v in new)

    s3 = await core.downscale()
    assert s3["n_new"] == 0
    assert s3["factor"] == pytest.approx(1.0, rel=1e-12)
    after = await _strengths(core)
    for key, value in strengths.items():
        assert after[key] == pytest.approx(value, rel=1e-12)


async def _key_ids_from_texts(core: EpisodicMemoryCore, texts: list[str]) -> set[str]:
    """Return normalized ids of persisted points whose text is in texts."""
    points = _flat(await core.storage.export(core.persisted_collection_names()))
    return {_key(p["id"]) for p in points if p["text"] in texts}


async def test_protected_keep_strength_and_ratios_hold(storage):
    """Protected traces keep their strength; unprotected ratios stay fixed."""
    core = await _core(storage, traces_per_day=4.0)
    for i in range(6):
        await core.store(f"o{i}", collection="episodic")
    await core.downscale()

    before = await _strengths(core)
    for i in range(4):
        await core.store(f"n{i}", collection="episodic")
    protect = await _protect(core, ["n0", "n1"])
    s = await core.downscale(protect=protect)
    after = await _strengths(core)

    n0_id = next(iter(await _key_ids_from_texts(core, ["n0"])))
    n1_id = next(iter(await _key_ids_from_texts(core, ["n1"])))
    assert after[n0_id] == pytest.approx(1.0, abs=1e-12)
    assert after[n1_id] == pytest.approx(1.0, abs=1e-12)

    # Ratios among the traces that existed before the second sleep, all unprotected.
    unprotected = list(before)
    for i, a in enumerate(unprotected):
        for b in unprotected[i + 1 :]:
            assert after[a] / after[b] == pytest.approx(before[a] / before[b], rel=1e-9)

    assert s["total_after"] < s["total_before"]
    assert s["protected"] == 2
    assert core.total_strength == pytest.approx(sum(after.values()), rel=1e-9)


async def test_downscale_never_touches_vectors(storage, monkeypatch):
    """Downscaling changes only payload log_base, never vectors."""
    core = await _core(storage)
    await core.store("keep", collection="episodic")
    protect = await _protect(core, ["keep"])
    before = _flat(await core.storage.export(core.persisted_collection_names()))
    before_by_id = {_key(p["id"]): list(p["vector"]) for p in before}

    calls = []
    if isinstance(storage, QdrantStorage):

        async def wrapped_upsert(*args, **kwargs):
            calls.append(kwargs.get("collection_name"))
            return await original_upsert(*args, **kwargs)

        original_upsert = storage._client.upsert
        storage._client.upsert = wrapped_upsert

    await core.downscale(protect=protect)

    after = _flat(await core.storage.export(core.persisted_collection_names()))
    for p in after:
        assert list(p["vector"]) == before_by_id[_key(p["id"])]

    if isinstance(storage, QdrantStorage):
        names = set(core.persisted_collection_names())
        for call in calls:
            assert call not in names


async def test_recall_ranks_by_strength_times_similarity(storage):
    """Recall ranks by h * sim and reports per-result similarity and strength."""
    e0 = [1.0] + [0.0] * (DIM - 1)
    e3 = [0.0, 0.0, 0.0, 1.0] + [0.0] * (DIM - 4)
    table = {
        "q": e0,
        "a": e0,
        "b": e0,
        "c": _unit([0.9] + [math.sqrt(1 - 0.81)] + [0.0] * (DIM - 2)),
        "d": _unit([0.95, 0.0] + [math.sqrt(1 - 0.9025)] + [0.0] * (DIM - 3)),
        "z": e3,
    }
    core = await _core(storage, embedder=_TableEmbedder(table), traces_per_day=1.0)

    await core.store("a", collection="episodic")
    await core.downscale()

    await core.store("b", collection="episodic")
    results, _ = await core.recall("q", k=2)
    assert [r.text for r in results] == ["b", "a"]
    assert results[0].score == pytest.approx(1.0 * 1.0, rel=1e-9)
    assert results[1].score == pytest.approx(1.0 * 0.82, rel=1e-9)
    assert results[1].similarity == pytest.approx(1.0, rel=1e-9)
    assert results[1].strength == pytest.approx(0.82, rel=1e-9)

    await core.store("d", collection="episodic")
    await core.store("z", collection="episodic")
    await core.downscale()
    await core.store("z", collection="episodic")
    await core.downscale()

    await core.store("c", collection="episodic")
    results, _ = await core.recall("q", k=4)
    c_idx = next(i for i, r in enumerate(results) if r.text == "c")
    d_idx = next(i for i, r in enumerate(results) if r.text == "d")
    assert c_idx < d_idx

    order = [r.text for r in results]
    await core.store("z", collection="episodic")
    await core.downscale()
    results2, _ = await core.recall("q", k=4)
    assert [r.text for r in results2] == order


async def test_topk_matches_brute_force(storage):
    """Backend recall agrees with a brute-force ranking over exported points."""
    rng = random.Random(7)
    query = _unit([rng.gauss(0.0, 1.0) for _ in range(DIM)])
    table: dict[str, list[float]] = {"q": query}
    episodic_texts: list[str] = []
    for i in range(60):
        vec = _unit([rng.gauss(0.0, 1.0) for _ in range(DIM)])
        text = f"t{i}"
        table[text] = vec
        episodic_texts.append(text)
    for i in range(20):
        noise = [rng.gauss(0.0, 1e-4) for _ in range(DIM)]
        table[f"s{i}"] = _unit([q + n for q, n in zip(query, noise)])
    embedder = _TableEmbedder(table)
    core = await _core(storage, embedder=embedder, traces_per_day=10.0, prune_floor=0.3)

    for wake in range(6):
        batch = episodic_texts[wake * 10 : (wake + 1) * 10]
        for text in batch:
            await core.store(text, collection="episodic")
        for i in range(20):
            await core.store(f"s{i}", collection="semantic")
        protect = await _protect(core, random.Random(wake).sample(batch, 2))
        await core.downscale(protect=protect)

    exported = _flat(await core.storage.export(core.persisted_collection_names()))
    episodic_points = [
        p for p in exported if p["collection"] == core.collection_name("episodic")
    ]
    episodic_ids = {_key(p["id"]) for p in episodic_points}
    for k in (1, 5, 20):
        results, _ = await core.recall("q", k=k, collection="episodic")
        qvec = await embedder.encode("q")
        brute = []
        for p in episodic_points:
            cos = _cos(qvec, p["vector"])
            if cos <= 0.0:
                continue
            brute.append((core.strength_of(p["payload"]) * cos, _key(p["id"])))
        brute.sort(key=lambda t: t[0], reverse=True)
        brute = brute[:k]
        assert len(results) == len(brute)
        for r, (score, bid) in zip(results, brute):
            assert r.score == pytest.approx(score, abs=1e-5)
            assert _key(r.point_id) in episodic_ids
        scores = [s for s, _ in brute]
        for i, r in enumerate(results):
            unique = True
            if i > 0 and abs(scores[i] - scores[i - 1]) <= 1e-5:
                unique = False
            if i < len(scores) - 1 and abs(scores[i] - scores[i + 1]) <= 1e-5:
                unique = False
            if unique:
                assert _key(r.point_id) == brute[i][1]


async def test_floor_prunes_weak_traces(storage):
    """Traces that fall below the prune floor are deleted during sleep."""
    e0 = [1.0] + [0.0] * (DIM - 1)
    e_last = [0.0] * (DIM - 1) + [1.0]
    table = {"q": e0, "a": e0, "z": e_last}
    core = await _core(storage, embedder=_TableEmbedder(table), traces_per_day=1.0, prune_floor=0.7)
    await core.store("a", collection="episodic")
    summary1 = await core.downscale()
    assert summary1["pruned_floor"] == 0
    a_id = next(iter(await _key_ids_from_texts(core, ["a"])))
    assert (await _strengths(core))[a_id] == pytest.approx(0.82, rel=1e-12)

    await core.store("z", collection="episodic")
    summary2 = await core.downscale()
    assert summary2["pruned_floor"] >= 1
    exported = _flat(await core.storage.export(core.persisted_collection_names()))
    assert not any(p["text"] == "a" for p in exported)
    results, _ = await core.recall("q", k=5)
    assert "a" not in [r.text for r in results]
    for p in exported:
        assert core.strength_of(p["payload"]) >= 0.7


async def test_migration_backfills_once(storage):
    """Legacy points without log_base are backfilled and only once."""
    await storage.ensure_collection("mnemos_episodic")
    await storage.write_stamp("mnemos_embedding_space", _TableEmbedder().space)
    vec = _unit([1.0] * DIM)
    for i in range(3):
        await storage.upsert(
            "mnemos_episodic",
            vector=vec,
            text=f"legacy-{i}",
            payload={"timestamp": 1.0},
            affect=None,
        )
    core = await _core(storage)
    points = _flat(await core.storage.export(core.persisted_collection_names()))
    for p in points:
        assert p["payload"]["log_base"] == 0.0
        assert p["payload"]["born_sleep"] == -1
    meta = await storage.read_meta("mnemos_strength")
    assert meta == {
        "log_gain": 0.0,
        "sleeps": 0,
        "total": 3.0,
        "entity_time": 0.0,
        "bytes": await storage.total_size(core.persisted_collection_names()),
    }
    assert meta["bytes"] > 0

    core2 = await _core(storage)
    changed = await storage.backfill_strength(core2.persisted_collection_names(), log_base=0.0)
    assert changed == 0
    assert await storage.read_meta("mnemos_strength") == meta


async def test_store_without_meta_but_with_log_base_is_refused(storage):
    """A point with log_base but no strength record is rejected."""
    await storage.ensure_collection("mnemos_episodic")
    await storage.write_stamp("mnemos_embedding_space", _TableEmbedder().space)
    await storage.upsert(
        "mnemos_episodic",
        vector=_unit([1.0] * DIM),
        text="orphan",
        payload={"timestamp": 1.0, "log_base": -3.0},
        affect=None,
    )
    with pytest.raises(StorageError):
        await _core(storage)


async def test_preservation_round_trip(storage, request, tmp_path):
    """export_state/import_state preserves trace strengths exactly."""
    core = await _core(storage, traces_per_day=4.0)
    await core.store("a", collection="episodic")
    await core.store("b", collection="episodic")
    await core.downscale()
    await core.store("c", collection="episodic")
    protect = await _protect(core, ["c"])
    assert protect
    await core.downscale(protect=protect)
    state = await core.export_state()

    kind = request.node.callspec.params["storage"]
    (tmp_path / "b").mkdir(exist_ok=True)
    storage2 = await _open_storage(kind, tmp_path / "b")
    try:
        core2 = await _core(storage2)
        await core2.import_state(state)
        s1 = await _strengths(core)
        s2 = await _strengths(core2)
        assert set(s1.keys()) == set(s2.keys())
        for k in s1:
            assert s1[k] == pytest.approx(s2[k], abs=1e-12)
        assert core2.log_gain == pytest.approx(core.log_gain, abs=1e-12)
        assert core2.sleeps == core.sleeps
        assert core2.total_strength == pytest.approx(core.total_strength, rel=1e-9)
        assert state["strength"] == core2._strength_meta()
    finally:
        await storage2.shutdown()


async def test_old_bundle_is_backfilled_and_bad_bundle_refused(storage, request, tmp_path):
    """Bundles without a strength record are backfilled or rejected cleanly."""
    core = await _core(storage, traces_per_day=4.0)
    await core.store("a", collection="episodic")
    await core.downscale()
    state = await core.export_state()

    kind = request.node.callspec.params["storage"]

    async def import_modified(modifier, subdir):
        subdir.mkdir(parents=True, exist_ok=True)
        storage2 = await _open_storage(kind, subdir)
        core2 = await _core(storage2)
        await core2.store("pre", collection="episodic")
        before = len(_flat(await core2.storage.export(core2.persisted_collection_names())))
        my_state = copy.deepcopy(state)
        modifier(my_state)
        try:
            await core2.import_state(my_state)
        except StorageError:
            after = len(_flat(await core2.storage.export(core2.persisted_collection_names())))
            assert after == before
            await storage2.shutdown()
            raise
        return core2, storage2

    # Case (a): remove strength record and reserved keys.
    def remove_all(s):
        s.pop("strength", None)
        for pts in s["persisted"].values():
            for p in pts:
                for k in ("log_base", "born_sleep", "entity_time"):
                    p["payload"].pop(k, None)

    core_a, storage_a = await import_modified(remove_all, tmp_path / "a")
    try:
        points = _flat(await core_a.storage.export(core_a.persisted_collection_names()))
        for p in points:
            assert p["payload"]["log_base"] == 0.0
            assert p["payload"]["born_sleep"] == -1
            assert core_a.strength_of(p["payload"]) == pytest.approx(1.0, abs=1e-12)
    finally:
        await storage_a.shutdown()

    # Case (b): remove only strength record; existing log_base is fatal.
    def remove_strength_only(s):
        s.pop("strength", None)

    with pytest.raises(StorageError):
        await import_modified(remove_strength_only, tmp_path / "b")


async def test_crash_between_meta_and_protect_only_loses_strength(storage, monkeypatch):
    """A crash after the meta write leaves no trace stronger than before."""
    core = await _core(storage, traces_per_day=4.0)
    await core.store("a", collection="episodic")
    await core.downscale()
    await core.store("b", collection="episodic")
    protect = await _protect(core, ["b"])
    assert protect
    before = await _strengths(core)

    async def fail(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(storage, "set_log_base", fail)
    with pytest.raises(RuntimeError):
        await core.downscale(protect=protect)

    after = await _strengths(core)
    for k in before:
        assert after[k] <= before[k] + 1e-12
    b_id = next(iter(await _key_ids_from_texts(core, ["b"])))
    expected_factor = math.exp((1 / core._traces_per_day) * math.log(core._retention_per_day))
    assert after[b_id] == pytest.approx(expected_factor, rel=1e-12)
    assert after[b_id] < 1.0


async def test_numerics_far_from_zero_log_gain(storage, request):
    """Strength arithmetic remains exact when log_gain is far from zero."""
    if request.node.callspec.params["storage"] == "qdrant":
        pytest.skip("in-memory and sqlite-vec only")
    await storage.ensure_collection("mnemos_episodic")
    await storage.write_stamp("mnemos_embedding_space", _TableEmbedder().space)
    await storage.write_meta(
        "mnemos_strength",
        {"log_gain": -5000.0, "sleeps": 7, "total": 0.0, "entity_time": 0.0, "bytes": 0},
    )
    e0 = [1.0] + [0.0] * (DIM - 1)
    table = {
        "q": e0,
        "a": e0,
        "b": _unit([0.8, 0.6] + [0.0] * (DIM - 2)),
    }
    # Two traces stored against a day of two: the factor is exactly 0.82.
    core = await _core(storage, embedder=_TableEmbedder(table), traces_per_day=2.0)
    await core.store("a", collection="episodic")
    await core.store("b", collection="episodic")
    protect = await _protect(core, ["b"])
    await core.downscale(protect=protect)
    strengths = await _strengths(core)
    a_id = next(iter(await _key_ids_from_texts(core, ["a"])))
    b_id = next(iter(await _key_ids_from_texts(core, ["b"])))
    assert strengths[a_id] == pytest.approx(0.82, rel=1e-12)
    assert strengths[b_id] == pytest.approx(1.0, rel=1e-12)

    results, _ = await core.recall("q", k=2)
    assert [r.text for r in results] == ["a", "b"]
    assert results[0].score == pytest.approx(0.82 * 1.0, rel=1e-9)
    # sqlite-vec stores float32 vectors, so the similarity is exact to about 1e-7.
    assert results[1].score == pytest.approx(1.0 * 0.8, rel=1e-6)


async def test_drift_over_many_sleeps():
    """Strength drift over a thousand sleeps matches the product of factors."""
    storage = InMemoryStorage(latent_dim=DIM)
    await storage.initialize()
    try:
        # A floor far below the fading strength, so drift is measured, not pruning.
        core = await _core(storage, traces_per_day=24.0, prune_floor=1e-9)
        await core.store("keep", collection="episodic")
        await core.store("fade", collection="episodic")
        factors: list[float] = []
        n_news: list[int] = []
        for _ in range(1000):
            exported = _flat(await core.storage.export(core.persisted_collection_names()))
            keep = next(p for p in exported if p["text"] == "keep")
            protect = [(keep["collection"], _key(keep["id"]), float(keep["payload"]["log_base"]))]
            await core.store("filler", collection="episodic")
            summary = await core.downscale(protect=protect)
            factors.append(summary["factor"])
            n_news.append(summary["n_new"])

        strengths = await _strengths(core)
        keep_id = next(iter(await _key_ids_from_texts(core, ["keep"])))
        fade_id = next(iter(await _key_ids_from_texts(core, ["fade"])))
        assert strengths[keep_id] == pytest.approx(1.0, rel=1e-9)
        product = math.prod(factors)
        assert strengths[fade_id] == pytest.approx(product, rel=1e-9)
        expected = 0.82 ** (sum(n_news) / 24.0)
        assert strengths[fade_id] == pytest.approx(expected, rel=1e-9)
        assert core.total_strength == pytest.approx(sum(strengths.values()), rel=1e-9)
    finally:
        await storage.shutdown()


async def test_entity_time_continues_across_restart(storage):
    """Entity time resumes from the newest persisted trace, not wall time."""
    clock = _Clock(10.0)
    core1 = await _core(storage, clock=clock, short_term_capacity=1)
    await core1.store("first", payload={"timestamp": 1.0})
    clock.t = 20.0
    await core1.store("second", payload={"timestamp": 2.0})
    await core1.consolidate_now()

    clock2 = _Clock(0.0)
    core2 = await _core(storage, clock=clock2)
    clock2.t = 0.5
    pid = await core2.store("third", payload={"timestamp": 3.0}, collection="episodic")
    points = _flat(await core2.storage.export(core2.persisted_collection_names()))
    found = next(p for p in points if _key(p["id"]) == _key(pid))
    assert found["payload"]["entity_time"] > 20.0


# ------------------------------------------------------------------
# sqlite-vec specific paging and migration tests
# ------------------------------------------------------------------


async def test_sqlite_search_filters_collection_inside_index(tmp_path):
    """sqlite-vec search respects the collection filter."""
    pytest.importorskip("sqlite_vec")
    s = SqliteVecStorage(latent_dim=DIM, db_path=str(tmp_path / "m.db"))
    await s.initialize()
    try:
        rng = random.Random(3)
        q = _unit([rng.gauss(0.0, 1.0) for _ in range(DIM)])
        other = [{"id": f"o{i}", "text": "x", "payload": {"log_base": 0.0}, "vector": q, "affect": None} for i in range(50)]
        target = [{"id": f"t{i}", "text": "x", "payload": {"log_base": 0.0}, "vector": _unit([rng.gauss(0.0, 1.0) for _ in range(DIM)]), "affect": None} for i in range(10)]
        await s.replace_collection("other", other)
        await s.replace_collection("target", target)
        hits = await s.search("target", query_vector=q, limit=5)
        assert len(hits) == 5
        target_ids = {p["id"] for p in target}
        for h in hits:
            assert h.point_id in target_ids
    finally:
        await s.shutdown()


async def test_sqlite_search_pages_past_4096(tmp_path):
    """sqlite-vec search can page past one SQLite page of results."""
    pytest.importorskip("sqlite_vec")
    s = SqliteVecStorage(latent_dim=DIM, db_path=str(tmp_path / "m.db"))
    await s.initialize()
    try:
        rng = random.Random(5)
        q = _unit([rng.gauss(0.0, 1.0) for _ in range(DIM)])
        points = []
        for i in range(6000):
            vec = _unit([rng.gauss(0.0, 1.0) for _ in range(DIM)])
            points.append({"id": f"p{i}", "text": "x", "payload": {"log_base": 0.0}, "vector": vec, "affect": None})
        await s.replace_collection("c", points)
        hits = await s.search("c", query_vector=q, limit=5000)
        assert len(hits) == 5000
        scored = sorted(
            [(p["id"], _cos(q, p["vector"])) for p in points],
            key=lambda t: t[1],
            reverse=True,
        )[:5000]
        hit_scores = [h.score for h in hits]
        exp_scores = [sc for _, sc in scored]
        for a, b in zip(hit_scores, exp_scores):
            assert a == pytest.approx(b, abs=1e-5)
        for i, h in enumerate(hits):
            unique = True
            if i > 0 and abs(exp_scores[i] - exp_scores[i - 1]) <= 1e-6:
                unique = False
            if i < len(exp_scores) - 1 and abs(exp_scores[i] - exp_scores[i + 1]) <= 1e-6:
                unique = False
            if unique:
                assert h.point_id == scored[i][0]
    finally:
        await s.shutdown()


# ------------------------------------------------------------------
# Interrupted import, blocked sleep, and recovery
# ------------------------------------------------------------------


async def test_crash_after_replace_before_meta(storage, request, tmp_path):
    """A crash after replace but before the imported meta leaves the pending flag set."""
    core = await _core(storage, traces_per_day=4.0)
    for i in range(3):
        await core.store(f"x{i}", collection="episodic")
    await core.downscale()
    state = await core.export_state()
    expected = await _strengths(core)

    kind = request.node.callspec.params["storage"]
    (tmp_path / "crash").mkdir(parents=True, exist_ok=True)
    storage2 = await _open_storage(kind, tmp_path / "crash")
    try:
        original_replace = storage2.replace_collection
        original_write_meta = storage2.write_meta
        post_replace = False
        crashed = False

        async def wrapped_replace(name, points):
            nonlocal post_replace
            result = await original_replace(name, points)
            post_replace = True
            return result

        async def wrapped_write_meta(key, value):
            nonlocal crashed
            if post_replace and not crashed:
                crashed = True
                raise RuntimeError("meta failed")
            return await original_write_meta(key, value)

        storage2.replace_collection = wrapped_replace
        storage2.write_meta = wrapped_write_meta

        core2 = await _core(storage2)
        with pytest.raises(RuntimeError, match="meta failed"):
            await core2.import_state(state)

        meta = await storage2.read_meta(core2.strength_key)
        assert meta.get("import_pending") is True

        core3 = await _core(storage2)
        summary = await core3.downscale()
        assert summary["blocked"] == "import_pending"

        storage2.replace_collection = original_replace
        storage2.write_meta = original_write_meta
        await core3.import_state(state)

        meta2 = await storage2.read_meta(core3.strength_key)
        assert meta2.get("import_pending") in (None, False)
        assert meta2.get("blocked_sleeps") in (None, 0)

        actual = await _strengths(core3)
        assert set(expected.keys()) == set(actual.keys())
        for k in expected:
            assert expected[k] == pytest.approx(actual[k], abs=1e-12)

        summary2 = await core3.downscale()
        assert summary2["blocked"] is None
    finally:
        await storage2.shutdown()


async def test_legacy_bundle_import_clears_pending(storage, request, tmp_path):
    """A legacy bundle without strength record clears the pending flag and gets strength 1."""
    core = await _core(storage, traces_per_day=4.0)
    for i in range(3):
        await core.store(f"x{i}", collection="episodic")
    await core.downscale()
    state = await core.export_state()

    state.pop("strength", None)
    for pts in state["persisted"].values():
        for p in pts:
            for k in ("log_base", "born_sleep", "entity_time"):
                p["payload"].pop(k, None)

    kind = request.node.callspec.params["storage"]
    (tmp_path / "legacy").mkdir(parents=True, exist_ok=True)
    storage2 = await _open_storage(kind, tmp_path / "legacy")
    try:
        core2 = await _core(storage2)
        await core2.import_state(state)

        meta = await storage2.read_meta(core2.strength_key)
        assert meta.get("import_pending") in (None, False)
        assert meta.get("blocked_sleeps") in (None, 0)

        points = _flat(await core2.storage.export(core2.persisted_collection_names()))
        assert len(points) == 3
        for p in points:
            assert p["payload"]["log_base"] == 0.0
            assert p["payload"]["born_sleep"] == -1
            assert core2.strength_of(p["payload"]) == pytest.approx(1.0, abs=1e-12)

        assert core2.store_bytes == await storage2.total_size(
            core2.persisted_collection_names()
        )

        summary = await core2.downscale()
        assert summary["blocked"] is None
    finally:
        await storage2.shutdown()


async def test_meta_bytes_after_mid_prune_crash(storage):
    """A mid-prune crash leaves the strength meta byte and total counters exact."""
    core = await _core(storage, traces_per_day=4.0)
    for i in range(3):
        await core.store(f"e{i}", collection="episodic")
    for i in range(3):
        await core.store(f"s{i}", collection="semantic")
    await core.downscale()

    core2 = await _core(storage, traces_per_day=4.0, budget_bytes=1)

    original_delete = storage.delete_points
    call_count = 0

    async def wrapped_delete_points(collection, ids):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return await original_delete(collection, ids)
        raise RuntimeError("disk gone")

    storage.delete_points = wrapped_delete_points
    try:
        with pytest.raises(RuntimeError, match="disk gone"):
            await core2.downscale()
    finally:
        storage.delete_points = original_delete

    names = core2.persisted_collection_names()
    scan_bytes = await storage.total_size(names)
    meta = await storage.read_meta(core2.strength_key)
    assert meta["bytes"] == scan_bytes

    points = _flat(await core2.storage.export(names))
    expected_total = sum(core2.strength_of(p["payload"]) for p in points)
    assert meta["total"] == pytest.approx(expected_total, rel=1e-9)


async def test_total_strength_self_heals(storage):
    """A corrupted total strength is repaired when a fresh core initializes."""
    core = await _core(storage, traces_per_day=4.0)
    await core.store("x", collection="episodic")
    await core.downscale()

    key = core.strength_key
    meta = await storage.read_meta(key)
    await storage.write_meta(key, {**meta, "total": 12345.0})

    core2 = await _core(storage, traces_per_day=4.0)
    points = _flat(await core2.storage.export(core2.persisted_collection_names()))
    expected = sum(core2.strength_of(p["payload"]) for p in points)
    assert core2.total_strength == pytest.approx(expected, rel=1e-9)


async def test_summary_and_health_surface_a_blocked_sleep(bus, tmp_path):
    """A blocked sleep is visible in the downscale summary, health file, and consolidation phase."""
    storage = InMemoryStorage(latent_dim=DIM)
    await storage.initialize()
    try:
        embedder = FakeEmbedder(latent_dim=DIM)
        await storage.write_stamp("mnemos_embedding_space", embedder.space)
        await storage.write_meta(
            "mnemos_strength",
            {
                "log_gain": 0.0,
                "sleeps": 0,
                "total": 0.0,
                "entity_time": 0.0,
                "bytes": 0,
                "import_pending": True,
            },
        )

        core = EpisodicMemoryCore(
            embedder,
            storage,
            health_path=tmp_path / "h.json",
            budget_bytes=1,
        )
        await core.initialize()

        summary = await core.downscale()
        assert summary["blocked"] == "import_pending"
        assert summary["blocked_sleeps"] == 1
        assert summary["persist_refusals"] == 0

        health = json.loads((tmp_path / "h.json").read_text(encoding="utf-8"))
        assert health["import_pending"] is True
        assert health["blocked_sleeps"] == 1

        class FakeEpisodicMemory:
            opened = False
            closed = False

            def open_replay_window(self):
                self.opened = True

            def close_replay_window(self):
                self.closed = True

            async def replay_now(self):
                return []

            async def downscale(self, protect=()):
                return await core.downscale(protect=protect)

        result = await deep_consolidation(FakeEpisodicMemory())
        assert not result.success
        assert "downscale blocked: import_pending" in result.error
        assert result.metadata["downscale"]["blocked"] == "import_pending"
    finally:
        await storage.shutdown()


async def test_persist_refused_when_pending_and_over_twice_budget(storage, caplog, tmp_path):
    """Persist is refused while import is pending and the store is over twice its budget."""
    await storage.write_stamp(
        "mnemos_embedding_space", FakeEmbedder(latent_dim=DIM).space
    )
    await storage.write_meta(
        "mnemos_strength",
        {
            "log_gain": 0.0,
            "sleeps": 0,
            "total": 0.0,
            "entity_time": 0.0,
            "bytes": 0,
            "import_pending": True,
        },
    )

    core = EpisodicMemoryCore(
        FakeEmbedder(latent_dim=DIM),
        storage,
        budget_bytes=1,
    )
    await core.initialize()

    first = await core.store("first", collection="episodic")
    assert first is not None

    with caplog.at_level(logging.ERROR, logger="kaine.modules.episodic_memory.memory"):
        for i in range(3):
            assert await core.store(f"refused-{i}", collection="episodic") is None

    error_records = [
        r
        for r in caplog.records
        if r.levelno == logging.ERROR and "refused to store a trace" in r.message
    ]
    assert error_records

    exported = _flat(await core.storage.export(core.persisted_collection_names()))
    assert len(exported) == 1
    assert core._persist_refusals == 3

    meta = await storage.read_meta(core.strength_key)
    assert meta.get("persist_refusals") == 3

    cleared = await recover_interrupted_import(storage)
    assert cleared["cleared"] is True

    core2 = EpisodicMemoryCore(
        FakeEmbedder(latent_dim=DIM),
        storage,
        budget_bytes=1,
    )
    await core2.initialize()
    after = await core2.store("after", collection="episodic")
    assert after is not None
    assert len(_flat(await core2.storage.export(core2.persisted_collection_names()))) == 2


async def test_persist_racing_downscale(storage):
    """A store that races downscale is persisted in the next wake."""
    core = await _core(storage, traces_per_day=4.0)
    await core.store("before", collection="episodic")

    gate = asyncio.Event()
    original_scan = storage.scan_store

    async def gated_scan(collections):
        await gate.wait()
        return await original_scan(collections)

    storage.scan_store = gated_scan
    try:
        down_task = asyncio.create_task(core.downscale())
        await asyncio.sleep(0.01)
        store_task = asyncio.create_task(core.store("late", collection="episodic"))
        gate.set()
        summary, pid = await asyncio.gather(down_task, store_task)
    finally:
        storage.scan_store = original_scan

    assert pid is not None
    points = _flat(await core.storage.export(core.persisted_collection_names()))
    late = next(p for p in points if p["text"] == "late")
    assert late["payload"]["born_sleep"] == core.sleeps
    assert core.strength_of(late["payload"]) == pytest.approx(1.0, abs=1e-12)
    assert core.store_bytes == await storage.total_size(
        core.persisted_collection_names()
    )
    assert summary["n_new"] == 1


async def test_recall_cap_logs_once(caplog, monkeypatch):
    """When the search cap is reached recall logs once and still returns a result."""
    storage = InMemoryStorage(latent_dim=DIM)
    await storage.initialize()
    try:
        e0 = [1.0] + [0.0] * (DIM - 1)
        table = {"q": e0}
        for i in range(8):
            eps = 0.001 * (i + 1)
            table[f"weak-{i}"] = _unit([1.0, eps] + [0.0] * (DIM - 2))
        # Cosine 0.95 with the cue: less similar than the weak traces, but stronger.
        table["strong"] = _unit([0.95, (1 - 0.95**2) ** 0.5] + [0.0] * (DIM - 2))
        embedder = _TableEmbedder(table)
        core = await _core(storage, embedder=embedder, traces_per_day=1.0)

        for i in range(8):
            await core.store(f"weak-{i}", collection="episodic")
        await core.downscale()
        await core.store("filler", collection="episodic")
        await core.downscale()
        await core.store("strong", collection="episodic")

        monkeypatch.setattr("kaine.modules.episodic_memory.memory._RECALL_SEARCH_CAP", 8)

        with caplog.at_level(logging.INFO, logger="kaine.modules.episodic_memory.memory"):
            results, _ = await core.recall("q", k=1)

        assert results
        approx_records = [
            r
            for r in caplog.records
            if r.levelno == logging.INFO and "approximate" in r.message
        ]
        assert len(approx_records) == 1
    finally:
        await storage.shutdown()


async def test_sqlite_search_with_many_ties(tmp_path):
    """sqlite-vec search handles large ties without duplicates or truncation bugs."""
    pytest.importorskip("sqlite_vec")
    s = SqliteVecStorage(latent_dim=DIM, db_path=str(tmp_path / "m.db"))
    await s.initialize()
    try:
        shared = _unit([1.0] * DIM)
        rng = random.Random(11)
        points = [
            {"id": f"s{i}", "text": "x", "payload": {"log_base": 0.0}, "vector": shared, "affect": None}
            for i in range(5000)
        ]
        for i in range(100):
            points.append(
                {
                    "id": f"r{i}",
                    "text": "x",
                    "payload": {"log_base": 0.0},
                    "vector": _unit([rng.gauss(0.0, 1.0) for _ in range(DIM)]),
                    "affect": None,
                }
            )
        await s.replace_collection("c", points)
        hits = await s.search("c", query_vector=shared, limit=4500)
        assert len(hits) == 4500
        ids = [h.point_id for h in hits]
        assert len(set(ids)) == len(ids)
        hits = await s.search("c", query_vector=shared, limit=10000)
        assert len(hits) == 5100
        ids = [h.point_id for h in hits]
        assert len(set(ids)) == len(ids)
    finally:
        await s.shutdown()




async def test_sqlite_old_vector_table_is_rebuilt(tmp_path):
    """sqlite-vec migrates an old single-table schema to the partitioned one."""
    pytest.importorskip("sqlite_vec")
    import sqlite3

    import sqlite_vec

    path = tmp_path / "old_mnemos.db"
    try:
        db = sqlite3.connect(str(path))
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.execute(
            "CREATE TABLE memories (rowid INTEGER PRIMARY KEY AUTOINCREMENT, collection TEXT, point_id TEXT, text TEXT, payload TEXT, affect TEXT)"
        )
        db.execute(
            "CREATE VIRTUAL TABLE vec_memories USING vec0(embedding float[8] distance_metric=cosine)"
        )
        for coll, count in [("a", 3), ("b", 2)]:
            for i in range(count):
                vec = struct.pack("8f", *[float(x) for x in _unit([random.Random(i).gauss(0.0, 1.0) for _ in range(DIM)])])
                cur = db.execute(
                    "INSERT INTO memories (collection, point_id, text, payload, affect) VALUES (?, ?, ?, ?, ?)",
                    (coll, f"{coll}-{i}", f"{coll}-{i}", "{}", "null"),
                )
                rowid = cur.lastrowid
                db.execute(
                    "INSERT INTO vec_memories (rowid, embedding) VALUES (?, ?)",
                    (rowid, vec),
                )
        db.commit()
        db.close()

        s = SqliteVecStorage(latent_dim=DIM, db_path=str(path))
        await s.initialize()
        try:
            schema_db = sqlite3.connect(str(path))
            try:
                row = schema_db.execute("SELECT sql FROM sqlite_master WHERE name = 'vec_memories'").fetchone()
                assert "partition key" in row[0].lower()
            finally:
                schema_db.close()
            points = _flat(await s.export(["a", "b"]))
            assert len(points) == 5
            for p in points:
                assert len(p["vector"]) == DIM
                assert all(math.isfinite(v) for v in p["vector"])
            hits = await s.search("b", query_vector=_unit([1.0] * DIM), limit=5)
            assert len(hits) == 2
        finally:
            await s.shutdown()

        s2 = SqliteVecStorage(latent_dim=DIM, db_path=str(path))
        await s2.initialize()
        try:
            points2 = _flat(await s2.export(["a", "b"]))
            assert len(points2) == 5
        finally:
            await s2.shutdown()
    finally:
        if path.exists():
            path.unlink()


# ------------------------------------------------------------------
# Module-level replay and phase tests
# ------------------------------------------------------------------


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


async def test_replay_pool_is_the_whole_wake(bus):
    """Replay draws from the whole wake, not just the last consolidation batch."""
    clock = _Clock()
    core = EpisodicMemoryCore(FakeEmbedder(latent_dim=DIM), InMemoryStorage(latent_dim=DIM), short_term_capacity=8, entity_clock=clock)
    await core.initialize()
    m = EpisodicMemory(bus, core=core, replay_selection_top_k=5)

    # Previous wake.
    for i in range(10):
        clock.t += 1.0
        await m.core.store(f"prev-{i}", affect={"intensity": 1.0})
    await m.core.consolidate_now()
    await m.core.downscale()

    # Current wake: 50 traces, one high-affect at index 3.
    for i in range(50):
        clock.t += 1.0
        intensity = 1.0 if i == 3 else 0.0
        await m.core.store(f"curr-{i}", affect={"intensity": intensity})
    await m.core.consolidate_now()

    m.open_replay_window()
    events = await m.replay_now()
    m.close_replay_window()

    exported = _flat(await m.core.storage.export(m.core.persisted_collection_names()))
    target_id = next(_key(p["id"]) for p in exported if p["text"] == "curr-3")
    prev_ids = {_key(p["id"]) for p in exported if p["text"].startswith("prev-")}
    assert _key(events[0].point_id) == target_id
    assert target_id not in {_key(t[0]) for t in m.core.last_consolidated}
    for ev in events:
        assert ev.collection == "mnemos_episodic"
        assert isinstance(ev.log_base, float)
        assert _key(ev.point_id) not in prev_ids


async def test_replay_recency_uses_entity_time(bus):
    """Replay recency uses entity_time, not the wall timestamp payload."""
    clock = _Clock(0.0)
    core = EpisodicMemoryCore(FakeEmbedder(latent_dim=DIM), InMemoryStorage(latent_dim=DIM), short_term_capacity=8, entity_clock=clock)
    await core.initialize()
    m = EpisodicMemory(bus, core=core, replay_selection_top_k=1)

    clock.t = 1.0
    await m.core.store("first", payload={"timestamp": 200.0}, affect={"intensity": 0.5})
    clock.t = 2.0
    await m.core.store("second", payload={"timestamp": 100.0}, affect={"intensity": 0.5})
    await m.core.consolidate_now()

    m.open_replay_window()
    events = await m.replay_now()
    m.close_replay_window()
    assert events[0].point_id == next(_key(p["id"]) for p in (_flat(await m.core.storage.export(m.core.persisted_collection_names()))) if p["text"] == "second")


def _all_bucket_texts(buckets):
    """Flatten texts from select_cross_period_traces output."""
    return [str(trace.get("text", "")) for traces in buckets.values() for trace in traces]


async def test_cross_period_selection_sees_no_pruned_trace(bus):
    """Cross-period selection does not include traces pruned below the floor."""
    core = EpisodicMemoryCore(
        FakeEmbedder(latent_dim=DIM),
        InMemoryStorage(latent_dim=DIM),
        traces_per_day=1.0,
        prune_floor=0.7,
        entity_clock=_Clock(),
    )
    await core.initialize()
    m = EpisodicMemory(bus, core=core)
    await m.core.store("old", collection="episodic")
    for i in range(3):
        await m.core.store(f"filler-{i}", collection="episodic")
        await m.core.downscale()
    buckets = await m.select_cross_period_traces(periods=1, per_period=50)
    texts = _all_bucket_texts(buckets)
    assert "old" not in texts
    # The newest filler survived pruning and is selected, so the check is not vacuous.
    assert "filler-2" in texts


async def test_deep_consolidation_protects_replayed_traces():
    """deep_consolidation passes replay events to downscale as protected traces."""
    sentinel_a = ReplayEvent(point_id="a", loop_payload={}, observer_payload={}, collection="mnemos_episodic", log_base=-0.1)
    sentinel_b = ReplayEvent(point_id="b", loop_payload={}, observer_payload={}, collection="mnemos_episodic", log_base=-0.2)

    class FakeOk:
        opened = False
        closed = False
        protect = []

        def open_replay_window(self):
            self.opened = True

        def close_replay_window(self):
            self.closed = True

        async def replay_now(self):
            return [sentinel_a, sentinel_b]

        async def downscale(self, protect=()):
            self.protect = list(protect)
            return {"n_new": 3, "factor": 0.9, "protected": 2, "total_before": 5.0, "total_after": 4.6, "pruned_floor": 0, "pruned_budget": 0, "store_bytes": 0}

    fake = FakeOk()
    result = await deep_consolidation(fake)
    assert result.success
    assert fake.protect == [sentinel_a, sentinel_b]
    expected_meta = {"n_new": 3, "factor": 0.9, "protected": 2, "total_before": 5.0, "total_after": 4.6, "pruned_floor": 0, "pruned_budget": 0, "store_bytes": 0}
    assert result.metadata["downscale"] == expected_meta

    class FakeReplayFail:
        downscale_calls = 0

        def open_replay_window(self): pass
        def close_replay_window(self): pass

        async def replay_now(self):
            raise RuntimeError("replay failed")

        async def downscale(self, protect=()):
            self.__class__.downscale_calls += 1
            return {"n_new": 0, "factor": 1.0, "protected": 0, "total_before": 1.0, "total_after": 1.0, "pruned_floor": 0, "pruned_budget": 0, "store_bytes": 0}

    fake2 = FakeReplayFail()
    result2 = await deep_consolidation(fake2)
    assert not result2.success
    assert "replay_now" in result2.error
    assert result2.metadata["downscale_skipped"] == "replay failed"
    assert fake2.downscale_calls == 0


async def test_episodic_memory_downscale_maps_events_to_protect(bus, monkeypatch):
    """Mnemos.downscale maps ReplayEvent objects to core protect triples."""
    core = EpisodicMemoryCore(FakeEmbedder(latent_dim=DIM), InMemoryStorage(latent_dim=DIM), entity_clock=_Clock())
    await core.initialize()
    m = EpisodicMemory(bus, core=core)

    recorded = []

    async def recorder(protect=()):
        recorded.append(list(protect))
        return {}

    monkeypatch.setattr(m.core, "downscale", recorder)
    await m.downscale(
        protect=[
            ReplayEvent(point_id="p", loop_payload={}, observer_payload={}, collection="mnemos_episodic", log_base=-0.5),
            ReplayEvent(point_id="short_term:0", loop_payload={}, observer_payload={}),
        ]
    )
    assert recorded == [[("mnemos_episodic", "p", -0.5)]]


async def test_config(bus):
    """Factory validates sleep-strength configuration."""
    with pytest.raises(ConfigurationError):
        make_sleep(None, {"consolidation": {"downscale_factor": 0.9}})

    with pytest.raises(ValueError):
        make_episodic_memory(bus, {"backend": "inmemory", "strength": {"retention_per_day": 1.5}})

    with pytest.raises(ValueError):
        make_episodic_memory(bus, {"backend": "inmemory", "strength": {"prune_floor": 0.0}})

    with pytest.raises(ConfigurationError):
        make_episodic_memory(bus, {"backend": "inmemory", "storage_budget_bytes": 0})

    with pytest.raises(ConfigurationError):
        make_episodic_memory(bus, {"backend": "inmemory", "storage_budget_bytes": True})

    with pytest.raises(ValueError, match="unknown"):
        make_episodic_memory(bus, {"backend": "inmemory", "strength": {"bogus": 1}})

    assert make_episodic_memory(bus, {"backend": "inmemory"}).core._traces_per_day == 288000.0
    assert (
        make_episodic_memory(bus, {"backend": "inmemory", "strength": {"traces_per_day": 1000}})
        .core._traces_per_day
        == 1000.0
    )

    with pytest.raises(ConfigurationError):
        make_episodic_memory(bus, {"backend": "inmemory", "strength": {"traces_per_day": 0}})

    with pytest.raises(ConfigurationError):
        make_episodic_memory(bus, {"backend": "inmemory", "strength": {"traces_per_day": True}})


# ------------------------------------------------------------------
# Pruning
# ------------------------------------------------------------------


async def test_replayed_traces_exempt_from_budget(storage):
    """Replayed traces are exempt from the byte budget."""
    core = await _core(storage, traces_per_day=4.0, budget_bytes=1)
    for i in range(4):
        await core.store(f"o{i}", collection="episodic")
    summary1 = await core.downscale()
    assert summary1["pruned_floor"] == 0
    assert summary1["pruned_budget"] == 4
    assert _flat(await core.storage.export(core.persisted_collection_names())) == []

    for i in range(4):
        await core.store(f"n{i}", collection="episodic")
    protect = await _protect(core, ["n0", "n1"])
    summary2 = await core.downscale(protect=protect)
    assert summary2["pruned_floor"] == 0
    assert summary2["pruned_budget"] == 2
    exported = _flat(await core.storage.export(core.persisted_collection_names()))
    texts = {p["text"] for p in exported}
    assert texts == {"n0", "n1"}
    for p in exported:
        assert core.strength_of(p["payload"]) == pytest.approx(1.0, abs=1e-12)
    total_size = sum(int(p["payload"]["size_bytes"]) for p in exported)
    assert summary2["store_bytes"] == total_size


async def test_budget_prunes_weakest_then_oldest(storage):
    """Budget pruning removes the weakest trace, breaking ties by entity time."""
    clock = _Clock()
    core = await _core(storage, clock=clock, traces_per_day=4.0)
    for text in ("o0", "o1", "o2"):
        clock.t += 1.0
        await core.store(text, collection="episodic")
    await core.downscale()
    for text in ("n0", "n1"):
        clock.t += 1.0
        await core.store(text, collection="episodic")
    await core.downscale()

    exported = _flat(await core.storage.export(core.persisted_collection_names()))
    size_o0 = int(next(p["payload"]["size_bytes"] for p in exported if p["text"] == "o0"))
    B = core.store_bytes - size_o0 - 1

    core2 = await _core(storage, clock=clock, traces_per_day=4.0, budget_bytes=B)
    summary = await core2.downscale()
    assert summary["n_new"] == 0
    assert summary["factor"] == pytest.approx(1.0, rel=1e-12)
    assert summary["pruned_floor"] == 0
    assert summary["pruned_budget"] == 2

    exported2 = _flat(await core2.storage.export(core2.persisted_collection_names()))
    texts = {p["text"] for p in exported2}
    assert texts == {"o2", "n0", "n1"}
    assert core2.store_bytes <= B


async def test_no_pruning_while_awake(storage):
    """Traces are deleted only during sleep, never while the entity is awake."""
    core = await _core(storage, budget_bytes=1, short_term_capacity=2)
    for i in range(6):
        await core.store(f"s{i}", collection="short_term")
    for i in range(3):
        await core.store(f"e{i}", collection="episodic")
    exported = _flat(await core.storage.export(core.persisted_collection_names()))
    assert len(exported) == 7
    assert core.short_term_size == 2
    assert core.store_bytes > 1
    summary = await core.downscale()
    assert summary["pruned_budget"] == 7
    assert _flat(await core.storage.export(core.persisted_collection_names())) == []


async def test_store_bytes_matches_a_scan(storage):
    """store_bytes tracks the persisted store size exactly."""
    core = await _core(storage, traces_per_day=4.0)
    for i in range(3):
        await core.store(f"a{i}", collection="episodic")
    await core.downscale()
    for i in range(2):
        await core.store(f"b{i}", collection="episodic")
    protect = await _protect(core, ["b0"])
    await core.downscale(protect=protect)
    scan = await storage.total_size(core.persisted_collection_names())
    assert core.store_bytes == scan

    core2 = await _core(storage, traces_per_day=4.0)
    assert core2.store_bytes == scan


async def test_preserved_bundle_unaffected_by_later_pruning(storage, request, tmp_path):
    """An exported bundle keeps every point even if the live store is pruned."""
    core = await _core(storage, traces_per_day=4.0)
    for i in range(5):
        await core.store(f"x{i}", collection="episodic")
    await core.downscale()
    state = await core.export_state()
    expected = copy.deepcopy(state["persisted"])

    core._budget_bytes = 1
    summary = await core.downscale()
    # The live store was pruned; the captured bundle was not.
    assert summary["pruned_budget"] == 5
    assert _flat(await core.storage.export(core.persisted_collection_names())) == []
    assert state["persisted"] == expected

    kind = request.node.callspec.params["storage"]
    (tmp_path / "c").mkdir(exist_ok=True)
    storage2 = await _open_storage(kind, tmp_path / "c")
    try:
        core2 = await _core(storage2)
        await core2.import_state(state)
        exported = _flat(await core2.storage.export(core2.persisted_collection_names()))
        assert len(exported) == 5
        assert {p["text"] for p in exported} == {f"x{i}" for i in range(5)}
    finally:
        await storage2.shutdown()


async def test_weakest_orders_across_collections(storage):
    """weakest returns points in ascending order across collections and is tie-complete."""
    await storage.ensure_collection("ca")
    await storage.ensure_collection("cb")

    rng = random.Random(17)
    for i in range(12):
        lb = -3.0 + (i % 3)
        vector = _unit([rng.gauss(0.0, 1.0) for _ in range(DIM)])
        await storage.upsert(
            "ca",
            vector=vector,
            text=f"ca-{i}",
            payload={"log_base": lb, "entity_time": float(i), "size_bytes": 100},
            affect=None,
        )

    cycle_cb = [-2.5, -2.0, -0.5]
    for i in range(12):
        lb = cycle_cb[i % 3]
        vector = _unit([rng.gauss(0.0, 1.0) for _ in range(DIM)])
        await storage.upsert(
            "cb",
            vector=vector,
            text=f"cb-{i}",
            payload={"log_base": lb, "entity_time": float(i), "size_bytes": 100},
            affect=None,
        )

    text_by = {
        (p["collection"], _key(p["id"])): p["text"]
        for p in _flat(await storage.export(["ca", "cb"]))
    }

    brute = sorted(
        [
            (-3.0 + (i % 3), float(i), f"ca-{i}")
            for i in range(12)
        ]
        + [
            (cycle_cb[i % 3], float(i), f"cb-{i}")
            for i in range(12)
        ],
        key=lambda t: (t[0], t[1], t[2]),
    )

    for limit in (1, 3, 5, 9, 30):
        got = await storage.weakest(["ca", "cb"], limit=limit)
        assert len(got) >= min(limit, 24)

        pairs = []
        for p in got:
            assert p["size_bytes"] == 100
            text = text_by[(p["collection"], _key(p["id"]))]
            lb = float(p["log_base"])
            et = float(p["entity_time"])
            pairs.append((lb, et, text))

        for a, b in zip(pairs, pairs[1:]):
            assert (a[0], a[1]) <= (b[0], b[1])

        expected = brute[: len(got)]
        assert sorted((lb, et) for lb, et, _ in pairs) == sorted(
            (lb, et) for lb, et, _ in expected
        )

        # Tie-complete: every point at or below the last returned strength is returned.
        if pairs:
            last_lb = pairs[-1][0]
            returned = {text for _, _, text in pairs}
            for lb, _, text in brute:
                if lb <= last_lb:
                    assert text in returned


async def test_failed_delete_mid_prune_keeps_s_true(storage):
    """A failed delete leaves store_bytes and meta bytes aligned with the real store."""
    core = await _core(storage, traces_per_day=4.0)
    for i in range(3):
        await core.store(f"e{i}", collection="episodic")
    for i in range(3):
        await core.store(f"s{i}", collection="semantic")
    await core.downscale()

    core2 = await _core(storage, traces_per_day=4.0, budget_bytes=1)

    original_delete = storage.delete_points
    call_count = 0

    async def wrapped_delete_points(collection, ids):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return await original_delete(collection, ids)
        raise RuntimeError("disk gone")

    storage.delete_points = wrapped_delete_points
    try:
        with pytest.raises(RuntimeError, match="disk gone"):
            await core2.downscale()
    finally:
        storage.delete_points = original_delete

    scan = await storage.total_size(core2.persisted_collection_names())
    assert core2.store_bytes == scan
    meta = await storage.read_meta(core2.strength_key)
    assert meta["bytes"] == scan

    exported = _flat(await core2.storage.export(core2.persisted_collection_names()))
    assert len(exported) == 3

    # One byte over the budget: exactly one more deletion is needed.
    B = scan - 1

    core3 = await _core(storage, traces_per_day=4.0, budget_bytes=B)
    summary = await core3.downscale()
    assert summary["pruned_budget"] == 1
    assert len(_flat(await core3.storage.export(core3.persisted_collection_names()))) == 2
    assert core3.store_bytes <= B


async def test_crash_mid_prune_then_restart_does_not_over_prune(storage):
    """A fresh core after a crash resumes with the correct byte count."""
    core = await _core(storage, traces_per_day=4.0)
    for i in range(3):
        await core.store(f"e{i}", collection="episodic")
    for i in range(3):
        await core.store(f"s{i}", collection="semantic")
    await core.downscale()

    core2 = await _core(storage, traces_per_day=4.0, budget_bytes=1)

    original_delete = storage.delete_points
    call_count = 0

    async def wrapped_delete_points(collection, ids):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return await original_delete(collection, ids)
        raise RuntimeError("disk gone")

    storage.delete_points = wrapped_delete_points
    try:
        with pytest.raises(RuntimeError, match="disk gone"):
            await core2.downscale()
    finally:
        storage.delete_points = original_delete

    core3 = await _core(storage, traces_per_day=4.0)
    scan = await storage.total_size(core3.persisted_collection_names())
    assert core3.store_bytes == scan
    summary = await core3.downscale()
    assert summary["n_new"] == 0
    assert summary["factor"] == pytest.approx(1.0, rel=1e-12)
    assert summary["pruned_floor"] == 0
    assert summary["pruned_budget"] == 0
    assert len(_flat(await core3.storage.export(core3.persisted_collection_names()))) == 3


async def test_import_pending_blocks_sleep_until_reimport(storage, request, tmp_path, caplog):
    """An interrupted import blocks sleep until a successful re-import clears it."""
    core = await _core(storage, traces_per_day=4.0)
    for i in range(3):
        await core.store(f"x{i}", collection="episodic")
    await core.downscale()
    state = await core.export_state()

    kind = request.node.callspec.params["storage"]
    (tmp_path / "import").mkdir(parents=True, exist_ok=True)
    storage2 = await _open_storage(kind, tmp_path / "import")
    try:
        original_replace = storage2.replace_collection
        call_count = 0

        async def wrapped_replace_collection(name, points):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("replace failed")
            return await original_replace(name, points)

        storage2.replace_collection = wrapped_replace_collection
        core2 = await _core(storage2)

        with pytest.raises(RuntimeError, match="replace failed"):
            await core2.import_state(state)

        meta = await storage2.read_meta(core2.strength_key)
        assert meta.get("import_pending") is True

        summary1 = await core2.downscale()
        assert summary1["blocked"] == "import_pending"
        assert summary1["blocked_sleeps"] == 1

        summary2 = await core2.downscale()
        assert summary2["blocked"] == "import_pending"
        assert summary2["blocked_sleeps"] == 2

        meta2 = await storage2.read_meta(core2.strength_key)
        assert meta2.get("import_pending") is True
        assert meta2.get("blocked_sleeps") == 2

        with caplog.at_level(logging.ERROR, logger="kaine.modules.episodic_memory.memory"):
            core3 = await _core(storage2)

        error_records = [
            r
            for r in caplog.records
            if r.levelno == logging.ERROR and "interrupted" in r.message
        ]
        assert error_records

        summary3 = await core3.downscale()
        assert summary3["blocked"] == "import_pending"
        assert summary3["blocked_sleeps"] == 3

        storage2.replace_collection = original_replace
        await core3.import_state(state)
        meta3 = await storage2.read_meta(core3.strength_key)
        assert meta3.get("import_pending") in (None, False)
        assert meta3.get("blocked_sleeps") in (None, 0)

        summary4 = await core3.downscale()
        assert summary4["blocked"] is None
        assert summary4["blocked_sleeps"] == 0
    finally:
        await storage2.shutdown()


async def test_strength_is_clamped_and_finite():
    """Strength is capped at 1 and rejects non-finite inputs."""
    storage = InMemoryStorage(latent_dim=DIM)
    await storage.initialize()
    try:
        core = await _core(storage)
        assert core.strength_of({"log_base": 5.0}) == pytest.approx(1.0, abs=1e-12)
        core._log_gain = 1e308
        with pytest.raises(StorageError):
            core.strength_of({"log_base": 1e308})
    finally:
        await storage.shutdown()


async def test_recall_search_rounds_are_bounded():
    """Recall grows its search limit and stops once the top result is exact."""
    storage = InMemoryStorage(latent_dim=DIM)
    await storage.initialize()
    try:
        rng = random.Random(13)
        e0 = [1.0] + [0.0] * (DIM - 1)
        table = {"q": e0}
        for i in range(600):
            eps = rng.uniform(0.05, 0.15)
            vec = _unit([1.0, eps] + [0.0] * (DIM - 2))
            table[f"t{i}"] = vec
        embedder = _TableEmbedder(table)
        core = await _core(storage, embedder=embedder, traces_per_day=600.0)

        for i in range(600):
            await core.store(f"t{i}", collection="episodic")
        await core.downscale()

        original_search = storage.search
        call_count = 0

        async def wrapped_search(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return await original_search(*args, **kwargs)

        storage.search = wrapped_search
        results, _ = await core.recall("q", k=1)
        assert call_count <= 4
        assert len(results) == 1

        qvec = await embedder.encode("q")
        exported = _flat(await core.storage.export(core.persisted_collection_names()))
        best = max(
            (core.strength_of(p["payload"]) * _cos(qvec, p["vector"]), _key(p["id"]))
            for p in exported
        )
        assert _key(results[0].point_id) == best[1]
    finally:
        await storage.shutdown()


async def test_sqlite_search_ties_across_page_boundaries(tmp_path):
    """sqlite-vec search returns exact top-k when ties cross page boundaries."""
    pytest.importorskip("sqlite_vec")
    s = SqliteVecStorage(latent_dim=DIM, db_path=str(tmp_path / "m.db"))
    await s.initialize()
    try:
        rng = random.Random(0)
        q = _unit([1.0] * DIM)
        points = []
        for g in range(10):
            vec = _unit([rng.gauss(0.0, 1.0) for _ in range(DIM)])
            for i in range(7):
                points.append(
                    {
                        "id": f"g{g}-{i}",
                        "text": "x",
                        "payload": {"log_base": 0.0},
                        "vector": vec,
                        "affect": None,
                    }
                )
        await s.replace_collection("c", points)

        brute = sorted(
            ((_cos(q, p["vector"]), p["id"]) for p in points),
            key=lambda t: t[0],
            reverse=True,
        )
        for limit in (1, 6, 7, 8, 20, 69, 70, 100):
            hits = await s.search("c", query_vector=q, limit=limit)
            n = min(limit, 70)
            assert len(hits) == n
            ids = [h.point_id for h in hits]
            assert len(set(ids)) == len(ids)
            scores = [h.score for h in hits]
            assert scores == sorted(scores, reverse=True)
            got = sorted(round(sc, 6) for sc in scores)
            exp = sorted(round(sc, 6) for sc, _ in brute[:n])
            assert got == exp
    finally:
        await s.shutdown()
