# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class NexusConfig:
    host: str = "127.0.0.1"
    port: int = 8088
    conversation_enabled: bool = False
    diagnostics_enabled: bool = True
    conversation_history_lookback: int = 50
    # Privacy override. Default False. When True, diagnostics surface
    # receives full content payloads. Operators see a "dev mode" banner.
    dev_content_override: bool = False
    # Operator authentication. Empty string means no token is configured;
    # state-changing endpoints and privileged read surfaces return 401.
    # Loaded from KAINE_NEXUS_TOKEN env or config/secrets.toml [nexus] operator_token.
    operator_token: str = ""
    # CSRF/Origin protection. Defaults cover loopback-only operation.
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:8088", "http://localhost:8088")
    host_allowlist: tuple[str, ...] = ("127.0.0.1", "localhost")
    # Explicit opt-in required to bind a non-loopback interface.
    non_loopback_allowed: bool = False

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "NexusConfig":
        data = dict(data or {})
        return cls(
            host=str(data.get("host", cls.host)),
            port=int(data.get("port", cls.port)),
            conversation_enabled=bool(data.get("conversation_enabled", cls.conversation_enabled)),
            diagnostics_enabled=bool(data.get("diagnostics_enabled", cls.diagnostics_enabled)),
            conversation_history_lookback=int(
                data.get("conversation_history_lookback", cls.conversation_history_lookback)
            ),
            dev_content_override=bool(data.get("dev_content_override", cls.dev_content_override)),
            operator_token=str(data.get("operator_token", cls.operator_token)),
            allowed_origins=cls._parse_string_tuple(
                data.get("allowed_origins", cls.allowed_origins)
            ),
            host_allowlist=cls._parse_string_tuple(data.get("host_allowlist", cls.host_allowlist)),
            non_loopback_allowed=bool(data.get("non_loopback_allowed", cls.non_loopback_allowed)),
        )

    @staticmethod
    def _parse_string_tuple(value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            return tuple(v.strip() for v in value.split(",") if v.strip())
        if isinstance(value, (list, tuple)):
            return tuple(str(v).strip() for v in value if str(v).strip())
        return ()


def _env_flag(name: str) -> bool | None:
    """Parse a boolean deployment override from the environment.

    Returns ``None`` when the variable is unset so the TOML value (or the
    dataclass default) is kept untouched; otherwise maps the common truthy
    spellings (``1``/``true``/``yes``/``on``, case-insensitive) to ``True`` and
    everything else to ``False``.
    """
    raw = os.environ.get(name)
    if raw is None:
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_nexus_config(path: str | os.PathLike[str] | None = None) -> NexusConfig:
    target = Path(path or "config/kaine.toml")
    raw: dict[str, Any] = {}
    if target.exists():
        raw = tomllib.loads(target.read_text())
    config = NexusConfig.from_mapping(raw.get("nexus"))
    # Deployment overrides. A container mounts the baked, always-current kaine.toml
    # and expresses its handful of deployment-specific deltas through the environment
    # rather than a hand-maintained parallel copy of the whole config (which silently
    # drifts from the source of truth). KAINE_NEXUS_HOST / KAINE_NEXUS_PORT bind all
    # interfaces inside the container — the shipped default 127.0.0.1 is unreachable
    # via the published port mapping — while the compose publish rule keeps external
    # exposure loopback-only. KAINE_NEXUS_CONVERSATION_ENABLED toggles the
    # conversation surface (the only [nexus] delta with no other env knob).
    host = os.environ.get("KAINE_NEXUS_HOST")
    port = os.environ.get("KAINE_NEXUS_PORT")
    if host or port:
        config = replace(
            config,
            host=host or config.host,
            port=int(port) if port else config.port,
        )
    conversation = _env_flag("KAINE_NEXUS_CONVERSATION_ENABLED")
    if conversation is not None:
        config = replace(config, conversation_enabled=conversation)
    token = os.environ.get("KAINE_NEXUS_TOKEN")
    if token is not None:
        config = replace(config, operator_token=token)
    return config
