# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kaine.cycle.individuation_producer import LookOutcome
from kaine.cycle.individuation_scheduler import IndividuationScheduler
from kaine.lifecycle.individuation_store import (
    IndividuationStoreError,
    LedgerUnreadable,
)
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor
from tests.test_individuation_scheduler import (
    Clock,
    FakeCore,
    FakeDoc,
    Ledger,
    load_ledger,
    make,
    save_ledger,
    write_reference,
)


@pytest.fixture(autouse=True)
def reset_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


class AdvancingCaptureCore(FakeCore):
    async def capture_reference(self, kind: str) -> tuple[FakeDoc | None, str | None]:
        self.captures.append(kind)
        self.clock.t += 1000
        return (None, "request_failed")


class BirthCaptureCore(FakeCore):
    def __init__(
        self,
        clock: Clock,
        paths,
        sched: IndividuationScheduler | None = None,
    ):
        super().__init__(clock, sched)
        self.paths = paths

    async def capture_reference(self, kind: str) -> tuple[FakeDoc | None, str | None]:
        self.captures.append(kind)
        self.clock.t += 4000
        write_reference(self.paths)
        save_ledger(self.paths, Ledger(reference_id="r"))
        return (FakeDoc("birth"), None)


class ScoredThenErrorCore(FakeCore):
    def __init__(
        self,
        clock: Clock,
        paths,
        sched: IndividuationScheduler | None = None,
    ):
        super().__init__(clock, sched)
        self.paths = paths

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
        ledger = load_ledger(self.paths)
        save_ledger(
            self.paths,
            dataclasses.replace(
                ledger, looks_completed=ledger.looks_completed + 1
            ),
        )
        raise RuntimeError("boom")


async def test_capture_store_failure_backs_off_instead_of_clearing(tmp_path: Path):
    sched, core, _clock = make(tmp_path)
    core.raise_on_capture = LedgerUnreadable("x")
    sched.request_capture("birth")
    await sched.tick()
    assert sched._capture_kind == "birth"
    assert sched._capture_at == 5.0
    assert core.captures == ["birth"]


async def test_capture_retry_counts_from_attempt_end(tmp_path: Path):
    sched, _core, clock = make(tmp_path)
    core = AdvancingCaptureCore(clock, sched)
    sched.bind(core)
    sched.request_capture("birth")
    await sched.tick()
    assert sched._capture_at == clock.t + 5
    assert core.captures == ["birth"]


async def test_capture_time_is_not_lived_time(tmp_path: Path):
    sched, _core, clock = make(tmp_path)
    core = BirthCaptureCore(clock, sched._paths, sched)
    sched.bind(core)
    sched.request_capture("birth")
    await sched.tick()
    clock.t += 50
    await sched.tick()
    ledger = load_ledger(sched._paths)
    assert ledger.lived_seconds < 100.0


async def test_capture_not_blocked_by_embedder(tmp_path: Path):
    sched, core, _clock = make(tmp_path, embedder_ready=lambda: False)
    sched.request_capture("birth")
    await sched.tick()
    assert core.captures == ["birth"]


async def test_scored_then_exception_is_not_inconclusive(tmp_path: Path):
    sched, _core, clock = make(tmp_path)
    core = ScoredThenErrorCore(clock, sched._paths, sched)
    sched.bind(core)
    paths = sched._paths
    write_reference(paths)
    save_ledger(paths, Ledger(reference_id="r", lived_seconds=10.0, lived_ticks=5))
    await sched.tick()
    clock.t = 10
    await sched.tick()
    ledger = load_ledger(paths)
    assert ledger.inconclusive_since is None
    assert sched._look_due_at is None
    assert sched.state.last_outcome == "error"


async def test_look_exception_retries(tmp_path: Path):
    sched, core, clock = make(tmp_path)
    paths = sched._paths
    write_reference(paths)
    save_ledger(paths, Ledger(reference_id="r", lived_seconds=10.0, lived_ticks=5))
    core.raise_on_look = RuntimeError("boom")
    await sched.tick()
    clock.t = 10
    await sched.tick()
    assert sched._look_due_at == 60.0
    assert sched.state.last_outcome == "error"


async def test_alert_not_repeated_when_flag_save_fails(
    tmp_path: Path, monkeypatch
):
    real_save_ledger = save_ledger

    def failing_save_ledger(paths_obj, ledger):
        if ledger.inconclusive_alerted:
            raise IndividuationStoreError("disk full")
        return real_save_ledger(paths_obj, ledger)

    monkeypatch.setattr(
        "kaine.cycle.individuation_scheduler.save_ledger", failing_save_ledger
    )

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

    clock.t = 60
    await sched.tick()
    assert len(core.looks) == 2
    assert len(alerts) == 1


class SlowRaisingCore(FakeCore):
    async def look(
        self, *, warmed_up: bool, lived_seconds: float, lived_ticks: int
    ) -> LookOutcome:
        self.clock.t += 1000
        raise RuntimeError("boom")


async def test_inconclusive_retry_counts_from_look_end(tmp_path: Path):
    sched, core, clock = make(tmp_path)
    write_reference(sched._paths)
    save_ledger(
        sched._paths, Ledger(reference_id="r", lived_seconds=10.0, lived_ticks=5)
    )
    core.next_look = LookOutcome("inconclusive", "request_failed", None)
    core.look_delay = 1000.0
    await sched.tick()
    clock.t = 10
    await sched.tick()
    assert sched._look_due_at == clock.t + 50


async def test_error_retry_counts_from_look_end(tmp_path: Path):
    sched, _core, clock = make(tmp_path)
    core = SlowRaisingCore(clock)
    sched.bind(core)
    write_reference(sched._paths)
    save_ledger(
        sched._paths, Ledger(reference_id="r", lived_seconds=10.0, lived_ticks=5)
    )
    await sched.tick()
    clock.t = 10
    await sched.tick()
    assert sched._look_due_at == clock.t + 50
