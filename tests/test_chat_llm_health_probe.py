# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The Nexus chat-LLM health probe must tolerate chat_url given as the Ollama
server root (the shipped default, no /v1) or with a trailing /v1, normalizing
to the /v1/models listing endpoint either way. Regression for the chat_url
native-root config change, which otherwise made the probe hit a 404 /models
path and report a healthy Ollama as degraded.
"""
from __future__ import annotations

import httpx
import pytest

from kaine.nexus import health
from kaine.nexus.health import DEGRADED, UP, probe_chat_llm


class _ModelsResp:
    status_code = 200

    def json(self):
        return {"data": [{"id": "qwen3.6:latest"}]}


class _PropsResp:
    status_code = 200
    body = {"is_sleeping": False}

    def json(self):
        return self.body


class _Recorder:
    urls: list[str] = []
    raises_connect_error = False

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        _Recorder.urls.append(url)
        if url.endswith("/v1/models"):
            return _ModelsResp()
        if url.endswith("/props"):
            if _Recorder.raises_connect_error:
                raise httpx.ConnectError("x")
            return _PropsResp()
        raise httpx.HTTPError(f"unexpected URL {url}")


def _reset_recorder():
    _Recorder.urls = []
    _Recorder.raises_connect_error = False
    _PropsResp.status_code = 200
    _PropsResp.body = {"is_sleeping": False}


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
    _reset_recorder()
    monkeypatch.setattr(health.httpx, "AsyncClient", _Recorder)
    status, _ = await probe_chat_llm(base_url=base, model_id=None)
    assert _Recorder.urls[0] == "http://127.0.0.1:11434/v1/models"
    assert status == UP


@pytest.mark.asyncio
async def test_probe_asleep_organ_returns_up_with_asleep_detail(monkeypatch):
    _reset_recorder()
    monkeypatch.setattr(health.httpx, "AsyncClient", _Recorder)
    _PropsResp.body = {"is_sleeping": True}
    status, detail = await probe_chat_llm(
        base_url="http://127.0.0.1:11434", model_id=None
    )
    assert status == UP
    assert "asleep" in detail
    assert len(_Recorder.urls) == 2
    assert _Recorder.urls[1].endswith("/props")


@pytest.mark.asyncio
async def test_probe_awake_organ_returns_up_without_asleep_detail(monkeypatch):
    _reset_recorder()
    monkeypatch.setattr(health.httpx, "AsyncClient", _Recorder)
    status, detail = await probe_chat_llm(
        base_url="http://127.0.0.1:11434", model_id=None
    )
    assert status == UP
    assert "asleep" not in detail
    assert len(_Recorder.urls) == 2


@pytest.mark.asyncio
async def test_probe_missing_props_endpoint_returns_up_unchanged(monkeypatch):
    _reset_recorder()
    monkeypatch.setattr(health.httpx, "AsyncClient", _Recorder)
    _PropsResp.status_code = 404
    status, detail = await probe_chat_llm(
        base_url="http://127.0.0.1:11434", model_id=None
    )
    assert status == UP
    assert detail == "1 models served"
    assert "asleep" not in detail


@pytest.mark.asyncio
async def test_probe_props_connect_error_returns_up(monkeypatch):
    _reset_recorder()
    monkeypatch.setattr(health.httpx, "AsyncClient", _Recorder)
    _Recorder.raises_connect_error = True
    status, detail = await probe_chat_llm(
        base_url="http://127.0.0.1:11434", model_id=None
    )
    assert status == UP
    assert detail == "1 models served"


@pytest.mark.asyncio
async def test_probe_degraded_when_model_not_served(monkeypatch):
    _reset_recorder()
    monkeypatch.setattr(health.httpx, "AsyncClient", _Recorder)
    status, detail = await probe_chat_llm(
        base_url="http://127.0.0.1:11434", model_id="not-served:latest"
    )
    assert status == DEGRADED
    assert "not served" in detail
    assert not any(u.endswith("/props") for u in _Recorder.urls)
