# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Trace-strength downscaling for sleep, paper A.10."""

from __future__ import annotations

import copy
import math
import random
import struct
import uuid
from pathlib import Path
from typing import Any

import pytest

from kaine.boot.errors import ConfigurationError
from kaine.boot.factories.hypnos import make_hypnos
from kaine.boot.factories.mnemos import make_mnemos
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.hypnos.phases import deep_consolidation
from kaine.modules.mnemos import (
    FakeEmbedder,
    InMemoryStorage,
    Mnemos,
    MnemosCore,
)
from kaine.modules.mnemos.replay import ReplayEvent
from kaine.modules.mnemos.storage import (
    QdrantStorage,
    SqliteVecStorage,
    StorageError,
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


async def _core(storage, *, embedder=None, clock=None, **kw) -> MnemosCore:
    """Create and initialize a MnemosCore over the given storage."""
    core = MnemosCore(
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


async def _strengths(core: MnemosCore) -> dict[str, float]:
    """Map normalized point id to current strength for persisted points."""
    points = _flat(await core.storage.export(core.persisted_collection_names()))
    return {_key(p["id"]): core.strength_of(p["payload"]) for p in points}


async def _protect(core: MnemosCore, texts: list[str]) -> list[tuple[str, str, float]]:
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


async def _key_ids_from_texts(core: MnemosCore, texts: list[str]) -> set[str]:
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
    core = await _core(storage, embedder=embedder, traces_per_day=10.0, silence_floor=0.3)

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
            if core.is_silent(p["payload"]):
                continue
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


async def test_silent_traces(storage):
    """Silent traces remain stored but are excluded from recall."""
    e0 = [1.0] + [0.0] * (DIM - 1)
    table = {"q": e0, "a": e0, "z": [0.0] * (DIM - 1) + [1.0]}
    core = await _core(storage, embedder=_TableEmbedder(table), traces_per_day=1.0, silence_floor=0.7)
    await core.store("a", collection="episodic")
    for _ in range(3):
        await core.store("z", collection="episodic")
        await core.downscale()
    results, _ = await core.recall("q", k=5)
    assert "a" not in [r.text for r in results]
    exported = _flat(await core.storage.export(core.persisted_collection_names()))
    assert any(p["text"] == "a" for p in exported)
    summary = await core.downscale()
    assert summary["silent"] >= 1


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
    }

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
        {"log_gain": -5000.0, "sleeps": 7, "total": 0.0, "entity_time": 0.0},
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
        core = await _core(storage, traces_per_day=24.0)
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


async def test_sqlite_min_log_base_filter_pages(tmp_path):
    """sqlite-vec search pages correctly with min_log_base filtering."""
    pytest.importorskip("sqlite_vec")
    s = SqliteVecStorage(latent_dim=DIM, db_path=str(tmp_path / "m.db"))
    await s.initialize()
    try:
        rng = random.Random(13)
        q = _unit([rng.gauss(0.0, 1.0) for _ in range(DIM)])
        near = []
        for i in range(5000):
            near.append(
                {
                    "id": f"n{i}",
                    "text": "x",
                    "payload": {"log_base": -10.0},
                    "vector": _unit([q[j] + rng.gauss(0.0, 0.01) for j in range(DIM)]),
                    "affect": None,
                }
            )
        far = []
        for i in range(5):
            far.append(
                {
                    "id": f"f{i}",
                    "text": "x",
                    "payload": {"log_base": 0.0},
                    "vector": _unit([rng.gauss(0.0, 1.0) for _ in range(DIM)]),
                    "affect": None,
                }
            )
        await s.replace_collection("c", near + far)
        hits = await s.search("c", query_vector=q, limit=5, min_log_base=-1.0)
        assert len(hits) == 5
        for h in hits:
            assert h.point_id.startswith("f")
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
    core = MnemosCore(FakeEmbedder(latent_dim=DIM), InMemoryStorage(latent_dim=DIM), short_term_capacity=8, entity_clock=clock)
    await core.initialize()
    m = Mnemos(bus, core=core, replay_selection_top_k=5)

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
    core = MnemosCore(FakeEmbedder(latent_dim=DIM), InMemoryStorage(latent_dim=DIM), short_term_capacity=8, entity_clock=clock)
    await core.initialize()
    m = Mnemos(bus, core=core, replay_selection_top_k=1)

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


async def test_cross_period_selection_skips_silent(bus):
    """Cross-period selection does not include silent traces."""
    core = MnemosCore(
        FakeEmbedder(latent_dim=DIM),
        InMemoryStorage(latent_dim=DIM),
        traces_per_day=1.0,
        silence_floor=0.7,
        entity_clock=_Clock(),
    )
    await core.initialize()
    m = Mnemos(bus, core=core)
    await m.core.store("old", collection="episodic")
    for i in range(3):
        await m.core.store(f"filler-{i}", collection="episodic")
        await m.core.downscale()
    buckets = await m.select_cross_period_traces(periods=1, per_period=50)
    texts = _all_bucket_texts(buckets)
    assert "old" not in texts
    # The newest filler is not silent and is selected, so the check is not vacuous.
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
            return {"n_new": 3, "factor": 0.9, "protected": 2, "total_before": 5.0, "total_after": 4.6, "silent": 0}

    fake = FakeOk()
    result = await deep_consolidation(fake)
    assert result.success
    assert fake.protect == [sentinel_a, sentinel_b]
    expected_meta = {"n_new": 3, "factor": 0.9, "protected": 2, "total_before": 5.0, "total_after": 4.6, "silent": 0}
    assert result.metadata["downscale"] == expected_meta

    class FakeReplayFail:
        def open_replay_window(self): pass
        def close_replay_window(self): pass
        async def replay_now(self):
            raise RuntimeError("replay failed")
        async def downscale(self, protect=()):
            self.protect = list(protect)
            return {"n_new": 0, "factor": 1.0, "protected": 0, "total_before": 1.0, "total_after": 1.0, "silent": 0}

    fake2 = FakeReplayFail()
    result2 = await deep_consolidation(fake2)
    assert not result2.success
    assert "replay_now" in result2.error
    assert fake2.protect == []


async def test_mnemos_downscale_maps_events_to_protect(bus, monkeypatch):
    """Mnemos.downscale maps ReplayEvent objects to core protect triples."""
    core = MnemosCore(FakeEmbedder(latent_dim=DIM), InMemoryStorage(latent_dim=DIM), entity_clock=_Clock())
    await core.initialize()
    m = Mnemos(bus, core=core)

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
        make_hypnos(None, {"consolidation": {"downscale_factor": 0.9}})

    with pytest.raises(ValueError):
        make_mnemos(bus, {"backend": "inmemory", "strength": {"retention_per_day": 1.5}})

    with pytest.raises(ValueError):
        make_mnemos(bus, {"backend": "inmemory", "strength": {"silence_floor": 0.0}})

    with pytest.raises(Exception):
        make_mnemos(bus, {"backend": "inmemory", "strength": {"bogus": 1}})

    m = make_mnemos(bus, {"backend": "inmemory", "_traces_per_day": 1000.0})
    assert m.core._traces_per_day == 1000.0
