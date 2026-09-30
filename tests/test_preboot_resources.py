# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Pre-boot RESOURCES rows (caps-never-break-memory): the bus memory budget
against Redis maxmemory, and free disk on every durable path.

Every external read is faked: the bus probe (maxmemory + live per-entry
sizes) is an injected async callable and disk usage an injected function, so
no test touches a live Redis or measures a real filesystem.
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


def _probe(maxmemory: int, live: dict[str, int] | None = None):
    async def _run(_streams: list[str]):
        return maxmemory, dict(live or {})

    return _run


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
    cfg = {
        "modules": {"topos": True},
        "bus": {
            "default_maxlen": 100000,
            "per_stream_maxlen": {"workspace.broadcast": 1000, "cycle.out": 2000, "topos.out": 10},
        },
    }
    total, shares = preboot.bus_budget(cfg)
    assert total == (1000 * 6_600 + 2000 * 250 + 10 * 40_000) * 2
    assert shares[0].stream == "workspace.broadcast"
    assert all(s.source == preboot.SIZE_TABLE for s in shares)


def test_budget_prefers_live_sizes_then_table_then_estimate():
    cfg = {"modules": {"topos": True, "mnemos": True}, "bus": {"default_maxlen": 100}}
    _, shares = preboot.bus_budget(cfg, {"topos.out": 50_000, "mnemos.out": 0})
    by = {s.stream: s for s in shares}
    assert (by["topos.out"].entry_bytes, by["topos.out"].source) == (50_000, preboot.SIZE_LIVE)
    assert by["cycle.out"].source == preboot.SIZE_TABLE
    assert (by["mnemos.out"].entry_bytes, by["mnemos.out"].source) == (
        2_000,
        preboot.SIZE_ESTIMATE,
    )


def test_shipped_config_budget_uses_new_caps():
    import tomllib

    root = Path(__file__).resolve().parents[1]
    with (root / "config" / "kaine.toml").open("rb") as fh:
        cfg = tomllib.load(fh)
    cfg["modules"] = {"topos": True, "audition": True}
    _, shares = preboot.bus_budget(cfg)
    by = {s.stream: s.bytes for s in shares}
    assert by["topos.out"] == 12000 * 40_000
    assert by["audition.out"] == 12000 * 400
    assert by["workspace.broadcast"] == 100000 * 6_600


# ---------------------------------------------------------------------------
# Bus budget row
# ---------------------------------------------------------------------------


def _measured_config(budget_gib: float = 1.0) -> dict[str, Any]:
    """Only table-measured streams: workspace.broadcast sized so the budget
    (x2 headroom) is ``budget_gib``; cycle.out holds no entries."""
    n = int(budget_gib * GIB) // (2 * 6_600)
    return {
        "modules": {},
        "bus": {"default_maxlen": 100000, "per_stream_maxlen": {"workspace.broadcast": n, "cycle.out": 0}},
    }


def _estimated_config() -> dict[str, Any]:
    """A small measured part plus a large unmeasured stream (mnemos.out at the
    2 KB estimate: 300000 x 2 KB x 2 = about 1.1 GiB)."""
    return {
        "modules": {"mnemos": True},
        "bus": {
            "default_maxlen": 100000,
            "per_stream_maxlen": {
                "workspace.broadcast": 1000,
                "cycle.out": 0,
                "mnemos.out": 300000,
            },
        },
    }


async def test_bus_budget_pass_when_well_under_maxmemory():
    rows = await preboot.check_bus_budget(_measured_config(), probe=_probe(4 * GIB))
    assert [r.status for r in rows] == [preboot.PASS]
    assert rows[0].group == preboot.GROUP_RESOURCES
    assert rows[0].name == "Bus budget"
    assert "maxmemory 4.00 GiB" in rows[0].detail


async def test_bus_budget_warn_above_seventy_percent():
    rows = await preboot.check_bus_budget(_measured_config(), probe=_probe(int(1.2 * GIB)))
    assert rows[0].status == preboot.WARN
    assert "KAINE_REDIS_MAXMEMORY" in rows[0].detail


async def test_bus_budget_fail_when_measured_streams_exceed_maxmemory():
    rows = await preboot.check_bus_budget(_measured_config(), probe=_probe(GIB // 2))
    assert rows[0].status == preboot.FAIL
    assert "KAINE_REDIS_MAXMEMORY" in rows[0].detail


async def test_bus_budget_warns_when_overage_rests_on_estimates():
    rows = await preboot.check_bus_budget(_estimated_config(), probe=_probe(GIB // 2))
    assert rows[0].status == preboot.WARN
    assert "mnemos.out" in rows[0].detail
    assert "estimate" in rows[0].detail
    assert "12gb" in rows[0].detail


async def test_bus_budget_fails_when_live_sample_confirms_overage():
    """A live measurement of the same stream turns the estimate into a fact."""
    rows = await preboot.check_bus_budget(
        _estimated_config(), probe=_probe(GIB // 2, {"mnemos.out": 2_000})
    )
    assert rows[0].status == preboot.FAIL
    assert "live" in rows[0].detail


async def test_bus_budget_warn_when_maxmemory_unreadable():
    async def _refused(_streams) -> tuple[int, dict[str, int]]:
        raise ConnectionError("connection refused")

    rows = await preboot.check_bus_budget(_measured_config(), probe=_refused)
    assert rows[0].status == preboot.WARN
    assert "could not read Redis maxmemory" in rows[0].detail
    assert "ConnectionError" in rows[0].detail


async def test_bus_budget_warn_when_probe_hangs(monkeypatch):
    monkeypatch.setattr(preboot, "BUS_PROBE_TIMEOUT_S", 0.05)

    async def _hang(_streams):
        await asyncio.sleep(10)
        return 0, {}

    rows = await preboot.check_bus_budget(_measured_config(), probe=_hang)
    assert rows[0].status == preboot.WARN


async def test_bus_budget_warn_when_maxmemory_unlimited():
    rows = await preboot.check_bus_budget(_measured_config(), probe=_probe(0))
    assert rows[0].status == preboot.WARN
    assert "no limit" in rows[0].detail


async def test_bus_budget_fail_on_malformed_bus_table():
    rows = await preboot.check_bus_budget(
        {"bus": {"per_stream_maxlen": "lots"}}, probe=_probe(4 * GIB)
    )
    assert rows[0].status == preboot.FAIL


class _FakeRedis:
    def __init__(self, reply: Any = None, *, xlen: int = 0, usage: int | None = None) -> None:
        self._reply = reply
        self._xlen = xlen
        self._usage = usage

    async def config_get(self, key: str) -> Any:
        assert key == "maxmemory"
        return self._reply

    async def xlen(self, _stream: str) -> int:
        return self._xlen

    async def memory_usage(self, _stream: str) -> int | None:
        return self._usage


async def test_bus_client_reads_maxmemory():
    bus = AsyncBus(BusConfig(password="x"), client=_FakeRedis({"maxmemory": "4294967296"}))
    assert await bus.server_maxmemory() == 4 * GIB


async def test_bus_client_maxmemory_empty_reply_raises():
    bus = AsyncBus(BusConfig(password="x"), client=_FakeRedis({}))
    with pytest.raises(ValueError):
        await bus.server_maxmemory()


async def test_bus_client_samples_entry_size():
    bus = AsyncBus(BusConfig(password="x"), client=_FakeRedis(xlen=1000, usage=40_000_000))
    assert await bus.stream_entry_bytes("topos.out") == 40_000


async def test_bus_client_does_not_sample_short_streams():
    bus = AsyncBus(BusConfig(password="x"), client=_FakeRedis(xlen=5, usage=10_000))
    assert await bus.stream_entry_bytes("topos.out") is None


# ---------------------------------------------------------------------------
# Disk free rows
# ---------------------------------------------------------------------------


def _disk_config(tmp_path: Path, **extra: Any) -> dict[str, Any]:
    """Every durable path under tmp_path (so nothing resolves to the cwd)."""
    state = tmp_path / "state"
    data = tmp_path / "data"
    state.mkdir()
    data.mkdir()
    return {
        "preboot": {"state_root": str(state), "data_root": str(data), **extra},
        "lifecycle": {"snapshots_path": str(state / "forks")},
        "preservation": {
            "divergence_monitor": {"out_root": str(tmp_path / "backups")},
            "welfare_response": {"out_root": str(tmp_path / "backups")},
        },
        "evaluation": {
            "paths": {
                "trajectory_dir": str(data / "trajectory"),
                "evaluation_logs": str(data / "evaluation"),
            }
        },
        "research_event_log": {
            "log_dir": str(data / "evaluation" / "research_events"),
            "raw_archive": {"archive_dir": str(state / "research" / "raw")},
        },
        "hypnos": {
            "voice_alignment": {
                "adapter_output_dir": str(state / "hypnos" / "adapters"),
                "trainer_workdir": str(state / "hypnos" / "jobs"),
            }
        },
        "ignition_log": {"directory": str(data / "ignition")},
        "spot": {"incident_log": {"path": str(state / "cycle" / "incidents")}},
        "eidolon": {"persistence_path": str(state / "eidolon" / "self_model.json")},
    }


def _usage(free_gib: float, total_gib: float):
    def _fn(_path: Path) -> _Usage:
        total = int(total_gib * GIB)
        free = int(free_gib * GIB)
        return _Usage(total, total - free, free)

    return _fn


def _one_device(_path: Path) -> int:
    return 1


def _rows(cfg, usage, device_of=_one_device):
    return preboot.check_disk(cfg, disk_usage=usage, device_of=device_of)


def _disk_statuses(rows) -> list[str]:
    return [r.status for r in rows if r.name != "Disk free (Redis data)"]


def test_durable_paths_cover_every_configured_store(tmp_path):
    cfg = _disk_config(tmp_path)
    labels = {label for label, _ in preboot.durable_paths(cfg)}
    for key in (
        "[preboot].state_root",
        "[preboot].data_root",
        "[lifecycle].snapshots_path",
        "[preservation.divergence_monitor].out_root",
        "[preservation.welfare_response].out_root",
        "[evaluation.paths].trajectory_dir",
        "[evaluation.paths].evaluation_logs",
        "[research_event_log].log_dir",
        "[research_event_log.raw_archive].archive_dir",
        "[hypnos.voice_alignment].adapter_output_dir",
        "[hypnos.voice_alignment].trainer_workdir",
        "[ignition_log].directory",
        "[spot.incident_log].path",
        "[eidolon].persistence_path",
    ):
        assert key in labels
    paths = dict(preboot.durable_paths(cfg))
    assert paths["[eidolon].persistence_path"] == tmp_path / "state" / "eidolon"
    assert paths["[preservation.welfare_response].out_root"] == tmp_path / "backups"


def test_durable_paths_use_module_defaults():
    paths = dict(preboot.durable_paths({}))
    assert paths["[lifecycle].snapshots_path"] == Path("state/forks")
    assert paths["[hypnos.voice_alignment].adapter_output_dir"] == Path("state/hypnos/adapters")
    assert paths["[ignition_log].directory"] == Path("data/ignition")
    assert paths["[preservation.divergence_monitor].out_root"] == Path("backups")


def test_disk_pass_with_plenty_of_space(tmp_path):
    rows = _rows(_disk_config(tmp_path), _usage(100, 500))
    assert _disk_statuses(rows) == [preboot.PASS]
    assert "backups" in rows[0].detail
    assert [r.status for r in rows if r.name == "Disk free (Redis data)"] == [preboot.SKIP]


def test_disk_rows_split_by_filesystem(tmp_path):
    cfg = _disk_config(tmp_path)
    backups = tmp_path / "backups"
    backups.mkdir()

    def _device(path: Path) -> int:
        return 2 if Path(path) == backups else 1

    def _usage_by_fs(path: Path) -> _Usage:
        if Path(path) == backups:
            return _Usage(100 * GIB, 95 * GIB, 5 * GIB)
        return _Usage(500 * GIB, 400 * GIB, 100 * GIB)

    rows = _rows(cfg, _usage_by_fs, _device)
    by_name = {r.name: r for r in rows}
    backup_row = next(r for r in rows if "out_root" in r.name)
    assert backup_row.status == preboot.FAIL
    assert str(backups) in backup_row.detail
    assert by_name["Disk free ([preboot].state_root +11)"].status == preboot.PASS


def test_disk_warn_below_warn_threshold(tmp_path):
    assert _disk_statuses(_rows(_disk_config(tmp_path), _usage(15, 100))) == [preboot.WARN]


def test_disk_fail_below_absolute_floor(tmp_path):
    assert _disk_statuses(_rows(_disk_config(tmp_path), _usage(8, 100))) == [preboot.FAIL]


def test_disk_fail_below_percentage_floor_on_large_disk(tmp_path):
    assert _disk_statuses(_rows(_disk_config(tmp_path), _usage(40, 1000))) == [preboot.FAIL]


def test_disk_thresholds_come_from_config(tmp_path):
    cfg = _disk_config(
        tmp_path,
        disk_fail_min_free_gb=1.0,
        disk_fail_min_free_percent=0.0,
        disk_warn_min_free_gb=2.0,
    )
    assert _disk_statuses(_rows(cfg, _usage(8, 100))) == [preboot.PASS]


def test_disk_measures_native_redis_dir_when_present(tmp_path):
    cfg = _disk_config(tmp_path)
    redis_dir = Path(cfg["preboot"]["state_root"]) / "services" / "redis" / "data"
    redis_dir.mkdir(parents=True)
    rows = _rows(cfg, _usage(100, 500))
    assert not any(r.name == "Disk free (Redis data)" for r in rows)
    assert str(redis_dir) in rows[0].detail


def test_disk_missing_path_measures_nearest_existing_parent(tmp_path):
    cfg = _disk_config(tmp_path)
    seen: list[Path] = []

    def _fn(path: Path) -> _Usage:
        seen.append(Path(path))
        return _Usage(500 * GIB, 400 * GIB, 100 * GIB)

    def _device(path: Path) -> int:
        seen.append(Path(path))
        return 1

    _rows(cfg, _fn, _device)
    # state/forks does not exist yet: it is measured at state/.
    assert tmp_path / "state" in seen
    assert tmp_path / "state" / "forks" not in seen


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


def test_extra_disk_paths_adds_row(tmp_path):
    state = tmp_path / "state"
    data = tmp_path / "data"
    extra = tmp_path / "studies"
    for directory in (state, data, extra):
        directory.mkdir()
    config = {
        "preboot": {
            **preboot.PREBOOT_DEFAULTS,
            "state_root": str(state),
            "data_root": str(data),
            "extra_disk_paths": [str(extra)],
        }
    }
    rows = preboot.check_disk(
        config,
        disk_usage=lambda p: type("U", (), {"total": 2**40, "free": 2**39})(),
        device_of=lambda p: 1,
    )
    details = " ".join(r.detail for r in rows)
    assert str(extra) in details


def test_extra_disk_paths_non_list_refused():
    config = {"preboot": {"extra_disk_paths": "studies"}}
    with pytest.raises(ValueError, match=r"\[preboot\]\.extra_disk_paths"):
        preboot.durable_paths(config)
