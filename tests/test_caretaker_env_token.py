# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import os
from pathlib import Path

import pytest

import kaine.secrets_file
from kaine.cycle.caretaker import (
    CARETAKER_TOKEN_ENV_PREFIX,
    CaretakerConfig,
    ChannelResult,
    load_token,
    notify,
)


@pytest.fixture(autouse=True)
def reset_unreadable_warnings():
    kaine.secrets_file._reset_unreadable_warnings()
    yield
    kaine.secrets_file._reset_unreadable_warnings()


def _write_secrets(path: Path, token_name: str = "ntfy", value: str = "filetoken") -> None:
    path.write_text(f'[caretaker.tokens]\n{token_name} = "{value}"\n')
    path.chmod(0o600)


def _skip_if_root():
    if os.geteuid() == 0:
        pytest.skip("root can read 0o000 files")


def test_env_wins_over_file(tmp_path, monkeypatch):
    secrets_path = tmp_path / "secrets.toml"
    _write_secrets(secrets_path, "ntfy", "filetoken")
    monkeypatch.setenv(f"{CARETAKER_TOKEN_ENV_PREFIX}NTFY", "envtoken")

    result = load_token("ntfy", secrets_path=secrets_path, env=os.environ)
    assert result == "envtoken"


def test_env_wins_over_unreadable_file(tmp_path, monkeypatch):
    _skip_if_root()

    secrets_path = tmp_path / "secrets.toml"
    _write_secrets(secrets_path, "ntfy", "filetoken")
    monkeypatch.setenv(f"{CARETAKER_TOKEN_ENV_PREFIX}NTFY", "envtoken")
    secrets_path.chmod(0o000)
    try:
        result = load_token("ntfy", secrets_path=secrets_path, env=os.environ)
        assert result == "envtoken"
    finally:
        secrets_path.chmod(0o600)


def test_file_token_when_no_env(tmp_path):
    secrets_path = tmp_path / "secrets.toml"
    _write_secrets(secrets_path, "ntfy", "filetoken")

    result = load_token("ntfy", secrets_path=secrets_path, env={})
    assert result == "filetoken"


def test_unreadable_file_returns_none(tmp_path):
    _skip_if_root()

    secrets_path = tmp_path / "secrets.toml"
    _write_secrets(secrets_path, "ntfy", "filetoken")
    secrets_path.chmod(0o000)
    try:
        result = load_token("ntfy", secrets_path=secrets_path, env={})
        assert result is None
    finally:
        secrets_path.chmod(0o600)


@pytest.mark.parametrize("env_value", ["", "   ", "\t\n"])
def test_empty_env_falls_back_to_file(tmp_path, monkeypatch, env_value):
    secrets_path = tmp_path / "secrets.toml"
    _write_secrets(secrets_path, "ntfy", "filetoken")
    monkeypatch.setenv(f"{CARETAKER_TOKEN_ENV_PREFIX}NTFY", env_value)

    result = load_token("ntfy", secrets_path=secrets_path, env=os.environ)
    assert result == "filetoken"


def test_token_name_none_returns_none(tmp_path):
    result = load_token(None, secrets_path=tmp_path / "missing.toml", env={})
    assert result is None


def test_notify_http_uses_env_token(monkeypatch):
    env_token = "envtoken"
    monkeypatch.setenv(f"{CARETAKER_TOKEN_ENV_PREFIX}NTFY", env_token)

    cfg = CaretakerConfig.from_section(
        {
            "channels": [
                {
                    "kind": "http",
                    "url": "http://127.0.0.1:9/notify",
                    "token_name": "ntfy",
                }
            ]
        }
    )

    captured = {}

    def fake_http_sender(notice, url, token):
        captured["token"] = token
        return ChannelResult(kind="http", accepted=True, detail="")

    notice = {
        "install_label": "test",
        "time": "2026-01-01T00:00:00+00:00",
        "event": "starting_unattended",
        "conditions": None,
        "dashboard_url": "http://127.0.0.1:8088/",
    }

    results = notify(cfg, notice, http_sender=fake_http_sender)
    assert len(results) == 1
    assert results[0].accepted is True
    assert captured["token"] == env_token
