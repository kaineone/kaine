# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Load-bearing: a Phantasia training pass writes NO files to disk.

Training is in-memory only. The trajectory buffer is never serialized. This test
snapshots /tmp and the project directory before a training pass and asserts that
no new `.pt`/`.pkl`/`.npy`/`.arrow`/`.jsonl` files appeared afterward.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.phantasia.module import Phantasia


BANNED_EXTENSIONS = (".pt", ".pkl", ".npy", ".arrow", ".jsonl")


def _scan(root: Path) -> set[Path]:
    found: set[Path] = set()
    if not root.exists():
        return found
    for path in root.rglob("*"):
        try:
            if path.is_file() and path.suffix.lower() in BANNED_EXTENSIONS:
                found.add(path)
        except OSError:
            continue
    return found


def _event(source: str, type_: str, salience: float = 0.5) -> Event:
    return Event(
        source=source,
        type=type_,
        payload={},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _snapshot(tick: int) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=tick,
        selected_events=[("0-0", _event("soma", "soma.report", 0.5))],
    )


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


@pytest.mark.asyncio
async def test_training_pass_writes_no_disk_artifacts(bus: AsyncBus):
    project_root = Path(__file__).parent.parent
    tmp_root = Path("/tmp")

    ph = Phantasia(bus, backend="fake", training_enabled=True)
    await ph.initialize()
    try:
        for i in range(20):
            await ph.on_workspace(_snapshot(i))

        pre_tmp = _scan(tmp_root)
        pre_project = _scan(project_root)

        # Run the in-memory training pass (the operation under test).
        outcome = ph.train_now()
        assert outcome.steps > 0
        assert not outcome.aborted

        # Also run scenario generation (imagination rollout) for good measure.
        await ph._handle_peer_event(
            "hypnos.out", _event("hypnos", "hypnos.sleep.started")
        )
        await ph.generate_scenario(seed_memory_id="m")

        post_tmp = _scan(tmp_root)
        post_project = _scan(project_root)
    finally:
        await ph.shutdown()

    leaked = (post_tmp - pre_tmp) | (post_project - pre_project)
    assert leaked == set(), (
        "ZERO-PERSISTENCE VIOLATED: training/imagination wrote disk artifacts: "
        f"{sorted(str(p) for p in leaked)}"
    )


@pytest.mark.asyncio
async def test_buffer_never_serialized(bus: AsyncBus):
    """serialize() must not contain the trajectory buffer contents."""
    ph = Phantasia(bus, backend="fake")
    await ph.initialize()
    try:
        for i in range(10):
            await ph.on_workspace(_snapshot(i))
        assert ph.buffer_size == 10
        state = ph.serialize()
        # No list-of-vectors anywhere in the serialized state.
        for value in state.values():
            assert not (isinstance(value, list) and value and isinstance(value[0], list))
    finally:
        await ph.shutdown()
