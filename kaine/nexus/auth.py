# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Operator authentication dependency for Nexus.

A single bearer-token scheme protects every state-changing endpoint and every
privileged read surface. The token is configured in ``NexusConfig.operator_token``
(populated from ``KAINE_NEXUS_TOKEN`` or ``config/secrets.toml``) and is never
logged.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, Request, status

from kaine.nexus.config import NexusConfig

log = logging.getLogger(__name__)

_AUTH_HEADER_PREFIX = "Bearer "


class NexusAuthError(HTTPException):
    """Raised when a request lacks a valid operator token."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="operator authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _constant_time_equal(a: str, b: str) -> bool:
    """Timing-safe string comparison."""
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= ord(x) ^ ord(y)
    return result == 0


def require_operator_token(request: Request) -> None:
    """FastAPI dependency: validate ``Authorization: Bearer <token>``.

    Returns 401 when the token is missing or mismatched. The configured token
    is read from ``request.app.state.config`` (a ``NexusConfig`` installed by
    ``create_app``).
    """
    config: Optional[NexusConfig] = getattr(getattr(request, "app", None), "state", None)
    if config is not None:
        config = getattr(config, "config", None)
    if not isinstance(config, NexusConfig):
        log.warning("nexus auth: missing NexusConfig in app.state")
        raise NexusAuthError()

    expected = config.operator_token
    if not expected:
        # No token configured: every state-changing request is rejected. The
        # operator must explicitly set a token; this is fail-closed.
        log.warning("nexus auth: request rejected because operator_token is not configured")
        raise NexusAuthError()

    auth = request.headers.get("Authorization", "")
    if not auth.startswith(_AUTH_HEADER_PREFIX):
        raise NexusAuthError()

    presented = auth[len(_AUTH_HEADER_PREFIX) :]
    if not _constant_time_equal(presented, expected):
        log.warning("nexus auth: invalid operator token presented")
        raise NexusAuthError()
