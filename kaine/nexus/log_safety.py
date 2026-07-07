# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Neutralize caller-supplied text before it reaches a log line.

Nexus HTTP routers log operator-supplied fields (e.g. a freeze reason). A raw
value may embed CR/LF or other control characters and forge or split log
records (log injection, CWE-117). :func:`sanitize_log_value` collapses those to
spaces so an untrusted value can only ever occupy the single line the caller
intended.
"""
from __future__ import annotations

__all__ = ["sanitize_log_value"]


def sanitize_log_value(value: object) -> str:
    """Return ``value`` as a single-line, control-character-free string.

    Line breaks are removed first (the log-forging vector); any remaining
    non-printable characters (tabs, other C0/C1 controls) are then replaced
    with a space. Printable content — including spaces — is preserved so the
    log stays readable.
    """
    text = str(value).replace("\r", " ").replace("\n", " ")
    return "".join(ch if ch.isprintable() else " " for ch in text)
