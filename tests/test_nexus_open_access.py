# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from kaine.nexus import __main__ as nexus_main
from kaine.nexus.app import create_app
from kaine.nexus.auth import (
    LoginRateLimiter,
    NexusAuthError,
    SessionStore,
    auth_error_handler,
    build_auth_router,
    require_operator_token,
)
from kaine.nexus.config import NexusConfig, NexusConfigError, load_nexus_config
from kaine.nexus.csrf import NexusCSRFMiddleware


def _session_store(config: NexusConfig) -> SessionStore:
    return SessionStore(
        idle_seconds=config.session_idle_minutes * 60,
        max_age_seconds=config.session_max_hours * 3600,
    )


def _limiter(config: NexusConfig) -> LoginRateLimiter:
    return LoginRateLimiter(
        max_failures=config.login_max_failures,
        window_s=config.login_failure_window_s,
    )


def _auth_app(config: NexusConfig) -> FastAPI:
    app = FastAPI()
    app.state.config = config
    app.state.sessions = _session_store(config)
    app.state.login_limiter = _limiter(config)
    app.add_exception_handler(NexusAuthError, auth_error_handler)
    app.include_router(build_auth_router(config))

    @app.post("/mutate")
    async def mutate(_=Depends(require_operator_token)):
        return {"ok": True}

    @app.get("/read")
    async def read(_=Depends(require_operator_token)):
        return {"ok": True}

    return app


def _csrf_app(config: NexusConfig) -> FastAPI:
    app = FastAPI()
    app.add_middleware(NexusCSRFMiddleware, config=config)

    @app.get("/read")
    async def read():
        return {"ok": True}

    @app.post("/mutate")
    async def mutate():
        return {"ok": True}

    return app


def _create_full_app(
    config: NexusConfig,
    rate_control_publisher=None,
) -> FastAPI:
    bridge = AsyncMock()
    bridge.start = AsyncMock()
    bridge.stop = AsyncMock()

    async def history_loader(lookback: int) -> list[tuple[str, object]]:
        return []

    def metrics_snapshot() -> dict[str, object]:
        return {}

    return create_app(
        config=config,
        bridge=bridge,
        history_loader=history_loader,
        metrics_snapshot=metrics_snapshot,
        rate_control_publisher=rate_control_publisher,
    )


def test_open_mode_privileged_requests_succeed_without_token():
    config = NexusConfig(access="open", operator_token="")
    client = TestClient(_auth_app(config), base_url="http://127.0.0.1:8088")

    assert client.get("/read").status_code == 200
    assert (
        client.post(
            "/mutate",
            headers={"Origin": "http://127.0.0.1:8088"},
        ).status_code
        == 200
    )


def test_open_mode_login_get_redirects_to_landing():
    config = NexusConfig(access="open", conversation_enabled=False)
    client = TestClient(_auth_app(config), base_url="http://127.0.0.1:8088")

    r = client.get("/login", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/diagnostics/"


def test_open_mode_login_post_redirects_to_landing():
    config = NexusConfig(access="open", conversation_enabled=False)
    client = TestClient(_auth_app(config), base_url="http://127.0.0.1:8088")

    r = client.post("/login", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/diagnostics/"


def test_open_mode_foreign_host_rejected():
    config = NexusConfig(access="open", allowed_origins=(), host_allowlist=())
    client = TestClient(_csrf_app(config))

    r = client.get("/read", headers={"Host": "evil.example"})
    assert r.status_code == 403
    assert r.json()["detail"] == "host not allowed"


def test_open_mode_cross_origin_post_rejected():
    config = NexusConfig(
        access="open",
        allowed_origins=("http://localhost:8088",),
        host_allowlist=("127.0.0.1",),
    )
    client = TestClient(_csrf_app(config), base_url="http://127.0.0.1:8088")

    r = client.post("/mutate", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert r.json()["detail"] == "cross-origin request rejected"


def test_token_mode_still_requires_operator_token():
    config = NexusConfig(access="token", operator_token="")
    client = TestClient(_auth_app(config), base_url="http://127.0.0.1:8088")

    assert client.get("/read").status_code == 401
    assert client.post("/mutate").status_code == 401


def test_root_redirects_when_conversation_disabled():
    config = NexusConfig(
        access="open",
        conversation_enabled=False,
        diagnostics_enabled=True,
    )
    app = _create_full_app(config)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    r = client.get("/", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/diagnostics/"


def test_bad_access_env_raises(monkeypatch, tmp_path):
    p = tmp_path / "kaine.toml"
    p.write_text("[nexus]\n")
    monkeypatch.setenv("KAINE_NEXUS_ACCESS", "bogus")

    with pytest.raises(NexusConfigError) as exc:
        load_nexus_config(path=p)

    assert "bogus" in str(exc.value)


def test_empty_access_env_keeps_toml_value(monkeypatch, tmp_path):
    p = tmp_path / "kaine.toml"
    p.write_text('[nexus]\naccess = "open"\n')
    monkeypatch.setenv("KAINE_NEXUS_ACCESS", "")

    cfg = load_nexus_config(path=p)
    assert cfg.access == "open"


def test_extra_hosts_extend_allowlist_and_origins(monkeypatch, tmp_path):
    p = tmp_path / "kaine.toml"
    p.write_text("[nexus]\nport = 8088\n")
    monkeypatch.setenv(
        "KAINE_NEXUS_EXTRA_HOSTS",
        "kaine-box.tail1234.ts.net, 100.64.0.7",
    )

    cfg = load_nexus_config(path=p)
    assert any(entry == "kaine-box.tail1234.ts.net" for entry in cfg.host_allowlist)
    assert any(entry == "100.64.0.7" for entry in cfg.host_allowlist)
    assert any(entry == "https://kaine-box.tail1234.ts.net" for entry in cfg.allowed_origins)
    assert any(entry == "http://100.64.0.7:8088" for entry in cfg.allowed_origins)


def test_invalid_extra_host_raises(monkeypatch, tmp_path):
    p = tmp_path / "kaine.toml"
    p.write_text("[nexus]\n")
    monkeypatch.setenv("KAINE_NEXUS_EXTRA_HOSTS", "bad_host!")

    with pytest.raises(NexusConfigError) as exc:
        load_nexus_config(path=p)

    assert "bad_host!" in str(exc.value)


def test_published_port_added_to_extra_origins(monkeypatch, tmp_path):
    p = tmp_path / "kaine.toml"
    p.write_text("[nexus]\nport = 8088\n")
    monkeypatch.setenv("KAINE_NEXUS_EXTRA_HOSTS", "kaine-box.tail1234.ts.net")
    monkeypatch.setenv("KAINE_NEXUS_PUBLISHED_PORT", "9099")

    cfg = load_nexus_config(path=p)
    assert any(entry == "http://kaine-box.tail1234.ts.net:9099" for entry in cfg.allowed_origins)


def test_committed_config_ships_open_access():
    path = Path(__file__).parent.parent / "config" / "kaine.toml"
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    assert raw["nexus"]["access"] == "open"


def test_main_open_non_loopback_without_token_starts(monkeypatch):
    config = NexusConfig(
        access="open",
        host="0.0.0.0",
        non_loopback_allowed=True,
        operator_token="",
        conversation_enabled=False,
        diagnostics_enabled=True,
    )
    app = FastAPI()

    async def fake_build():
        return (app, config)

    monkeypatch.setattr(nexus_main, "_build", fake_build)
    runs = []

    def fake_run(app_obj, host, port):
        runs.append((host, port))

    monkeypatch.setattr(nexus_main.uvicorn, "run", fake_run)
    assert nexus_main.main() == 0
    assert runs == [("0.0.0.0", 8088)]


def test_main_token_non_loopback_without_token_exits(monkeypatch):
    config = NexusConfig(
        access="token",
        host="0.0.0.0",
        non_loopback_allowed=True,
        operator_token="",
        conversation_enabled=False,
        diagnostics_enabled=True,
    )
    app = FastAPI()

    async def fake_build():
        return (app, config)

    monkeypatch.setattr(nexus_main, "_build", fake_build)
    monkeypatch.setattr(nexus_main.uvicorn, "run", lambda **kwargs: None)
    assert nexus_main.main() == 1


def test_read_only_blocks_cycle_rates_and_publisher_not_called():
    config = NexusConfig(access="open", read_only=True, operator_token="")
    publisher = AsyncMock()
    app = _create_full_app(config, rate_control_publisher=publisher)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    r = client.post(
        "/diagnostics/cycle/rates",
        json={"processing_rate_hz": 1.0},
        headers={"Origin": "http://127.0.0.1:8088"},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "Nexus is in read-only mode: controls are off"
    publisher.assert_not_called()


def test_read_only_diagnostics_page_renders_banner():
    config = NexusConfig(
        access="open",
        read_only=True,
        operator_token="",
        conversation_enabled=False,
        diagnostics_enabled=True,
    )
    app = _create_full_app(config)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    r = client.get("/diagnostics/")
    assert r.status_code == 200
    assert "readonly-banner" in r.text


def test_read_only_blocks_any_control_route():
    config = NexusConfig(access="open", read_only=True, operator_token="")
    app = _create_full_app(config)
    client = TestClient(app, base_url="http://127.0.0.1:8088")

    r = client.post("/forks", json={}, headers={"Origin": "http://127.0.0.1:8088"})
    assert r.status_code == 403
    assert r.json()["detail"] == "Nexus is in read-only mode: controls are off"


def test_read_only_env_override(monkeypatch, tmp_path):
    p = tmp_path / "kaine.toml"
    p.write_text("[nexus]\n")
    monkeypatch.setenv("KAINE_NEXUS_READ_ONLY", "1")

    cfg = load_nexus_config(path=p)
    assert cfg.read_only is True
