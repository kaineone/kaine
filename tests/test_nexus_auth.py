# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from fastapi import Depends, FastAPI
from starlette.testclient import TestClient

from kaine.nexus.auth import NexusAuthError, _constant_time_equal, require_operator_token
from kaine.nexus.config import NexusConfig


def _app(config: NexusConfig) -> FastAPI:
    app = FastAPI()
    app.state.config = config

    @app.post("/mutate")
    async def mutate(_=Depends(require_operator_token)):
        return {"ok": True}

    @app.get("/read")
    async def read(_=Depends(require_operator_token)):
        return {"ok": True}

    return app


def test_missing_config_rejects():
    app = FastAPI()

    @app.post("/mutate")
    async def mutate(_=Depends(require_operator_token)):
        return {"ok": True}

    client = TestClient(app)
    r = client.post("/mutate", headers={"Authorization": "Bearer x"})
    assert r.status_code == 401
    assert r.json()["detail"] == "operator authentication required"


def test_no_token_configured_rejects():
    config = NexusConfig(operator_token="")
    client = TestClient(_app(config))
    r = client.post("/mutate", headers={"Authorization": "Bearer x"})
    assert r.status_code == 401


def test_missing_header_rejects():
    config = NexusConfig(operator_token="s3cret")
    client = TestClient(_app(config))
    r = client.post("/mutate")
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers
    assert r.headers["WWW-Authenticate"] == "Bearer"


def test_wrong_token_rejects():
    config = NexusConfig(operator_token="s3cret")
    client = TestClient(_app(config))
    r = client.post("/mutate", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_correct_token_allows():
    config = NexusConfig(operator_token="s3cret")
    client = TestClient(_app(config))
    r = client.post("/mutate", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_constant_time_equal_detects_difference():
    assert _constant_time_equal("abc", "abc") is True
    assert _constant_time_equal("abc", "abC") is False
    assert _constant_time_equal("abc", "abcd") is False


def test_auth_error_has_bearer_www_authenticate():
    exc = NexusAuthError()
    assert exc.status_code == 401
    assert exc.headers == {"WWW-Authenticate": "Bearer"}
