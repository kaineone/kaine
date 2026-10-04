# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""the single home of the organ, model-server key and free-disk defaults; boundary-neutral so every layer may import it."""

import os
from typing import Any, Mapping

DEFAULT_ORGAN_PORT = 11434  # the port the shipped config serves the organ on
DEFAULT_CHAT_URL = f"http://127.0.0.1:{DEFAULT_ORGAN_PORT}/v1"
MODEL_SERVER_API_KEY_ENV = "KAINE_MODEL_SERVER_API_KEY"
DEFAULT_MIN_FREE_GB = 20.0

DEFAULT_REDIS_PORT = 6479  # the KAINE-owned Redis container's host port (compose/redis.yml)
DEFAULT_QDRANT_PORT = 6533  # the KAINE-owned Qdrant container's host port (compose/qdrant.yml), not upstream's 6333


def lingua_chat_url(config: Mapping[str, Any] | None) -> str:
    """[lingua].chat_url, else DEFAULT_CHAT_URL."""
    section = (config or {}).get("lingua") or {}
    return lingua_section_chat_url(section)


def lingua_section_chat_url(section: Mapping[str, Any] | None) -> str:
    """[lingua] section chat_url, else DEFAULT_CHAT_URL."""
    chat_url = (section or {}).get("chat_url")
    return str(chat_url) if chat_url else DEFAULT_CHAT_URL


def lingua_section_api_key(section: Mapping[str, Any] | None) -> str | None:
    """[lingua].api_key when set and non-empty, else the environment variable, else None."""
    return (section or {}).get("api_key") or os.environ.get(MODEL_SERVER_API_KEY_ENV) or None


def model_server_api_key(config: Mapping[str, Any] | None) -> str | None:
    """[lingua].api_key when set and non-empty, else the environment variable, else None."""
    return lingua_section_api_key((config or {}).get("lingua") or {})
