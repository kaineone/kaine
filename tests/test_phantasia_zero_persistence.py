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
async def test_training_pass_writes_no_disk_artifacts(
    bus: AsyncBus, tmp_path, monkeypatch
):
    """A Phantasia training/imagination pass writes NO model-state files to disk.

    Uses a private TMPDIR and an audit-hook write recorder so the test is
    hermetic and not affected by concurrent machine-wide /tmp traffic.
    """
    from tests.zero_persistence import (
        WriteRecorder,
        format_zero_persistence_failure,
        leaked_writes,
        redirect_temp,
        scan,
    )

    project_root = Path(__file__).parent.parent
    private_tmp = redirect_temp(tmp_path, monkeypatch)

    ph = Phantasia(bus, backend="fake", training_enabled=True)
    await ph.initialize()
    try:
        for i in range(20):
            await ph.on_workspace(_snapshot(i))

        pre_project = scan(project_root, BANNED_EXTENSIONS)
        pre_private = scan(private_tmp, BANNED_EXTENSIONS)

        with WriteRecorder() as recorder:
            # Run the in-memory training pass (the operation under test).
            outcome = ph.train_now()
            assert outcome.steps > 0
            assert not outcome.aborted

            # Also run scenario generation (imagination rollout) for good measure.
            await ph._handle_peer_event(
                "hypnos.out", _event("hypnos", "hypnos.sleep.started")
            )
            await ph.generate_scenario(seed_memory_id="m")

        post_project = scan(project_root, BANNED_EXTENSIONS)
        post_private = scan(private_tmp, BANNED_EXTENSIONS)
    finally:
        await ph.shutdown()

    by_path: dict[str, set[str]] = {}
    for p in leaked_writes(recorder.writes, BANNED_EXTENSIONS):
        by_path.setdefault(str(Path(p)), set()).add("recorder")
    for p in post_project - pre_project:
        by_path.setdefault(str(p), set()).add("project")
    for p in post_private - pre_private:
        by_path.setdefault(str(p), set()).add("tmpdir")

    assert not by_path, format_zero_persistence_failure(by_path)


def test_training_leak_detector_catches_real_leak(tmp_path, monkeypatch):
    """The write recorder and private-temp scan must catch transient and
    on-disk model-state leaks respectively."""
    import tempfile

    from tests.zero_persistence import WriteRecorder, leaked_writes, redirect_temp, scan

    private = redirect_temp(tmp_path, monkeypatch)
    with WriteRecorder() as recorder:
        # Transient model-state file: created and deleted while recording.
        with tempfile.NamedTemporaryFile(suffix=".pt", delete=True, dir=tmp_path) as f:
            f.write(b"x")
        # Lingering model-state file under the private temp dir.
        (private / "leak.pt").write_bytes(b"x")

    recorded = leaked_writes(recorder.writes, BANNED_EXTENSIONS)
    scanned = scan(private, BANNED_EXTENSIONS)

    assert any(Path(p).suffix.lower() == ".pt" for p in recorded), (
        "recorder missed transient .pt write"
    )
    assert any(p.name == "leak.pt" for p in scanned), (
        "scan missed .pt in private temp dir"
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
