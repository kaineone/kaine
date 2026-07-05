# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.modules.lingua.client import (
    ChatClient,
    ChatRequest,
    ChatResponse,
    FakeChatClient,
    OpenAIChatClient,
)


def test_default_base_url():
    c = OpenAIChatClient()
    assert c.base_url == "http://127.0.0.1:11434/v1"


def test_base_url_trailing_slash_stripped():
    c = OpenAIChatClient(base_url="http://x/v1/")
    assert c.base_url == "http://x/v1"


def test_fake_satisfies_protocol():
    assert isinstance(FakeChatClient(), ChatClient)


def test_fake_default_echoes_prompt():
    import asyncio
    f = FakeChatClient()
    out = asyncio.run(f.complete(ChatRequest(prompt="hello", model="m")))
    assert "echo" in out.text.lower()
    assert "hello" in out.text


@pytest.mark.asyncio
async def test_fake_returns_scripted_responses_in_order():
    f = FakeChatClient(responses=["one", "two"])
    a = await f.complete(ChatRequest(prompt="?", model="m"))
    b = await f.complete(ChatRequest(prompt="?", model="m"))
    c = await f.complete(ChatRequest(prompt="?", model="m"))
    assert a.text == "one"
    assert b.text == "two"
    assert "echo" in c.text.lower()  # exhausted, falls back to echo


@pytest.mark.asyncio
async def test_fake_records_requests():
    f = FakeChatClient()
    await f.complete(ChatRequest(prompt="hi", model="m"))
    assert len(f.requests) == 1
    assert f.requests[0].prompt == "hi"


@pytest.mark.asyncio
async def test_fake_aclose_marks_closed():
    f = FakeChatClient()
    await f.aclose()
    assert f.closed is True


def test_chat_response_carries_metadata():
    resp = ChatResponse(text="x", model="m", prompt_tokens=10, completion_tokens=5)
    assert resp.prompt_tokens == 10
    assert resp.completion_tokens == 5
    assert resp.latency_ms == 0.0


# --- reasoning suppression on the OpenAI-compatible endpoint ------------------
#
# The organ runs with chain-of-thought OFF. On the /v1 surface this travels via
# chat_template_kwargs.enable_thinking (the portable llama.cpp mechanism), NOT
# Ollama's native top-level `think` flag. These pin that mapping + the fail-safe
# retry, which is the unit-level half of the unify-inference parity gate.


class _FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {
            "model": "m",
            "choices": [{"message": {"content": "hi"}}],
            "usage": {},
        }
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeHTTP:
    """Captures posted bodies; returns scripted responses in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.posts = []  # list of (path, json_body)

    async def post(self, path, json):
        self.posts.append((path, json))
        return self._responses.pop(0)

    async def aclose(self):
        pass


def _client_with(http):
    c = OpenAIChatClient()
    c._client = http  # inject (bypass lazy httpx construction)
    return c


@pytest.mark.asyncio
async def test_suppression_sends_chat_template_kwarg_not_think():
    http = _FakeHTTP([_FakeResp()])
    c = _client_with(http)
    await c.complete(ChatRequest(prompt="p", model="m", think=False))
    path, body = http.posts[0]
    assert path == "/chat/completions"
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert "think" not in body  # never the Ollama-native top-level flag


@pytest.mark.asyncio
async def test_no_kwarg_when_think_is_none():
    http = _FakeHTTP([_FakeResp()])
    c = _client_with(http)
    await c.complete(ChatRequest(prompt="p", model="m", think=None))
    _path, body = http.posts[0]
    assert "chat_template_kwargs" not in body


@pytest.mark.asyncio
async def test_retries_without_kwarg_when_server_rejects_it():
    # First call 400s complaining about the template kwarg; client retries plain.
    rejected = _FakeResp(status_code=400, text="unknown enable_thinking kwarg")
    ok = _FakeResp()
    http = _FakeHTTP([rejected, ok])
    c = _client_with(http)
    out = await c.complete(ChatRequest(prompt="p", model="m", think=False))
    assert out.text == "hi"
    assert len(http.posts) == 2
    assert "chat_template_kwargs" in http.posts[0][1]
    assert "chat_template_kwargs" not in http.posts[1][1]  # retry dropped it


@pytest.mark.asyncio
async def test_api_key_sets_bearer_header():
    c = OpenAIChatClient(api_key="sk-xyz")
    client = c._ensure_client()
    assert client.headers.get("Authorization") == "Bearer sk-xyz"
    await c.aclose()


@pytest.mark.asyncio
async def test_no_auth_header_when_keyless():
    c = OpenAIChatClient()
    client = c._ensure_client()
    assert "Authorization" not in client.headers
    await c.aclose()
