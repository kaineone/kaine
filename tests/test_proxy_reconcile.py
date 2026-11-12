# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from kaine.residency.ledger import Ledger, State
from kaine.residency.proxy_reconcile import (
    query_proxy_models,
    reconcile_proxy,
    unload_for_admission,
    unload_proxy_model,
)

BASE = "http://127.0.0.1:8080"


def _ledger_with_models(**kwargs):
    """Build a ledger and register models with given footprints."""
    total = sum(kwargs.values()) * 2 or 4096
    ledger = Ledger(budget_bytes=total)
    for name, fp in kwargs.items():
        ledger.register(name, footprint_bytes=fp)
    return ledger


def _mock_client(method="get", response=None, side_effect=None):
    client = AsyncMock()
    mock_method = AsyncMock(return_value=response, side_effect=side_effect)
    setattr(client, method, mock_method)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


# --- query_proxy_models ---

@pytest.mark.asyncio
async def test_query_returns_model_status():
    payload = {"model_a": "loaded", "model_b": "idle"}
    resp = httpx.Response(200, json=payload, request=httpx.Request("GET", BASE))
    client = _mock_client("get", response=resp)

    with patch("kaine.residency.proxy_reconcile.httpx.AsyncClient", return_value=client):
        result = await query_proxy_models(BASE)

    assert result == {"model_a": "loaded", "model_b": "idle"}


@pytest.mark.asyncio
async def test_query_returns_empty_on_connection_error():
    client = _mock_client("get", side_effect=httpx.ConnectError("refused"))

    with patch("kaine.residency.proxy_reconcile.httpx.AsyncClient", return_value=client):
        result = await query_proxy_models(BASE)

    assert result == {}


@pytest.mark.asyncio
async def test_query_returns_empty_on_non_200():
    resp = httpx.Response(500, request=httpx.Request("GET", BASE))
    client = _mock_client("get", response=resp)

    with patch("kaine.residency.proxy_reconcile.httpx.AsyncClient", return_value=client):
        result = await query_proxy_models(BASE)

    assert result == {}


# --- unload_proxy_model ---

@pytest.mark.asyncio
async def test_unload_success():
    resp = httpx.Response(200, request=httpx.Request("POST", BASE))
    client = _mock_client("post", response=resp)

    with patch("kaine.residency.proxy_reconcile.httpx.AsyncClient", return_value=client):
        ok = await unload_proxy_model(BASE, "model_a")

    assert ok is True


@pytest.mark.asyncio
async def test_unload_failure():
    resp = httpx.Response(500, request=httpx.Request("POST", BASE))
    client = _mock_client("post", response=resp)

    with patch("kaine.residency.proxy_reconcile.httpx.AsyncClient", return_value=client):
        ok = await unload_proxy_model(BASE, "model_a")

    assert ok is False


@pytest.mark.asyncio
async def test_unload_connection_error():
    client = _mock_client("post", side_effect=httpx.ConnectError("refused"))

    with patch("kaine.residency.proxy_reconcile.httpx.AsyncClient", return_value=client):
        ok = await unload_proxy_model(BASE, "model_a")

    assert ok is False


# --- reconcile_proxy ---

@pytest.mark.asyncio
async def test_reconcile_noop_when_proxy_none():
    ledger = _ledger_with_models(stt=400)
    with patch("kaine.residency.proxy_reconcile.query_proxy_models") as mock_q:
        await reconcile_proxy(ledger, BASE, "none")
        mock_q.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_marks_loaded_models_resident():
    ledger = _ledger_with_models(stt=400, tts=300)
    assert ledger.get("stt").state == State.ABSENT

    with patch(
        "kaine.residency.proxy_reconcile.query_proxy_models",
        return_value={"stt": "loaded"},
    ):
        await reconcile_proxy(ledger, BASE, "llama-swap")

    assert ledger.get("stt").state == State.RESIDENT
    assert ledger.get("tts").state == State.ABSENT


@pytest.mark.asyncio
async def test_reconcile_marks_absent_models_cold():
    ledger = _ledger_with_models(stt=400, tts=300)
    ledger.mark_resident("stt")
    ledger.mark_resident("tts")

    with patch(
        "kaine.residency.proxy_reconcile.query_proxy_models",
        return_value={"stt": "loaded"},
    ):
        await reconcile_proxy(ledger, BASE, "llama-swap")

    assert ledger.get("stt").state == State.RESIDENT
    assert ledger.get("tts").state == State.COLD


@pytest.mark.asyncio
async def test_reconcile_ignores_unregistered_models():
    ledger = _ledger_with_models(stt=400)

    with patch(
        "kaine.residency.proxy_reconcile.query_proxy_models",
        return_value={"stt": "loaded", "unknown_model": "loaded"},
    ):
        await reconcile_proxy(ledger, BASE, "llama-swap")

    assert ledger.get("stt").state == State.RESIDENT
    assert ledger.get("unknown_model") is None


@pytest.mark.asyncio
async def test_reconcile_preserves_loading_state():
    ledger = _ledger_with_models(stt=400)
    await ledger.try_admit("stt", 400)
    assert ledger.get("stt").state == State.LOADING

    with patch(
        "kaine.residency.proxy_reconcile.query_proxy_models",
        return_value={"stt": "loaded"},
    ):
        await reconcile_proxy(ledger, BASE, "llama-swap")

    assert ledger.get("stt").state == State.LOADING


# --- unload_for_admission ---

@pytest.mark.asyncio
async def test_unload_for_admission_noop_when_proxy_none():
    ledger = _ledger_with_models(stt=400)
    ok = await unload_for_admission(ledger, BASE, "none", "tts", 300)
    assert ok is False


@pytest.mark.asyncio
async def test_unload_for_admission_evicts_candidates():
    ledger = Ledger(budget_bytes=1000)
    ledger.register("stt", footprint_bytes=400)
    ledger.register("tts", footprint_bytes=300)
    ledger.register("new_model", footprint_bytes=0)
    ledger.mark_resident("stt")
    ledger.mark_resident("tts")

    with patch(
        "kaine.residency.proxy_reconcile.unload_proxy_model",
        return_value=True,
    ):
        ok = await unload_for_admission(
            ledger, BASE, "llama-swap", "new_model", 500,
        )

    assert ok is True


@pytest.mark.asyncio
async def test_unload_for_admission_returns_false_if_not_enough():
    ledger = Ledger(budget_bytes=500)
    ledger.register("stt", footprint_bytes=400, ttl_seconds=0)
    ledger.register("new_model", footprint_bytes=0)
    ledger.mark_resident("stt")
    ledger.get("stt").pinned = True

    with patch(
        "kaine.residency.proxy_reconcile.unload_proxy_model",
        return_value=True,
    ):
        ok = await unload_for_admission(
            ledger, BASE, "llama-swap", "new_model", 400,
        )

    assert ok is False


@pytest.mark.asyncio
async def test_trust_env_false():
    resp = httpx.Response(200, json={}, request=httpx.Request("GET", BASE))
    client = _mock_client("get", response=resp)

    with patch(
        "kaine.residency.proxy_reconcile.httpx.AsyncClient",
        return_value=client,
    ) as mock_cls:
        await query_proxy_models(BASE)
        mock_cls.assert_called_once_with(timeout=5.0, trust_env=False)
