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
        )


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
    return config
