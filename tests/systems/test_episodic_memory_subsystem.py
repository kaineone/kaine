# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The episodic memory subsystem: store + recall via the in-memory backend."""
from __future__ import annotations

import pytest

from kaine.modules.episodic_memory.embeddings import FakeEmbedder
from kaine.modules.episodic_memory.module import EpisodicMemory
from tests.systems._harness import SubsystemHarness


@pytest.mark.asyncio
async def test_episodic_memory_constructs_with_inmemory_backend():
    async with SubsystemHarness() as h:
        episodic_memory = EpisodicMemory(
            h.bus,
            embedder=FakeEmbedder(),
            backend="inmemory",
            short_term_capacity=8,
            recall_top_k=3,
        )
        await h.register(episodic_memory)
        # No exception at boot. Serialize returns a dict.
        state = episodic_memory.serialize()
        assert isinstance(state, dict)
        assert state.get("short_term_size", 0) == 0


@pytest.mark.asyncio
async def test_episodic_memory_short_term_accepts_external_speech():
    async with SubsystemHarness() as h:
        episodic_memory = EpisodicMemory(
            h.bus,
            embedder=FakeEmbedder(),
            backend="inmemory",
            short_term_capacity=8,
            recall_top_k=3,
        )
        await h.register(episodic_memory)
        # the episodic memory module observes the bus; a language module external_speech event should
        # land in its short-term buffer (or at least not crash the module).
        await h.inject_to_stream(
            "language.external",
            source="language",
            type="external_speech",
            payload={"text": "hello world"},
        )
        # Drive the episodic memory module's workspace-driven consolidation by broadcasting.
        await h.broadcast_workspace({"tick_index": 0, "selected": []})
        # Smoke check: the module is still alive and serializing.
        assert episodic_memory.serialize() is not None
