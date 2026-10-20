# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The cycle entrypoint starts the awake housekeeping floor only with the sleep module and housekeeping enabled."""
from __future__ import annotations

import asyncio
import logging

import fakeredis.aioredis
import pytest

import kaine.storage
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.__main__ import _start_housekeeping_floor
from kaine.cycle.housekeeping_floor import FloorConfig, data_volumes


def test_floor_config_defaults() -> None:
    cfg = FloorConfig()
    assert cfg.reserve_bytes == 5 * 1024**3
    assert cfg.reserve_share == 0.05
    assert cfg.floor_period_s == 60.0


def test_from_section_none_is_an_empty_table() -> None:
    assert FloorConfig.from_section(None) == FloorConfig()


def test_from_section_reads_its_three_keys() -> None:
    cfg = FloorConfig.from_section(
        {"reserve_bytes": 1024, "reserve_share": 0.2, "floor_period_s": 0.05}
    )
    assert cfg.reserve_bytes == 1024
    assert cfg.reserve_share == pytest.approx(0.2)
    assert cfg.floor_period_s == pytest.approx(0.05)


def test_from_section_accepts_ints_for_the_float_fields() -> None:
    cfg = FloorConfig.from_section({"reserve_share": 0, "floor_period_s": 5})
    assert cfg.reserve_share == 0.0
    assert cfg.floor_period_s == 5.0


def test_from_section_ignores_housekeeper_keys() -> None:
    cfg = FloorConfig.from_section(
        {"enabled": False, "disk_budget_bytes": 7, "reserve_bytes": 2048}
    )
    assert cfg.reserve_bytes == 2048
    assert cfg.reserve_share == 0.05
    assert cfg.floor_period_s == 60.0


def test_from_section_rejects_a_non_dict() -> None:
    with pytest.raises(ValueError, match=r"\[sleep\.housekeeping\]"):
        FloorConfig.from_section(["not", "a", "table"])


@pytest.mark.parametrize("bad", [-1, 1.5, True, "5G", None])
def test_from_section_rejects_bad_reserve_bytes(bad: object) -> None:
    with pytest.raises(ValueError, match="reserve_bytes"):
        FloorConfig.from_section({"reserve_bytes": bad})


@pytest.mark.parametrize("bad", [-0.1, 1.0, 1.5, float("nan"), float("inf"), True, "0.5", None])
def test_from_section_rejects_bad_reserve_share(bad: object) -> None:
    with pytest.raises(ValueError, match="reserve_share"):
        FloorConfig.from_section({"reserve_share": bad})


@pytest.mark.parametrize("bad", [0, 0.0, -1.0, float("nan"), float("inf"), True, "60", None])
def test_from_section_rejects_bad_floor_period_s(bad: object) -> None:
    with pytest.raises(ValueError, match="floor_period_s"):
        FloorConfig.from_section({"floor_period_s": bad})


def test_data_volumes_resolve_under_the_data_root(tmp_path) -> None:  # noqa: ANN001
    previous = kaine.storage.data_root()
    try:
        kaine.storage.set_data_root(tmp_path)
        volumes = data_volumes()
    finally:
        kaine.storage.set_data_root(previous)
    assert volumes == {"data": tmp_path / "data", "state": tmp_path / "state"}


def test_sleep_module_off_starts_nothing() -> None:
    task = _start_housekeeping_floor(
        {"modules": {"sleep": False}, "sleep": {"housekeeping": {}}},
        object(),
        asyncio.Event(),
        is_asleep=lambda: True,
    )
    assert task is None


def test_housekeeping_disabled_starts_nothing() -> None:
    task = _start_housekeeping_floor(
        {"modules": {"sleep": True}, "sleep": {"housekeeping": {"enabled": False}}},
        object(),
        asyncio.Event(),
        is_asleep=lambda: True,
    )
    assert task is None


@pytest.mark.asyncio
async def test_bad_reserve_share_logs_and_returns_none(caplog) -> None:  # noqa: ANN001
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=fakeredis.aioredis.FakeRedis(decode_responses=True))
    try:
        with caplog.at_level(logging.WARNING):
            task = _start_housekeeping_floor(
                {"modules": {"sleep": True}, "sleep": {"housekeeping": {"reserve_share": 1.5}}},
                bus,
                asyncio.Event(),
                is_asleep=lambda: True,
            )
        assert task is None
        assert "reserve_share" in caplog.text
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_enabled_sleep_module_starts_a_floor_task_that_ends_on_stop() -> None:
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=fakeredis.aioredis.FakeRedis(decode_responses=True))
    stop = asyncio.Event()
    task = _start_housekeeping_floor(
        {"modules": {"sleep": True}, "sleep": {"housekeeping": {"floor_period_s": 0.05}}},
        bus,
        stop,
        is_asleep=lambda: True,
    )
    try:
        assert task is not None
        assert task.get_name() == "cycle.housekeeping_floor"
        await asyncio.sleep(0.05)
        assert not task.done()
        stop.set()
        await asyncio.wait_for(task, timeout=2.0)
        assert task.done()
    finally:
        stop.set()
        if task is not None and not task.done():
            task.cancel()
        await bus.close()
