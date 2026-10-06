# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Launch-token and server-side session store for the setup server."""
from __future__ import annotations

import hmac
import secrets
import time
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class LaunchSessionStore:
    """Single-use, expiring launch tokens and opaque server-side sessions."""

    ttl_seconds: float = 120.0
    now: Callable[[], float] = field(default_factory=lambda: time.time)

    def __post_init__(self) -> None:
        self._tokens: dict[str, tuple[float, bool]] = {}
        self.sessions: dict[str, dict] = {}

    def issue(self) -> str:
        """Create a new launch token and return it."""
        token = secrets.token_urlsafe(32)
        self._tokens[token] = (self.now(), False)
        return token

    def exchange(self, token: str) -> str | None:
        """Validate ``token`` and return a fresh session id, or ``None``."""
        if not isinstance(token, str) or not token.isascii():
            return None
        for stored, (issued, used) in self._tokens.items():
            if hmac.compare_digest(stored, token):
                if used or (self.now() - issued) > self.ttl_seconds:
                    return None
                self._tokens[stored] = (issued, True)
                sid = secrets.token_urlsafe(32)
                self.sessions[sid] = {
                    "created": self.now(),
                    "config": {},
                    "extra": {},
                    "step_index": 0,
                    "acknowledged": False,
                }
                return sid
        return None

    def drop(self, sid: str) -> None:
        """Discard a session (no-op if it does not exist)."""
        self.sessions.pop(sid, None)
