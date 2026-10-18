# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from typing import Any

import pytest

from kaine.modules.language.client import (
    OWN_TURN_CUE,
    ChatClient,
    ChatRequest,
    ChatResponse,
    FakeChatClient,
    LlamaCppChatClient,
    OpenAIChatClient,
    chat_messages,
    own_turn_text,
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


# --- own-turn request layout --------------------------------------------------
#
# The organ's chat template requires a user turn, so an own-turn prompt is sent
# as a trailing assistant message after a fixed user cue. llama-server echoes
# the continued prompt at the start of the reply, so the client strips it before
# returning the response.


def test_chat_messages_user_turn_by_default():
    assert chat_messages(ChatRequest(prompt="p", model="m", system="s")) == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "p"},
    ]
    assert chat_messages(ChatRequest(prompt="p", model="m")) == [
        {"role": "user", "content": "p"},
    ]


def test_chat_messages_own_turn():
    assert OWN_TURN_CUE == "(next)"
    assert chat_messages(
        ChatRequest(prompt="## My notes\n", model="m", system="s", own_turn=True)
    ) == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": OWN_TURN_CUE},
        {"role": "assistant", "content": "## My notes\n"},
    ]


@pytest.mark.asyncio
async def test_own_turn_body_sends_trailing_assistant_message():
    http = _FakeHTTP([_FakeResp()])
    c = _client_with(http)
    await c.complete(
        ChatRequest(prompt="frame\n", model="m", system="s", own_turn=True)
    )
    _path, body = http.posts[0]
    assert body["messages"][-1] == {"role": "assistant", "content": "frame\n"}
    assert body["messages"][-2] == {"role": "user", "content": "(next)"}


@pytest.mark.asyncio
async def test_own_turn_strips_echoed_prompt():
    payload = {
        "model": "m",
        "choices": [{"message": {"content": "frame\n The sound is new."}}],
        "usage": {},
    }
    http = _FakeHTTP([_FakeResp(payload=payload)])
    c = _client_with(http)
    out = await c.complete(
        ChatRequest(prompt="frame\n", model="m", system="s", own_turn=True)
    )
    assert out.text == "The sound is new."
    assert out.from_content is True


@pytest.mark.asyncio
async def test_own_turn_echo_only_is_not_content():
    payload = {
        "model": "m",
        "choices": [{"message": {"content": "frame\n"}}],
        "usage": {},
    }
    http = _FakeHTTP([_FakeResp(payload=payload)])
    c = _client_with(http)
    out = await c.complete(
        ChatRequest(prompt="frame\n", model="m", system="s", own_turn=True)
    )
    assert out.text == ""
    assert out.from_content is False


@pytest.mark.asyncio
async def test_own_turn_without_echo_keeps_generated_text():
    payload = {
        "model": "m",
        "choices": [{"message": {"content": "  The sound is new."}}],
        "usage": {},
    }
    http = _FakeHTTP([_FakeResp(payload=payload)])
    c = _client_with(http)
    out = await c.complete(
        ChatRequest(prompt="frame\n", model="m", system="s", own_turn=True)
    )
    assert out.text == "The sound is new."


@pytest.mark.asyncio
async def test_user_turn_reply_is_not_trimmed():
    payload = {
        "model": "m",
        "choices": [{"message": {"content": "frame\n rest"}}],
        "usage": {},
    }
    http = _FakeHTTP([_FakeResp(payload=payload)])
    c = _client_with(http)
    out = await c.complete(
        ChatRequest(prompt="frame\n", model="m", system="s", own_turn=False)
    )
    assert out.text == "frame\n rest"


def test_own_turn_text_helper():
    user_req = ChatRequest(prompt="frame\n", model="m", own_turn=False)
    assert own_turn_text(user_req, "frame\n rest") == "frame\n rest"

    own_req = ChatRequest(prompt="frame\n", model="m", own_turn=True)
    assert own_turn_text(own_req, "frame\n rest") == "rest"
    assert own_turn_text(own_req, "  The sound is new.") == "The sound is new."


class _FakeLlama:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "choices": [
                {"message": {"content": "frame\nhello"}, "finish_reason": "stop"}
            ],
            "usage": {},
            "model": "m",
        }


@pytest.mark.asyncio
async def test_llama_cpp_client_uses_same_messages_and_trims():
    c = LlamaCppChatClient(model_path="/x.gguf")
    fake = _FakeLlama()
    c._llama = fake
    req = ChatRequest(prompt="frame\n", model="m", system="s", own_turn=True)
    out = await c.complete(req)
    assert fake.calls[0]["messages"] == chat_messages(req)
    assert out.text == "hello"
    assert out.from_content is True


def test_own_turn_text_strips_trimmed_echo():
    req = ChatRequest(
        prompt="frame\n## What I say\n", model="m", own_turn=True
    )
    assert (
        own_turn_text(req, "frame\n## What I sayThe sound is new.")
        == "The sound is new."
    )


def test_own_turn_text_keeps_unechoed_output():
    req = ChatRequest(
        prompt="frame\n## What I say\n", model="m", own_turn=True
    )
    content = "  The frame is new.\n## not a heading"
    assert own_turn_text(req, content) == "The frame is new.\n## not a heading"
    assert own_turn_text(req, "fram") == "fram"
