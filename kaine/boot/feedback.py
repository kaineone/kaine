# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Boot helpers for the workspace feedback extension and content level.

These functions read the `[workspace.feedback]` and `[workspace.content]`
tables and build a `FeedbackController` (optionally holding a
`ContentLevel`) when the extensions are enabled. They keep the boot
layer separate from the cycle types.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from kaine.boot.errors import ConfigurationError
from kaine.workspace.content import ContentLevel
from kaine.workspace.feedback import FeedbackController, WorkspaceFeedbackSettings

FEEDBACK_SECTION_KEY = "workspace_feedback"
DEFAULT_PROCESSOR_DIMS: dict[str, int] = {
    "vision": 768,
    "audition": 64,
    "interoception": 8,
}


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


def content_section(kaine_config: Mapping[str, Any]) -> dict[str, Any]:
    """The `[workspace.content]` table as a plain dict, {} when absent."""
    workspace = kaine_config.get("workspace") or {}
    content = workspace.get("content") or {}
    if not isinstance(content, Mapping):
        raise ConfigurationError("[workspace.content] must be a table")
    return dict(content)


def make_content_level(kaine_config: Mapping[str, Any]) -> ContentLevel | None:
    """Build a ContentLevel from [workspace.content], or None when disabled."""
    section = content_section(kaine_config)
    if not section.get("enabled", False):
        return None

    code_dim = int(section.get("code_dim", 32))
    encoder_lr = float(section.get("encoder_lr", 1e-3))
    decoder_lr = float(section.get("decoder_lr", 1e-3))

    raw_dims = section.get("processor_dims")
    if raw_dims is not None:
        if not isinstance(raw_dims, Mapping):
            raise ConfigurationError(
                "[workspace.content].processor_dims must be a table"
            )
        processor_dims = {str(k): int(v) for k, v in raw_dims.items()}
    else:
        processor_dims = dict(DEFAULT_PROCESSOR_DIMS)

    return ContentLevel(
        processor_dims,
        code_dim=code_dim,
        encoder_lr=encoder_lr,
        decoder_lr=decoder_lr,
    )


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

    content = make_content_level(kaine_config)

    return FeedbackController(settings, content=content, seed=seed, clock=clock)
