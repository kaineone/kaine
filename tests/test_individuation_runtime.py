# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from kaine.bus.schema import Event
from kaine.cycle.individuation_probe import ProbeFailure
from kaine.cycle.individuation_runtime import (
    DEFAULT_DISCLOSURE,
    IndividuationConfig,
    build_runtime,
)
from kaine.lifecycle.individuation_store import (
    Ledger,
    ProbeSample,
    ReferenceDoc,
    battery_digest_of,
    conditioning_digest,
    load_ledger,
    save_ledger,
    save_reference,
)
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor


@pytest.fixture(autouse=True)
def reset_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


class FakeChatClient:
    async def complete(self, req: Any) -> Any:
        class Resp:
            text = "probe response"
            from_content = True
            finish_reason = "stop"
            completion_tokens = 1
            raw: dict = {}
            lora_applied = False

        return Resp()


class FakeLingua:
    def __init__(self) -> None:
        self.chat_client = FakeChatClient()
        self._cond = {
            "model_id": "m",
            "temperature": 0.5,
            "think": False,
            "persona_digest": "abcd1234abcd1234",
        }

    def probe_self_model(self) -> dict:
        return {
            "values": ["val"],
            "behavioral_norms": ["norm"],
            "situation_facts": [DEFAULT_DISCLOSURE],
        }

    def probe_request(
        self, about: str, *, seed: int, max_tokens: int, self_model: dict
    ) -> Any:
        return MagicMock()

    def is_idle(self, quiet_s: float) -> bool:
        return True

    def probe_conditions(self) -> dict:
        return dict(self._cond)


class FakeEmbedder:
    kind = "sentence_transformers"
    model_id = "e"
    latent_dim = 3

    async def embed(self, text: str) -> list[float]:
        return [0.0] * self.latent_dim


class FakeEnsureFact:
    def __init__(self) -> None:
        self.facts: list[str] = []

    async def __call__(self, fact: str) -> bool:
        self.facts.append(fact)
        return True


class FakeBus:
    def __init__(self) -> None:
        self.events: list[Event] = []
        self._entries: list[tuple[str, Event]] = []

    async def publish(self, event: Event) -> None:
        self.events.append(event)

    async def last_entry_id(self, stream: str) -> str:
        return "0-0"

    def queue(self, *entries: tuple[str, Event]) -> None:
        self._entries.extend(entries)

    async def read_entries(
        self, stream: str, last_id: str, count: int, block_ms: int
    ) -> tuple[list[tuple[str, Event]], str | None]:
        # Like XREAD BLOCK: deliver what is queued, else wait briefly.
        if self._entries:
            batch, self._entries = self._entries, []
            return (batch, batch[-1][0])
        await asyncio.sleep(0.005)
        return ([], None)


class FakeEmbedderWithKind(FakeEmbedder):
    kind = "hash"


def build(tmp_path: Path, **over: Any):
    config = IndividuationConfig.from_dict(over.pop("config", None))
    bus = FakeBus()
    ef = FakeEnsureFact()
    lingua = FakeLingua()
    embedder = over.pop("embedder", FakeEmbedder())
    kwargs: dict[str, Any] = {
        "config": config,
        "battery": ["q1", "q2"],
        "lingua": lingua,
        "ensure_fact": ef,
        "embedder": embedder,
        "adapter_output_dir": None,
        "per_request_adapter": False,
        "state_root": tmp_path / "ind",
        "clock_now": lambda: 0.0,
        "paused_seconds": lambda: 0.0,
        "tick_index": lambda: 0,
        "is_paused": lambda: False,
        "organ_unloaded": lambda: False,
        "hypnos_sleeping": None,
        "born_at": lambda: None,
        "is_gestating": lambda: False,
        "bus": bus,
        "notify": None,
        "entity_name": "test",
    }
    kwargs.update(over)
    runtime = build_runtime(**kwargs)
    runtime.ensure_fact = ef
    return runtime


def test_config_defaults():
    cfg = IndividuationConfig.from_dict(None)
    assert cfg.enabled is False
    assert cfg.disclosure == DEFAULT_DISCLOSURE


def test_config_validation():
    with pytest.raises(ValueError, match="bogus"):
        IndividuationConfig.from_dict({"bogus": 1})
    with pytest.raises(ValueError):
        IndividuationConfig.from_dict({"enabled": "yes"})
    with pytest.raises(ValueError):
        IndividuationConfig.from_dict({"disclosure": ""})
    with pytest.raises(ValueError):
        IndividuationConfig.from_dict({"alpha_total": 2.0})


def test_config_subsections():
    cfg = IndividuationConfig.from_dict(
        {"enabled": True, "n_current": 4, "daily_s": 600}
    )
    assert cfg.producer.n_current == 4
    assert cfg.scheduler.daily_s == 600


async def test_start_disclosure_and_boot_capture(tmp_path: Path):
    runtime = build(tmp_path)
    await runtime.start()
    assert runtime.ensure_fact.facts == [DEFAULT_DISCLOSURE]
    assert runtime.scheduler._capture_kind == "capture"


async def test_start_gestating_on_birth(tmp_path: Path):
    runtime = build(tmp_path, is_gestating=lambda: True)
    await runtime.start()
    assert runtime.scheduler._capture_kind is None
    runtime.on_birth()
    assert runtime.scheduler._capture_kind == "birth"
    runtime.scheduler.notify_sleep_completed()
    assert runtime.scheduler._capture_kind == "capture"


async def test_start_asleep(tmp_path: Path):
    runtime = build(tmp_path, hypnos_sleeping=lambda: True)
    await runtime.start()
    assert runtime.scheduler.abort_reason() == "asleep"


def _make_reference(paths: Any, reference_id: str):
    samples = tuple(
        tuple(
            ProbeSample(
                text=f"p{i}s{j}",
                seed=j,
                finish_reason="stop",
                completion_tokens=1,
            )
            for j in range(2)
        )
        for i in range(2)
    )
    return ReferenceDoc(
        reference_id=reference_id,
        reference_kind="capture",
        captured_at=datetime.now(timezone.utc).isoformat(),
        born_at=None,
        battery=("q1", "q2"),
        battery_digest=battery_digest_of(("q1", "q2")),
        conditions={},
        conditioning={
            "adapter_sha": "none",
            "identity_values": ["v"],
            "identity_norms": ["n"],
        },
        samples=samples,
    )


async def test_recovery_no_ledger(tmp_path: Path):
    runtime = build(tmp_path)
    paths = runtime.paths
    paths.root.mkdir(parents=True, exist_ok=True)
    doc = _make_reference(paths, "ref-1")
    save_reference(paths, doc)
    assert not paths.ledger.exists()
    await runtime.start()
    ledger = load_ledger(paths)
    assert ledger is not None
    assert ledger.reference_id == doc.reference_id
    assert ledger.last_look_conditions_digest == conditioning_digest(
        adapter_sha=None, values=["v"], norms=["n"]
    )
    assert runtime.scheduler._capture_kind is None


async def test_recovery_mismatched_ledger(tmp_path: Path):
    runtime = build(tmp_path)
    paths = runtime.paths
    paths.root.mkdir(parents=True, exist_ok=True)
    old = Ledger(reference_id="old", looks_completed=3, alpha_spent=0.01)
    save_ledger(paths, old)
    doc = _make_reference(paths, "ref-2")
    save_reference(paths, doc)
    await runtime.start()
    ledger = load_ledger(paths)
    assert ledger.reference_id == doc.reference_id
    assert ledger.looks_completed == 3
    assert ledger.alpha_spent == 0.01


async def test_publish_divergence(tmp_path: Path):
    runtime = build(tmp_path)
    await runtime.publish_divergence(
        {"divergence_scalar": 0.3, "significant": True, "extra": "x"}
    )
    assert len(runtime.bus.events) == 1
    ev = runtime.bus.events[0]
    assert ev.source == "individuation"
    assert ev.type == "individuation.divergence"
    assert set(ev.payload.keys()) == {"divergence_scalar", "significant"}
    assert ev.payload["divergence_scalar"] == 0.3
    assert ev.payload["significant"] is True


async def test_alert_and_notify(tmp_path: Path):
    calls: list[str] = []

    async def notify(kind: str) -> None:
        calls.append(kind)

    runtime = build(tmp_path, notify=notify)
    await runtime.alert({"inconclusive_since": "2026-01-01", "days": 14.0})
    assert len(runtime.bus.events) == 1
    assert runtime.bus.events[0].type == "individuation.alert"
    assert calls == ["individuation_inconclusive"]

    async def bad_notify(kind: str) -> None:
        raise RuntimeError("boom")

    runtime2 = build(tmp_path, notify=bad_notify)
    with pytest.raises(RuntimeError, match="boom"):
        await runtime2.alert({"inconclusive_since": "2026-01-02", "days": 1.0})


async def test_watch_hypnos(tmp_path: Path):
    runtime = build(tmp_path)
    now = datetime.now(timezone.utc)
    start_ev = Event(
        source="hypnos",
        type="hypnos.sleep.started",
        payload={},
        salience=0.5,
        timestamp=now,
    )
    end_ev = Event(
        source="hypnos",
        type="hypnos.sleep.completed",
        payload={},
        salience=0.5,
        timestamp=now,
    )
    runtime.bus.queue(("1-0", start_ev))
    stop = asyncio.Event()
    task = asyncio.create_task(runtime._watch_hypnos(stop))
    await asyncio.sleep(0.05)
    assert runtime.scheduler._asleep is True
    runtime.bus.queue(("2-0", end_ev))
    await asyncio.sleep(0.05)
    assert runtime.scheduler._asleep is False
    assert runtime.scheduler._look_due_at is not None
    stop.set()
    try:
        await asyncio.wait_for(task, 1)
    except asyncio.TimeoutError:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            # Expected: the watcher was cancelled just above.
            pass


async def test_hash_embedder_not_ready(tmp_path: Path):
    runtime = build(tmp_path, embedder=FakeEmbedderWithKind())
    assert runtime.scheduler._blocked_reason() == "embedder_not_ready"


async def test_run_returns_on_stop(tmp_path: Path):
    runtime = build(tmp_path, is_gestating=lambda: True)
    runtime.scheduler._sleep = lambda s: asyncio.sleep(0.001)
    stop = asyncio.Event()

    async def stopper() -> None:
        await asyncio.sleep(0.05)
        stop.set()

    asyncio.create_task(stopper())
    await asyncio.wait_for(runtime.run(stop), 5)


class UndisclosedLingua(FakeLingua):
    def probe_self_model(self) -> dict:
        return {"values": ["val"], "behavioral_norms": ["norm"], "situation_facts": []}


async def test_probe_requires_the_disclosure(tmp_path: Path):
    runtime = build(tmp_path, lingua=UndisclosedLingua())
    result = await runtime.core._sampler("q1", 1)
    assert isinstance(result, ProbeFailure)
    assert result.reason == "disclosure_not_ready"
