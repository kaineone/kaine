# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Mnemos subsystem: store + recall via the in-memory backend."""
from __future__ import annotations

import pytest

from kaine.modules.mnemos.module import Mnemos
from kaine.modules.mnemos.embeddings import FakeEmbedder

from tests.systems._harness import SubsystemHarness


@pytest.mark.asyncio
async def test_mnemos_constructs_with_inmemory_backend():
    async with SubsystemHarness() as h:
        mnemos = Mnemos(
            h.bus,
            embedder=FakeEmbedder(),
            backend="inmemory",
            short_term_capacity=8,
            recall_top_k=3,
        )
        await h.register(mnemos)
        # No exception at boot. Serialize returns a dict.
        state = mnemos.serialize()
        assert isinstance(state, dict)
        assert state.get("short_term_size", 0) == 0


@pytest.mark.asyncio
async def test_mnemos_short_term_accepts_external_speech():
    async with SubsystemHarness() as h:
        mnemos = Mnemos(
            h.bus,
            embedder=FakeEmbedder(),
            backend="inmemory",
            short_term_capacity=8,
            recall_top_k=3,
        )
        await h.register(mnemos)
        # Mnemos observes the bus; a Lingua external_speech event should
        # land in its short-term buffer (or at least not crash the module).
        await h.inject_to_stream(
            "lingua.external",
            source="lingua",
            type="external_speech",
            payload={"text": "hello world"},
        )
        # Drive Mnemos's workspace-driven consolidation by broadcasting.
        await h.broadcast_workspace({"tick_index": 0, "selected": []})
        # Smoke check: the module is still alive and serializing.
        assert mnemos.serialize() is not None
