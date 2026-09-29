# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Pre-boot RESOURCES rows (caps-never-break-memory): the bus memory budget
against Redis maxmemory, and free disk on the state/data roots.

Every external read is faked: maxmemory comes from an injected async reader
and disk usage from an injected function, so no test touches a live Redis or
measures a real filesystem.
"""

from __future__ import annotations

import asyncio
from collections import namedtuple
from pathlib import Path
from typing import Any

import pytest

import kaine.preboot as preboot
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig

GIB = 2**30
_Usage = namedtuple("_Usage", "total used free")


def _bus_config(**bus: Any) -> dict[str, Any]:
    """A config whose budget is exactly controlled: only workspace.broadcast
    and cycle.out (no modules), both at known maxlen x size."""
    return {"modules": {}, "bus": {"default_maxlen": 100000, **bus}}


def _reader(value: int):
    async def _read() -> int:
        return value

    return _read


# ---------------------------------------------------------------------------
# Budget arithmetic
# ---------------------------------------------------------------------------


def test_budget_streams_cover_enabled_modules_and_extras():
    streams = preboot.budget_streams(
        {"lingua": True, "nous": True, "topos": True, "soma": False}
    )
    assert streams[:2] == ["workspace.broadcast", "cycle.out"]
    for s in (
        "topos.out",
        "lingua.out",
        "lingua.internal",
        "lingua.external",
        "nous.out",
        "volition.out",
        "volition_feedback.out",
    ):
        assert s in streams
    assert "soma.out" not in streams


def test_budget_is_maxlen_times_size_times_headroom():
    cfg = _bus_config(per_stream_maxlen={"workspace.broadcast": 1000, "cycle.out": 2000})
    cfg["modules"] = {"topos": True}
    cfg["bus"]["per_stream_maxlen"]["topos.out"] = 10
    total, per = preboot.bus_budget(cfg)
    expected = (1000 * 6_600 + 2000 * 250 + 10 * 40_000) * 2
    assert total == expected
    assert per[0][0] == "workspace.broadcast"


def test_shipped_config_budget_uses_new_caps():
    import tomllib

    root = Path(__file__).resolve().parents[1]
    with (root / "config" / "kaine.toml").open("rb") as fh:
        cfg = tomllib.load(fh)
    cfg["modules"] = {"topos": True, "audition": True}
    _, per = preboot.bus_budget(cfg)
    by_stream = dict(per)
    assert by_stream["topos.out"] == 12000 * 40_000
    assert by_stream["audition.out"] == 12000 * 400
    assert by_stream["workspace.broadcast"] == 100000 * 6_600


# ---------------------------------------------------------------------------
# Bus budget row
# ---------------------------------------------------------------------------


def _one_gib_budget_config() -> dict[str, Any]:
    # workspace.broadcast: n x 6600 B, cycle.out 0 entries -> budget = 2 x n x 6600.
    n = GIB // (2 * 6_600)
    return _bus_config(per_stream_maxlen={"workspace.broadcast": n, "cycle.out": 0})


async def test_bus_budget_pass_when_well_under_maxmemory():
    rows = await preboot.check_bus_budget(
        _one_gib_budget_config(), read_maxmemory=_reader(4 * GIB)
    )
    assert [r.status for r in rows] == [preboot.PASS]
    assert rows[0].group == preboot.GROUP_RESOURCES
    assert rows[0].name == "Bus budget"
    assert "maxmemory 4.00 GiB" in rows[0].detail


async def test_bus_budget_warn_above_seventy_percent():
    rows = await preboot.check_bus_budget(
        _one_gib_budget_config(), read_maxmemory=_reader(int(1.2 * GIB))
    )
    assert rows[0].status == preboot.WARN
    assert "KAINE_REDIS_MAXMEMORY" in rows[0].detail


async def test_bus_budget_fail_when_over_maxmemory():
    rows = await preboot.check_bus_budget(
        _one_gib_budget_config(), read_maxmemory=_reader(GIB // 2)
    )
    assert rows[0].status == preboot.FAIL
    assert "KAINE_REDIS_MAXMEMORY" in rows[0].detail


async def test_bus_budget_warn_when_maxmemory_unreadable():
    async def _refused() -> int:
        raise ConnectionError("connection refused")

    rows = await preboot.check_bus_budget(_one_gib_budget_config(), read_maxmemory=_refused)
    assert rows[0].status == preboot.WARN
    assert "could not read Redis maxmemory" in rows[0].detail
    assert "ConnectionError" in rows[0].detail


async def test_bus_budget_warn_when_maxmemory_probe_hangs(monkeypatch):
    monkeypatch.setattr(preboot, "BUS_PROBE_TIMEOUT_S", 0.05)

    async def _hang() -> int:
        await asyncio.sleep(10)
        return 0

    rows = await preboot.check_bus_budget(_one_gib_budget_config(), read_maxmemory=_hang)
    assert rows[0].status == preboot.WARN


async def test_bus_budget_warn_when_maxmemory_unlimited():
    rows = await preboot.check_bus_budget(_one_gib_budget_config(), read_maxmemory=_reader(0))
    assert rows[0].status == preboot.WARN
    assert "no limit" in rows[0].detail


async def test_bus_budget_fail_on_malformed_bus_table():
    rows = await preboot.check_bus_budget(
        {"bus": {"per_stream_maxlen": "lots"}}, read_maxmemory=_reader(4 * GIB)
    )
    assert rows[0].status == preboot.FAIL


class _FakeRedis:
    def __init__(self, reply: Any) -> None:
        self._reply = reply

    async def config_get(self, key: str) -> Any:
        assert key == "maxmemory"
        return self._reply


async def test_bus_client_reads_maxmemory():
    bus = AsyncBus(BusConfig(password="x"), client=_FakeRedis({"maxmemory": "4294967296"}))
    assert await bus.server_maxmemory() == 4 * GIB


async def test_bus_client_maxmemory_empty_reply_raises():
    bus = AsyncBus(BusConfig(password="x"), client=_FakeRedis({}))
    with pytest.raises(ValueError):
        await bus.server_maxmemory()


# ---------------------------------------------------------------------------
# Disk free rows
# ---------------------------------------------------------------------------


def _disk_config(tmp_path: Path, **extra: Any) -> dict[str, Any]:
    state = tmp_path / "state"
    data = tmp_path / "data"
    state.mkdir()
    data.mkdir()
    return {"preboot": {"state_root": str(state), "data_root": str(data), **extra}}


def _usage(free_gib: float, total_gib: float):
    def _fn(_path: Path) -> _Usage:
        total = int(total_gib * GIB)
        free = int(free_gib * GIB)
        return _Usage(total, total - free, free)

    return _fn


def _statuses(rows) -> dict[str, str]:
    return {r.name: r.status for r in rows}


def test_disk_pass_with_plenty_of_space(tmp_path):
    rows = preboot.check_disk(_disk_config(tmp_path), disk_usage=_usage(100, 500))
    st = _statuses(rows)
    assert st["Disk free (state root)"] == preboot.PASS
    assert st["Disk free (data root)"] == preboot.PASS
    assert st["Disk free (Redis data)"] == preboot.SKIP


def test_disk_warn_below_warn_threshold(tmp_path):
    rows = preboot.check_disk(_disk_config(tmp_path), disk_usage=_usage(15, 100))
    assert _statuses(rows)["Disk free (state root)"] == preboot.WARN


def test_disk_fail_below_absolute_floor(tmp_path):
    rows = preboot.check_disk(_disk_config(tmp_path), disk_usage=_usage(8, 100))
    assert _statuses(rows)["Disk free (data root)"] == preboot.FAIL


def test_disk_fail_below_percentage_floor_on_large_disk(tmp_path):
    rows = preboot.check_disk(_disk_config(tmp_path), disk_usage=_usage(40, 1000))
    assert _statuses(rows)["Disk free (state root)"] == preboot.FAIL


def test_disk_thresholds_come_from_config(tmp_path):
    cfg = _disk_config(
        tmp_path,
        disk_fail_min_free_gb=1.0,
        disk_fail_min_free_percent=0.0,
        disk_warn_min_free_gb=2.0,
    )
    rows = preboot.check_disk(cfg, disk_usage=_usage(8, 100))
    assert _statuses(rows)["Disk free (state root)"] == preboot.PASS


def test_disk_measures_native_redis_dir_when_present(tmp_path):
    cfg = _disk_config(tmp_path)
    redis_dir = Path(cfg["preboot"]["state_root"]) / "services" / "redis" / "data"
    redis_dir.mkdir(parents=True)
    seen: list[Path] = []

    def _fn(path: Path) -> _Usage:
        seen.append(Path(path))
        return _Usage(500 * GIB, 400 * GIB, 100 * GIB)

    rows = preboot.check_disk(cfg, disk_usage=_fn)
    assert _statuses(rows)["Disk free (Redis data)"] == preboot.PASS
    assert redis_dir in seen


def test_disk_missing_root_measures_nearest_existing_parent(tmp_path):
    cfg = {"preboot": {"state_root": str(tmp_path / "nope" / "state"), "data_root": str(tmp_path)}}
    seen: list[Path] = []

    def _fn(path: Path) -> _Usage:
        seen.append(Path(path))
        return _Usage(500 * GIB, 400 * GIB, 100 * GIB)

    rows = preboot.check_disk(cfg, disk_usage=_fn)
    assert _statuses(rows)["Disk free (state root)"] == preboot.PASS
    assert tmp_path in seen


def test_disk_unknown_preboot_key_fails(tmp_path):
    rows = preboot.check_disk({"preboot": {"disk_min": 3}}, disk_usage=_usage(100, 500))
    assert [r.status for r in rows] == [preboot.FAIL]
    assert "disk_min" in rows[0].detail


def test_disk_non_numeric_threshold_fails(tmp_path):
    rows = preboot.check_disk(
        {"preboot": {"disk_warn_min_free_gb": "lots"}}, disk_usage=_usage(100, 500)
    )
    assert [r.status for r in rows] == [preboot.FAIL]


def test_shipped_preboot_table_has_defaults():
    import tomllib

    root = Path(__file__).resolve().parents[1]
    with (root / "config" / "kaine.toml").open("rb") as fh:
        cfg = tomllib.load(fh)
    assert cfg["preboot"] == preboot.PREBOOT_DEFAULTS


# ---------------------------------------------------------------------------
# WARN status in the report
# ---------------------------------------------------------------------------


def test_warn_rows_do_not_fail_the_gate():
    results = [
        preboot.CheckResult("g", "a", preboot.PASS),
        preboot.CheckResult("g", "b", preboot.WARN, "close to the cap"),
    ]
    assert preboot.report_ok(results) is True
    line = preboot.verdict_line(results)
    assert "VERDICT: PASS" in line
    assert "1 warn" in line
    assert "[WARN]" in preboot.render_table(results)


async def test_run_async_checks_includes_resources(monkeypatch):
    async def _noop(*_a, **_k):
        return []

    async def _resources(_config):
        return [preboot.CheckResult(preboot.GROUP_RESOURCES, "Bus budget", preboot.PASS)]

    for name in ("check_services", "check_organ", "check_perception", "check_welfare"):
        monkeypatch.setattr(preboot, name, _noop)
    monkeypatch.setattr(preboot, "check_resources", _resources)
    results = await preboot.run_async_checks({"modules": {}})
    assert [r.name for r in results] == ["Bus budget"]
