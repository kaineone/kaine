# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import fakeredis
import fakeredis.aioredis
import pytest

import kaine.storage
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.housekeeping_floor import AwakeFloor, FloorConfig, data_volumes
from kaine.dashboard.health.probes import DEGRADED, NOT_CONFIGURED, UP
from kaine.persistence.study_record_gate import StudyRecordGate


class Usage:
    """A mutable stand-in for shutil.disk_usage's result."""

    def __init__(self, *, total, used, free):
        self.total = total
        self.used = used
        self.free = free


class FakeHousekeeper:
    def __init__(self, usage, free_per_call):
        self.usage = usage
        self.free_per_call = free_per_call
        self.calls = []
        self._excess = 0.0

    async def reclaim_regenerable(self, *, free_bytes, target_free, device=None):
        self.calls.append({"free_before": free_bytes(), "target_free": target_free})
        self.usage.free += self.free_per_call
        return {"reclaimed_files": 1, "reclaimed_bytes": self.free_per_call}

    def disk_excess(self):
        return self._excess


class FakePressure:
    def __init__(self):
        self.notes = []

    def note_floor_disk_excess(self, excess):
        self.notes.append(excess)


@pytest.fixture
def bus():
    return AsyncBus(BusConfig(password="x", audit_required=False), client=fakeredis.aioredis.FakeRedis(decode_responses=True))


def make_fake_stat(devices):
    """os.stat for the fake volume paths; every other path gets the real stat.

    Patching the floor module's os.stat patches the shared os module, so the
    fake must delegate (pytest and tmp_path cleanup call os.stat too)."""
    real_stat = os.stat

    def fake_stat(path, *args, **kwargs):
        key = Path(path) if isinstance(path, (str, Path)) else path
        if key in devices:
            return SimpleNamespace(st_dev=devices[key])
        return real_stat(path, *args, **kwargs)

    return fake_stat


def test_reachable_target() -> None:
    """S5: on an 8 GiB volume R=5 GiB target is (total+R)//2; on 1 TiB it is 2R."""
    floor = AwakeFloor(
        FakeHousekeeper(Usage(total=8 * 1024**3, used=0, free=0), 0),
        FakePressure(),
        volumes={"vol": Path("/vol")},
        reserve_bytes=5 * 1024**3,
        reserve_share=0.05,
        period_s=60.0,
        is_asleep=lambda: False,
        gate=StudyRecordGate(),
        bus=None,
        disk_usage=lambda p: Usage(total=8 * 1024**3, used=0, free=0),
    )
    total = 8 * 1024**3
    r = floor.reserve(total)
    assert r == 5 * 1024**3
    assert floor.target(total) == (total + r) // 2

    big_total = 1024**4
    big_r = floor.reserve(big_total)
    assert floor.target(big_total) == 2 * big_r


@pytest.mark.asyncio
async def test_s5_small_volume_suspends_then_resumes_at_target(monkeypatch) -> None:
    """8 GiB volume with R=5 GiB: free 1 GiB suspends; free back at 8 GiB resumes."""
    total = 8 * 1024**3
    usage = Usage(total=total, used=total - 1024**3, free=1024**3)
    hk = FakeHousekeeper(usage, 3 * 1024**3)
    gate = StudyRecordGate()
    floor = AwakeFloor(
        hk,
        FakePressure(),
        volumes={"vol": Path("/vol")},
        reserve_bytes=5 * 1024**3,
        reserve_share=0.05,
        period_s=60.0,
        is_asleep=lambda: False,
        gate=gate,
        bus=None,
        disk_usage=lambda p: usage,
    )
    monkeypatch.setattr(
        "kaine.cycle.housekeeping_floor.os.stat",
        make_fake_stat({Path("/vol"): 1}),
    )

    actions1 = await floor.check_once()
    assert gate.suspended
    assert len(hk.calls) == 1
    assert hk.calls[0]["target_free"] == floor.target(total)
    assert any(a["action"] == "reclaim" for a in actions1)
    assert any(a["action"] == "suspend" for a in actions1)

    usage.free = 8 * 1024**3
    actions2 = await floor.check_once()
    assert not gate.suspended
    assert any(a["action"] == "resume" for a in actions2)


def test_validate_volumes_raises_when_reserve_unreachable() -> None:
    usage = Usage(total=1000, used=0, free=0)
    floor = AwakeFloor(
        FakeHousekeeper(usage, 0),
        FakePressure(),
        volumes={"vol": Path("/vol")},
        reserve_bytes=2000,
        reserve_share=0.0,
        period_s=60.0,
        is_asleep=lambda: False,
        gate=StudyRecordGate(),
        bus=None,
        disk_usage=lambda p: usage,
    )
    with pytest.raises(ValueError, match="vol.*1000.*2000"):
        floor.validate_volumes()


def test_validate_volumes_ok_when_reserve_fits() -> None:
    usage = Usage(total=1000, used=0, free=0)
    floor = AwakeFloor(
        FakeHousekeeper(usage, 0),
        FakePressure(),
        volumes={"vol": Path("/vol")},
        reserve_bytes=500,
        reserve_share=0.0,
        period_s=60.0,
        is_asleep=lambda: False,
        gate=StudyRecordGate(),
        bus=None,
        disk_usage=lambda p: usage,
    )
    floor.validate_volumes()


@pytest.mark.asyncio
async def test_reclaim_error_continues_and_reaches_resume(monkeypatch) -> None:
    usage1 = Usage(total=1000, used=900, free=100)
    usage2 = Usage(total=1000, used=900, free=100)
    hk = FakeHousekeeper(usage1, 0)
    original = hk.reclaim_regenerable
    calls = 0

    async def reclaim_with_raise(*, free_bytes, target_free, device=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        return await original(free_bytes=free_bytes, target_free=target_free, device=device)

    hk.reclaim_regenerable = reclaim_with_raise
    gate = StudyRecordGate()
    floor = AwakeFloor(
        hk,
        FakePressure(),
        volumes={"v1": Path("/v1"), "v2": Path("/v2")},
        reserve_bytes=200,
        reserve_share=0.0,
        period_s=60.0,
        is_asleep=lambda: False,
        gate=gate,
        bus=None,
        disk_usage=lambda p: usage1 if p == Path("/v1") else usage2,
    )
    monkeypatch.setattr(
        "kaine.cycle.housekeeping_floor.os.stat",
        make_fake_stat({Path("/v1"): 1, Path("/v2"): 2}),
    )

    await floor.check_once()
    assert calls == 2
    assert len(hk.calls) == 1
    assert hk.calls[0]["target_free"] == floor.target(1000)
    assert gate.suspended


@pytest.mark.asyncio
async def test_is_asleep_after_first_volume_skips_others(monkeypatch) -> None:
    usage1 = Usage(total=1000, used=900, free=100)
    usage2 = Usage(total=1000, used=900, free=100)
    hk = FakeHousekeeper(usage1, 0)
    n = 0

    def is_asleep():
        nonlocal n
        n += 1
        return n >= 3

    floor = AwakeFloor(
        hk,
        FakePressure(),
        volumes={"v1": Path("/v1"), "v2": Path("/v2")},
        reserve_bytes=200,
        reserve_share=0.0,
        period_s=60.0,
        is_asleep=is_asleep,
        gate=StudyRecordGate(),
        bus=None,
        disk_usage=lambda p: usage1 if p == Path("/v1") else usage2,
    )
    monkeypatch.setattr(
        "kaine.cycle.housekeeping_floor.os.stat",
        make_fake_stat({Path("/v1"): 1, Path("/v2"): 2}),
    )

    await floor.check_once()
    assert n == 3
    assert len(hk.calls) == 1


def test_data_volumes_includes_all_sinks_and_state(monkeypatch) -> None:
    monkeypatch.setattr(kaine.storage, "resolve", lambda p: Path(p))
    cfg = {
        "evaluation": {
            "paths": {
                "evaluation_logs": "data/evaluation",
                "trajectory_dir": "data/workspace_trajectory",
            }
        },
        "research_event_log": {
            "log_dir": "data/events",
            "external_utterances": {"log_dir": "data/ext"},
            "dashboard_record": {"log_dir": "data/dash"},
            "raw_archive": {"archive_dir": "data/raw"},
        },
    }
    vols = data_volumes(cfg)
    assert vols["evaluation"] == Path("data/evaluation")
    assert vols["trajectory"] == Path("data/workspace_trajectory")
    assert vols["research_events"] == Path("data/events")
    assert vols["external_utterances"] == Path("data/ext")
    assert vols["dashboard_record"] == Path("data/dash")
    assert vols["raw_bus_archive"] == Path("data/raw")
    assert vols["state"] == Path("state")


def test_data_volumes_defaults_when_absent(monkeypatch) -> None:
    monkeypatch.setattr(kaine.storage, "resolve", lambda p: Path(p))
    vols = data_volumes({})
    assert vols["evaluation"] == Path("data/evaluation")
    assert vols["trajectory"] == Path("data/workspace_trajectory")
    assert vols["state"] == Path("state")
    assert "research_events" not in vols


@pytest.mark.parametrize("bad", [0, 1, 2.0])
def test_floor_config_rejects_bad_reserve_share(bad) -> None:
    with pytest.raises(ValueError, match="reserve_share"):
        FloorConfig.from_section({"reserve_share": bad})


@pytest.mark.parametrize("bad", [0, -1, True])
def test_floor_config_rejects_bad_reserve_bytes(bad) -> None:
    with pytest.raises(ValueError, match="reserve_bytes"):
        FloorConfig.from_section({"reserve_bytes": bad})


@pytest.mark.parametrize("bad", [0, -1.0])
def test_floor_config_rejects_bad_floor_period_s(bad) -> None:
    with pytest.raises(ValueError, match="floor_period_s"):
        FloorConfig.from_section({"floor_period_s": bad})


def test_make_sleep_bad_floor_config_raises(bus) -> None:
    from kaine.boot.factories.sleep import make_sleep

    with pytest.raises(ValueError, match="reserve_share"):
        make_sleep(bus, {"housekeeping": {"reserve_share": 2.0}})


@pytest.mark.asyncio
async def test_start_housekeeping_floor_bad_config_raises(bus) -> None:
    from kaine.cycle.__main__ import _start_housekeeping_floor

    stop = asyncio.Event()
    with pytest.raises(ValueError, match="reserve_share"):
        _start_housekeeping_floor(
            {"modules": {"sleep": True}, "sleep": {"housekeeping": {"reserve_share": 2.0}}},
            bus,
            stop,
            lambda: False,
        )


def test_make_sleep_empty_archive_dir_logs_warning(bus, caplog) -> None:
    from kaine.boot.factories.sleep import make_sleep

    with caplog.at_level("WARNING"):
        make_sleep(bus, {"housekeeping": {"enabled": True, "archive_dir": ""}})
    assert "sleep housekeeping is enabled without an archive volume" in caplog.text


def test_dashboard_housekeeping_archive_probe(tmp_path, monkeypatch) -> None:
    from kaine.dashboard.health.config import build_dependency_specs

    base = {
        "redis_cfg": {},
        "qdrant_cfg": {},
        "qdrant_secret_key": None,
        "redis_password": None,
        "language_cfg": {},
        "audition_cfg": {},
        "vocal_cfg": {},
        "planning_cfg": {},
    }

    # Disabled.
    specs = build_dependency_specs(
        **base, sleep_cfg={"housekeeping": {"enabled": False}}
    )
    assert asyncio.run(specs[-1].probe()) == (NOT_CONFIGURED, "housekeeping disabled")

    # Empty archive_dir.
    specs = build_dependency_specs(
        **base, sleep_cfg={"housekeeping": {"enabled": True, "archive_dir": ""}}
    )
    assert asyncio.run(specs[-1].probe()) == (
        DEGRADED,
        "housekeeping is enabled without an archive volume: study records never leave the host and the housekeeping pressure grows; set [sleep.housekeeping].archive_dir to a mounted volume",
    )

    # Missing directory.
    specs = build_dependency_specs(
        **base,
        sleep_cfg={"housekeeping": {"enabled": True, "archive_dir": str(tmp_path / "nope")}},
    )
    assert asyncio.run(specs[-1].probe()) == (
        DEGRADED,
        "archive_dir is not a mounted volume",
    )

    # Same filesystem as data (ismount patched to False so the st_dev check runs).
    same_dir = tmp_path / "archive"
    same_dir.mkdir()
    monkeypatch.setattr("os.path.ismount", lambda p: False)
    specs = build_dependency_specs(
        **base,
        sleep_cfg={"housekeeping": {"enabled": True, "archive_dir": str(same_dir)}},
    )
    assert asyncio.run(specs[-1].probe()) == (
        DEGRADED,
        "archive_dir is not a mounted volume",
    )

    # Mounted directory.
    monkeypatch.setattr("os.path.ismount", lambda p: True)
    assert asyncio.run(specs[-1].probe()) == (UP, "archive volume mounted")
