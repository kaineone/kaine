# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Configuration errors and the unknown-key guards every factory uses."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass
from kaine.config import require_known_keys


class ConfigurationError(ValueError):
    """Raised at startup when a module's config is invalid (e.g. a Nous
    complexity envelope whose worst-case step count exceeds the threshold)."""


class VoiceAlignmentConfigError(ConfigurationError):
    """Raised when voice_alignment is enabled and operator-approved but the
    [training] extras (unsloth, trl, peft, datasets) are not installed.

    This combination is a configuration error: silently falling back to
    FakeTrainer would produce training cycles that appear to succeed while
    writing no real adapter — a pretend process.  The operator must either
    install the extras or disable voice_alignment.
    """


def _require_keys(section: dict[str, Any], allowed: set[str]) -> None:
    # Delegates to the shared boundary-neutral guard; an empty table name
    # preserves boot's bare "unknown config keys: ..." message exactly.
    require_known_keys(section, allowed)


def _pop(section: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    _require_keys(section, allowed)
    return {k: section[k] for k in section if k in allowed}
