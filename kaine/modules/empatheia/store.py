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

`EmpatheiaMergeStrategy` mirrors `MnemosMergeStrategy` in
``kaine.lifecycle.strategies``: reconcile two diverged `AgentStore`
snapshots by summing interaction counts (additive — both branches saw
real interactions) and merging emotion histograms via weighted average
(interaction count is the weight).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional, Protocol, runtime_checkable

from kaine.modules.empatheia.agent import AgentModel
from kaine.text_embedding import DEFAULT_LATENT_DIM

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class AgentStore(Protocol):
    async def initialize(self) -> None: ...

    async def shutdown(self) -> None: ...

    async def get(self, agent_id: str) -> Optional[AgentModel]: ...

    async def put(self, model: AgentModel) -> None: ...

    async def all_ids(self) -> list[str]: ...

    def serialize(self) -> bytes: ...

    def deserialize(self, data: bytes) -> None: ...


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

    async def initialize(self) -> None:
        return

    async def shutdown(self) -> None:
        return

    async def get(self, agent_id: str) -> Optional[AgentModel]:
        return self._profiles.get(agent_id)

    async def put(self, model: AgentModel) -> None:
        self._profiles[model.id] = model

    async def all_ids(self) -> list[str]:
        return list(self._profiles)

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
        # Local cache so serialize() works without an async context.
        self._cache: dict[str, AgentModel] = {}

    async def initialize(self) -> None:
        if self._client is not None:
            return
        import asyncio

        def _open():
            from qdrant_client import AsyncQdrantClient  # type: ignore[import-untyped]

            return AsyncQdrantClient(
                host=self._host,
                port=self._port,
                api_key=self._api_key,
                https=False,
            )

        self._client = await asyncio.to_thread(_open)
        await self._ensure_collection()

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

    async def _embed(self, model: AgentModel) -> list[float]:
        """Return an embedding for the agent's behavioral summary.

        The embedding is derived from a textual rendering of the
        behavioral summary (numeric features only — no raw sense data).
        Falls back to a zero vector if no embedder is available.
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
                log.warning("QdrantAgentStore embed failed", exc_info=True)
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

    async def put(self, model: AgentModel) -> None:
        self._cache[model.id] = model
        if self._client is None:
            return
        try:
            from qdrant_client import models  # type: ignore[import-untyped]

            vector = await self._embed(model)
            profile_json = json.dumps(model.to_dict())
            payload = {"agent_id": model.id, "profile_json": profile_json}
            # Use agent_id as a stable point ID (hex-encoded for Qdrant).
            point_id = model.id.encode("utf-8").hex()
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
        except Exception:
            log.warning("QdrantAgentStore.put failed for %s", model.id, exc_info=True)

    async def all_ids(self) -> list[str]:
        return list(self._cache)

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


# ---------------------------------------------------------------------------
# Merge strategy (for the fork/merge subsystem)
# ---------------------------------------------------------------------------


class EmpatheiaMergeStrategy:
    """Reconcile two diverged AgentStore snapshots.

    Semantics
    ---------
    - interaction_count: SUM — both branches saw real interactions.
    - emotion_histogram: weighted average by interaction count — each
      branch's histogram is weighted by how many observations it made.
    - behavioral_summary: weighted average by interaction count.
    - reliability: weighted average by interaction count.
    - first_seen: min (earliest observation).
    - last_seen: max (most recent observation).

    The merged profile is persisted to the store before completing.
    """

    def merge(
        self,
        state_a: dict[str, Any] | None,
        state_b: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if state_a is None and state_b is None:
            return {}
        if state_a is None:
            return dict(state_b or {})
        if state_b is None:
            return dict(state_a or {})

        profiles_a: dict[str, Any] = state_a.get("profiles", {})
        profiles_b: dict[str, Any] = state_b.get("profiles", {})
        all_ids = set(profiles_a) | set(profiles_b)

        merged_profiles: dict[str, Any] = {}
        for agent_id in all_ids:
            pa = profiles_a.get(agent_id)
            pb = profiles_b.get(agent_id)
            if pa is None:
                merged_profiles[agent_id] = dict(pb)
            elif pb is None:
                merged_profiles[agent_id] = dict(pa)
            else:
                merged_profiles[agent_id] = _merge_profiles(pa, pb)

        return {"profiles": merged_profiles}


def _merge_profiles(
    pa: dict[str, Any], pb: dict[str, Any]
) -> dict[str, Any]:
    """Merge two AgentModel dicts by weighted average."""
    count_a = int(pa.get("interaction_count", 0))
    count_b = int(pb.get("interaction_count", 0))
    total = count_a + count_b

    if total == 0:
        # No observations on either side — take pa as base.
        return dict(pa)

    w_a = count_a / total
    w_b = count_b / total

    # Merge emotion histogram (weighted average).
    hist_a = pa.get("emotion_histogram") or {}
    hist_b = pb.get("emotion_histogram") or {}
    all_cats = set(hist_a) | set(hist_b)
    merged_hist = {
        cat: w_a * float(hist_a.get(cat, 0.0)) + w_b * float(hist_b.get(cat, 0.0))
        for cat in all_cats
    }

    # Merge behavioral_summary (weighted average).
    bsummary_a = pa.get("behavioral_summary") or {}
    bsummary_b = pb.get("behavioral_summary") or {}
    all_bkeys = set(bsummary_a) | set(bsummary_b)
    merged_bsummary = {
        k: w_a * float(bsummary_a.get(k, 0.0)) + w_b * float(bsummary_b.get(k, 0.0))
        for k in all_bkeys
    }

    # Reliability: weighted average.
    reliability = (
        w_a * float(pa.get("reliability", 1.0))
        + w_b * float(pb.get("reliability", 1.0))
    )

    return {
        "id": pa.get("id") or pb.get("id"),
        "label": pa.get("label") or pb.get("label"),
        "emotion_histogram": merged_hist,
        "behavioral_summary": merged_bsummary,
        "reliability": reliability,
        "interaction_count": total,
        "first_seen": min(
            float(pa.get("first_seen", 0.0)), float(pb.get("first_seen", 0.0))
        ),
        "last_seen": max(
            float(pa.get("last_seen", 0.0)), float(pb.get("last_seen", 0.0))
        ),
    }


async def apply_merged_state(
    store: AgentStore,
    merged_state: dict[str, Any],
) -> None:
    """Persist every profile in a merged state dict to the store.

    Called by the fork/merge manager after ``EmpatheiaMergeStrategy.merge``
    to satisfy the requirement that merged profiles are persisted before
    the merge completes.
    """
    profiles = merged_state.get("profiles") or {}
    for agent_id, profile_dict in profiles.items():
        model = AgentModel.from_dict(profile_dict)
        await store.put(model)
