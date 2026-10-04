# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Provenance and seed wiring for the Lingua chat client."""

from __future__ import annotations

from typing import Any

import pytest

import kaine.organ_window_state as ows
from kaine.modules.lingua.client import ChatRequest, OpenAIChatClient


def _set_window(tmp_path, phase):
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


def test_seed_sent_only_when_set():
    client = OpenAIChatClient(base_url="http://127.0.0.1:11434/v1")

    seeded = ChatRequest(model="m", prompt="p", seed=1234)
    body_seeded = client._body(seeded, think=False)
    assert body_seeded["seed"] == 1234

    default = ChatRequest(model="m", prompt="p")
    body_default = client._body(default, think=False)
    assert "seed" not in body_default


@pytest.mark.asyncio
async def test_real_answer_is_from_content(tmp_path, monkeypatch):
    path = _set_window(tmp_path, ows.PHASE_IDLE)
    monkeypatch.setattr(ows, "ORGAN_WINDOW_STATE", path)

    response = {
        "choices": [{"message": {"content": "tea"}, "finish_reason": "stop"}],
        "usage": {"completion_tokens": 3},
    }
    fake = _FakeHTTP(response=response)
    client = OpenAIChatClient(base_url="http://127.0.0.1:11434/v1")
    client._client = fake

    resp = await client.complete(ChatRequest(prompt="order", model="m"))
    assert resp.text == "tea"
    assert resp.from_content is True
    assert resp.finish_reason == "stop"
    assert resp.completion_tokens == 3


@pytest.mark.asyncio
async def test_reasoning_only_is_not_from_content(tmp_path, monkeypatch):
    path = _set_window(tmp_path, ows.PHASE_IDLE)
    monkeypatch.setattr(ows, "ORGAN_WINDOW_STATE", path)

    response = {
        "choices": [
            {
                "message": {"content": "", "reasoning_content": "thinking..."},
                "finish_reason": "length",
            }
        ]
    }
    fake = _FakeHTTP(response=response)
    client = OpenAIChatClient(base_url="http://127.0.0.1:11434/v1")
    client._client = fake

    resp = await client.complete(ChatRequest(prompt="think", model="m"))
    assert resp.text == "thinking..."
    assert resp.from_content is False
    assert resp.finish_reason == "length"


@pytest.mark.asyncio
async def test_resting_organ_is_not_from_content(tmp_path, monkeypatch):
    path = _set_window(tmp_path, ows.PHASE_TRAINING)
    monkeypatch.setattr(ows, "ORGAN_WINDOW_STATE", path)

    client = OpenAIChatClient(base_url="http://127.0.0.1:1/v1")
    resp = await client.complete(ChatRequest(prompt="hello", model="m"))
    assert resp.from_content is False
    assert resp.finish_reason is None
    assert resp.raw.get("organ_resting") is True


@pytest.mark.asyncio
async def test_non_200_raises(tmp_path, monkeypatch):
    path = _set_window(tmp_path, ows.PHASE_IDLE)
    monkeypatch.setattr(ows, "ORGAN_WINDOW_STATE", path)

    fake = _FakeHTTP(status_code=500)
    client = OpenAIChatClient(base_url="http://127.0.0.1:11434/v1")
    client._client = fake

    with pytest.raises(RuntimeError):
        await client.complete(ChatRequest(prompt="x", model="m"))


@pytest.mark.asyncio
async def test_seed_reaches_the_wire(tmp_path, monkeypatch):
    path = _set_window(tmp_path, ows.PHASE_IDLE)
    monkeypatch.setattr(ows, "ORGAN_WINDOW_STATE", path)

    response = {
        "choices": [{"message": {"content": "hi"}}],
        "model": "m",
        "usage": {},
    }
    fake = _FakeHTTP(response=response)
    client = OpenAIChatClient(base_url="http://127.0.0.1:11434/v1")
    client._client = fake

    await client.complete(ChatRequest(prompt="hi", model="m", seed=7))
    assert fake.posted[0]["seed"] == 7
