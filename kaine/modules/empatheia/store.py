# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Agent profile persistence for Empatheia.

`AgentStore` is the protocol. `QdrantAgentStore` is the production
backend (collection ``empatheia_agents``, all-MiniLM-L6-v2 embeddings
from the single boundary-neutral :mod:`kaine.text_embedding` wrapper —
the same embedder and cosine scale Mnemos and the evaluation sidecar use).
`InMemoryAgentStore` is the deterministic test backend (no external
services required).

Both backends implement `serialize()` / `deserialize()` losslessly for
the fork/merge subsystem.

Fork merges reconcile these snapshots with `EmpatheiaMergeStrategy` in
``kaine.lifecycle.strategies`` (interaction counts summed; histograms,
behavioural summaries and reliability averaged with interaction count as
the weight).
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Optional, Protocol, Sequence, runtime_checkable

from kaine.modules.empatheia.agent import AgentModel
from kaine.text_embedding import DEFAULT_LATENT_DIM

log = logging.getLogger(__name__)


# Namespace used to derive deterministic Qdrant point IDs from agent IDs.
_AGENT_ID_NAMESPACE = uuid.UUID("5b0c7d2e-8f41-4a3c-9d6e-1f2a3b4c5d6e")


def _point_id(agent_id: str) -> str:
    """Return a deterministic Qdrant point id (UUIDv5) for ``agent_id``."""
    return str(uuid.uuid5(_AGENT_ID_NAMESPACE, agent_id))


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class AgentStore(Protocol):
    async def initialize(self) -> None:
        """Protocol member: initialize."""

    async def shutdown(self) -> None:
        """Protocol member: shutdown."""

    async def get(self, agent_id: str) -> Optional[AgentModel]:
        """Protocol member: get."""

    async def put(self, model: AgentModel) -> None:
        """Protocol member: put."""

    async def all_ids(self) -> list[str]:
        """Protocol member: all ids."""

    async def all_profiles(self) -> dict[str, AgentModel]:
        """Protocol member: all profiles."""

    async def replace_all(self, models: Sequence[AgentModel]) -> None:
        """Protocol member: replace all."""

    def serialize(self) -> bytes:
        """Protocol member: serialize."""

    def deserialize(self, data: bytes) -> None:
        """Protocol member: deserialize."""


# ---------------------------------------------------------------------------
# In-memory backend (tests + minimal deployments)
# ---------------------------------------------------------------------------


class InMemoryAgentStore:
    """Pure-Python backend for tests.

    All profiles live in a dict; ``serialize``/``deserialize`` use JSON
    so the round-trip is lossless for all numeric/string fields.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, AgentModel] = {}
        self._initialized = False

    async def initialize(self) -> None:
        self._initialized = True
        return

    async def shutdown(self) -> None:
        return

    async def get(self, agent_id: str) -> Optional[AgentModel]:
        return self._profiles.get(agent_id)

    async def put(self, model: AgentModel) -> None:
        self._profiles[model.id] = model

    async def all_ids(self) -> list[str]:
        return list(self._profiles)

    async def all_profiles(self) -> dict[str, AgentModel]:
        return dict(self._profiles)

    async def replace_all(self, models: Sequence[AgentModel]) -> None:
        self._profiles.clear()
        for model in models:
            self._profiles[model.id] = model

    def serialize(self) -> bytes:
        payload = {
            agent_id: model.to_dict()
            for agent_id, model in self._profiles.items()
        }
        return json.dumps(payload).encode("utf-8")

    def deserialize(self, data: bytes) -> None:
        payload: dict[str, Any] = json.loads(data.decode("utf-8"))
        self._profiles = {
            agent_id: AgentModel.from_dict(d)
            for agent_id, d in payload.items()
        }


# ---------------------------------------------------------------------------
# Qdrant backend (production)
# ---------------------------------------------------------------------------


class QdrantAgentStore:
    """Qdrant-backed agent profile store.

    Uses the all-MiniLM-L6-v2 embedder (reused from Mnemos) to store a
    behavioral summary embedding alongside the profile JSON payload.
    This enables future similarity search over known agents.

    The embedder is optional at construction time (for tests that inject
    an InMemoryAgentStore instead); if not provided, embeddings default
    to a zero vector of the declared latent_dim.

    Profiles are keyed by agent_id in the Qdrant payload so they can be
    fetched by scroll / filter — we don't rely on point ID stability
    across restarts.
    """

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 6533,
        api_key: str,
        collection: str = "empatheia_agents",
        latent_dim: int = DEFAULT_LATENT_DIM,
        embedder: Any = None,
    ) -> None:
        if not api_key:
            raise ValueError(
                "QdrantAgentStore requires api_key"
            )
        self._host = host
        self._port = int(port)
        self._api_key = api_key
        self._collection = collection
        self._latent_dim = int(latent_dim)
        self._embedder = embedder
        self._client: Any = None
        self._initialized = False
        # Local cache so serialize() works without an async context.
        self._cache: dict[str, AgentModel] = {}
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def initialize(self) -> None:
        if self._initialized:
            return
        if self._client is None:
            await self._open_client()
        await self._ensure_collection()
        self._initialized = True

    async def _open_client(self) -> None:
        def _open():
            from qdrant_client import AsyncQdrantClient  # type: ignore[import-untyped]

            return AsyncQdrantClient(
                host=self._host,
                port=self._port,
                api_key=self._api_key,
                https=False,
            )

        self._client = await asyncio.to_thread(_open)

    async def _ensure_collection(self) -> None:
        from qdrant_client import models  # type: ignore[import-untyped]

        assert self._client is not None
        existing = await self._client.get_collections()
        existing_names = {c.name for c in existing.collections}
        if self._collection not in existing_names:
            await self._client.create_collection(
                collection_name=self._collection,
                vectors_config=models.VectorParams(
                    size=self._latent_dim,
                    distance=models.Distance.COSINE,
                ),
            )

    async def shutdown(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                log.warning("QdrantAgentStore close failed", exc_info=True)
            self._client = None

    async def _build_embedding(self, model: AgentModel) -> list[float]:
        """Return an embedding for the agent's behavioral summary.

        The embedding is derived from a textual rendering of the
        behavioral summary (numeric features only — no raw sense data).
        Falls back to a zero vector when no embedder is configured or
        the embedder fails, because only the profile payload is ever
        read back.
        """
        summary_text = (
            f"agent:{model.label} "
            f"reliability:{model.reliability:.3f} "
            f"interactions:{model.interaction_count} "
            + " ".join(
                f"{k}:{v:.3f}"
                for k, v in sorted(model.emotion_histogram.items())
                if v > 0.0
            )
        )
        if self._embedder is not None:
            try:
                return await self._embedder.encode(summary_text)
            except Exception:
                log.warning("QdrantAgentStore embed failed; storing the profile with a zero vector", exc_info=True)
        return [0.0] * self._latent_dim

    async def get(self, agent_id: str) -> Optional[AgentModel]:
        # Try cache first (avoids Qdrant roundtrip in hot paths).
        if agent_id in self._cache:
            return self._cache[agent_id]
        if self._client is None:
            return None
        try:
            from qdrant_client import models  # type: ignore[import-untyped]

            result = await self._client.scroll(
                collection_name=self._collection,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="agent_id",
                            match=models.MatchValue(value=agent_id),
                        )
                    ]
                ),
                limit=1,
                with_payload=True,
            )
            points, _ = result
            if not points:
                return None
            payload = dict(points[0].payload or {})
            profile_json = payload.get("profile_json", "")
            if not profile_json:
                return None
            d = json.loads(profile_json)
            model = AgentModel.from_dict(d)
            self._cache[agent_id] = model
            return model
        except Exception:
            log.warning("QdrantAgentStore.get failed for %s", agent_id, exc_info=True)
            return None

    async def _put_strict(self, model: AgentModel) -> None:
        from qdrant_client import models  # type: ignore[import-untyped]

        assert self._client is not None
        vector = await self._build_embedding(model)
        profile_json = json.dumps(model.to_dict())
        payload = {"agent_id": model.id, "profile_json": profile_json}
        # Qdrant point ids must be an unsigned integer or a UUID.
        point_id = _point_id(model.id)
        await self._client.upsert(
            collection_name=self._collection,
            points=[
                models.PointStruct(
                    id=point_id,
                    vector=list(vector),
                    payload=payload,
                )
            ],
        )

    async def put(self, model: AgentModel) -> None:
        self._cache[model.id] = model
        if self._client is None:
            return
        try:
            async with self._get_lock():
                await self._put_strict(model)
        except Exception:
            log.warning("QdrantAgentStore.put failed for %s", model.id, exc_info=True)

    async def all_ids(self) -> list[str]:
        return list(self._cache)

    async def all_profiles(self) -> dict[str, AgentModel]:
        if self._client is None:
            raise RuntimeError(
                "QdrantAgentStore is not initialized: no Qdrant client"
            )
        profiles: dict[str, AgentModel] = {}
        offset = None
        try:
            while True:
                points, offset = await self._client.scroll(
                    collection_name=self._collection,
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for p in points:
                    payload = dict(getattr(p, "payload", None) or {})
                    profile_json = payload.get("profile_json")
                    if not profile_json:
                        continue
                    d = json.loads(profile_json)
                    model = AgentModel.from_dict(d)
                    profiles[model.id] = model
                if offset is None:
                    break
        except Exception as exc:
            raise RuntimeError(
                f"QdrantAgentStore.all_profiles failed for collection {self._collection!r}: {exc}"
            ) from exc
        profiles.update(self._cache)
        return profiles

    async def replace_all(self, models: Sequence[AgentModel]) -> None:
        if self._client is None:
            raise RuntimeError(
                "QdrantAgentStore is not initialized: no Qdrant client"
            )
        async with self._get_lock():
            try:
                existing = await self._client.get_collections()
                existing_names = {c.name for c in existing.collections}
                if self._collection in existing_names:
                    await self._client.delete_collection(collection_name=self._collection)
            except Exception as exc:
                raise RuntimeError(
                    f"QdrantAgentStore.replace_all failed deleting {self._collection!r}: {exc}"
                ) from exc
            await self._ensure_collection()
            self._cache.clear()
            for model in models:
                await self._put_strict(model)

    def serialize(self) -> bytes:
        """Lossless snapshot of all known profiles (from cache)."""
        payload = {
            agent_id: model.to_dict()
            for agent_id, model in self._cache.items()
        }
        return json.dumps(payload).encode("utf-8")

    def deserialize(self, data: bytes) -> None:
        """Restore profiles from a snapshot (populates cache; Qdrant sync is lazy)."""
        payload: dict[str, Any] = json.loads(data.decode("utf-8"))
        self._cache = {
            agent_id: AgentModel.from_dict(d)
            for agent_id, d in payload.items()
        }
