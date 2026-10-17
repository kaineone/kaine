# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import logging

import pytest
from fastapi import FastAPI

from kaine.dashboard import __main__ as dashboard_main
from kaine.dashboard.config import DashboardConfig


def _build_fake(config: DashboardConfig):
    async def fake_build():
        return (FastAPI(), config)

    return fake_build


def _uvicorn_recorder():
    calls = []

    def fake_run(app_obj, **kwargs):
        calls.append({"app": app_obj, "kwargs": kwargs})

    return fake_run, calls


def _token_in_caplog(caplog):
    return any("KAINE_DASHBOARD_TOKEN" in record.message for record in caplog.records)


@pytest.fixture
def _capture_errors(caplog):
    caplog.set_level(logging.ERROR, logger="kaine.dashboard.__main__")


def test_main_token_loopback_without_token_exits(monkeypatch, caplog, _capture_errors):
    config = DashboardConfig(
        access="token",
        host="127.0.0.1",
        non_loopback_allowed=False,
        operator_token="",
        conversation_enabled=False,
        diagnostics_enabled=True,
    )
    fake_build = _build_fake(config)
    fake_run, calls = _uvicorn_recorder()

    monkeypatch.setattr(dashboard_main, "_build", fake_build)
    monkeypatch.setattr(dashboard_main.uvicorn, "run", fake_run)

    assert dashboard_main.main() == 1
    assert calls == []
    assert _token_in_caplog(caplog)


def test_main_token_non_loopback_without_token_exits(monkeypatch, caplog, _capture_errors):
    config = DashboardConfig(
        access="token",
        host="0.0.0.0",
        non_loopback_allowed=True,
        operator_token="",
        conversation_enabled=False,
        diagnostics_enabled=True,
    )
    fake_build = _build_fake(config)
    fake_run, calls = _uvicorn_recorder()

    monkeypatch.setattr(dashboard_main, "_build", fake_build)
    monkeypatch.setattr(dashboard_main.uvicorn, "run", fake_run)

    assert dashboard_main.main() == 1
    assert calls == []
    assert _token_in_caplog(caplog)


def test_main_token_loopback_with_token_runs(monkeypatch):
    config = DashboardConfig(
        access="token",
        host="127.0.0.1",
        non_loopback_allowed=False,
        operator_token="t" * 40,
        conversation_enabled=False,
        diagnostics_enabled=True,
    )
    fake_build = _build_fake(config)
    fake_run, calls = _uvicorn_recorder()

    monkeypatch.setattr(dashboard_main, "_build", fake_build)
    monkeypatch.setattr(dashboard_main.uvicorn, "run", fake_run)

    assert dashboard_main.main() == 0
    assert len(calls) == 1
    assert calls[0]["kwargs"]["host"] == "127.0.0.1"


def test_main_open_loopback_without_token_runs(monkeypatch):
    config = DashboardConfig(
        access="open",
        host="127.0.0.1",
        non_loopback_allowed=False,
        operator_token="",
        conversation_enabled=False,
        diagnostics_enabled=True,
    )
    fake_build = _build_fake(config)
    fake_run, calls = _uvicorn_recorder()

    monkeypatch.setattr(dashboard_main, "_build", fake_build)
    monkeypatch.setattr(dashboard_main.uvicorn, "run", fake_run)

    assert dashboard_main.main() == 0
    assert len(calls) == 1
