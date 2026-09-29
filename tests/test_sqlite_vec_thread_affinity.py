# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The sqlite-vec store keeps its SQLite connection on one owning thread.

A ``sqlite3`` connection may only be used on the thread that created it
(``check_same_thread``), and a single connection is not safe for concurrent
use. :class:`SqliteVecStorage` therefore owns a dedicated single-worker
executor: the connection is opened, used and closed on that one thread for its
whole life, and every call is serialised through it.

These tests force the situation that made the store fail intermittently: the
event loop's default executor hands work to a *different* worker thread than
the one that opened the connection. They do it deterministically by swapping
the default executor, or by driving the store from another event loop on
another thread.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sqlite_vec = pytest.importorskip("sqlite_vec")

from kaine.modules.mnemos.storage import SqliteVecStorage, StorageError  # noqa: E402


def _vec(i: float) -> list[float]:
    return [1.0, float(i), 0.5, -0.25]


@pytest.mark.asyncio
async def test_calls_survive_a_different_default_executor_thread(tmp_path: Path):
    storage = SqliteVecStorage(latent_dim=4, db_path=str(tmp_path / "m.db"))
    await storage.initialize()
    loop = asyncio.get_running_loop()
    # A fresh default executor guarantees that any work routed through
    # ``asyncio.to_thread`` / the default executor runs on a new thread, not
    # the one that opened the connection.
    swapped = ThreadPoolExecutor(max_workers=1, thread_name_prefix="other")
    loop.set_default_executor(swapped)
    try:
        pid = await storage.upsert(
            "episodic", vector=_vec(1), text="one", payload={}, affect=None
        )
        assert await storage.count("episodic", strict=True) == 1
        hits = await storage.search("episodic", query_vector=_vec(1), limit=1)
        assert [h.point_id for h in hits] == [pid]
        await storage.write_stamp("k", {
            "model_id": "m", "dim": 4, "pooling": "mean", "normalized": True,
        })
        assert (await storage.read_stamp("k"))["model_id"] == "m"
        assert await storage.vector_dim("episodic") == 4
        exported = await storage.export(["episodic"])
        assert len(exported["episodic"]) == 1
        assert await storage.replace_collection("episodic", exported["episodic"]) == 1
        await storage.delete("episodic", pid)
        assert await storage.count("episodic", strict=True) == 0
    finally:
        await storage.shutdown()


def test_calls_from_another_event_loop_thread(tmp_path: Path):
    storage = SqliteVecStorage(latent_dim=4, db_path=str(tmp_path / "m.db"))
    asyncio.run(storage.initialize())
    errors: list[BaseException] = []

    def _other_thread() -> None:
        async def _use() -> None:
            await storage.upsert(
                "semantic", vector=_vec(2), text="two", payload={}, affect=None
            )
            assert await storage.count("semantic", strict=True) == 1

        try:
            asyncio.run(_use())
        except BaseException as exc:  # surfaced to the test thread below
            errors.append(exc)

    t = threading.Thread(target=_other_thread)
    t.start()
    t.join()
    try:
        assert errors == []
    finally:
        asyncio.run(storage.shutdown())


@pytest.mark.asyncio
async def test_concurrent_calls_are_serialised(tmp_path: Path):
    storage = SqliteVecStorage(latent_dim=4, db_path=str(tmp_path / "m.db"))
    await storage.initialize()
    try:
        await asyncio.gather(*[
            storage.upsert(
                "episodic", vector=_vec(i), text=f"m{i}", payload={"i": i},
                affect=None,
            )
            for i in range(50)
        ])
        assert await storage.count("episodic", strict=True) == 50
    finally:
        await storage.shutdown()


@pytest.mark.asyncio
async def test_shutdown_closes_on_the_owning_thread(tmp_path: Path, caplog):
    storage = SqliteVecStorage(latent_dim=4, db_path=str(tmp_path / "m.db"))
    await storage.initialize()
    await storage.upsert(
        "episodic", vector=_vec(1), text="one", payload={}, affect=None
    )
    with caplog.at_level(logging.WARNING, logger="kaine.modules.mnemos.storage"):
        await storage.shutdown()
    assert "sqlite-vec close failed" not in caplog.text
    # The owning worker thread is gone once the store is shut down.
    assert not [
        t for t in threading.enumerate() if t.name.startswith("mnemos-sqlite")
    ]
    # A closed store refuses work instead of touching a dead connection.
    with pytest.raises(StorageError):
        await storage.search("episodic", query_vector=_vec(1), limit=1)
    assert await storage.count("episodic") == 0
    # And it can be reopened: the data persisted.
    await storage.initialize()
    try:
        assert await storage.count("episodic", strict=True) == 1
    finally:
        await storage.shutdown()
