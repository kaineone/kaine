# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kaine.cycle.individuation_probe import ProbeFailure
from kaine.cycle.individuation_producer import LookOutcome
from kaine.cycle.individuation_scheduler import (
    IndividuationScheduler,
    SchedulerSettings,
)
from kaine.lifecycle.individuation_store import (
    IndividuationPaths,
    Ledger,
    ReferenceExists,
    load_ledger,
    save_ledger,
)
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor


@pytest.fixture(autouse=True)
def reset_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


class Clock:
    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


class WallClock:
    def __init__(self, clock: Clock):
        self.base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.clock = clock

    def __call__(self) -> datetime:
        return self.base + timedelta(seconds=self.clock.t)


async def no_sleep(_s: float) -> None:
    pass


class FakeDoc:
    def __init__(self, kind: str):
        self.reference_kind = kind


class FakeCore:
    def __init__(self, clock: Clock, sched: IndividuationScheduler | None = None):
        self.clock = clock
        self.sched = sched
        self.looks: list[dict] = []
        self.captures: list[str] = []
        self.next_look = LookOutcome("scored", None, None)
        self.capture_result: tuple[FakeDoc | None, str | None] = (
            FakeDoc("birth"),
            None,
        )
        self.due = True
        self.raise_on_look: Exception | None = None
        self.raise_on_capture: Exception | None = None
        self.look_delay: float | None = None
        self.recorded_abort: str | None = None

    def look_due(self) -> bool:
        return self.due

    async def look(
        self, *, warmed_up: bool, lived_seconds: float, lived_ticks: int
    ) -> LookOutcome:
        self.looks.append(
            {
                "warmed_up": warmed_up,
                "lived_seconds": lived_seconds,
                "lived_ticks": lived_ticks,
            }
        )
        if self.raise_on_look is not None:
            raise self.raise_on_look
        if self.look_delay is not None:
            self.clock.t += self.look_delay
        if self.sched is not None:
            self.recorded_abort = self.sched.abort_reason()
        return self.next_look

    async def capture_reference(self, kind: str) -> tuple[FakeDoc | None, str | None]:
        self.captures.append(kind)
        if self.raise_on_capture is not None:
            raise self.raise_on_capture
        return self.capture_result


def write_reference(paths: IndividuationPaths) -> None:
    paths.reference.parent.mkdir(parents=True, exist_ok=True)
    paths.reference.write_bytes(b"exists")


def make(tmp_path: Path, **overrides):
    clock = Clock(0.0)
    wall = WallClock(clock)
    paths = IndividuationPaths(root=tmp_path)
    settings = SchedulerSettings(
        sleep_settle_s=10,
        daily_s=1000,
        min_look_interval_s=100,
        min_lived_time_s=5,
        min_observations=2,
        blocked_retry_s=20,
        inconclusive_retry_s=50,
        lived_persist_s=30,
        inconclusive_alert_s=500,
        capture_retry_initial_s=5,
        capture_retry_max_s=20,
        run_deadline_s=60,
        capture_deadline_s=120,
        idle_poll_s=1,
    )
    kwargs = {
        "paths": paths,
        "settings": settings,
        "clock_now": clock,
        "paused_seconds": lambda: 0.0,
        "tick_index": lambda: None,
        "organ_unloaded": lambda: False,
        "paused": lambda: False,
        "embedder_ready": lambda: True,
        "lingua_idle": lambda: True,
        "alert": lambda d: None,
        "monotonic": clock,
        "now": wall,
        "sleep": no_sleep,
    }
    kwargs.update(overrides)
    sched = IndividuationScheduler(**kwargs)
    core = FakeCore(clock, sched)
    sched.bind(core)
    return sched, core, clock


async def test_boot_look_when_ready(tmp_path: Path):
    sched, core, clock = make(tmp_path)
    paths = sched._paths
    write_reference(paths)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    save_ledger(
        paths,
        Ledger(
            reference_id="r",
            lived_seconds=10.0,
            lived_ticks=5,
            last_look_at=(base - timedelta(seconds=200)).isoformat(),
        ),
    )
    await sched.tick()
    assert len(core.looks) == 0
    clock.t += 10
    await sched.tick()
    assert len(core.looks) == 1
    clock.t += 1
    await sched.tick()
    assert len(core.looks) == 1


async def test_sleep_schedules_and_blocks_look(tmp_path: Path):
    settings = SchedulerSettings(
        sleep_settle_s=10,
        daily_s=1000,
        min_look_interval_s=1,
        min_lived_time_s=5,
        min_observations=2,
        blocked_retry_s=20,
        inconclusive_retry_s=50,
        lived_persist_s=30,
        inconclusive_alert_s=500,
        capture_retry_initial_s=5,
        capture_retry_max_s=20,
        run_deadline_s=60,
        capture_deadline_s=120,
        idle_poll_s=1,
    )
    sched, core, clock = make(tmp_path, settings=settings)
    paths = sched._paths
    write_reference(paths)
    save_ledger(paths, Ledger(reference_id="r", lived_seconds=10.0, lived_ticks=5))
    await sched.tick()
    clock.t = 10
    await sched.tick()
    assert len(core.looks) == 1
    clock.t = 11
    sched.notify_sleep_started()
    assert sched.abort_reason() == "asleep"
    await sched.tick()
    assert len(core.looks) == 1
    sched.notify_sleep_completed()
    assert sched._look_due_at == 21.0
    clock.t = 21
    await sched.tick()
    assert len(core.looks) == 2


async def test_warm_up_blocks_look(tmp_path: Path):
    sched, core, clock = make(tmp_path)
    paths = sched._paths
    write_reference(paths)
    save_ledger(paths, Ledger(reference_id="r", lived_seconds=1.0, lived_ticks=1))
    await sched.tick()
    clock.t = 10
    await sched.tick()
    assert len(core.looks) == 0
    assert sched.state.last_reason == "warming_up"


async def test_interval_respects_min_look_interval(tmp_path: Path):
    sched, core, clock = make(tmp_path)
    paths = sched._paths
    write_reference(paths)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    save_ledger(
        paths,
        Ledger(
            reference_id="r",
            lived_seconds=10.0,
            lived_ticks=5,
            last_look_at=(base - timedelta(seconds=40)).isoformat(),
        ),
    )
    await sched.tick()
    clock.t = 10
    await sched.tick()
    assert len(core.looks) == 0
    assert sched.state.last_reason == "interval"
    assert sched._look_due_at == 60.0
    clock.t = 60
    await sched.tick()
    assert len(core.looks) == 1
    clock.t = 61
    await sched.tick()
    assert len(core.looks) == 1


async def test_blocked_reasons_skip_and_retry(tmp_path: Path):
    for reason in ("organ_unloaded", "paused", "embedder_not_ready"):
        root = tmp_path / reason
        root.mkdir()
        sched, core, clock = make(root)
        paths = sched._paths
        write_reference(paths)
        save_ledger(paths, Ledger(reference_id="r", lived_seconds=10.0, lived_ticks=5))
        if reason == "organ_unloaded":
            sched._organ_unloaded = lambda: True
        elif reason == "paused":
            sched._paused = lambda: True
        else:
            sched._embedder_ready = lambda: False
        await sched.tick()
        clock.t = 10
        await sched.tick()
        assert sched.state.last_reason == reason
        assert sched._look_due_at == 30.0
        assert load_ledger(paths).inconclusive_since is not None

    root = tmp_path / "not_due"
    root.mkdir()
    sched, core, clock = make(root)
    paths = sched._paths
    write_reference(paths)
    save_ledger(paths, Ledger(reference_id="r", lived_seconds=10.0, lived_ticks=5))
    sched._paused = lambda: True
    core.due = False
    await sched.tick()
    clock.t = 10
    await sched.tick()
    assert load_ledger(paths).inconclusive_since is None


async def test_predicate_raises_fail_toward_not_probing(tmp_path: Path):
    sched, core, clock = make(tmp_path)
    paths = sched._paths
    write_reference(paths)
    save_ledger(paths, Ledger(reference_id="r", lived_seconds=10.0, lived_ticks=5))
    sched._organ_unloaded = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    await sched.tick()
    clock.t = 10
    await sched.tick()
    assert len(core.looks) == 0
    assert sched.state.last_reason == "organ_unloaded"


async def test_deadline_exceeded_while_look_running(tmp_path: Path):
    sched, core, clock = make(tmp_path)
    paths = sched._paths
    write_reference(paths)
    save_ledger(paths, Ledger(reference_id="r", lived_seconds=10.0, lived_ticks=5))
    core.look_delay = 70.0
    await sched.tick()
    clock.t = 10
    await sched.tick()
    assert core.recorded_abort == "deadline_exceeded"
    assert len(core.looks) == 1


async def test_gate_waits_for_lingua_idle_and_aborts(tmp_path: Path):
    calls = 0

    async def counting_sleep(s: float) -> None:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)  # yield, so the test timeout can fire
        if calls >= 2:
            sched.notify_sleep_started()

    sched, core, clock = make(tmp_path, lingua_idle=lambda: False, sleep=counting_sleep)
    sampler_calls = 0

    async def fake_sampler(prompt: str, seed: int) -> str:
        nonlocal sampler_calls
        sampler_calls += 1
        return "sampled"

    gated = sched.gate(fake_sampler)
    result = await asyncio.wait_for(gated("p", 1), timeout=5)
    assert isinstance(result, ProbeFailure)
    assert result.reason == "asleep"
    assert sampler_calls == 0
    assert calls >= 2


async def test_lived_time_persists(tmp_path: Path):
    tick_idx = 0

    def tick_index() -> int:
        nonlocal tick_idx
        return tick_idx

    sched, core, clock = make(tmp_path, tick_index=tick_index)
    paths = sched._paths
    write_reference(paths)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    save_ledger(
        paths,
        Ledger(
            reference_id="r",
            lived_seconds=0.0,
            lived_ticks=0,
            last_look_at=(base - timedelta(seconds=200)).isoformat(),
        ),
    )
    await sched.tick()
    for _ in range(5):
        clock.t += 10
        tick_idx += 1
        await sched.tick()
    ledger = load_ledger(paths)
    assert ledger.lived_seconds == 30.0
    assert ledger.lived_ticks == 3

    sched2, _, _ = make(
        tmp_path, tick_index=tick_index, monotonic=clock, clock_now=clock
    )
    await sched2.tick()
    assert load_ledger(paths).lived_seconds == ledger.lived_seconds
    assert load_ledger(paths).lived_ticks == ledger.lived_ticks

    # The restarted scheduler adds only what it lived itself.
    for _ in range(3):
        clock.t += 10
        tick_idx += 1
        await sched2.tick()
    after = load_ledger(paths)
    assert after.lived_seconds == ledger.lived_seconds + 30.0
    assert after.lived_ticks == ledger.lived_ticks + 3


async def test_no_ledger_drops_pending_lived_time(tmp_path: Path):
    sched, core, clock = make(tmp_path)
    paths = sched._paths
    write_reference(paths)
    await sched.tick()
    clock.t += 10
    await sched.tick()
    clock.t += 30
    await sched.tick()
    assert not paths.ledger.exists()
    assert sched._pending_s == 0.0
    assert sched._pending_ticks == 0


async def test_capture_request(tmp_path: Path):
    sched, core, clock = make(tmp_path)
    sched.request_capture("birth")
    await sched.tick()
    assert core.captures == ["birth"]
    assert sched._capture_kind is None


async def test_capture_blocked_retries(tmp_path: Path):
    sched, core, clock = make(tmp_path, paused=lambda: True)
    sched.request_capture("birth")
    await sched.tick()
    assert sched._capture_at == 20.0
    assert sched.state.last_reason == "paused"
    clock.t = 20
    await sched.tick()
    assert sched._capture_at == 40.0
    clock.t = 40
    sched._paused = lambda: False
    await sched.tick()
    assert core.captures == ["birth"]


async def test_capture_failure_backs_off(tmp_path: Path):
    sched, core, clock = make(tmp_path)
    core.capture_result = (None, "request_failed")
    sched.request_capture("birth")
    await sched.tick()
    # Retry delays are 5, 10, 20, then 20 (capped).
    assert sched._capture_at == 5.0
    assert sched._capture_backoff == 10.0
    clock.t = 5
    await sched.tick()
    assert sched._capture_at == 15.0
    assert sched._capture_backoff == 20.0
    clock.t = 15
    await sched.tick()
    assert sched._capture_at == 35.0
    assert sched._capture_backoff == 20.0
    clock.t = 35
    await sched.tick()
    assert sched._capture_at == 55.0
    assert sched._capture_backoff == 20.0
    assert core.captures == ["birth", "birth", "birth", "birth"]


async def test_capture_store_error_clears_request(tmp_path: Path):
    sched, core, clock = make(tmp_path)
    core.raise_on_capture = ReferenceExists("already exists")
    sched.request_capture("birth")
    await sched.tick()
    assert sched._capture_kind is None
    assert sched._capture_at is None
    assert core.captures == ["birth"]


async def test_inconclusive_alert(tmp_path: Path):
    alerts: list[dict] = []

    async def record_alert(d: dict) -> None:
        alerts.append(d)

    sched, core, clock = make(tmp_path, alert=record_alert)
    paths = sched._paths
    write_reference(paths)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    save_ledger(
        paths,
        Ledger(
            reference_id="r",
            lived_seconds=10.0,
            lived_ticks=5,
            inconclusive_since=(base - timedelta(seconds=600)).isoformat(),
            inconclusive_alerted=False,
            last_look_at=(base - timedelta(seconds=200)).isoformat(),
        ),
    )
    core.next_look = LookOutcome("inconclusive", "request_failed", None)
    await sched.tick()
    clock.t = 10
    await sched.tick()
    assert len(alerts) == 1
    assert alerts[0]["kind"] == "individuation_inconclusive"
    assert load_ledger(paths).inconclusive_alerted is True

    # Further inconclusive attempts in the same stretch do not alert again.
    clock.t = 10 + 50
    await sched.tick()
    assert len(core.looks) == 2
    assert len(alerts) == 1


async def test_alert_failure_retried(tmp_path: Path):
    calls = 0

    async def flaky_alert(d: dict) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")

    sched, core, clock = make(tmp_path, alert=flaky_alert)
    paths = sched._paths
    write_reference(paths)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    save_ledger(
        paths,
        Ledger(
            reference_id="r",
            lived_seconds=10.0,
            lived_ticks=5,
            inconclusive_since=(base - timedelta(seconds=600)).isoformat(),
            inconclusive_alerted=False,
            last_look_at=(base - timedelta(seconds=200)).isoformat(),
        ),
    )
    core.next_look = LookOutcome("inconclusive", "request_failed", None)
    await sched.tick()
    clock.t = 10
    await sched.tick()
    assert calls == 1
    assert load_ledger(paths).inconclusive_alerted is False
    clock.t = 60
    await sched.tick()
    assert calls == 2
    assert load_ledger(paths).inconclusive_alerted is True


async def test_scored_clears_trigger(tmp_path: Path):
    sched, core, clock = make(tmp_path)
    paths = sched._paths
    write_reference(paths)
    save_ledger(paths, Ledger(reference_id="r", lived_seconds=10.0, lived_ticks=5))
    await sched.tick()
    clock.t = 10
    await sched.tick()
    assert len(core.looks) == 1
    assert sched._look_due_at is None


async def test_inconclusive_reschedules(tmp_path: Path):
    sched, core, clock = make(tmp_path)
    paths = sched._paths
    write_reference(paths)
    save_ledger(paths, Ledger(reference_id="r", lived_seconds=10.0, lived_ticks=5))
    core.next_look = LookOutcome("inconclusive", "x", None)
    await sched.tick()
    clock.t = 10
    await sched.tick()
    assert sched._look_due_at == 60.0


async def test_exception_outcome_error(tmp_path: Path):
    sched, core, clock = make(tmp_path)
    paths = sched._paths
    write_reference(paths)
    save_ledger(paths, Ledger(reference_id="r", lived_seconds=10.0, lived_ticks=5))
    core.raise_on_look = RuntimeError("boom")
    await sched.tick()
    clock.t = 10
    await sched.tick()
    assert sched.state.last_outcome == "error"
    assert sched.state.last_reason == "RuntimeError"


async def test_run_survives_exception_and_stops(tmp_path: Path):
    sched, core, clock = make(tmp_path)

    stops = 0

    async def stop_after_two(s: float) -> None:
        nonlocal stops
        stops += 1
        if stops >= 2:
            sched.stop()

    sched._sleep = stop_after_two

    bad_calls = 0
    orig_tick = sched.tick

    async def bad_tick() -> None:
        nonlocal bad_calls
        bad_calls += 1
        if bad_calls == 1:
            raise RuntimeError("boom")
        return await orig_tick()

    sched.tick = bad_tick

    await sched.run()
    assert bad_calls >= 2
    assert stops >= 2
    assert sched._stopped is True


def test_settings_validation():
    with pytest.raises(ValueError):
        SchedulerSettings(daily_s=0)
    with pytest.raises(ValueError):
        SchedulerSettings(capture_retry_initial_s=30, capture_retry_max_s=20)
