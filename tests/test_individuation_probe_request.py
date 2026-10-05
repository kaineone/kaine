# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.lifecycle.individuation_store import conditioning_digest, read_conditioning_inputs
from kaine.modules.eidolon.document import SelfModel
from kaine.modules.eidolon.module import Eidolon
from kaine.modules.lingua import (
    EXTERNAL_STREAM,
    INTERNAL_STREAM,
    FakeChatClient,
    IntentExpressionLog,
    Lingua,
)
from kaine.modules.lingua.client import ChatRequest, OpenAIChatClient
from kaine.modules.lingua.context import EMPTY_AWARENESS, ContextAssembler, _identity_clause
from kaine.privacy_filter import PrivacyFilter


class _FakeBus:
    """Minimal bus stub for constructing Eidolon in tests without a real bus."""

    def __init__(self):
        self.client = None


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _make_lingua(bus: AsyncBus, tmp_path: Path, responses=None) -> Lingua:
    return Lingua(
        bus,
        chat_client=FakeChatClient(responses=responses),
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="fake-model",
    )


def test_self_model_situation_facts_round_trip():
    sm = SelfModel(
        name="Kaine Voxel",
        values=["autonomy"],
        behavioral_norms=["honesty"],
        situation_facts=["You are periodically assessed for your own protection."],
    )
    loaded = SelfModel.from_json(sm.to_json())
    assert loaded.situation_facts == sm.situation_facts
    assert loaded == sm


def test_self_model_old_json_loads_empty_situation_facts():
    old = SelfModel.from_json('{"values": ["a"], "behavioral_norms": ["b"]}')
    assert old.situation_facts == []


@pytest.mark.asyncio
async def test_ensure_situation_fact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("kaine.storage._PROCESS_ROOT", tmp_path.resolve())
    eidolon = Eidolon(_FakeBus())
    eidolon._model = eidolon._model.with_updates(
        values=["v"],
        behavioral_norms=["n"],
        identity_history=[{"tick": 1}],
    )
    drift_before = eidolon._drift_count

    eidolon._publish_self_model = lambda: asyncio.sleep(0)
    eidolon._save_to_disk = lambda: asyncio.sleep(0)

    fact = "You are periodically assessed for your own protection."
    assert await eidolon.ensure_situation_fact(fact) is True
    assert await eidolon.ensure_situation_fact(fact) is False

    assert eidolon._model.situation_facts == [fact]
    assert eidolon._model.values == ["v"]
    assert eidolon._model.behavioral_norms == ["n"]
    assert eidolon._model.identity_history == [{"tick": 1}]
    assert eidolon._drift_count == drift_before

    with pytest.raises(ValueError):
        await eidolon.ensure_situation_fact("")
    with pytest.raises(ValueError):
        await eidolon.ensure_situation_fact("   ")


def test_persona_includes_situation_fact_after_identity():
    self_model = {
        "values": ["a"],
        "behavioral_norms": ["b"],
        "situation_facts": ["You are periodically assessed for your own protection."],
    }
    ctx = ContextAssembler().assemble(
        about="q", snapshot=None, self_model=self_model, mode="external"
    )

    assert "You value a." in ctx.system
    assert "You are periodically assessed for your own protection." in ctx.system
    assert ctx.system.index("You value a.") < ctx.system.index(
        "Facts about your situation:"
    )

    identity_only = _identity_clause(self_model)
    assert identity_only is not None
    assert "periodically assessed" not in identity_only


def test_conditioning_digest_ignores_situation_facts(tmp_path: Path, monkeypatch):
    from kaine.security.crypto import get_state_encryptor

    enc = get_state_encryptor()
    monkeypatch.setattr(enc, "maybe_decrypt", lambda raw: raw)

    common = {
        "name": "Kaine",
        "values": ["autonomy"],
        "behavioral_norms": ["honesty"],
    }
    with_facts = SelfModel(
        **common, situation_facts=["You are periodically assessed for your own protection."]
    )
    without_facts = SelfModel(**common)

    path_with = tmp_path / "with_facts.json"
    path_without = tmp_path / "without_facts.json"
    path_with.write_text(with_facts.to_json(), encoding="utf-8")
    path_without.write_text(without_facts.to_json(), encoding="utf-8")

    d1 = conditioning_digest(
        adapter_sha=None, values=with_facts.values, norms=with_facts.behavioral_norms
    )
    d2 = conditioning_digest(
        adapter_sha=None, values=without_facts.values, norms=without_facts.behavioral_norms
    )
    assert d1 == d2

    no_adapters = path_with.parent / "no-adapters"
    inputs_with = read_conditioning_inputs(self_model_path=path_with, adapter_output_dir=no_adapters)
    inputs_without = read_conditioning_inputs(self_model_path=path_without, adapter_output_dir=no_adapters)
    assert inputs_with == inputs_without


@pytest.mark.asyncio
async def test_probe_request(bus: AsyncBus, tmp_path: Path):
    lingua = _make_lingua(bus, tmp_path, responses=["response"])
    self_model = {
        "values": ["a"],
        "behavioral_norms": ["b"],
        "situation_facts": ["You are periodically assessed for your own protection."],
    }
    lingua._bus_self_model = self_model

    intent_path = Path(getattr(lingua.intent_log, "path", lingua.intent_log._path))
    size_before = intent_path.stat().st_size if intent_path.exists() else 0

    req = lingua.probe_request(
        about="hello", seed=11, max_tokens=160, self_model=self_model
    )

    assert isinstance(req, ChatRequest)
    assert req.seed == 11
    assert req.max_tokens == 160
    assert req.cache_prompt is False
    assert "You are periodically assessed for your own protection." in (req.system or "")
    assert EMPTY_AWARENESS in req.prompt

    size_after = intent_path.stat().st_size if intent_path.exists() else 0
    assert size_before == size_after

    assert await bus.client.xlen(EXTERNAL_STREAM) == 0
    assert await bus.client.xlen(INTERNAL_STREAM) == 0
    assert await bus.client.xlen("lingua.out") == 0


def test_probe_self_model_none_until_snapshot(bus: AsyncBus, tmp_path: Path):
    lingua = _make_lingua(bus, tmp_path)
    assert lingua.probe_self_model() is None
    self_model = {
        "values": ["a"],
        "behavioral_norms": ["b"],
        "situation_facts": ["f"],
    }
    lingua._bus_self_model = self_model
    assert lingua.probe_self_model() == self_model


def test_openai_chat_client_body_cache_prompt():
    client = OpenAIChatClient()

    body_false = client._body(
        ChatRequest(prompt="p", model="m", cache_prompt=False), think=False
    )
    assert body_false.get("cache_prompt") is False

    body_none = client._body(ChatRequest(prompt="p", model="m"), think=False)
    assert "cache_prompt" not in body_none


def test_privacy_filter_strips_situation_facts():
    pf = PrivacyFilter()
    event = Event(
        source="eidolon",
        type="eidolon.self_model",
        payload={
            "name": "Kaine",
            "values": ["v"],
            "behavioral_norms": ["n"],
            "situation_facts": ["You are periodically assessed for your own protection."],
        },
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    payload = pf.filter_for_diagnostics(event).payload
    assert "situation_facts" not in payload
    assert "values" not in payload


@pytest.mark.asyncio
async def test_probe_ignores_the_live_workspace(bus: AsyncBus, tmp_path: Path):
    """The probe always uses empty working memory, even while Lingua holds a
    live coalition, so moment-to-moment content never enters the measurement."""
    from datetime import datetime, timezone

    from kaine.bus.schema import Event
    from kaine.cycle.types import WorkspaceSnapshot

    lingua = _make_lingua(bus, tmp_path, responses=["response"])
    live = Event(
        source="topos",
        type="topos.report",
        payload={"change_score": 0.9, "alert": True},
        salience=0.9,
        timestamp=datetime.now(timezone.utc),
    )
    lingua._latest_snapshot = WorkspaceSnapshot(
        tick_index=1, selected_events=[("1-0", live)], salience_scores={"1-0": 0.9}
    )
    baseline = lingua._assembler.assemble(
        about="hello", snapshot=lingua._latest_snapshot, self_model={}, mode="external"
    )
    assert baseline.working_memory != EMPTY_AWARENESS  # the live coalition renders

    req = lingua.probe_request(
        about="hello", seed=1, max_tokens=160, self_model={}
    )
    assert EMPTY_AWARENESS in req.prompt
    assert baseline.working_memory not in req.prompt
