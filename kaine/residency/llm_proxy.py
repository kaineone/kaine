# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Generate a llama-swap proxy config from the KAINE configuration.

llama-swap sits in front of one or more llama-server instances, starts and
stops them on demand, and enforces idle TTLs and exclusive groups. When
``[residency].llm_proxy = "llama-swap"``, this module produces the YAML
config the proxy reads at startup.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kaine.defaults import DEFAULT_ORGAN_PORT, language_section_chat_url
from kaine.storage import resolve

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "state/residency/llama-swap.yaml"

# Upstream llama-server instances managed by the proxy get sequential ports
# starting here. Kept above the organ's default (11434) and below ephemeral.
UPSTREAM_BASE_PORT = 11440


@dataclass(frozen=True)
class LlamaSwapModel:
    alias: str
    cmd: str
    ttl: int


@dataclass(frozen=True)
class LlamaSwapConfig:
    models: tuple[LlamaSwapModel, ...]
    groups: dict[str, tuple[str, ...]]
    listen_port: int

    def to_dict(self) -> dict[str, Any]:
        models: dict[str, dict[str, Any]] = {}
        for m in self.models:
            models[m.alias] = {"cmd": m.cmd, "ttl": m.ttl}
        groups: dict[str, dict[str, Any]] = {}
        for name, members in self.groups.items():
            groups[name] = {"swap": True, "members": list(members)}
        return {"models": models, "groups": groups}


def _port_from_chat_url(chat_url: str) -> int:
    from urllib.parse import urlparse

    parsed = urlparse(chat_url if "//" in chat_url else "//" + chat_url)
    return int(parsed.port or DEFAULT_ORGAN_PORT)


def _build_upstream_cmd(
    binary: Path,
    gguf: Path,
    alias: str,
    port: int,
) -> str:
    parts = [
        str(binary),
        "-m", str(gguf),
        "--alias", alias,
        "--host", "127.0.0.1",
        "--port", str(port),
        "--jinja",
        "--reasoning-budget", "0",
        # The proxy manages TTL; the upstream server stays loaded.
        "--sleep-idle-seconds", "-1",
    ]
    return " ".join(parts)


def generate_llama_swap_config(
    config: dict[str, Any],
) -> LlamaSwapConfig | None:
    """Build a llama-swap config from the merged KAINE configuration.

    Returns None when llm_proxy is not "llama-swap".
    """
    from kaine.residency.config import from_config as residency_from_config

    residency = residency_from_config(config)
    if residency.llm_proxy != "llama-swap":
        return None

    language = config.get("language") or {}
    model_id = language.get("model_id")
    if not model_id:
        logger.warning("llm_proxy is llama-swap but [language].model_id is not set")
        return None

    chat_url = language_section_chat_url(language)
    listen_port = _port_from_chat_url(chat_url)

    from kaine.organ_server.lifecycle import locate_binary
    from kaine.organ_server.served import detect_organ_backend, served_gguf_path

    backend = detect_organ_backend()
    binary = locate_binary(backend.backend)
    if binary is None:
        logger.warning(
            "llm_proxy is llama-swap but no llama-server binary found"
        )
        return None

    gguf = served_gguf_path()
    ttl = residency.ttl_overrides.get("language", residency.ttl_seconds)

    upstream_port = UPSTREAM_BASE_PORT
    cmd = _build_upstream_cmd(binary, gguf, model_id, upstream_port)

    chat_model = LlamaSwapModel(alias=model_id, cmd=cmd, ttl=ttl)
    return LlamaSwapConfig(
        models=(chat_model,),
        groups={"llm": (model_id,)},
        listen_port=listen_port,
    )


def write_llama_swap_config(
    config: LlamaSwapConfig,
    path: str | Path | None = None,
) -> Path:
    """Write the llama-swap config YAML atomically."""
    import yaml

    target = Path(resolve(DEFAULT_CONFIG_PATH if path is None else path))
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = yaml.safe_dump(config.to_dict(), default_flow_style=False, sort_keys=False)
    tmp = target.with_name(
        f"{target.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    )
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(target)
    return target
