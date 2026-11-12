# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from kaine.config import ConfigShapeError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResidencyConfig:
    enabled: bool = False
    reserve_bytes: int | None = None
    ttl_seconds: int = 120
    ttl_overrides: dict[str, int] = field(default_factory=dict)
    pin: str = "language"
    prewarm: tuple[str, ...] = ()
    llm_proxy: str = "none"
    interactive_queue_max: int = 16
    background_queue_max: int = 64
    perception_queue_max: int = 32
    perception_queue_max_age_s: float = 10.0


def from_config(config: dict[str, Any]) -> ResidencyConfig:
    """Build ResidencyConfig from the merged KAINE configuration dict.

    Reads config.get("residency") or {}. Missing keys use defaults.
    Raises ConfigShapeError on invalid types.
    """
    section = config.get("residency") or {}
    if not isinstance(section, dict):
        raise ConfigShapeError("residency must be a mapping")

    enabled = section.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigShapeError("enabled must be bool")

    reserve_bytes = section.get("reserve_bytes", None)
    if reserve_bytes is not None:
        if not isinstance(reserve_bytes, int):
            raise ConfigShapeError("reserve_bytes must be int")
        if reserve_bytes <= 0:
            raise ConfigShapeError("reserve_bytes must be > 0")

    ttl_seconds = section.get("ttl_seconds", 120)
    if not isinstance(ttl_seconds, int):
        raise ConfigShapeError("ttl_seconds must be int")
    if ttl_seconds < 0:
        raise ConfigShapeError("ttl_seconds must be >= 0")

    ttl_overrides = section.get("ttl_overrides", {})
    if not isinstance(ttl_overrides, dict):
        raise ConfigShapeError("ttl_overrides must be dict")
    for value in ttl_overrides.values():
        if not isinstance(value, int):
            raise ConfigShapeError("ttl_overrides values must be int")
        if value < 0:
            raise ConfigShapeError("ttl_overrides values must be >= 0")

    pin = section.get("pin", "language")
    if not isinstance(pin, str):
        raise ConfigShapeError("pin must be str")

    prewarm = section.get("prewarm", [])
    if not isinstance(prewarm, list) or not all(isinstance(item, str) for item in prewarm):
        raise ConfigShapeError("prewarm must be list of str")

    llm_proxy = section.get("llm_proxy", "none")
    if not isinstance(llm_proxy, str):
        raise ConfigShapeError("llm_proxy must be str")
    if llm_proxy not in ("none", "llama-swap"):
        raise ConfigShapeError("llm_proxy must be 'none' or 'llama-swap'")

    interactive_queue_max = section.get("interactive_queue_max", 16)
    if not isinstance(interactive_queue_max, int):
        raise ConfigShapeError("interactive_queue_max must be int")
    if interactive_queue_max <= 0:
        raise ConfigShapeError("interactive_queue_max must be > 0")

    background_queue_max = section.get("background_queue_max", 64)
    if not isinstance(background_queue_max, int):
        raise ConfigShapeError("background_queue_max must be int")
    if background_queue_max <= 0:
        raise ConfigShapeError("background_queue_max must be > 0")

    perception_queue_max = section.get("perception_queue_max", 32)
    if not isinstance(perception_queue_max, int):
        raise ConfigShapeError("perception_queue_max must be int")
    if perception_queue_max <= 0:
        raise ConfigShapeError("perception_queue_max must be > 0")

    perception_queue_max_age_s = section.get("perception_queue_max_age_s", 10.0)
    if not isinstance(perception_queue_max_age_s, (int, float)):
        raise ConfigShapeError("perception_queue_max_age_s must be a number")
    if perception_queue_max_age_s <= 0:
        raise ConfigShapeError("perception_queue_max_age_s must be > 0")

    return ResidencyConfig(
        enabled=enabled,
        reserve_bytes=reserve_bytes,
        ttl_seconds=ttl_seconds,
        ttl_overrides=dict(ttl_overrides),
        pin=pin,
        prewarm=tuple(prewarm),
        llm_proxy=llm_proxy,
        interactive_queue_max=interactive_queue_max,
        background_queue_max=background_queue_max,
        perception_queue_max=perception_queue_max,
        perception_queue_max_age_s=float(perception_queue_max_age_s),
    )
