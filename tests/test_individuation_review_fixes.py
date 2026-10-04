# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the review fixes to the individuation store, probe and disclosure."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import kaine.organ_window_state as ows
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.lifecycle.individuation_store import (
    INCONCLUSIVE_REASONS,
    IndividuationPaths,
    IndividuationStoreError,
    Ledger,
    LedgerUnreadable,
    ProbeSample,
    ReferenceDoc,
    ReferenceUnreadable,
    battery_digest_of,
    build_report,
    load_reference,
    read_reports,
    save_ledger,
    save_reference,
)
from kaine.modules.eidolon.module import Eidolon
from kaine.modules.lingua.client import ChatRequest, LlamaCppChatClient, OpenAIChatClient
from kaine.security.crypto import get_state_encryptor
from kaine.storage import set_data_root


def _set_window(tmp_path: Path, phase: str) -> Path:
    path = tmp_path / "organ_window.json"
    ows.write_window_state(phase, path=path)
    return path


class _FakeHTTP:
    def __init__(self, response: dict[str, Any] | None = None, status_code: int = 200):
        self.response = response or {
            "choices": [{"message": {"content": ""}}],
            "usage": {},
        }
        self.status_code = status_code
        self.posted: list[dict[str, Any]] = []

    async def post(self, url: str, json: dict[str, Any] | None = None):
        self.posted.append(json or {})

        class _R:
            def __init__(self, status_code: int, body: dict[str, Any]):
                self.status_code = status_code
                self._body = body

            def raise_for_status(self):
                if self.status_code != 200:
                    raise RuntimeError(str(self.status_code))

            def json(self):
                return self._body

        return _R(self.status_code, self.response)

    async def aclose(self):
        return None


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _valid_reference(reference_id: str = "r1") -> ReferenceDoc:
    battery = ("p1", "p2")
    sample = ProbeSample(text="s", seed=1, finish_reason="stop", completion_tokens=1)
    return ReferenceDoc(
        reference_id=reference_id,
        reference_kind="birth",
        captured_at="2024-01-01T00:00:00+00:00",
        born_at=None,
        battery=battery,
        battery_digest=battery_digest_of(battery),
        conditions={},
        conditioning={},
        samples=((sample, sample), (sample, sample)),
    )


def test_ledger_from_dict_rejects_non_finite_alpha_spent(tmp_path: Path):
    base = {
        "reference_id": "r1",
        "looks_completed": 0,
        "alpha_spent": 0.0,
        "lived_seconds": 0.0,
        "lived_ticks": 0,
    }
    for bad in (float("nan"), float("inf"), float("-inf")):
        d = {**base, "alpha_spent": bad}
        with pytest.raises(LedgerUnreadable):
            Ledger.from_dict(d)


def test_ledger_from_dict_rejects_non_finite_lived_seconds(tmp_path: Path):
    base = {
        "reference_id": "r1",
        "looks_completed": 0,
        "alpha_spent": 0.0,
        "lived_seconds": 0.0,
        "lived_ticks": 0,
    }
    for bad in (float("nan"), float("inf"), float("-inf")):
        d = {**base, "lived_seconds": bad}
        with pytest.raises(LedgerUnreadable):
            Ledger.from_dict(d)


def test_save_ledger_rejects_non_finite_new_ledger(tmp_path: Path):
    paths = IndividuationPaths(tmp_path)
    for key in ("alpha_spent", "lived_seconds"):
        ledger = Ledger(
            reference_id="r1",
            **{key: float("nan")},  # type: ignore[arg-type]
        )
        with pytest.raises(IndividuationStoreError):
            save_ledger(paths, ledger)


def test_save_reference_no_overwrite_raises(tmp_path: Path):
    paths = IndividuationPaths(tmp_path)
    doc = _valid_reference()
    save_reference(paths, doc)
    with pytest.raises(IndividuationStoreError, match="overwrite=True"):
        save_reference(paths, doc)


def test_save_reference_overwrite_succeeds(tmp_path: Path):
    paths = IndividuationPaths(tmp_path)
    doc1 = _valid_reference("r1")
    doc2 = _valid_reference("r2")
    save_reference(paths, doc1)
    save_reference(paths, doc2, overwrite=True)
    loaded = load_reference(paths)
    assert loaded is not None
    assert loaded.reference_id == "r2"


def test_save_reference_corrupt_existing_raises_reference_unreadable(
    tmp_path: Path,
):
    paths = IndividuationPaths(tmp_path)
    paths.reference.write_text("not encrypted", encoding="utf-8")
    doc = _valid_reference()
    with pytest.raises(ReferenceUnreadable):
        save_reference(paths, doc)


def test_build_report_rejects_unknown_inconclusive_reason():
    with pytest.raises(ValueError):
        build_report(outcome="inconclusive", inconclusive_reason="not_a_reason")


def test_build_report_rejects_long_string():
    long_name = "x" * 201
    with pytest.raises(ValueError, match="200"):
        build_report(
            outcome="inconclusive",
            inconclusive_reason="no_reference",
            entity_name=long_name,
        )


def test_build_report_accepts_all_enumerated_reasons():
    for reason in INCONCLUSIVE_REASONS:
        report = build_report(outcome="inconclusive", inconclusive_reason=reason)
        assert report["inconclusive_reason"] == reason


def test_read_reports_logs_warning_for_garbage(caplog, tmp_path: Path):
    paths = IndividuationPaths(tmp_path)
    paths.reports.mkdir(parents=True)
    (paths.reports / "2024.jsonl").write_text("not-encrypted-garbage\n", encoding="utf-8")

    with caplog.at_level("WARNING"):
        read_reports(paths, reference_id="r1")

    assert any("skipped" in r.message.lower() for r in caplog.records)
    assert any("1" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_ensure_situation_fact_publishes_and_persists(
    bus: AsyncBus, tmp_path: Path
):
    set_data_root(tmp_path)
    eidolon = Eidolon(bus)
    fact = "You are periodically assessed for your own protection."

    assert await eidolon.ensure_situation_fact(fact) is True

    stream = getattr(eidolon, "out", "eidolon.out")
    records = await bus.client.xrevrange(stream, max="+", min="-", count=1)
    assert records
    _id, fields = records[0]
    assert fields.get("type") == "eidolon.self_model"
    payload_raw = fields.get("payload", "{}")
    payload = (
        json.loads(payload_raw)
        if isinstance(payload_raw, (str, bytes, bytearray))
        else payload_raw
    )
    assert fact in payload["situation_facts"]

    raw = eidolon._persistence_path.read_bytes()
    text = get_state_encryptor().maybe_decrypt(raw).decode("utf-8")
    data = json.loads(text)
    assert fact in data["situation_facts"]

    before = await bus.client.xlen(stream)
    assert await eidolon.ensure_situation_fact(fact) is False
    assert await bus.client.xlen(stream) == before


@pytest.mark.asyncio
async def test_openai_complete_lora_applied_true(tmp_path: Path, monkeypatch):
    path = _set_window(tmp_path, ows.PHASE_IDLE)
    monkeypatch.setattr(ows, "ORGAN_WINDOW_STATE", path)

    class Resolver:
        async def lora_field(self):
            return [{"id": 0, "scale": 1.0}]

    client = OpenAIChatClient(base_url="http://x", lora_resolver=Resolver())
    http = _FakeHTTP(
        response={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {},
            "model": "m",
        }
    )
    client._client = http

    resp = await client.complete(ChatRequest(model="m", prompt="p"))
    assert resp.lora_applied is True
    assert any("lora" in body for body in http.posted)


@pytest.mark.asyncio
async def test_openai_complete_lora_applied_false(tmp_path: Path, monkeypatch):
    path = _set_window(tmp_path, ows.PHASE_IDLE)
    monkeypatch.setattr(ows, "ORGAN_WINDOW_STATE", path)

    client = OpenAIChatClient(base_url="http://x")
    http = _FakeHTTP(
        response={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {},
            "model": "m",
        }
    )
    client._client = http

    resp = await client.complete(ChatRequest(model="m", prompt="p"))
    assert resp.lora_applied is False
    assert not any("lora" in body for body in http.posted)


@pytest.mark.asyncio
async def test_llama_cpp_complete_seed_and_finish_reason():
    client = LlamaCppChatClient(model_path="dummy.gguf")

    class StubLlama:
        def __init__(self):
            self.calls: list[dict[str, Any]] = []

        def create_chat_completion(self, **kw: Any):
            self.calls.append(kw)
            return {
                "choices": [
                    {"message": {"content": "x"}, "finish_reason": "stop"}
                ],
                "usage": {},
            }

    stub = StubLlama()
    client._llama = stub

    resp = await client.complete(ChatRequest(model="m", prompt="p", seed=42))
    assert stub.calls[0].get("seed") == 42
    assert resp.finish_reason == "stop"
    assert resp.from_content is True
    assert resp.text == "x"
    assert resp.lora_applied is False

    await client.complete(ChatRequest(model="m", prompt="p"))
    assert "seed" not in stub.calls[1]
