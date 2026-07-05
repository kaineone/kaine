# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Operator-confirmed transfer-coordination primitives.

Currently a single module: :mod:`kaine.transfer.email_request`, the
operator-confirmed request-for-storage mailer used by the welfare-gated
decommission flow (and reusable by future transfer flows). No entity data
ever passes through this package — only requests, local paths, and situation
text.
"""
from __future__ import annotations

from kaine.transfer.email_request import (
    RenderedEmail,
    SendResult,
    SmtpConfig,
    render_request_email,
    send_or_write,
)

__all__ = [
    "RenderedEmail",
    "SendResult",
    "SmtpConfig",
    "render_request_email",
    "send_or_write",
]
