# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class NexusConfig:
    host: str = "127.0.0.1"
    port: int = 8088
    conversation_enabled: bool = True
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


def load_nexus_config(path: str | os.PathLike[str] | None = None) -> NexusConfig:
    target = Path(path or "config/kaine.toml")
    if not target.exists():
        return NexusConfig()
    raw = tomllib.loads(target.read_text())
    return NexusConfig.from_mapping(raw.get("nexus"))
