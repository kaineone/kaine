# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for kaine.defaults — single-source defaults and guards."""

from pathlib import Path

from kaine.defaults import (
    DEFAULT_CHAT_URL,
    DEFAULT_MIN_FREE_GB,
    DEFAULT_ORGAN_PORT,
    MODEL_SERVER_API_KEY_ENV,
    lingua_chat_url,
    lingua_section_api_key,
    lingua_section_chat_url,
    model_server_api_key,
)


def test_model_server_api_key_config_over_env(monkeypatch):
    monkeypatch.setenv(MODEL_SERVER_API_KEY_ENV, "env-key")
    assert model_server_api_key({"lingua": {"api_key": "config-key"}}) == "config-key"


def test_model_server_api_key_env_when_config_missing(monkeypatch):
    monkeypatch.setenv(MODEL_SERVER_API_KEY_ENV, "env-key")
    assert model_server_api_key({}) == "env-key"
    assert model_server_api_key({"lingua": {}}) == "env-key"
    assert model_server_api_key(None) == "env-key"


def test_model_server_api_key_env_when_config_empty(monkeypatch):
    monkeypatch.setenv(MODEL_SERVER_API_KEY_ENV, "env-key")
    assert model_server_api_key({"lingua": {"api_key": ""}}) == "env-key"
    assert lingua_section_api_key({"api_key": ""}) == "env-key"


def test_model_server_api_key_none_when_both_absent(monkeypatch):
    monkeypatch.delenv(MODEL_SERVER_API_KEY_ENV, raising=False)
    assert model_server_api_key({}) is None
    assert model_server_api_key(None) is None
    assert model_server_api_key({"lingua": {"api_key": ""}}) is None


def test_lingua_chat_url_default_and_override():
    assert lingua_chat_url({}) == DEFAULT_CHAT_URL
    assert lingua_chat_url(None) == DEFAULT_CHAT_URL
    assert lingua_chat_url({"lingua": {"chat_url": ""}}) == DEFAULT_CHAT_URL
    assert lingua_chat_url({"lingua": {"chat_url": "http://x/v1"}}) == "http://x/v1"
    assert lingua_section_chat_url({}) == DEFAULT_CHAT_URL
    assert lingua_section_chat_url({"chat_url": "http://y/v1"}) == "http://y/v1"


def test_default_values():
    assert DEFAULT_ORGAN_PORT == 11434
    assert DEFAULT_CHAT_URL == "http://127.0.0.1:11434/v1"
    assert DEFAULT_MIN_FREE_GB == 20.0


def test_no_stray_port_literal():
    root = Path(__file__).resolve().parents[1] / "kaine"
    allowed = {"kaine/net.py", "kaine/defaults.py"}
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(root.parent).as_posix()
        if "11434" in path.read_text() and rel not in allowed:
            raise AssertionError(f"{rel} contains the organ port literal 11434")


def test_no_stray_key_read():
    root = Path(__file__).resolve().parents[1] / "kaine"
    allowed = {"kaine/defaults.py"}
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(root.parent).as_posix()
        if "KAINE_MODEL_SERVER_API_KEY" in path.read_text() and rel not in allowed:
            raise AssertionError(f"{rel} reads KAINE_MODEL_SERVER_API_KEY directly")
