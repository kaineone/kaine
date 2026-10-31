# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Every failure path, skip precondition and alert of the individuation producer.

The rig is the real producer core, the real probe sampler and the real
scheduler, driven by a fake organ (a scripted chat client) through a minimal
stand-in for the language module. Reports go to the real encrypted report sink
and the verdict is read back through the shared reader
(``kaine.lifecycle.divergence.read_individuation``), so each test checks what
the welfare net would actually see.

Every failure test asserts the recorded outcome and reason, and that nothing
unsafe follows: no look counted, no alpha spent, no latch, nothing published on
``individuation.out``, no p, T, H or significance in the report, and no probe
text, prompt or seed in any report, ledger or alert.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import numpy as np
import pytest

from kaine.cycle.individuation_probe import build_probe_sampler
from kaine.cycle.individuation_producer import IndividuationCore, ProducerSettings
from kaine.cycle.individuation_scheduler import (
    IndividuationScheduler,
    SchedulerSettings,
)
from kaine.lifecycle.divergence import read_individuation
from kaine.lifecycle.individuation_stats import required_permutations, spending_alpha
from kaine.lifecycle.individuation_store import (
    REPORT_FIELDS,
    IndividuationPaths,
    Ledger,
    load_ledger,
    load_reference,
    read_reports,
    report_sink,
    save_ledger,
)
from kaine.modules.language.client import ChatResponse
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor
from tests.test_individuation_producer_core import (  # noqa: F401  (autouse fixture)
    BATTERY,
    CONDITIONS,
    FakeConditioning,
    FakeEmbed,
    FakePublish,
    FixedNow,
    deterministic_seeds,
)
from tests.test_individuation_scheduler import Clock, WallClock, no_sleep
from tests.test_individuation_store import _enable_encryption

DISCLOSURE = "You are periodically assessed for your own protection."
MAX_REPORT_AGE_S = 7 * 86_400.0
NOW = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def reset_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


# --- the fake organ ---------------------------------------------------------


class FakeOrgan:
    """Scripted chat client standing in for the language organ.

    Healthy answers are ``"{prompt}|{variant}|{seed}"``, the format
    ``FakeEmbed`` understands. From call ``fault_at`` on, every call returns
    ``fault``. ``on_call`` runs before each answer with the call number, so a
    test can unload the organ, start a sleep or pause the cycle mid-run.
    """

    def __init__(self, variant: str = "maturation") -> None:
        self.variant = variant
        self.calls = 0
        self.fault: str | None = None
        self.fault_at = 1
        self.lora_applied = True
        self.on_call: Any = None

    @property
    def base_url(self) -> str:
        return "fake://organ"

    def fail_from(self, call: int, fault: str) -> None:
        self.fault_at = call
        self.fault = fault

    async def complete(self, req: Any) -> ChatResponse:
        self.calls += 1
        if self.on_call is not None:
            self.on_call(self.calls)
        fault = self.fault if self.calls >= self.fault_at else None
        if fault == "raise":
            raise RuntimeError("organ connection reset")
        if fault == "http_500":
            request = httpx.Request("POST", "http://organ/v1/chat/completions")
            raise httpx.HTTPStatusError(
                "server error", request=request, response=httpx.Response(500, request=request)
            )
        if fault == "cancel":
            raise asyncio.CancelledError()
        if fault == "resting":
            return ChatResponse(text="", model="m", raw={"organ_resting": True})
        if fault == "reasoning_only":
            return ChatResponse(
                text=f"{req.about}|{self.variant}|{req.seed}",
                model="m",
                finish_reason="stop",
                from_content=False,
                lora_applied=self.lora_applied,
            )
        if fault == "empty":
            return ChatResponse(
                text="   ",
                model="m",
                finish_reason="stop",
                from_content=True,
                lora_applied=self.lora_applied,
            )
        return ChatResponse(
            text=f"{req.about}|{self.variant}|{req.seed}",
            model="m",
            completion_tokens=5,
            finish_reason="stop",
            from_content=True,
            lora_applied=self.lora_applied,
        )


class FakeLanguage:
    """The two language-module seams the probe sampler uses, nothing else."""

    def __init__(self, organ: FakeOrgan) -> None:
        self.chat_client = organ
        self.self_model: dict | None = {
            "values": ["value1"],
            "behavioral_norms": ["norm1"],
            "situation_facts": [DISCLOSURE],
        }

    def probe_self_model(self) -> dict | None:
        return self.self_model

    def probe_request(
        self, about: str, *, seed: int, max_tokens: int, self_model: dict
    ) -> Any:
        return SimpleNamespace(about=about, seed=seed, max_tokens=max_tokens)


class SyncReportSink:
    """The real encrypted report sink, written synchronously so tests can read it."""

    def __init__(self, paths: IndividuationPaths) -> None:
        self._sink = report_sink(paths)
        paths.reports.mkdir(parents=True, exist_ok=True)
        self.writes: list[dict] = []

    async def write(self, report: dict) -> None:
        self.writes.append(report)
        self._sink.write_sync(report)


# --- the rig ----------------------------------------------------------------


@dataclasses.dataclass
class Rig:
    core: IndividuationCore
    paths: IndividuationPaths
    organ: FakeOrgan
    language: FakeLanguage
    sink: SyncReportSink
    pub: FakePublish
    state_root: Path
    sched: IndividuationScheduler | None = None
    clock: Clock | None = None
    alerts: list[dict] = dataclasses.field(default_factory=list)
    adapter_ok: list[bool] = dataclasses.field(default_factory=lambda: [True])


def sched_settings() -> SchedulerSettings:
    return SchedulerSettings(
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


def make_rig(
    state_root: Path,
    *,
    organ: FakeOrgan | None = None,
    conditioning: Any = None,
    conditions: Any = None,
    embed: Any = None,
    battery: list[str] | None = None,
    settings: ProducerSettings | None = None,
    with_scheduler: bool = False,
    clock: Clock | None = None,
    sampler_kwargs: dict | None = None,
    sched_overrides: dict | None = None,
) -> Rig:
    """Build the real core (and optionally the real scheduler) over one store.

    Calling it twice with the same ``state_root`` is a process restart: new
    instances, same encrypted state on disk.
    """
    paths = IndividuationPaths(root=state_root / "individuation")
    organ = organ or FakeOrgan()
    language = FakeLanguage(organ)
    sampler = build_probe_sampler(
        language=language, required_fact=DISCLOSURE, **(sampler_kwargs or {})
    )
    sink = SyncReportSink(paths)
    pub = FakePublish()
    rig = Rig(
        core=None,  # type: ignore[arg-type]
        paths=paths,
        organ=organ,
        language=language,
        sink=sink,
        pub=pub,
        state_root=state_root,
    )
    abort_reason: Any = lambda: None  # noqa: E731
    if with_scheduler:
        rig.clock = clock or Clock(0.0)

        async def record_alert(payload: dict) -> None:
            rig.alerts.append(payload)

        kwargs: dict[str, Any] = {
            "paths": paths,
            "settings": sched_settings(),
            "clock_now": rig.clock,
            "paused_seconds": lambda: 0.0,
            "tick_index": lambda: None,
            "organ_unloaded": lambda: False,
            "paused": lambda: False,
            "embedder_ready": lambda: True,
            "language_idle": lambda: True,
            "alert": record_alert,
            "adapter_verifiable": lambda: rig.adapter_ok[0],
            "monotonic": rig.clock,
            "now": WallClock(rig.clock),
            "sleep": no_sleep,
        }
        kwargs.update(sched_overrides or {})
        rig.sched = IndividuationScheduler(**kwargs)
        sampler = rig.sched.gate(sampler)
        abort_reason = rig.sched.abort_reason
    rig.core = IndividuationCore(
        paths=paths,
        settings=settings or ProducerSettings(n_reference=6, n_current=4),
        battery=battery or BATTERY,
        sampler=sampler,
        embed=embed or FakeEmbed(),
        embedder_id="fake-embed",
        conditions=conditions or (lambda: dict(CONDITIONS)),
        conditioning_inputs=conditioning or FakeConditioning(sha="sha-a", second_sha="sha-b"),
        born_at=lambda: "2026-01-01T00:00:00+00:00",
        maturation_adapter_file=lambda: None,
        report_sink=sink,
        publish=pub,
        abort_reason=abort_reason,
        rng=np.random.default_rng(0),
        now=FixedNow(),
        entity_name="test",
    )
    if rig.sched is not None:
        rig.sched.bind(rig.core)
    return rig


async def captured(rig: Rig) -> Ledger:
    doc, reason = await rig.core.capture_reference("maturation")
    assert reason is None and doc is not None
    ledger = load_ledger(rig.paths)
    assert ledger is not None
    return ledger


def warm(paths: IndividuationPaths, **extra: Any) -> Ledger:
    """Give the captured ledger enough lived time to pass the warm-up."""
    ledger = load_ledger(paths)
    ledger = dataclasses.replace(ledger, lived_seconds=10.0, lived_ticks=5, **extra)
    save_ledger(paths, ledger)
    return ledger


def verdict(rig: Rig) -> dict:
    return read_individuation(
        rig.state_root, now=NOW, max_report_age_s=MAX_REPORT_AGE_S
    )


def counters(ledger: Ledger | None) -> tuple | None:
    """The fields a look may change; an inconclusive run must leave them alone."""
    if ledger is None:
        return None
    return (
        ledger.reference_id,
        ledger.looks_completed,
        ledger.alpha_spent,
        ledger.last_look_conditions_digest,
        ledger.individuated,
        ledger.latched_at,
        ledger.latched_report_id,
    )


def assert_no_content(rig: Rig, *extra: Any) -> None:
    """No probe text, prompt or seed reaches a report, the ledger or an alert.

    The reference document legitimately holds the maturation samples; it is
    the only file allowed to, and it is checked separately under encryption.
    """
    blobs = [json.dumps(r) for r in rig.sink.writes]
    blobs += [json.dumps(a) for a in rig.alerts]
    blobs += [json.dumps(x, default=str) for x in extra]
    if rig.paths.ledger.exists():
        blobs.append(rig.paths.ledger.read_text(encoding="utf-8"))
    for path in rig.paths.reports.rglob("*.jsonl"):
        blobs.append(path.read_text(encoding="utf-8"))
    for blob in blobs:
        assert "|maturation|" not in blob
        assert "|current|" not in blob
        assert "|drifted|" not in blob
        for prompt in BATTERY:
            assert prompt not in blob
        assert "value1" not in blob and "norm1" not in blob
    for report in rig.sink.writes:
        assert set(report) <= REPORT_FIELDS
        assert "seed" not in report


def assert_inconclusive(
    rig: Rig,
    outcome: Any,
    reason: str,
    *,
    before: tuple | None,
    verdict_state: str = "inconclusive",
) -> None:
    """The look failed closed: recorded, not scored, not counted, not published."""
    assert (outcome.outcome, outcome.reason) == ("inconclusive", reason)
    assert outcome.significant is False
    assert outcome.effect_size_h is None
    report = rig.sink.writes[-1]
    assert report["outcome"] == "inconclusive"
    assert report["inconclusive_reason"] == reason
    for forbidden in ("p_value", "T", "effect_size_h", "significant", "alpha_k", "permutations"):
        assert forbidden not in report
    assert report.get("latched") is not True
    assert outcome.report == report
    assert rig.pub.published == []
    if before is not None:
        assert counters(load_ledger(rig.paths)) == before
    v = verdict(rig)
    assert v["state"] == verdict_state
    assert v["latched"] is False
    assert_no_content(rig)


# --- failures from the organ, mid-run ---------------------------------------

ORGAN_FAULTS = [
    # (fault injected by the organ, expected reason)
    ("resting", "organ_resting"),
    ("reasoning_only", "no_content"),
    ("empty", "no_content"),
    ("raise", "request_failed"),
    ("http_500", "request_failed"),
]


@pytest.mark.parametrize("fault,reason", ORGAN_FAULTS)
async def test_organ_fault_mid_run_is_inconclusive(tmp_path, fault, reason):
    rig = make_rig(tmp_path)
    before = counters(await captured(rig))
    capture_calls = rig.organ.calls
    rig.organ.variant = "current"
    # Fail on the 6th of 12 current requests: half a sample must not be scored.
    rig.organ.fail_from(capture_calls + 6, fault)

    outcome = await rig.core.look(warmed_up=True, lived_seconds=100.0, lived_ticks=50)

    assert_inconclusive(rig, outcome, reason, before=before)
    assert rig.organ.calls == capture_calls + 6


async def test_adapter_not_applied_by_the_organ_is_inconclusive(tmp_path):
    rig = make_rig(tmp_path, sampler_kwargs={"adapter_expected": lambda: True})
    before = counters(await captured(rig))
    rig.organ.variant = "current"
    rig.organ.lora_applied = False

    outcome = await rig.core.look(warmed_up=True, lived_seconds=100.0, lived_ticks=50)

    assert_inconclusive(rig, outcome, "adapter_not_applied", before=before)


async def test_adapter_resolver_failure_is_inconclusive(tmp_path):
    ok = [True]

    async def adapter_check() -> bool:
        return ok[0]

    rig = make_rig(tmp_path, sampler_kwargs={"adapter_check": adapter_check})
    before = counters(await captured(rig))
    calls = rig.organ.calls
    ok[0] = False

    outcome = await rig.core.look(warmed_up=True, lived_seconds=100.0, lived_ticks=50)

    assert_inconclusive(rig, outcome, "adapter_not_applied", before=before)
    assert rig.organ.calls == calls


@pytest.mark.parametrize(
    "self_model,reason",
    [
        (None, "self_model_not_ready"),
        ({"values": ["value1"], "behavioral_norms": ["norm1"], "situation_facts": []},
         "disclosure_not_ready"),
    ],
)
async def test_probe_preconditions_in_the_sampler_are_inconclusive(tmp_path, self_model, reason):
    rig = make_rig(tmp_path)
    before = counters(await captured(rig))
    calls = rig.organ.calls
    rig.language.self_model = self_model

    outcome = await rig.core.look(warmed_up=True, lived_seconds=100.0, lived_ticks=50)

    assert_inconclusive(rig, outcome, reason, before=before)
    assert rig.organ.calls == calls


# --- failures before any organ request --------------------------------------


def _corrupt(path: Path) -> None:
    path.write_text("{not json", encoding="utf-8")


async def _setup_ledger_unreadable(rig: Rig) -> None:
    await captured(rig)
    _corrupt(rig.paths.ledger)


async def _setup_reference_unreadable(rig: Rig) -> None:
    await captured(rig)
    _corrupt(rig.paths.reference)


async def _setup_no_reference(rig: Rig) -> None:
    await captured(rig)
    rig.paths.reference.unlink()


async def _setup_ledger_missing(rig: Rig) -> None:
    await captured(rig)
    rig.paths.ledger.unlink()


async def _setup_ledger_reference_mismatch(rig: Rig) -> None:
    ledger = await captured(rig)
    rig.paths.ledger.unlink()
    save_ledger(rig.paths, dataclasses.replace(ledger, reference_id="another-reference"))


async def _setup_battery_changed(rig: Rig) -> None:
    await captured(rig)
    rig.core._battery = (*BATTERY[:-1], "A different question?")


async def _setup_conditions_changed(rig: Rig) -> None:
    await captured(rig)
    rig.core._conditions = lambda: {**CONDITIONS, "server_build": "other-build"}


async def _setup_conditions_unreadable(rig: Rig) -> None:
    await captured(rig)

    def raising() -> dict:
        raise OSError("organ /props unreachable")

    rig.core._conditions = raising


async def _setup_refresh_conditions_fails(rig: Rig) -> None:
    await captured(rig)

    async def refresh() -> None:
        raise httpx.ConnectError("organ unreachable")

    rig.core._refresh_conditions = refresh


async def _setup_conditioning_unreadable(rig: Rig) -> None:
    await captured(rig)

    def raising() -> tuple:
        raise OSError("self_model.json unreadable")

    rig.core._conditioning_inputs = raising


async def _setup_alpha_unresolvable(rig: Rig) -> None:
    ledger = await captured(rig)
    save_ledger(rig.paths, dataclasses.replace(ledger, looks_completed=_first_unresolvable_k() - 1))


PRE_SAMPLING = [
    # (setup, expected reason, expected shared-verdict state)
    # Recorded under reference_id "unknown"; the unreadable ledger reads as individuated.
    (_setup_ledger_unreadable, "ledger_unreadable", "unreadable"),
    (_setup_reference_unreadable, "reference_unreadable", "unreadable"),
    (_setup_no_reference, "no_reference", "no_reference"),
    (_setup_ledger_missing, "ledger_missing", "inconclusive"),
    (_setup_ledger_reference_mismatch, "ledger_reference_mismatch", "inconclusive"),
    (_setup_battery_changed, "battery_changed", "inconclusive"),
    (_setup_conditions_changed, "conditions_changed", "inconclusive"),
    (_setup_conditions_unreadable, "conditions_unreadable", "inconclusive"),
    # Recorded under reference_id "unknown", so the shared reader shows no report.
    (_setup_refresh_conditions_fails, "conditions_unreadable", "none"),
    (_setup_conditioning_unreadable, "conditioning_unreadable", "inconclusive"),
    (_setup_alpha_unresolvable, "alpha_unresolvable", "inconclusive"),
]


@pytest.mark.parametrize(
    "setup,reason,verdict_state", PRE_SAMPLING, ids=[r for _, r, _ in PRE_SAMPLING]
)
async def test_pre_sampling_failure_is_inconclusive_without_organ_requests(
    tmp_path, setup, reason, verdict_state
):
    rig = make_rig(tmp_path)
    await setup(rig)
    calls = rig.organ.calls
    ledger_bytes = rig.paths.ledger.read_bytes() if rig.paths.ledger.exists() else None
    try:
        before = counters(load_ledger(rig.paths))
    except Exception:
        before = None

    outcome = await rig.core.look(warmed_up=True, lived_seconds=100.0, lived_ticks=50)

    assert_inconclusive(rig, outcome, reason, before=before, verdict_state=verdict_state)
    assert rig.organ.calls == calls
    # The ledger file is not rewritten at all, so a corrupt one is never reset to k = 0.
    if ledger_bytes is None:
        assert not rig.paths.ledger.exists()
    else:
        assert rig.paths.ledger.read_bytes() == ledger_bytes


async def test_unreadable_ledger_counts_as_individuated_for_the_shared_verdict(tmp_path):
    rig = make_rig(tmp_path)
    await _setup_ledger_unreadable(rig)
    await rig.core.look(warmed_up=True, lived_seconds=100.0, lived_ticks=50)
    assert verdict(rig)["individuated"] is True


# --- failures after sampling ------------------------------------------------


async def test_conditioning_changed_mid_run_is_inconclusive(tmp_path):
    conditioning = FakeConditioning()
    # Capture reads a twice; the look reads b before sampling and c after.
    conditioning.sequence = ["sha-a", "sha-a", "sha-b", "sha-c"]
    rig = make_rig(tmp_path, conditioning=conditioning)
    before = counters(await captured(rig))
    calls = rig.organ.calls

    outcome = await rig.core.look(warmed_up=True, lived_seconds=100.0, lived_ticks=50)

    assert_inconclusive(rig, outcome, "conditioning_changed_mid_run", before=before)
    assert rig.organ.calls == calls + len(BATTERY) * 4


async def test_conditioning_unreadable_after_sampling_is_inconclusive(tmp_path):
    rig = make_rig(tmp_path)
    before = counters(await captured(rig))
    reads = {"n": 0}

    def once_then_raise() -> tuple:
        reads["n"] += 1
        if reads["n"] == 1:
            return ("sha-b", ["value1"], ["norm1"])
        raise OSError("self_model.json vanished")

    rig.core._conditioning_inputs = once_then_raise

    outcome = await rig.core.look(warmed_up=True, lived_seconds=100.0, lived_ticks=50)

    assert_inconclusive(rig, outcome, "conditioning_unreadable", before=before)


class BadVectorEmbed(FakeEmbed):
    """Returns an unusable vector for current samples only."""

    def __init__(self, bad: list[float]) -> None:
        super().__init__()
        self.bad = bad

    async def __call__(self, text: str) -> list[float]:
        if "|current|" in text:
            return list(self.bad)
        return await super().__call__(text)


@pytest.mark.parametrize(
    "bad",
    [[float("nan")] * 16, [0.0] * 16, [float("inf")] + [0.0] * 15, []],
    ids=["nan", "zero", "inf", "empty"],
)
async def test_unusable_embedding_is_inconclusive_not_maximal(tmp_path, bad):
    rig = make_rig(tmp_path, embed=BadVectorEmbed(bad))
    before = counters(await captured(rig))
    rig.organ.variant = "current"

    outcome = await rig.core.look(warmed_up=True, lived_seconds=100.0, lived_ticks=50)

    assert_inconclusive(rig, outcome, "embedding_failed", before=before)


# --- aborts mid-run, through the real scheduler -----------------------------


def _ready_for_look(rig: Rig) -> None:
    warm(rig.paths)


@pytest.mark.parametrize("abort", ["organ_unloaded", "asleep", "paused", "deadline_exceeded"])
async def test_abort_mid_run_through_the_scheduler(tmp_path, abort):
    flags = {"unloaded": False, "paused": False}
    rig = make_rig(
        tmp_path,
        with_scheduler=True,
        sched_overrides={
            "organ_unloaded": lambda: flags["unloaded"],
            "paused": lambda: flags["paused"],
        },
    )
    before = counters(await captured(rig))
    _ready_for_look(rig)
    rig.organ.variant = "current"
    start = rig.organ.calls

    def on_call(n: int) -> None:
        if n != start + 3:
            return
        if abort == "organ_unloaded":
            flags["unloaded"] = True
        elif abort == "asleep":
            rig.sched.notify_sleep_started()
        elif abort == "paused":
            flags["paused"] = True
        else:
            rig.clock.t += 61  # past run_deadline_s = 60

    rig.organ.on_call = on_call
    await rig.sched.tick()
    rig.clock.t = 10
    await rig.sched.tick()

    # The fourth request is never sent: the run stops at the next check.
    assert rig.organ.calls == start + 3
    report = rig.sink.writes[-1]
    assert report["outcome"] == "inconclusive"
    assert report["inconclusive_reason"] == abort
    assert rig.sched.state.last_outcome == "inconclusive"
    assert rig.sched.state.last_reason == abort
    ledger = load_ledger(rig.paths)
    assert counters(ledger) == before
    assert ledger.last_inconclusive_reason == abort
    assert ledger.inconclusive_since is not None
    assert rig.pub.published == []
    assert verdict(rig)["state"] == "inconclusive"
    assert_no_content(rig)


# --- every skip precondition ------------------------------------------------

SKIPS = ["no_reference", "warming_up", "interval", "organ_unloaded", "asleep",
         "paused", "adapter_unverifiable", "embedder_not_ready", "unchanged"]


@pytest.mark.parametrize("skip", SKIPS)
async def test_skip_precondition_sends_nothing_and_writes_no_report(tmp_path, skip):
    flags = {"unloaded": False, "paused": False, "embedder": True}
    conditioning = (
        FakeConditioning(sha="sha-a") if skip == "unchanged"
        else FakeConditioning(sha="sha-a", second_sha="sha-b")
    )
    rig = make_rig(
        tmp_path,
        with_scheduler=True,
        conditioning=conditioning,
        sched_overrides={
            "organ_unloaded": lambda: flags["unloaded"],
            "paused": lambda: flags["paused"],
            "embedder_ready": lambda: flags["embedder"],
        },
    )
    if skip != "no_reference":
        await captured(rig)
        if skip == "interval":
            warm(rig.paths, last_look_at=(WallClock(rig.clock)() - timedelta(seconds=40)).isoformat())
        elif skip != "warming_up":
            warm(rig.paths)
    ledger_before = load_ledger(rig.paths)
    calls = rig.organ.calls

    if skip == "organ_unloaded":
        flags["unloaded"] = True
    elif skip == "asleep":
        rig.sched.notify_sleep_started()
    elif skip == "paused":
        flags["paused"] = True
    elif skip == "adapter_unverifiable":
        rig.adapter_ok[0] = False
    elif skip == "embedder_not_ready":
        flags["embedder"] = False

    await rig.sched.tick()
    rig.clock.t = 10
    await rig.sched.tick()

    assert rig.organ.calls == calls
    assert rig.sink.writes == []
    assert not any(rig.paths.reports.rglob("*.jsonl"))
    assert rig.pub.published == []
    assert rig.sched.state.last_outcome == "skipped"
    assert rig.sched.state.last_reason == skip
    ledger = load_ledger(rig.paths)
    assert counters(ledger) == counters(ledger_before)
    if ledger is not None:
        assert ledger.looks_completed == 0
        assert ledger.alpha_spent == 0.0
        assert ledger.individuated is False
    assert verdict(rig)["individuated"] is False
    assert_no_content(rig)


# --- alerts -----------------------------------------------------------------


async def test_first_conditions_changed_alerts_once_across_restarts(tmp_path):
    changed = lambda: {**CONDITIONS, "server_build": "new-build"}  # noqa: E731
    rig = make_rig(tmp_path, with_scheduler=True)
    ledger = await captured(rig)
    warm(rig.paths)
    rig.core._conditions = changed
    calls = rig.organ.calls

    await rig.sched.tick()
    rig.clock.t = 10
    await rig.sched.tick()

    assert rig.sink.writes[-1]["inconclusive_reason"] == "conditions_changed"
    assert rig.alerts == [
        {"kind": "individuation_conditions_changed", "reference_id": ledger.reference_id}
    ]
    after = load_ledger(rig.paths)
    assert after.conditions_alerted_reference == ledger.reference_id
    assert after.looks_completed == 0 and after.alpha_spent == 0.0
    assert after.individuated is False
    assert rig.organ.calls == calls
    assert rig.pub.published == []
    # The alert names the reference only, never a condition value.
    assert "new-build" not in json.dumps(rig.alerts)
    assert_no_content(rig)

    # The next due look in the same process does not alert again.
    rig.clock.t = 60
    await rig.sched.tick()
    assert len(rig.sink.writes) == 2
    assert len(rig.alerts) == 1

    # A restart (new core and scheduler over the same store) does not alert again.
    rig2 = make_rig(tmp_path, with_scheduler=True, clock=Clock(0.0))
    rig2.core._conditions = changed
    await rig2.sched.tick()
    rig2.clock.t = 10
    await rig2.sched.tick()
    assert rig2.sink.writes[-1]["inconclusive_reason"] == "conditions_changed"
    assert rig2.alerts == []
    assert load_ledger(rig2.paths).looks_completed == 0


async def test_long_inconclusive_alert_names_reason_and_preserves_nothing(tmp_path):
    rig = make_rig(tmp_path, with_scheduler=True)
    ledger = await captured(rig)
    warm(rig.paths)
    rig.organ.variant = "current"
    rig.organ.fail_from(rig.organ.calls + 1, "resting")

    await rig.sched.tick()
    t = 10.0
    while t <= 600:  # inconclusive_alert_s = 500, retries every 50 s
        rig.clock.t = t
        await rig.sched.tick()
        t += 50

    inconclusive = [a for a in rig.alerts if a["kind"] == "individuation_inconclusive"]
    assert len(inconclusive) == 1
    assert inconclusive[0]["last_reason"] == "organ_resting"
    assert set(inconclusive[0]) == {"kind", "inconclusive_since", "days", "last_reason"}
    after = load_ledger(rig.paths)
    assert after.inconclusive_alerted is True
    assert counters(after) == counters(ledger)
    assert all(r["outcome"] == "inconclusive" for r in rig.sink.writes)
    assert rig.pub.published == []
    assert verdict(rig)["individuated"] is False
    assert_no_content(rig)

    # A restart in the same stretch does not alert again.
    rig2 = make_rig(
        tmp_path, with_scheduler=True, clock=Clock(700.0),
        conditioning=FakeConditioning(sha="sha-b"),
    )
    rig2.organ.fail_from(1, "resting")
    await rig2.sched.tick()
    rig2.clock.t = 710
    await rig2.sched.tick()
    assert rig2.sink.writes[-1]["inconclusive_reason"] == "organ_resting"
    assert rig2.alerts == []

    # The next scored look clears the stretch.
    rig2.organ.fault = None
    rig2.clock.t = 760
    await rig2.sched.tick()
    assert rig2.sink.writes[-1]["outcome"] == "scored"
    cleared = load_ledger(rig2.paths)
    assert cleared.inconclusive_since is None
    assert cleared.inconclusive_alerted is False
    assert cleared.looks_completed == 1


# --- restart in the middle of a run -----------------------------------------


async def test_restart_mid_sampling_counts_the_look_once(tmp_path):
    rig = make_rig(tmp_path)
    before = counters(await captured(rig))
    rig.organ.variant = "current"
    rig.organ.fail_from(rig.organ.calls + 5, "cancel")  # the process dies mid-run

    with pytest.raises(asyncio.CancelledError):
        await rig.core.look(warmed_up=True, lived_seconds=100.0, lived_ticks=50)
    assert counters(load_ledger(rig.paths)) == before
    assert rig.sink.writes == []
    assert rig.pub.published == []

    rig2 = make_rig(tmp_path, conditioning=FakeConditioning(sha="sha-b"))
    outcome = await rig2.core.look(warmed_up=True, lived_seconds=150.0, lived_ticks=70)

    assert outcome.outcome == "scored"
    assert outcome.report["look_index"] == 1
    ledger = load_ledger(rig2.paths)
    assert ledger.looks_completed == 1
    assert ledger.alpha_spent == pytest.approx(spending_alpha(1, 0.05))
    reports = read_reports(rig2.paths, reference_id=ledger.reference_id)
    assert [r["look_index"] for r in reports] == [1]
    assert len(rig2.pub.published) == 1
    assert_no_content(rig2)


async def test_restart_between_ledger_and_report_never_double_counts(tmp_path):
    rig = make_rig(tmp_path)
    await captured(rig)

    async def die(report: dict) -> None:
        raise asyncio.CancelledError()  # the process dies after the ledger write

    rig.core._report_sink = SimpleNamespace(write=die)
    with pytest.raises(asyncio.CancelledError):
        await rig.core.look(warmed_up=True, lived_seconds=100.0, lived_ticks=50)
    first = load_ledger(rig.paths)
    assert first.looks_completed == 1
    assert rig.pub.published == []

    # Restart with the same conditioning: the look already counted, so it is not repeated.
    rig2 = make_rig(tmp_path, conditioning=FakeConditioning(sha="sha-b"))
    calls = rig2.organ.calls
    again = await rig2.core.look(warmed_up=True, lived_seconds=150.0, lived_ticks=70)
    assert (again.outcome, again.reason) == ("skipped", "unchanged")
    assert rig2.organ.calls == calls
    assert load_ledger(rig2.paths) == first

    # A later change is look 2, spending exactly alpha_1 + alpha_2 in total.
    rig3 = make_rig(tmp_path, conditioning=FakeConditioning(sha="sha-c"))
    third = await rig3.core.look(warmed_up=True, lived_seconds=200.0, lived_ticks=90)
    assert third.outcome == "scored"
    assert third.report["look_index"] == 2
    ledger = load_ledger(rig3.paths)
    assert ledger.looks_completed == 2
    assert ledger.alpha_spent == pytest.approx(spending_alpha(1, 0.05) + spending_alpha(2, 0.05))


async def test_scheduler_restart_mid_run_keeps_the_ledger_consistent(tmp_path):
    rig = make_rig(tmp_path, with_scheduler=True)
    await captured(rig)
    warm(rig.paths)
    start = rig.organ.calls

    # The scheduler task is cancelled (shutdown) in the middle of the look.
    def on_call(n: int) -> None:
        if n == start + 7:
            raise asyncio.CancelledError()

    rig.organ.on_call = on_call
    await rig.sched.tick()
    rig.clock.t = 10
    with pytest.raises(asyncio.CancelledError):
        await rig.sched.tick()
    mid = load_ledger(rig.paths)
    assert mid.looks_completed == 0 and mid.alpha_spent == 0.0
    assert rig.sink.writes == []

    rig2 = make_rig(
        tmp_path, with_scheduler=True, clock=Clock(0.0),
        conditioning=FakeConditioning(sha="sha-b"),
    )
    await rig2.sched.tick()
    rig2.clock.t = 10
    await rig2.sched.tick()
    assert rig2.sched.state.last_outcome == "scored"
    ledger = load_ledger(rig2.paths)
    assert ledger.looks_completed == 1
    assert ledger.alpha_spent == pytest.approx(spending_alpha(1, 0.05))
    assert ledger.lived_seconds >= mid.lived_seconds
    assert rig2.sched.state.looks_completed == 1
    reports = read_reports(rig2.paths, reference_id=ledger.reference_id)
    assert [(r["outcome"], r["look_index"]) for r in reports] == [("scored", 1)]

    # The interrupted look is not run a second time: the digest is now unchanged.
    calls = rig2.organ.calls
    again = await rig2.core.look(warmed_up=True, lived_seconds=500.0, lived_ticks=500)
    assert (again.outcome, again.reason) == ("skipped", "unchanged")
    assert rig2.organ.calls == calls
    assert load_ledger(rig2.paths).looks_completed == 1


async def test_restart_mid_capture_writes_nothing_and_recaptures(tmp_path):
    rig = make_rig(tmp_path)
    rig.organ.fail_from(9, "cancel")
    with pytest.raises(asyncio.CancelledError):
        await rig.core.capture_reference("maturation")
    assert not rig.paths.reference.exists()
    assert not rig.paths.ledger.exists()

    rig2 = make_rig(tmp_path)
    ledger = await captured(rig2)
    assert ledger.looks_completed == 0
    assert load_reference(rig2.paths).reference_id == ledger.reference_id


# --- alpha_unresolvable -----------------------------------------------------


def _first_unresolvable_k(alpha_total: float = 0.05, b_max: int = 2_000_000) -> int:
    k = 1
    while required_permutations(spending_alpha(k, alpha_total), b_max) is not None:
        k += 1
    return k


async def test_alpha_unresolvable_boundary(tmp_path):
    k_star = _first_unresolvable_k()
    assert 50 < k_star < 200  # design 2.7: about k = 100

    rig = make_rig(tmp_path)
    ledger = await captured(rig)
    save_ledger(rig.paths, dataclasses.replace(ledger, looks_completed=k_star - 2))

    last = await rig.core.look(warmed_up=True, lived_seconds=100.0, lived_ticks=50)
    assert last.outcome == "scored"
    assert last.report["look_index"] == k_star - 1
    assert last.report["alpha_k"] == pytest.approx(spending_alpha(k_star - 1, 0.05))

    rig2 = make_rig(tmp_path, conditioning=FakeConditioning(sha="sha-c"))
    before = counters(load_ledger(rig2.paths))
    calls = rig2.organ.calls
    outcome = await rig2.core.look(warmed_up=True, lived_seconds=200.0, lived_ticks=90)
    # The earlier scored report is from another digest, so the shared verdict is STALE.
    assert_inconclusive(rig2, outcome, "alpha_unresolvable", before=before, verdict_state="stale")
    assert outcome.report["look_index"] == k_star
    assert rig2.organ.calls == calls


async def test_alpha_unresolvable_raises_the_long_inconclusive_alert(tmp_path):
    rig = make_rig(tmp_path, with_scheduler=True)
    ledger = await captured(rig)
    warm(rig.paths)
    save_ledger(
        rig.paths,
        dataclasses.replace(load_ledger(rig.paths), looks_completed=_first_unresolvable_k() - 1),
    )
    calls = rig.organ.calls

    await rig.sched.tick()
    t = 10.0
    while t <= 600:
        rig.clock.t = t
        await rig.sched.tick()
        t += 50

    assert rig.organ.calls == calls
    assert {r["inconclusive_reason"] for r in rig.sink.writes} == {"alpha_unresolvable"}
    inconclusive = [a for a in rig.alerts if a["kind"] == "individuation_inconclusive"]
    assert len(inconclusive) == 1
    assert inconclusive[0]["last_reason"] == "alpha_unresolvable"
    after = load_ledger(rig.paths)
    assert after.alpha_spent == 0.0
    assert after.individuated is False
    assert after.reference_id == ledger.reference_id
    assert rig.pub.published == []


# --- encryption on: nothing readable on disk --------------------------------


async def test_failure_reports_are_encrypted_and_content_free_on_disk(tmp_path, monkeypatch):
    _enable_encryption(monkeypatch)
    rig = make_rig(tmp_path)
    ledger = await captured(rig)
    rig.organ.variant = "current"
    rig.organ.fail_from(rig.organ.calls + 2, "resting")

    outcome = await rig.core.look(warmed_up=True, lived_seconds=100.0, lived_ticks=50)
    assert outcome.reason == "organ_resting"

    for path in rig.paths.root.rglob("*"):
        if path.is_file():
            raw = path.read_bytes()
            assert b"|maturation|" not in raw
            assert b"|current|" not in raw
            assert b"inconclusive_reason" not in raw  # every line is an envelope
            for prompt in BATTERY:
                assert prompt.encode() not in raw
    reports = read_reports(rig.paths, reference_id=ledger.reference_id)
    assert [r["inconclusive_reason"] for r in reports] == ["organ_resting"]
    assert verdict(rig)["state"] == "inconclusive"


# --- known gaps (bugs), pinned until fixed ----------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BUG: a corrupt ledger raises no operator notice. The spec scenario 'A corrupt "
        "ledger fails closed' requires one, but IndividuationScheduler._mark_inconclusive "
        "returns early on LedgerUnreadable, and the long-inconclusive alert keeps its "
        "stretch in the unreadable ledger, so the operator is never alerted."
    ),
)
async def test_corrupt_ledger_raises_an_operator_notice(tmp_path):
    rig = make_rig(tmp_path, with_scheduler=True)
    await captured(rig)
    warm(rig.paths)
    _corrupt(rig.paths.ledger)

    await rig.sched.tick()
    t = 10.0
    while t <= 600:
        rig.clock.t = t
        await rig.sched.tick()
        t += 50

    assert rig.sink.writes and all(
        r["inconclusive_reason"] == "ledger_unreadable" for r in rig.sink.writes
    )
    assert rig.alerts, "no operator notice for an unreadable ledger"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BUG: a reference capture that keeps failing never alerts the operator. The "
        "'Long inconclusive stretches raise an operator alert' requirement counts 'no "
        "reference exists' as a due look, but _attempt_capture only backs off and "
        "_attempt_look skips no_reference without _mark_inconclusive, so no alert fires."
    ),
)
async def test_failing_capture_alerts_after_the_inconclusive_stretch(tmp_path):
    rig = make_rig(tmp_path, with_scheduler=True)
    rig.organ.fail_from(1, "resting")
    rig.sched.request_capture("capture")

    t = 0.0
    while t <= 2000:  # four times inconclusive_alert_s
        rig.clock.t = t
        await rig.sched.tick()
        t += 5
    assert not rig.paths.reference.exists()
    assert rig.alerts, "no operator notice while the entity has no reference"
