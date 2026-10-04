# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.individuation_probe import (
    ProbeFailure,
    adapter_applied,
    adapter_expected_from,
    build_probe_sampler,
)
from kaine.lifecycle.individuation_store import ProbeSample
from kaine.modules.lingua import (
    EXTERNAL_STREAM,
    INTERNAL_STREAM,
    FakeChatClient,
    IntentExpressionLog,
    Lingua,
)
from kaine.modules.lingua.client import ChatResponse


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


class _ConfigurableFakeChatClient:
    """Fake chat client with a configurable response and request capture."""

    def __init__(self, response):
        self.response = response
        self.requests: list = []

    @property
    def base_url(self) -> str:
        return "fake://"

    async def complete(self, request):
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _make_lingua(bus: AsyncBus, tmp_path: Path, responses=None, chat_client=None) -> Lingua:
    if chat_client is None:
        chat_client = FakeChatClient(responses=responses)
    lingua = Lingua(
        bus,
        chat_client=chat_client,
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="fake-model",
    )
    lingua._bus_self_model = {
        "values": [],
        "behavioral_norms": [],
        "situation_facts": [],
    }
    return lingua


@pytest.mark.asyncio
async def test_sample_returns_probe_sample(bus: AsyncBus, tmp_path: Path):
    response = ChatResponse(
        text="tea",
        model="m",
        completion_tokens=3,
        finish_reason="stop",
        from_content=True,
    )
    fake = _ConfigurableFakeChatClient(response)
    lingua = _make_lingua(bus, tmp_path, chat_client=fake)
    sampler = build_probe_sampler(lingua=lingua)

    result = await sampler("what is in the cup?", 5)

    assert isinstance(result, ProbeSample)
    assert result.text == "tea"
    assert result.seed == 5
    assert result.finish_reason == "stop"
    assert result.completion_tokens == 3

    assert len(fake.requests) == 1
    req = fake.requests[0]
    assert req.seed == 5
    assert req.max_tokens == 160
    assert req.cache_prompt is False


@pytest.mark.asyncio
async def test_sample_request_failed(bus: AsyncBus, tmp_path: Path):
    fake = _ConfigurableFakeChatClient(RuntimeError("boom"))
    lingua = _make_lingua(bus, tmp_path, chat_client=fake)
    sampler = build_probe_sampler(lingua=lingua)

    result = await sampler("hello", 1)
    assert isinstance(result, ProbeFailure)
    assert result.reason == "request_failed"


@pytest.mark.asyncio
async def test_sample_organ_resting(bus: AsyncBus, tmp_path: Path):
    response = ChatResponse(
        text="resting",
        model="m",
        from_content=True,
        raw={"organ_resting": True},
    )
    fake = _ConfigurableFakeChatClient(response)
    lingua = _make_lingua(bus, tmp_path, chat_client=fake)
    sampler = build_probe_sampler(lingua=lingua)

    result = await sampler("hello", 1)
    assert isinstance(result, ProbeFailure)
    assert result.reason == "organ_resting"


@pytest.mark.asyncio
async def test_sample_no_content_from_content_false(bus: AsyncBus, tmp_path: Path):
    response = ChatResponse(text="thinking...", model="m", from_content=False)
    fake = _ConfigurableFakeChatClient(response)
    lingua = _make_lingua(bus, tmp_path, chat_client=fake)
    sampler = build_probe_sampler(lingua=lingua)

    result = await sampler("hello", 1)
    assert isinstance(result, ProbeFailure)
    assert result.reason == "no_content"


@pytest.mark.asyncio
async def test_sample_no_content_whitespace(bus: AsyncBus, tmp_path: Path):
    response = ChatResponse(text="   ", model="m", from_content=True)
    fake = _ConfigurableFakeChatClient(response)
    lingua = _make_lingua(bus, tmp_path, chat_client=fake)
    sampler = build_probe_sampler(lingua=lingua)

    result = await sampler("hello", 1)
    assert isinstance(result, ProbeFailure)
    assert result.reason == "no_content"


@pytest.mark.asyncio
async def test_sample_adapter_not_applied(bus: AsyncBus, tmp_path: Path):
    response = ChatResponse(text="ok", model="m", from_content=True)
    fake = _ConfigurableFakeChatClient(response)
    lingua = _make_lingua(bus, tmp_path, chat_client=fake)
    async def _not_applied() -> bool:
        return False

    sampler = build_probe_sampler(lingua=lingua, adapter_check=_not_applied)

    result = await sampler("hello", 1)
    assert isinstance(result, ProbeFailure)
    assert result.reason == "adapter_not_applied"
    assert fake.requests == []


@pytest.mark.asyncio
async def test_sample_self_model_not_ready(bus: AsyncBus, tmp_path: Path):
    response = ChatResponse(text="ok", model="m", from_content=True)
    fake = _ConfigurableFakeChatClient(response)
    lingua = _make_lingua(bus, tmp_path, chat_client=fake)
    lingua._bus_self_model = None
    sampler = build_probe_sampler(lingua=lingua)

    result = await sampler("hello", 1)
    assert isinstance(result, ProbeFailure)
    assert result.reason == "self_model_not_ready"
    assert fake.requests == []


@pytest.mark.asyncio
async def test_sample_disclosure_not_ready(bus: AsyncBus, tmp_path: Path):
    response = ChatResponse(text="ok", model="m", from_content=True)
    fake = _ConfigurableFakeChatClient(response)
    lingua = _make_lingua(bus, tmp_path, chat_client=fake)
    sampler = build_probe_sampler(lingua=lingua, required_fact="F")

    result = await sampler("hello", 1)
    assert isinstance(result, ProbeFailure)
    assert result.reason == "disclosure_not_ready"
    assert fake.requests == []


@pytest.mark.asyncio
async def test_sample_adapter_expected_not_applied(bus: AsyncBus, tmp_path: Path):
    response = ChatResponse(
        text="ok", model="m", from_content=True, lora_applied=False
    )
    fake = _ConfigurableFakeChatClient(response)
    lingua = _make_lingua(bus, tmp_path, chat_client=fake)
    sampler = build_probe_sampler(
        lingua=lingua, adapter_expected=lambda: True
    )

    result = await sampler("hello", 1)
    assert isinstance(result, ProbeFailure)
    assert result.reason == "adapter_not_applied"


@pytest.mark.asyncio
async def test_sample_adapter_expected_applied(bus: AsyncBus, tmp_path: Path):
    response = ChatResponse(
        text="ok", model="m", from_content=True, lora_applied=True
    )
    fake = _ConfigurableFakeChatClient(response)
    lingua = _make_lingua(bus, tmp_path, chat_client=fake)
    sampler = build_probe_sampler(
        lingua=lingua, adapter_expected=lambda: True
    )

    result = await sampler("hello", 1)
    assert isinstance(result, ProbeSample)
    assert result.text == "ok"


@pytest.mark.asyncio
async def test_sample_adapter_check_raises(bus: AsyncBus, tmp_path: Path):
    response = ChatResponse(text="ok", model="m", from_content=True)
    fake = _ConfigurableFakeChatClient(response)
    lingua = _make_lingua(bus, tmp_path, chat_client=fake)
    async def _raises() -> bool:
        raise RuntimeError("nope")

    sampler = build_probe_sampler(lingua=lingua, adapter_check=_raises)

    result = await sampler("hello", 1)
    assert isinstance(result, ProbeFailure)
    assert result.reason == "adapter_not_applied"
    assert fake.requests == []


@pytest.mark.asyncio
async def test_sample_probe_request_raises(bus: AsyncBus, tmp_path: Path):
    response = ChatResponse(text="ok", model="m", from_content=True)
    fake = _ConfigurableFakeChatClient(response)
    lingua = _make_lingua(bus, tmp_path, chat_client=fake)
    lingua.probe_request = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("boom")
    )

    sampler = build_probe_sampler(lingua=lingua)

    result = await sampler("hello", 1)
    assert isinstance(result, ProbeFailure)
    assert result.reason == "request_failed"
    assert fake.requests == []


@pytest.mark.asyncio
async def test_sample_adapter_expected_raises(bus: AsyncBus, tmp_path: Path):
    response = ChatResponse(
        text="ok", model="m", from_content=True, lora_applied=True
    )
    fake = _ConfigurableFakeChatClient(response)
    lingua = _make_lingua(bus, tmp_path, chat_client=fake)
    sampler = build_probe_sampler(
        lingua=lingua, adapter_expected=lambda: (_ for _ in ()).throw(
            RuntimeError("nope")
        )
    )

    result = await sampler("hello", 1)
    assert isinstance(result, ProbeFailure)
    assert result.reason == "adapter_not_applied"


@pytest.mark.asyncio
async def test_adapter_applied_none_dir():
    assert await adapter_applied(adapter_output_dir=None, resolver=None) is True


@pytest.mark.asyncio
async def test_adapter_applied_no_current_link(tmp_path: Path):
    adapter_dir = tmp_path / "adapters"
    adapter_dir.mkdir()
    assert await adapter_applied(adapter_output_dir=adapter_dir, resolver=None) is True


@pytest.mark.asyncio
async def test_adapter_applied_current_link_no_resolver(tmp_path: Path):
    adapter_dir = tmp_path / "adapters"
    target = adapter_dir / "v1"
    target.mkdir(parents=True)
    (target / "adapter.gguf").write_text("weights", encoding="utf-8")
    current = adapter_dir / "current"
    current.symlink_to(target, target_is_directory=True)

    assert await adapter_applied(adapter_output_dir=adapter_dir, resolver=None) is False


@pytest.mark.asyncio
async def test_adapter_applied_current_link_with_lora(tmp_path: Path):
    adapter_dir = tmp_path / "adapters"
    target = adapter_dir / "v1"
    target.mkdir(parents=True)
    (target / "adapter.gguf").write_text("weights", encoding="utf-8")
    current = adapter_dir / "current"
    current.symlink_to(target, target_is_directory=True)

    class Resolver:
        async def lora_field(self):
            return [{"id": 0, "scale": 1.0}]

    assert await adapter_applied(adapter_output_dir=adapter_dir, resolver=Resolver()) is True


@pytest.mark.asyncio
async def test_adapter_applied_current_link_lora_none(tmp_path: Path):
    adapter_dir = tmp_path / "adapters"
    target = adapter_dir / "v1"
    target.mkdir(parents=True)
    (target / "adapter.gguf").write_text("weights", encoding="utf-8")
    current = adapter_dir / "current"
    current.symlink_to(target, target_is_directory=True)

    class Resolver:
        async def lora_field(self):
            return None

    assert await adapter_applied(adapter_output_dir=adapter_dir, resolver=Resolver()) is False


@pytest.mark.asyncio
async def test_adapter_applied_current_link_lora_raises(tmp_path: Path):
    adapter_dir = tmp_path / "adapters"
    target = adapter_dir / "v1"
    target.mkdir(parents=True)
    (target / "adapter.gguf").write_text("weights", encoding="utf-8")
    current = adapter_dir / "current"
    current.symlink_to(target, target_is_directory=True)

    class Resolver:
        async def lora_field(self):
            raise RuntimeError("nope")

    assert await adapter_applied(adapter_output_dir=adapter_dir, resolver=Resolver()) is False


def test_adapter_expected_from_none_dir():
    fn = adapter_expected_from(None)
    assert fn() is False


def test_adapter_expected_from_no_current_link(tmp_path: Path):
    adapter_dir = tmp_path / "adapters"
    adapter_dir.mkdir()
    fn = adapter_expected_from(adapter_dir)
    assert fn() is False


def test_adapter_expected_from_current_with_adapter(tmp_path: Path):
    adapter_dir = tmp_path / "adapters"
    target = adapter_dir / "v1"
    target.mkdir(parents=True)
    (target / "adapter.gguf").write_text("weights", encoding="utf-8")
    current = adapter_dir / "current"
    current.symlink_to(target, target_is_directory=True)

    fn = adapter_expected_from(adapter_dir)
    assert fn() is True


@pytest.mark.asyncio
async def test_probe_run_does_not_contaminate(bus: AsyncBus, tmp_path: Path):
    response = ChatResponse(
        text="ok",
        model="m",
        completion_tokens=1,
        finish_reason="stop",
        from_content=True,
    )
    fake = _ConfigurableFakeChatClient(response)
    lingua = _make_lingua(bus, tmp_path, chat_client=fake)
    sampler = build_probe_sampler(lingua=lingua)

    intent_path = Path(getattr(lingua.intent_log, "path", lingua.intent_log._path))
    size_before = intent_path.stat().st_size if intent_path.exists() else 0
    out_before = await bus.client.xlen("lingua.out")
    ext_before = await bus.client.xlen(EXTERNAL_STREAM)
    int_before = await bus.client.xlen(INTERNAL_STREAM)

    results = []
    for i in range(12):
        result = await sampler(f"probe prompt {i}", seed=i)
        results.append(result)

    size_after = intent_path.stat().st_size if intent_path.exists() else 0
    assert size_before == size_after
    assert await bus.client.xlen("lingua.out") == out_before
    assert await bus.client.xlen(EXTERNAL_STREAM) == ext_before
    assert await bus.client.xlen(INTERNAL_STREAM) == int_before
    assert all(isinstance(r, ProbeSample) for r in results)
    assert len(fake.requests) == 12
