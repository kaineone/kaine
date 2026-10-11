# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import inspect
import tomllib
from pathlib import Path
from typing import Any

from kaine.modules.lingua.client import OpenAIChatClient, build_chat_client_registry

REPO_ROOT = Path(__file__).resolve().parents[1]


def _maybe_close(client: Any) -> None:
    close = getattr(client, "aclose", None)
    if close is None:
        return
    if inspect.iscoroutinefunction(close):
        asyncio.run(close())
    else:
        close()


def test_lingua_default_backend_is_openai() -> None:
    registry = build_chat_client_registry(
        chat_url="http://127.0.0.1:1/v1",
        api_key=None,
        timeout_s=1.0,
    )
    assert registry.default == "openai"


def test_lingua_openai_ollama_and_none_resolve_to_same_http_client() -> None:
    registry = build_chat_client_registry(
        chat_url="http://127.0.0.1:1/v1",
        api_key=None,
        timeout_s=1.0,
    )
    for selected in ("openai", "ollama", None):
        client = registry.resolve(selected)
        assert isinstance(client, OpenAIChatClient), selected
        _maybe_close(client)


def test_shipped_tier_profiles_use_openai_backend() -> None:
    for name in ("tier2.toml", "tier3.toml"):
        path = REPO_ROOT / "config" / "profiles" / name
        with path.open("rb") as f:
            config = tomllib.load(f)
        assert config.get("lingua", {}).get("backend") == "openai", name
