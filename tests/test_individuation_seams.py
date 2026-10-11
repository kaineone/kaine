# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kaine.cycle.caretaker import EVENT_KINDS
from kaine.lifecycle.individuation_store import (
    IndividuationStoreError,
    adapter_sha_of,
    conditioning_from_snapshot,
)
from kaine.modules.lingua.module import Lingua
from tests.test_individuation_scheduler import FakeCore, make


def test_lingua_is_idle(tmp_path: Path):
    lingua = Lingua(
        MagicMock(), chat_client=MagicMock(), intent_log=MagicMock()
    )
    assert lingua.is_idle(10) is True
    lingua._produce_in_flight = 1
    assert lingua.is_idle(10) is False
    lingua._produce_in_flight = 0
    lingua._last_produce_end = time.monotonic()
    assert lingua.is_idle(10) is False
    time.sleep(0.01)
    assert lingua.is_idle(0.0001) is True


async def test_lingua_produce_bookkeeping(tmp_path: Path):
    lingua = Lingua(
        MagicMock(), chat_client=MagicMock(), intent_log=MagicMock()
    )
    recorded: list[int] = []

    async def inner(*args, **kwargs) -> str:
        recorded.append(lingua._produce_in_flight)
        raise RuntimeError("boom")

    lingua._produce_inner = inner
    with pytest.raises(RuntimeError, match="boom"):
        await lingua._produce(
            about="a", snapshot=None, mode="external", stream="s"
        )
    assert recorded == [1]
    assert lingua._produce_in_flight == 0
    assert lingua._last_produce_end is not None


def test_lingua_probe_conditions(tmp_path: Path):
    l1 = Lingua(
        MagicMock(),
        chat_client=MagicMock(),
        intent_log=MagicMock(),
        persona_external="alpha",
    )
    l2 = Lingua(
        MagicMock(),
        chat_client=MagicMock(),
        intent_log=MagicMock(),
        persona_external="beta",
    )
    cond1 = l1.probe_conditions()
    cond2 = l2.probe_conditions()
    assert set(cond1.keys()) == {
        "model_id",
        "temperature",
        "think",
        "persona_digest",
        "persona_template_version",
    }
    expected = hashlib.sha256(
        json.dumps([None, "alpha", None]).encode("utf-8")
    ).hexdigest()[:16]
    assert cond1["persona_digest"] == expected
    assert cond1["persona_digest"] != cond2["persona_digest"]


def test_conditioning_from_snapshot():
    with pytest.raises(IndividuationStoreError):
        conditioning_from_snapshot(None, None)
    with pytest.raises(IndividuationStoreError):
        conditioning_from_snapshot({"values": "x"}, None)
    sha, values, norms = conditioning_from_snapshot(
        {"values": ["a"], "behavioral_norms": ["b"]}, None
    )
    assert sha is None
    assert values == ["a"]
    assert norms == ["b"]


def test_adapter_sha_of_none():
    assert adapter_sha_of(None) is None


def test_caretaker_event_kind():
    assert "individuation_inconclusive" in EVENT_KINDS


class RecordingFakeCore(FakeCore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls: list[dict] = []

    async def capture_reference(self, kind, *, regenerate=False):
        self.calls.append({"kind": kind, "regenerate": regenerate})
        return self.capture_result


async def test_scheduler_capture_regenerate(tmp_path: Path):
    sched, _, clock = make(tmp_path)
    core = RecordingFakeCore(clock, sched)
    sched.bind(core)

    sched.request_capture("capture", regenerate=True)
    await sched.tick()
    assert core.calls == [{"kind": "capture", "regenerate": True}]

    sched.request_capture("capture")
    await sched.tick()
    assert core.calls == [
        {"kind": "capture", "regenerate": True},
        {"kind": "capture", "regenerate": False},
    ]


async def test_lingua_not_idle_while_a_generation_task_runs():
    lingua = Lingua(MagicMock(), chat_client=MagicMock(), intent_log=MagicMock())
    gate = asyncio.Event()
    lingua._gen_task = asyncio.create_task(gate.wait())
    try:
        assert lingua.is_idle(0.0001) is False
    finally:
        gate.set()
        await lingua._gen_task
    assert lingua.is_idle(0.0001) is True
