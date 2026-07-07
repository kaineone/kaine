# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Verified end-to-end preservation + revive (entity-preservation-on-divergence).

Covers PR-1 (the capture/restore core):

* Mnemos real capture/restore for BOTH backends — InMemoryStorage end-to-end
  here; QdrantStorage export/import at the codec level + the fail-loud path when
  the store is unreachable.
* Phantasia world-model weight capture into the bundle (capability-bearing fake;
  a jax-gated DreamerV3 round-trip when the extra is present).
* ForkManager.preserve_live (live snapshot + encrypted bundle, run-stamped) and
  revive (reconstruct the same individual), with the fail-loud paths.

Continuity asserted on revive: self-model identity/values match, planted
memories are recallable, world-model weights match (when captured), adapters
present. Fail-loud paths: an uncapturable component raises (no partial bundle);
a revive that would drop a captured component raises.
"""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.experiment.run_context import RunContext, set_run_context
from kaine.lifecycle.manager import ForkManager
from kaine.lifecycle.preservation import PreservationError, ReviveError
from kaine.modules.eidolon import Eidolon, SelfModel
from kaine.modules.mnemos import FakeEmbedder, InMemoryStorage, Mnemos, MnemosCore
from kaine.modules.mnemos.storage import QdrantStorage, StorageError
from kaine.modules.phantasia.encoder import observation_dim
from kaine.modules.phantasia.module import Phantasia
from kaine.modules.phantasia.world_model import (
    CheckpointMismatchError,
    FakeWorldModel,
)
from kaine.modules.registry import ModuleRegistry
from kaine.security.crypto import (
    CryptoConfig,
    StateEncryptor,
    is_encrypted,
    set_state_encryptor,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


@pytest.fixture(autouse=True)
def _plaintext_encryptor():
    # Default: plaintext at rest so tests can introspect bundle contents.
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


@pytest.fixture(autouse=True)
def _run_context():
    set_run_context(
        RunContext(
            run_id="testrun0123456789",
            seed=7,
            started_at=datetime.now(timezone.utc).isoformat(),
            git_sha=None,
        )
    )
    yield
    set_run_context(None)


class _PersistableFake(FakeWorldModel):
    """FakeWorldModel + a real export/import codec (no jax needed).

    The codec is a faithful, deterministic serialization of the learned EMA
    decay weight — so we can assert weights survive preservation/revive without
    the [worldmodel] extra. Production gates persistence on this capability,
    which the plain FakeWorldModel lacks.
    """

    def export_params(self, *, extra=None) -> bytes:
        return json.dumps(
            {"decay": self._decay, "extra": dict(extra or {})}, sort_keys=True
        ).encode()

    def import_params(self, blob: bytes, *, extra=None) -> None:
        data = json.loads(blob)
        if data.get("extra") != dict(extra or {}):
            raise CheckpointMismatchError(
                f"extra mismatch: {data.get('extra')} != {dict(extra or {})}"
            )
        self._decay = float(data["decay"])


async def _build_mnemos(bus: AsyncBus, *, storage=None) -> Mnemos:
    emb = FakeEmbedder(latent_dim=8)
    await emb.load()
    storage = storage or InMemoryStorage(latent_dim=emb.latent_dim)
    core = MnemosCore(embedder=emb, storage=storage, short_term_capacity=8)
    m = Mnemos(bus, core=core)
    await m.initialize()
    return m


async def _build_synthetic_entity(
    bus: AsyncBus,
    tmp_path: Path,
    *,
    persist_phantasia: bool,
) -> tuple[ModuleRegistry, Path]:
    """A synthetic-but-REAL entity: Eidolon + Mnemos(in-memory) + Phantasia.

    Returns (registry, phantasia_checkpoint_path).
    """
    reg = ModuleRegistry()

    # Eidolon self-model with concrete identity + values.
    eidolon = Eidolon(
        bus, persistence_path=tmp_path / "self_model.json", save_interval_s=60
    )
    await eidolon.initialize()
    eidolon._model = SelfModel(name="Aria", values=["honesty", "curiosity"])
    eidolon._drift_count = 3
    reg.register(eidolon)

    # Mnemos with planted memories (short-term + persisted episodic).
    mnemos = await _build_mnemos(bus)
    await mnemos.core.store("I remember the blue door", collection="short_term")
    await mnemos.core.store(
        "The lighthouse keeper waved",
        affect={"intensity": 0.8, "valence": 0.5, "dominance": 0.1},
        collection="episodic",
    )
    reg.register(mnemos)

    # Phantasia — capability-bearing fake so weights can be captured w/o jax.
    ckpt = tmp_path / "phantasia" / "wm.ckpt"
    wm = _PersistableFake(obs_dim=observation_dim(), decay=0.42)
    phantasia = Phantasia(
        bus,
        world_model=wm,
        backend="dreamerv3" if persist_phantasia else "fake",
        persist_weights=persist_phantasia,
        checkpoint_path=str(ckpt),
    )
    await phantasia.initialize()
    reg.register(phantasia)

    return reg, ckpt


# ---------------------------------------------------------------------------
# Mnemos capture/restore — InMemoryStorage (end-to-end)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mnemos_inmemory_export_import_roundtrip(bus: AsyncBus):
    m = await _build_mnemos(bus)
    try:
        await m.core.store("alpha note", collection="short_term")
        await m.core.store(
            "beta episodic",
            affect={"intensity": 0.6, "valence": 0.2, "dominance": 0.0},
            collection="episodic",
        )
        captured = await m.export_preservation_state()
        assert captured["memory_state"]["short_term"]
        assert any(captured["memory_state"]["persisted"].values())

        # Restore into a fresh, empty Mnemos.
        m2 = await _build_mnemos(bus)
        n = await m2.import_preservation_state(captured)
        assert n >= 1
        assert m2.core.short_term_size == 1
        results, _ = await m2.core.recall("beta", collection="episodic")
        assert any("beta episodic" in r.text for r in results)
    finally:
        await m.shutdown()


# ---------------------------------------------------------------------------
# Mnemos capture/restore — QdrantStorage (codec + fail-loud)
# ---------------------------------------------------------------------------


class _FakeQdrantPoint:
    def __init__(self, pid, vector, payload):
        self.id = pid
        self.vector = vector
        self.payload = payload


class _FakeAsyncQdrant:
    """Minimal in-process double of AsyncQdrantClient for export/import."""

    def __init__(self):
        self.store: dict[str, list[_FakeQdrantPoint]] = {}

    class _Colls:
        def __init__(self, names):
            self.collections = [type("C", (), {"name": n}) for n in names]

    async def get_collections(self):
        return self._Colls(list(self.store))

    async def create_collection(self, collection_name, vectors_config):
        self.store.setdefault(collection_name, [])

    async def scroll(self, collection_name, limit, offset, with_payload, with_vectors):
        pts = self.store.get(collection_name, [])
        return pts, None

    async def upsert(self, collection_name, points):
        self.store.setdefault(collection_name, [])
        for p in points:
            self.store[collection_name].append(
                _FakeQdrantPoint(p.id, list(p.vector), dict(p.payload))
            )


@pytest.mark.asyncio
async def test_qdrant_export_import_roundtrip_codec():
    pytest.importorskip("qdrant_client")
    src = QdrantStorage(latent_dim=4, api_key="k")
    src._client = _FakeAsyncQdrant()
    await src.upsert(
        "mnemos_episodic",
        vector=[0.1, 0.2, 0.3, 0.4],
        text="planted memory",
        payload={"timestamp": 1.0},
        affect={"intensity": 0.9},
        point_id="p1",
    )
    dump = await src.export()
    assert dump["mnemos_episodic"][0]["text"] == "planted memory"
    assert dump["mnemos_episodic"][0]["affect"] == {"intensity": 0.9}

    dst = QdrantStorage(latent_dim=4, api_key="k")
    dst._client = _FakeAsyncQdrant()
    n = await dst.import_(dump)
    assert n == 1
    redump = await dst.export()
    assert redump["mnemos_episodic"][0]["vector"] == [0.1, 0.2, 0.3, 0.4]
    assert redump["mnemos_episodic"][0]["text"] == "planted memory"


@pytest.mark.asyncio
async def test_qdrant_export_fails_loud_when_unreachable():
    pytest.importorskip("qdrant_client")

    class _Broken:
        async def get_collections(self):
            raise ConnectionError("server unreachable")

    s = QdrantStorage(latent_dim=4, api_key="k")
    s._client = _Broken()
    with pytest.raises(StorageError, match="could not list collections"):
        await s.export()


# ---------------------------------------------------------------------------
# Full preserve_live -> revive continuity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preserve_live_then_revive_same_individual(bus: AsyncBus, tmp_path: Path):
    reg, ckpt = await _build_synthetic_entity(bus, tmp_path, persist_phantasia=True)
    fm = ForkManager(tmp_path / "forks")

    result = await fm.preserve_live(
        reg,
        reason="individuation",
        label="test-crossing",
        out_root=tmp_path / "backups",
        entity_name="aria",
    )
    assert result.ok
    assert result.run_id == "testrun0123456789"
    assert result.preservation_id
    assert result.world_model_captured is True
    bundle = tmp_path / "backups" / f"preservation_{result.preservation_id}_aria"
    # S5: entity-interior content is tarred (encryption disabled here → plaintext
    # bundle.tar); only the non-sensitive manifest stays loose. The loose
    # snapshot.json / phantasia/ originals are removed after tarring.
    assert (bundle / "manifest.json").is_file()
    assert (bundle / "bundle.tar").is_file()
    assert not (bundle / "snapshot.json").exists()
    assert not (bundle / "phantasia").exists()
    # World-model weights rode along inside the tar.
    import tarfile as _tarfile

    with _tarfile.open(bundle / "bundle.tar") as _tf:
        _names = _tf.getnames()
    assert "snapshot.json" in _names
    assert "phantasia/wm.ckpt" in _names

    # The live entity is untouched (read-only) and nothing was deleted.
    assert reg.get("eidolon").model.name == "Aria"
    assert list((tmp_path / "forks").iterdir())  # snapshot persisted

    # --- Revive into a FRESH registry ----------------------------------
    reg2 = ModuleRegistry()
    eid2 = Eidolon(
        bus, persistence_path=tmp_path / "self_model2.json", save_interval_s=60
    )
    await eid2.initialize()
    reg2.register(eid2)
    mnemos2 = await _build_mnemos(bus)
    reg2.register(mnemos2)
    wm2 = _PersistableFake(obs_dim=observation_dim(), decay=0.99)  # different init
    ph2 = Phantasia(
        bus,
        world_model=wm2,
        backend="dreamerv3",
        persist_weights=True,
        checkpoint_path=str(tmp_path / "phantasia2" / "wm.ckpt"),
    )
    await ph2.initialize()
    reg2.register(ph2)

    await fm.revive(bundle, reg2)

    # Continuity: self-model identity + values match.
    assert reg2.get("eidolon").model.name == "Aria"
    assert reg2.get("eidolon").model.values == ["honesty", "curiosity"]

    # Continuity: planted memories are recallable.
    st_results, _ = await mnemos2.core.recall("blue", collection="short_term")
    assert any("blue door" in r.text for r in st_results)
    ep_results, _ = await mnemos2.core.recall("lighthouse", collection="episodic")
    assert any("lighthouse keeper" in r.text for r in ep_results)

    # Continuity: world-model weights match (the captured decay was restored
    # into the live model, overwriting the 0.99 fresh init).
    assert wm2._decay == pytest.approx(0.42)

    try:
        await eid2.shutdown()
        await mnemos2.shutdown()
        await ph2.shutdown()
    finally:
        for m in reg.all_modules():
            await m.shutdown()


@pytest.mark.asyncio
async def test_preserve_live_sanitizes_operator_label(bus: AsyncBus, tmp_path: Path):
    """S8 — a path-like operator label is sanitized in the manifest."""
    reg, _ = await _build_synthetic_entity(bus, tmp_path, persist_phantasia=False)
    fm = ForkManager(tmp_path / "forks")
    try:
        result = await fm.preserve_live(
            reg,
            reason="manual",
            label="../../etc/passwd evil/label",
            out_root=tmp_path / "backups",
            entity_name="aria",
        )
        bundle = tmp_path / "backups" / f"preservation_{result.preservation_id}_aria"
        manifest = json.loads((bundle / "manifest.json").read_text())
        label = manifest["label"]
        # Only alphanumerics + - _ survive; no path separators or dots.
        assert "/" not in label
        assert "." not in label
        assert ".." not in label
        assert all(c.isalnum() or c in "-_" for c in label)
    finally:
        for m in reg.all_modules():
            await m.shutdown()


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics")
@pytest.mark.asyncio
async def test_preserve_live_bundle_dir_is_owner_only(bus: AsyncBus, tmp_path: Path):
    """S4 — the preservation bundle dir is 0700; the tar is 0600 (POSIX)."""
    reg, _ = await _build_synthetic_entity(bus, tmp_path, persist_phantasia=False)
    fm = ForkManager(tmp_path / "forks")
    try:
        result = await fm.preserve_live(
            reg, reason="manual", out_root=tmp_path / "backups", entity_name="aria"
        )
        bundle = tmp_path / "backups" / f"preservation_{result.preservation_id}_aria"
        assert (bundle.stat().st_mode & 0o777) == 0o700
        assert ((bundle / "bundle.tar").stat().st_mode & 0o077) == 0
    finally:
        for m in reg.all_modules():
            await m.shutdown()


@pytest.mark.asyncio
async def test_preserve_live_bundle_encrypted_at_rest(
    bus: AsyncBus, tmp_path: Path, monkeypatch
):
    """With state encryption on, the snapshot rides the StateEncryptor (the
    preserved individual is encrypted at rest) and still revives."""
    monkeypatch.setenv(
        "KAINE_STATE_KEY", base64.b64encode(os.urandom(32)).decode("ascii")
    )
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=True)))
    try:
        reg, _ = await _build_synthetic_entity(bus, tmp_path, persist_phantasia=False)
        fm = ForkManager(tmp_path / "forks")
        result = await fm.preserve_live(
            reg, reason="manual", out_root=tmp_path / "backups", entity_name="aria"
        )
        bundle = tmp_path / "backups" / f"preservation_{result.preservation_id}_aria"
        # S5: entity-interior content is tarred and the tar is StateEncryptor-
        # encrypted; no loose plaintext snapshot.json remains.
        assert (bundle / "bundle.tar.enc").is_file()
        assert not (bundle / "snapshot.json").exists()
        assert not (bundle / "bundle.tar").exists()
        raw = (bundle / "bundle.tar.enc").read_bytes()
        assert b"honesty" not in raw  # self-model value not in plaintext
        assert is_encrypted(base64.b64decode(raw))

        # Revive still works (encryption-aware reader).
        reg2 = ModuleRegistry()
        eid2 = Eidolon(
            bus, persistence_path=tmp_path / "sm2.json", save_interval_s=60
        )
        await eid2.initialize()
        reg2.register(eid2)
        m2 = await _build_mnemos(bus)
        reg2.register(m2)
        ph2 = Phantasia(bus, world_model=FakeWorldModel(observation_dim()), backend="fake")
        await ph2.initialize()
        reg2.register(ph2)
        await fm.revive(bundle, reg2)
        assert reg2.get("eidolon").model.values == ["honesty", "curiosity"]
        await eid2.shutdown()
        await m2.shutdown()
        await ph2.shutdown()
    finally:
        set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
        for m in reg.all_modules():
            await m.shutdown()


@pytest.mark.asyncio
async def test_preserve_live_records_world_model_not_captured_honestly(
    bus: AsyncBus, tmp_path: Path
):
    # Fake backend / persistence off → honestly recorded as NOT captured.
    reg, _ = await _build_synthetic_entity(bus, tmp_path, persist_phantasia=False)
    fm = ForkManager(tmp_path / "forks")
    try:
        result = await fm.preserve_live(
            reg, reason="manual", out_root=tmp_path / "backups", entity_name="aria"
        )
        assert result.ok
        assert result.world_model_captured is False
        snap = fm.load(result.snapshot_id)
        rec = snap.modules["phantasia"]["world_model_capture"]
        assert rec["captured"] is False
        assert "nothing learned" in rec["reason"]
    finally:
        for m in reg.all_modules():
            await m.shutdown()


# ---------------------------------------------------------------------------
# Fail-loud paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preserve_live_fails_loud_when_memory_uncapturable(
    bus: AsyncBus, tmp_path: Path
):
    """An unreachable memory store must abort preservation, not emit a partial
    bundle that looks complete."""
    pytest.importorskip("qdrant_client")
    reg = ModuleRegistry()
    eidolon = Eidolon(
        bus, persistence_path=tmp_path / "sm.json", save_interval_s=60
    )
    await eidolon.initialize()
    reg.register(eidolon)

    emb = FakeEmbedder(latent_dim=4)
    await emb.load()
    qs = QdrantStorage(latent_dim=4, api_key="k")

    class _Broken:
        async def get_collections(self):
            raise ConnectionError("unreachable")

    qs._client = _Broken()
    core = MnemosCore(embedder=emb, storage=qs, short_term_capacity=4)
    mnemos = Mnemos(bus, core=core)
    reg.register(mnemos)

    fm = ForkManager(tmp_path / "forks")
    with pytest.raises(PreservationError, match="preservation capture failed"):
        await fm.preserve_live(
            reg, reason="individuation", out_root=tmp_path / "backups",
            entity_name="aria",
        )
    # No bundle was written.
    assert not (tmp_path / "backups").exists() or not list(
        (tmp_path / "backups").iterdir()
    )
    await eidolon.shutdown()


@pytest.mark.asyncio
async def test_phantasia_preservation_fails_loud_when_checkpoint_save_fails(
    bus: AsyncBus, tmp_path: Path
):
    class _UnsavableFake(_PersistableFake):
        def export_params(self, *, extra=None) -> bytes:
            raise OSError("disk gone")

    wm = _UnsavableFake(obs_dim=observation_dim())
    ph = Phantasia(
        bus,
        world_model=wm,
        backend="dreamerv3",
        persist_weights=True,
        checkpoint_path=str(tmp_path / "p" / "wm.ckpt"),
    )
    await ph.initialize()
    try:
        with pytest.raises(RuntimeError, match="checkpoint save .* FAILED"):
            ph.export_preservation_weights()
    finally:
        # shutdown also tries to save; swallow its error path explicitly.
        try:
            await ph.shutdown()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_revive_fails_loud_when_module_missing(bus: AsyncBus, tmp_path: Path):
    reg, _ = await _build_synthetic_entity(bus, tmp_path, persist_phantasia=False)
    fm = ForkManager(tmp_path / "forks")
    try:
        result = await fm.preserve_live(
            reg, reason="manual", out_root=tmp_path / "backups", entity_name="aria"
        )
        bundle = tmp_path / "backups" / f"preservation_{result.preservation_id}_aria"

        # Target registry missing mnemos (a captured module) → fail loud.
        reg2 = ModuleRegistry()
        eid2 = Eidolon(
            bus, persistence_path=tmp_path / "sm2.json", save_interval_s=60
        )
        await eid2.initialize()
        reg2.register(eid2)
        with pytest.raises(ReviveError, match="missing modules"):
            await fm.revive(bundle, reg2)
        await eid2.shutdown()
    finally:
        for m in reg.all_modules():
            await m.shutdown()


@pytest.mark.asyncio
async def test_revive_fails_loud_when_captured_weights_absent_from_bundle(
    bus: AsyncBus, tmp_path: Path
):
    """Coverage gap: the bundle's snapshot RECORDS captured world-model weights
    but the phantasia checkpoint is missing from the tar. Revive must raise
    ReviveError ("…absent…") — never silently revive a world-model-less lesser
    individual. (Bundles are now tar; we rewrite bundle.tar to drop the
    phantasia/ member while keeping snapshot.json's captured=True record.)"""
    import tarfile

    reg, ckpt = await _build_synthetic_entity(bus, tmp_path, persist_phantasia=True)
    fm = ForkManager(tmp_path / "forks")
    try:
        result = await fm.preserve_live(
            reg, reason="individuation", out_root=tmp_path / "backups",
            entity_name="aria",
        )
        assert result.world_model_captured is True
        bundle = tmp_path / "backups" / f"preservation_{result.preservation_id}_aria"
        tar_path = bundle / "bundle.tar"

        # Rewrite the (plaintext) tar keeping ONLY snapshot.json — the phantasia
        # checkpoint the snapshot claims is captured is now absent from the tar.
        with tarfile.open(tar_path) as tf:
            snap_member = tf.getmember("snapshot.json")
            snap_bytes = tf.extractfile(snap_member).read()
            assert any(n.startswith("phantasia/") for n in tf.getnames())
        tar_path.unlink()
        with tarfile.open(tar_path, "w") as tf:
            info = tarfile.TarInfo("snapshot.json")
            info.size = len(snap_bytes)
            import io as _io

            tf.addfile(info, _io.BytesIO(snap_bytes))
        # Sanity: the phantasia checkpoint really is gone from the bundle.
        with tarfile.open(tar_path) as tf:
            assert not any(n.startswith("phantasia/") for n in tf.getnames())

        reg2 = ModuleRegistry()
        eid2 = Eidolon(bus, persistence_path=tmp_path / "sm2.json", save_interval_s=60)
        await eid2.initialize()
        reg2.register(eid2)
        m2 = await _build_mnemos(bus)
        reg2.register(m2)
        wm2 = _PersistableFake(obs_dim=observation_dim(), decay=0.99)
        ph2 = Phantasia(
            bus, world_model=wm2, backend="dreamerv3", persist_weights=True,
            checkpoint_path=str(tmp_path / "phantasia2" / "wm.ckpt"),
        )
        await ph2.initialize()
        reg2.register(ph2)
        with pytest.raises(ReviveError, match="absent"):
            await fm.revive(bundle, reg2)
        # The fresh model's init weights were NOT overwritten (no lesser revive
        # that quietly kept the wrong weights).
        assert wm2._decay == pytest.approx(0.99)
        await eid2.shutdown()
        await m2.shutdown()
        await ph2.shutdown()
    finally:
        for m in reg.all_modules():
            await m.shutdown()


@pytest.mark.asyncio
async def test_preserve_live_fails_loud_when_module_serialize_raises(
    bus: AsyncBus, tmp_path: Path
):
    """A module whose serialize() raises must abort the whole preservation with a
    PreservationError naming the module — and write NO bundle."""

    class _ExplodingModule:
        name = "saboteur"

        def serialize(self) -> dict:
            raise RuntimeError("cannot serialize self")

        def deserialize(self, state) -> None:  # pragma: no cover - never reached
            pass

    reg = ModuleRegistry()
    eidolon = Eidolon(bus, persistence_path=tmp_path / "sm.json", save_interval_s=60)
    await eidolon.initialize()
    reg.register(eidolon)
    reg.register(_ExplodingModule())

    fm = ForkManager(tmp_path / "forks")
    try:
        with pytest.raises(PreservationError, match="saboteur"):
            await fm.preserve_live(
                reg, reason="individuation", out_root=tmp_path / "backups",
                entity_name="aria",
            )
        # No bundle written.
        assert not (tmp_path / "backups").exists() or not list(
            (tmp_path / "backups").iterdir()
        )
    finally:
        await eidolon.shutdown()


@pytest.mark.asyncio
async def test_revive_fails_loud_on_corrupt_bundle(bus: AsyncBus, tmp_path: Path):
    """A bundle whose tar content is corrupt must raise on revive — never revive
    a silent empty individual."""
    reg, _ = await _build_synthetic_entity(bus, tmp_path, persist_phantasia=False)
    fm = ForkManager(tmp_path / "forks")
    try:
        result = await fm.preserve_live(
            reg, reason="manual", out_root=tmp_path / "backups", entity_name="aria"
        )
        bundle = tmp_path / "backups" / f"preservation_{result.preservation_id}_aria"
        # Corrupt the tar: overwrite with garbage that is not a valid tar archive.
        (bundle / "bundle.tar").write_bytes(b"\x00\x01\x02 not a tar at all \xff\xfe")

        reg2 = ModuleRegistry()
        eid2 = Eidolon(bus, persistence_path=tmp_path / "sm2.json", save_interval_s=60)
        await eid2.initialize()
        reg2.register(eid2)
        m2 = await _build_mnemos(bus)
        reg2.register(m2)
        # Either the tar fails to open (ReviveError) or it opens but carries no
        # snapshot.json (ReviveError "no snapshot.json"). Both are fail-loud.
        with pytest.raises(ReviveError):
            await fm.revive(bundle, reg2)
        # The fresh entity was NOT silently populated from an empty revive.
        assert reg2.get("eidolon").model.name != "Aria"
        await eid2.shutdown()
        await m2.shutdown()
    finally:
        for m in reg.all_modules():
            await m.shutdown()


@pytest.mark.asyncio
async def test_qdrant_import_fails_loud_on_upsert_error():
    """QdrantStorage.import_ must raise StorageError when the backend upsert
    fails — a revive that cannot restore the vector store must not silently
    produce a memory-poor lesser individual."""
    pytest.importorskip("qdrant_client")

    class _UpsertBroken(_FakeAsyncQdrant):
        async def upsert(self, collection_name, points):
            raise ConnectionError("upsert refused")

    dst = QdrantStorage(latent_dim=4, api_key="k")
    dst._client = _UpsertBroken()
    dump = {
        "mnemos_episodic": [
            {
                "id": "p1",
                "vector": [0.1, 0.2, 0.3, 0.4],
                "text": "planted memory",
                "payload": {"timestamp": 1.0},
                "affect": {"intensity": 0.9},
            }
        ]
    }
    with pytest.raises(StorageError, match="upserting into"):
        await dst.import_(dump)


@pytest.mark.asyncio
async def test_preservation_manifest_fields_match_result(
    bus: AsyncBus, tmp_path: Path
):
    """The loose (non-sensitive) manifest.json must agree with the
    PreservationResult on run_id / preservation_id / snapshot_id /
    world_model_captured / modules (the fields that ARE in the post-security
    manifest)."""
    reg, _ = await _build_synthetic_entity(bus, tmp_path, persist_phantasia=True)
    fm = ForkManager(tmp_path / "forks")
    try:
        result = await fm.preserve_live(
            reg, reason="individuation", out_root=tmp_path / "backups",
            entity_name="aria",
        )
        bundle = tmp_path / "backups" / f"preservation_{result.preservation_id}_aria"
        manifest = json.loads((bundle / "manifest.json").read_text())
        assert manifest["run_id"] == result.run_id == "testrun0123456789"
        assert manifest["preservation_id"] == result.preservation_id
        assert manifest["snapshot_id"] == result.snapshot_id
        assert manifest["world_model_captured"] == result.world_model_captured is True
        # modules list is the sorted set of captured module names.
        assert manifest["modules"] == sorted(
            m.name for m in reg.all_modules()
        )
        assert set(manifest["modules"]) == {"eidolon", "mnemos", "phantasia"}
        assert manifest["kind"] == "preservation"
        assert manifest["entity_name"] == "aria"
    finally:
        for m in reg.all_modules():
            await m.shutdown()


# ---------------------------------------------------------------------------
# jax-gated real DreamerV3 weight continuity (skipped if extra absent)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_dreamerv3_weight_capture_restore(bus: AsyncBus, tmp_path: Path):
    pytest.importorskip("jax")
    from kaine.modules.phantasia.world_model import DreamerV3WorldModel

    reg = ModuleRegistry()
    ckpt = tmp_path / "phantasia" / "wm.ckpt"
    wm = DreamerV3WorldModel(
        observation_dim(), deter_dim=8, stoch_dim=4, stoch_classes=3, hidden_dim=8
    )
    # Learn a little so weights are non-trivial.
    wm.train([[float((i + j) % 5) for j in range(observation_dim())] for i in range(8)])
    ph = Phantasia(
        bus, world_model=wm, backend="dreamerv3", persist_weights=True,
        checkpoint_path=str(ckpt),
    )
    await ph.initialize()
    reg.register(ph)
    fm = ForkManager(tmp_path / "forks")

    result = await fm.preserve_live(
        reg, reason="individuation", out_root=tmp_path / "backups",
        entity_name="aria",
    )
    assert result.world_model_captured
    bundle = tmp_path / "backups" / f"preservation_{result.preservation_id}_aria"
    captured_arrays = _npz_arrays(wm.export_params(extra={"encoder_version": _enc()}))

    # Revive into a fresh phantasia with a different random init.
    reg2 = ModuleRegistry()
    wm2 = DreamerV3WorldModel(
        observation_dim(), deter_dim=8, stoch_dim=4, stoch_classes=3,
        hidden_dim=8, seed=99,
    )
    ph2 = Phantasia(
        bus, world_model=wm2, backend="dreamerv3", persist_weights=True,
        checkpoint_path=str(tmp_path / "phantasia2" / "wm.ckpt"),
    )
    await ph2.initialize()
    reg2.register(ph2)
    await fm.revive(bundle, reg2)
    assert _npz_arrays(wm2.export_params(extra={"encoder_version": _enc()})) == (
        captured_arrays
    )

    await ph.shutdown()
    await ph2.shutdown()


def _enc() -> str:
    from kaine.modules.phantasia.encoder import VERSION

    return VERSION


def _npz_arrays(blob: bytes) -> dict[str, bytes]:
    """Name → raw array bytes (ignoring NPZ zip-container metadata)."""
    import io

    import numpy as np

    data = np.load(io.BytesIO(blob), allow_pickle=False)
    return {name: data[name].tobytes() for name in data.files}
