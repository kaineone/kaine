# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the language module's chat clients, focusing on request decoding."""

from __future__ import annotations

import kaine.organ_window_state as ows
from kaine.modules.language.client import (
    ChatRequest,
    DryPenalty,
    LlamaCppChatClient,
    OpenAIChatClient,
)


def test_dry_fields_sent_when_multiplier_positive() -> None:
    client = OpenAIChatClient(base_url="http://127.0.0.1:11434/v1")
    body = client._body(
        ChatRequest(
            prompt="p",
            model="m",
            dry=DryPenalty(0.8, 1.75, 2, 2048),
        ),
        think=False,
    )
    assert body["dry_multiplier"] == 0.8
    assert body["dry_base"] == 1.75
    assert body["dry_allowed_length"] == 2
    assert body["dry_penalty_last_n"] == 2048
    assert isinstance(body["dry_multiplier"], float)
    assert isinstance(body["dry_base"], float)
    assert isinstance(body["dry_allowed_length"], int)
    assert isinstance(body["dry_penalty_last_n"], int)


def test_no_dry_fields_without_penalty() -> None:
    client = OpenAIChatClient(base_url="http://127.0.0.1:11434/v1")
    for dry in (None, DryPenalty(0.0, 1.75, 2, 2048)):
        for think in (False, None):
            base_body = client._body(ChatRequest(prompt="p", model="m"), think=think)
            body = client._body(ChatRequest(prompt="p", model="m", dry=dry), think=think)
            assert not any(k.startswith("dry_") for k in body)
            assert body == base_body


def test_retry_body_keeps_dry() -> None:
    client = OpenAIChatClient(base_url="http://127.0.0.1:11434/v1")
    req = ChatRequest(prompt="p", model="m", dry=DryPenalty(0.8, 1.75, 2, 2048))
    body = client._body(req, think=None)
    assert body["dry_multiplier"] == 0.8
    assert body["dry_base"] == 1.75
    assert body["dry_allowed_length"] == 2
    assert body["dry_penalty_last_n"] == 2048
    assert "chat_template_kwargs" not in body


class _FakeHTTP:
    def __init__(self, response):
        self.response = response
        self.status_code = 200
        self.posted = []

    async def post(self, url, json=None):
        self.posted.append(json or {})

        class _R:
            def __init__(self, status_code, body):
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


async def test_complete_posts_dry_fields(tmp_path, monkeypatch) -> None:
    path = tmp_path / "organ_window.json"
    ows.write_window_state(ows.PHASE_IDLE, path=path)
    monkeypatch.setattr(ows, "ORGAN_WINDOW_STATE", path)

    client = OpenAIChatClient(base_url="http://127.0.0.1:11434/v1")
    fake = _FakeHTTP({"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}], "usage": {}})
    client._client = fake

    resp = await client.complete(ChatRequest(prompt="p", model="m", dry=DryPenalty(0.8, 1.75, 2, 512)))
    assert len(fake.posted) == 1
    body = fake.posted[0]
    assert body["dry_penalty_last_n"] == 512
    assert body["dry_multiplier"] == 0.8
    assert resp.text == "hi"


async def test_llama_cpp_backend_sends_no_dry(tmp_path, monkeypatch) -> None:
    path = tmp_path / "organ_window.json"
    ows.write_window_state(ows.PHASE_IDLE, path=path)
    monkeypatch.setattr(ows, "ORGAN_WINDOW_STATE", path)

    client = LlamaCppChatClient(model_path="/nonexistent.gguf")
    recorded = {}

    class _FakeLlama:
        def create_chat_completion(self, **kwargs):
            recorded["kwargs"] = kwargs
            return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}}

    client._llama = _FakeLlama()
    resp = await client.complete(ChatRequest(prompt="p", model="m", dry=DryPenalty(0.8, 1.75, 2, 512)))
    assert not any(k.startswith("dry") for k in recorded["kwargs"])
    assert resp.text == "ok"
