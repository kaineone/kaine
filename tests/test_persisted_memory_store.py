# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for persisted episodic-memory stores after a legacy rename."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kaine import legacy_names
from kaine.lifecycle.decommission import delete_entity_state
from kaine.memory_kinds import EPISODIC_MEMORY_COLLECTION_KINDS
from kaine.modules.episodic_memory import (
    EpisodicMemoryCore,
    FakeEmbedder,
    InMemoryStorage,
)
from kaine.modules.episodic_memory.storage import QdrantStorage

OLD_PREFIX = next(
    e["old"] for e in legacy_names.COLLECTIONS if e["new"] == "episodic_memory_"
)

DIM = 8


def _seed(state_root: Path) -> None:
    """Minimal on-disk state so delete_entity_state can run."""
    for path in ("self_model/f.json", "language/f.json", "perception/f.json"):
        p = state_root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}", encoding="utf-8")
    fork_snap = state_root / "forks" / "s1"
    fork_snap.mkdir(parents=True, exist_ok=True)
    (fork_snap / "snapshot.json").write_text(
        json.dumps({"id": "s1", "metadata": {}}), encoding="utf-8"
    )
    (state_root / "sleep" / "adapters").mkdir(parents=True, exist_ok=True)
    (state_root / "sleep" / "adapters" / "a.bin").write_bytes(b"w")
    (state_root / "cycle").mkdir(parents=True, exist_ok=True)
    (state_root / "cycle" / "runtime.json").write_text("{}", encoding="utf-8")
    (state_root / "cycle" / "control.json").write_text("{}", encoding="utf-8")


@pytest.mark.asyncio
async def test_qdrant_alias_resolves_existing_collection():
    """A renamed store reaches an old collection through a new-named alias."""
    qc = pytest.importorskip("qdrant_client")
    from qdrant_client import models

    storage = QdrantStorage(latent_dim=DIM, api_key="test")
    storage._client = qc.AsyncQdrantClient(location=":memory:")
    await storage.initialize()

    old_name = OLD_PREFIX + "episodic"
    await storage._client.create_collection(
        collection_name=old_name,
        vectors_config=models.VectorParams(
            size=DIM, distance=models.Distance.COSINE
        ),
    )
    await storage._client.upsert(
        collection_name=old_name,
        points=[
            models.PointStruct(
                id=1,
                vector=[1.0] * DIM,
                payload={"text": "hello"},
            )
        ],
    )
    await storage._client.update_collection_aliases(
        change_aliases_operations=[
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(
                    alias_name="episodic_memory_episodic",
                    collection_name=old_name,
                )
            )
        ]
    )

    await storage.ensure_collection("episodic_memory_episodic")
    collections = await storage._client.get_collections()
    assert {c.name for c in collections.collections} == {old_name}

    assert await storage.count("episodic_memory_episodic") == 1


@pytest.mark.asyncio
async def test_meta_records_carried_from_legacy_prefix():
    """Legacy meta/stamp records are copied under the new prefix on first read."""
    embedder = FakeEmbedder(latent_dim=DIM)
    storage = InMemoryStorage(latent_dim=DIM)
    await storage.initialize()

    old_strength = {
        "log_gain": 0.0,
        "sleeps": 2,
        "total": 1.0,
        "entity_time": 0.0,
        "bytes": 64,
    }
    await storage.write_meta(OLD_PREFIX + "strength", old_strength)
    await storage.write_stamp(OLD_PREFIX + "embedding_space", dict(embedder.space))

    await storage.upsert(
        collection="episodic_memory_episodic",
        vector=[1.0] * DIM,
        text="carried test",
        payload={"log_base": 0.5},
        affect=None,
        point_id="trace-1",
    )

    core = EpisodicMemoryCore(
        embedder=embedder,
        storage=storage,
        collection_prefix="episodic_memory_",
    )
    # Simulate the initialization reads that previously failed after a rename.
    await core._check_embedding_space_stamp()
    await core._init_strength()

    assert await storage.read_meta("episodic_memory_strength") == old_strength
    assert await storage.read_meta(OLD_PREFIX + "strength") == old_strength
    assert await storage.read_stamp(
        "episodic_memory_embedding_space"
    ) == dict(embedder.space)
    assert await storage.read_stamp(
        OLD_PREFIX + "embedding_space"
    ) == dict(embedder.space)


class _FakeQdrantClient:
    def __init__(self) -> None:
        self.collections: dict[str, Any] = {
            OLD_PREFIX + kind: None for kind in EPISODIC_MEMORY_COLLECTION_KINDS
        }
        self.deleted_collections: list[str] = []
        self.aliases_operations: list[Any] = []
        self.closed = False

    def get_collections(self):
        out = []
        for name in self.collections:
            c = type("_Coll", (), {})()
            c.name = name
            out.append(c)
        return type("_Collections", (), {"collections": out})()

    def get_aliases(self):
        out = []
        for kind in EPISODIC_MEMORY_COLLECTION_KINDS:
            a = type("_Alias", (), {})()
            a.alias_name = "episodic_memory_" + kind
            a.collection_name = OLD_PREFIX + kind
            out.append(a)
        return type("_Aliases", (), {"aliases": out})()

    def update_collection_aliases(self, change_aliases_operations):
        self.aliases_operations.extend(change_aliases_operations)

    def delete_collection(self, collection_name):
        self.deleted_collections.append(collection_name)

    def delete(self, *, collection_name, points_selector):
        pass

    def close(self):
        self.closed = True


def test_decommission_drops_renamed_aliases_and_old_collections(
    tmp_path, monkeypatch
):
    """Decommission deletes new-named aliases and the old collections they hid."""
    from kaine.lifecycle import decommission

    fake = _FakeQdrantClient()
    monkeypatch.setattr(decommission, "_qdrant_client", lambda _cfg: fake)

    state_root = tmp_path / "state"
    _seed(state_root)

    result = delete_entity_state(
        state_root=state_root,
        qdrant_cfg={
            "modules": {"episodic_memory": True},
            "episodic_memory": {"backend": "qdrant", "qdrant": {"host": "127.0.0.1", "port": 1}},
        },
        dry_run=False,
    )

    alias_names = {
        op.delete_alias.alias_name for op in fake.aliases_operations
    }
    expected_aliases = {
        "episodic_memory_" + kind for kind in EPISODIC_MEMORY_COLLECTION_KINDS
    }
    assert alias_names == expected_aliases

    expected_old = {
        OLD_PREFIX + kind for kind in EPISODIC_MEMORY_COLLECTION_KINDS
    }
    assert expected_old <= set(fake.deleted_collections)

    assert fake.closed
    assert result.errors == []
    assert any(
        entry.startswith("alias:") for entry in result.dropped_collections
    )
