# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The Lingua factory."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass
from kaine.boot.errors import _pop
from kaine.bus.client import AsyncBus
from kaine.defaults import lingua_section_api_key, lingua_section_chat_url
from kaine.modules.base import BaseModule


def make_lingua(bus: AsyncBus, section: dict[str, Any]) -> BaseModule:
    from kaine.modules.lingua.module import Lingua

    allowed = {
        "chat_url",
        "model_id",
        "temperature",
        "max_tokens",
        "think",
        "request_timeout_s",
        # read by kaine.organ_server.lifecycle when it launches the organ, not by Lingua
        "model_server_sleep_idle_seconds",
        "api_key",
        "intent_log_path",
        "context_max_events",
        "context_char_budget",
        "persona_name",
        "persona_external",
        "persona_internal",
        "baseline_salience",
        "alert_salience",
        # Runtime backend selection (openspec runtime-backends). Absent/"openai"
        # (or its alias "ollama") → today's OpenAI-compatible HTTP client
        # (Tier-2, built by Lingua exactly as before); "llama_cpp" → in-process
        # GGUF edge runtime. GGUF locators for the edge backend (unused by the
        # HTTP default).
        "backend",
        "gguf_path",
        "gguf_filename",
    }
    kw = _pop(section, allowed)
    kw.pop("model_server_sleep_idle_seconds", None)
    # Bearer token for a keyed model server (e.g. Unsloth Studio). Resolve from
    # [lingua].api_key, else the model-server key environment variable (so the secret
    # can stay out of the config file). None → keyless server (llama-server).
    kw["api_key"] = lingua_section_api_key(kw)

    # Backend seam. The default path is byte-for-byte behaviour-preserving: when
    # no edge backend is selected we do NOT build a client here — Lingua
    # constructs its OpenAIChatClient itself, exactly as it always has (openspec
    # runtime-backends, "Default backend preserves current behavior"). Only a
    # non-default backend resolves a client behind the ChatClient interface; a
    # backend that cannot load degrades to the HTTP client (its declared
    # fallback), the reason already recorded + surfaced on the health surface.
    backend = kw.pop("backend", None)
    gguf_path = kw.pop("gguf_path", None)
    gguf_filename = kw.pop("gguf_filename", None)
    if backend not in (None, "", "openai", "ollama"):
        from kaine.modules.lingua.client import build_chat_client_registry

        registry = build_chat_client_registry(
            chat_url=lingua_section_chat_url(kw),
            api_key=kw.get("api_key"),
            timeout_s=float(kw.get("request_timeout_s", 60.0)),
            model_id=kw.get("model_id"),
            gguf_path=gguf_path,
            gguf_filename=gguf_filename,
        )
        client = registry.resolve(backend)
        if client is not None:
            kw["chat_client"] = client
    return Lingua(bus, **kw)
