# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The Nexus chat-LLM health probe must tolerate chat_url given as the Ollama
server root (the shipped default, no /v1) or with a trailing /v1, normalizing
to the /v1/models listing endpoint either way. Regression for the chat_url
native-root config change, which otherwise made the probe hit a 404 /models
path and report a healthy Ollama as degraded.
"""
from __future__ import annotations

import pytest

from kaine.nexus import health
from kaine.nexus.health import DEGRADED, UP, probe_chat_llm


class _FakeResp:
    status_code = 200

    def json(self):
        return {"data": [{"id": "qwen3.6:latest"}]}


class _Recorder:
    last_url: str | None = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        _Recorder.last_url = url
        return _FakeResp()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "base",
    [
        "http://127.0.0.1:11434",
        "http://127.0.0.1:11434/",
        "http://127.0.0.1:11434/v1",
        "http://127.0.0.1:11434/v1/",
    ],
)
async def test_probe_normalizes_any_chat_url_to_v1_models(base, monkeypatch):
    monkeypatch.setattr(health.httpx, "AsyncClient", _Recorder)
    status, _ = await probe_chat_llm(base_url=base, model_id=None)
    assert _Recorder.last_url == "http://127.0.0.1:11434/v1/models"
    assert status == UP


@pytest.mark.asyncio
async def test_probe_degraded_when_model_not_served(monkeypatch):
    monkeypatch.setattr(health.httpx, "AsyncClient", _Recorder)
    status, detail = await probe_chat_llm(
        base_url="http://127.0.0.1:11434", model_id="not-served:latest"
    )
    assert status == DEGRADED
    assert "not served" in detail
