# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Boot helpers for the workspace feedback extension.

These functions read the `[workspace.feedback]` table and build a
`FeedbackController` when the extension is enabled. They keep the boot layer
separate from the cycle types.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from kaine.boot.errors import ConfigurationError
from kaine.workspace.feedback import FeedbackController, WorkspaceFeedbackSettings

FEEDBACK_SECTION_KEY = "workspace_feedback"


def feedback_section(kaine_config: Mapping[str, Any]) -> dict[str, Any]:
    """The `[workspace.feedback]` table as a plain dict, {} when absent."""
    workspace = kaine_config.get("workspace") or {}
    feedback = workspace.get("feedback") or {}
    if not isinstance(feedback, Mapping):
        raise ConfigurationError("[workspace.feedback] must be a table")
    return dict(feedback)


def feedback_settings(section: Mapping[str, Any] | None) -> WorkspaceFeedbackSettings | None:
    """Parse the table; a FeedbackSettingsError becomes a ConfigurationError."""
    if section is None:
        return None
    try:
        return WorkspaceFeedbackSettings.from_section(section)
    except ValueError as exc:
        raise ConfigurationError(f"[workspace.feedback]: {exc}") from exc


def make_workspace_feedback(
    kaine_config: Mapping[str, Any],
    *,
    seed: int | None,
    clock=None,
) -> FeedbackController | None:
    """The controller for the configured arm, or None when feedback is off."""
    settings = feedback_settings(feedback_section(kaine_config))
    if settings is None:
        return None

    oscillator = kaine_config.get("oscillator") or {}
    if bool(oscillator.get("enabled", False)):
        raise ConfigurationError(
            "workspace feedback runs with the coherence layer off ([oscillator].enabled = false)"
        )

    workspace_cfg = kaine_config.get("workspace") or {}
    if str(workspace_cfg.get("arm", "competitive")).strip().lower() != "competitive":
        raise ConfigurationError(
            "workspace feedback runs on the competitive arm ([workspace].arm)"
        )

    positive_control = kaine_config.get("positive_control") or {}
    if bool(positive_control.get("enabled", False)):
        raise ConfigurationError(
            "workspace feedback runs with the positive control off ([positive_control].enabled = false)"
        )

    if settings.arm == "matched_random" and seed is None:
        raise ConfigurationError("the matched_random feedback arm needs the run seed")

    return FeedbackController(settings, seed=seed, clock=clock)
