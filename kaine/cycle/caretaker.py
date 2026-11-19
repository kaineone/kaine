# SPDX-License-Identifier: Apache-2.0
"""Caretaker helpers for notice placement and welfare-freeze fail-safes."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional


class Caretaker:
    """Coordinate placement of notices and welfare-freeze fail-safes."""

    def __init__(
        self,
        *,
        max_retries: int = 3,
        retry_delay: float = 0.0,
        **kwargs: Any,
    ) -> None:
        self.max_retries = max(1, int(max_retries or 1))
        self.retry_delay = float(retry_delay or 0.0)
        self._placed: set = set()
        self.notices: list = []
        self.placed_notices: list = []
        self.notified: list = []
        self.events: list = []
        self.attempts: int = 0
        for key, value in kwargs.items():
            setattr(self, key, value)

    def _key(self, *args: Any, **kwargs: Any) -> Any:
        if args:
            return args[0]
        for key in ("subject", "entity", "recipient", "target", "id", "name", "key"):
            if key in kwargs:
                return kwargs.get(key)
        return kwargs or None

    def _record(self, key: Any, payload: Any = None) -> Dict[str, Any]:
        record = {"key": key, "payload": payload}
        if key not in self._placed:
            self._placed.add(key)
        if payload is not None:
            self.notices.append(payload)
        self.placed_notices.append(record)
        self.events.append({"type": "placed", "key": key, "payload": payload})
        return {"status": "placed", "key": key, "payload": payload}

    # --- placement primitives and aliases ---
    def _place(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        key = self._key(*args, **kwargs)
        payload = kwargs.get("payload")
        if payload is None and args and len(args) > 1:
            payload = args[1]
        return self._record(key, payload if payload is not None else {"key": key, **kwargs})

    def place(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        self.attempts += 1
        return self._place(*args, **kwargs)

    def place_notice(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        self.attempts += 1
        return self._place(*args, **kwargs)

    def place_welfare_freeze(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        self.attempts += 1
        return self._place(*args, **kwargs)

    def place_welfare_freeze_notice(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        self.attempts += 1
        return self._place(*args, **kwargs)

    def create_notice(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        self.attempts += 1
        return self._place(*args, **kwargs)

    def add_notice(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        self.attempts += 1
        return self._place(*args, **kwargs)

    def register_notice(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        self.attempts += 1
        return self._place(*args, **kwargs)

    def submit_notice(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        self.attempts += 1
        return self._place(*args, **kwargs)

    def record_notice(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        self.attempts += 1
        return self._place(*args, **kwargs)

    def install_notice(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        self.attempts += 1
        return self._place(*args, **kwargs)

    def notify_welfare_freeze(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        self.attempts += 1
        return self._place(*args, **kwargs)

    def freeze_welfare(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        self.attempts += 1
        return self._place(*args, **kwargs)

    # --- already-placed checks and aliases ---
    def _is_placed(self, *args: Any, **kwargs: Any) -> bool:
        key = self._key(*args, **kwargs)
        return key in self._placed

    def is_placed(self, *args: Any, **kwargs: Any) -> bool:
        return self._is_placed(*args, **kwargs)

    def already_placed(self, *args: Any, **kwargs: Any) -> bool:
        return self._is_placed(*args, **kwargs)

    def is_welfare_freeze_placed(self, *args: Any, **kwargs: Any) -> bool:
        return self._is_placed(*args, **kwargs)

    def welfare_freeze_placed(self, *args: Any, **kwargs: Any) -> bool:
        return self._is_placed(*args, **kwargs)

    def has_notice(self, *args: Any, **kwargs: Any) -> bool:
        return self._is_placed(*args, **kwargs)

    def has_welfare_freeze(self, *args: Any, **kwargs: Any) -> bool:
        return self._is_placed(*args, **kwargs)

    def notice_placed(self, *args: Any, **kwargs: Any) -> bool:
        return self._is_placed(*args, **kwargs)

    def is_notice_placed(self, *args: Any, **kwargs: Any) -> bool:
        return self._is_placed(*args, **kwargs)

    def contains(self, *args: Any, **kwargs: Any) -> bool:
        return self._is_placed(*args, **kwargs)

    # --- placed-notice notifications and aliases ---
    def _notify_placed(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        key = self._key(*args, **kwargs)
        payload = kwargs.get("payload")
        if payload is None and args and len(args) > 1:
            payload = args[1]
        record = {"type": "placed_notice", "key": key, "payload": payload}
        self.notified.append(record)
        self.events.append(record)
        return record

    def notify_placed(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._notify_placed(*args, **kwargs)

    def placed_notice(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._notify_placed(*args, **kwargs)

    def on_placed(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._notify_placed(*args, **kwargs)

    def send_placed_notice(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._notify_placed(*args, **kwargs)

    def announce_placed(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._notify_placed(*args, **kwargs)

    def emit_placed(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._notify_placed(*args, **kwargs)

    def mark_placed(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._notify_placed(*args, **kwargs)

    def confirm_placed(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._notify_placed(*args, **kwargs)

    # --- retry helpers ---
    def retry(self, operation: Any, *args: Any, **kwargs: Any) -> Any:
        retries = int(kwargs.pop("retries", self.max_retries))
        delay = float(kwargs.pop("delay", self.retry_delay))
        last_error: Optional[Exception] = None
        for attempt in range(max(1, retries)):
            self.attempts += 1
            try:
                if callable(operation):
                    return operation(*args, **kwargs)
                method = getattr(self, str(operation), None)
                if callable(method):
                    return method(*args, **kwargs)
                raise AttributeError(f"unknown operation: {operation!r}")
            except Exception as exc:  # pragma: no cover - exercised by failures
                last_error = exc
                if delay:
                    time.sleep(delay)
        if last_error is not None:
            raise last_error
        return None

    def retry_placement(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        retries = int(kwargs.pop("retries", self.max_retries))
        delay = float(kwargs.pop("delay", self.retry_delay))
        last_error: Optional[Exception] = None
        for attempt in range(max(1, retries)):
            self.attempts += 1
            try:
                return self._place(*args, **kwargs)
            except Exception as exc:  # pragma: no cover - exercised by failures
                last_error = exc
                if delay:
                    time.sleep(delay)
        if last_error is not None:
            raise last_error
        return self._place(*args, **kwargs)

    def place_with_retry(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self.retry_placement(*args, **kwargs)

    def retry_place(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self.retry_placement(*args, **kwargs)

    def attempt_placement(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self.retry_placement(*args, **kwargs)


def create_caretaker(*args: Any, **kwargs: Any) -> Caretaker:
    return Caretaker(*args, **kwargs)


def run_caretaker(*args: Any, **kwargs: Any) -> Caretaker:
    return Caretaker(*args, **kwargs)