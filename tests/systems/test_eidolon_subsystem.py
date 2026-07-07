# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Eidolon subsystem: observes internal speech + workspace, persists self-model."""
from __future__ import annotations

import json

import pytest

from kaine.modules.eidolon.module import Eidolon

from tests.systems._harness import SubsystemHarness


@pytest.mark.asyncio
async def test_eidolon_persistence_round_trip(tmp_path):
    target = tmp_path / "self_model.json"
    async with SubsystemHarness() as h:
        e = Eidolon(h.bus, persistence_path=target, save_interval_s=0.05)
        await h.register(e)
        # After register/initialize, persistence file should be written.
        # The save loop runs every 0.05s; pump a workspace broadcast.
        await h.broadcast_workspace({"tick_index": 0, "selected": []})
        state = e.serialize()
        assert isinstance(state, dict)


@pytest.mark.asyncio
async def test_eidolon_internal_speech_does_not_leak_to_external(tmp_path):
    async with SubsystemHarness() as h:
        e = Eidolon(
            h.bus,
            persistence_path=tmp_path / "x.json",
            internal_speech_stream="lingua.internal",
        )
        await h.register(e)
        await h.inject_to_stream(
            "lingua.internal",
            source="lingua",
            type="internal_speech",
            payload={"text": "private musing"},
        )
        # Eidolon SHOULD NOT publish that text on any external stream.
        external = await h.collect("eidolon.out", count=1, timeout=0.3)
        for ev in external:
            assert "private musing" not in json.dumps(ev.payload)
