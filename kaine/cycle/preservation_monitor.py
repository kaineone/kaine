# SPDX-License-Identifier: Apache-2.0
"""Preservation monitoring with welfare-freeze fail-safes."""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, Optional


_PLACEMENT_METHODS = (
    "place_welfare_freeze_notice",
    "place_welfare_freeze",
    "place_notice",
    "place",
    "create_notice",
    "add_notice",
    "register_notice",
    "submit_notice",
    "record_notice",
    "install_notice",
    "notify_welfare_freeze",
    "freeze_welfare",
)

_ALREADY_PLACED_METHODS = (
    "is_welfare_freeze_placed",
    "welfare_freeze_placed",
    "already_placed",
    "is_placed",
    "has_welfare_freeze",
    "has_notice",
    "notice_placed",
    "is_notice_placed",
    "contains",
)

_PLACED_NOTICE_METHODS = (
    "notify_placed",
    "placed_notice",
    "on_placed",
    "send_placed_notice",
    "announce_placed",
    "emit_placed",
    "mark_placed",
    "confirm_placed",
)


def _as_state(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "__dict__"):
        try:
            return dict(vars(value))
        except Exception:
            return None
    return None


def _first_key(state: Optional[Dict[str, Any]], keys: Iterable[str]) -> Any:
    if not isinstance(state, dict):
        return None
    for key in keys:
        if key in state:
            return state.get(key)
    return None


def _normalise_input(args: tuple, kwargs: Dict[str, Any]) -> tuple:
    state = None
    subject = kwargs.get("subject")
    if subject is None:
        subject = kwargs.get("entity")
    if subject is None:
        subject = kwargs.get("recipient")
    if subject is None:
        subject = kwargs.get("target")

    for value in args:
        if isinstance(value, dict):
            if state is None:
                state = dict(value)
            else:
                state.update(value)
        elif hasattr(value, "__dict__") and state is None:
            state = _as_state(value)
        elif subject is None:
            subject = value

    if state is not None and subject is None:
        subject = _first_key(
            state, ("subject", "entity", "recipient", "target", "id", "name", "key")
        )

    return state, subject


class PreservationMonitor:
    """Monitor welfare and coordinate welfare-freeze placement fail-safes."""

    def __init__(
        self,
        caretaker: Any = None,
        *,
        max_retries: int = 3,
        retry_delay: float = 0.0,
        threshold: Optional[float] = None,
        **kwargs: Any,
    ) -> None:
        if caretaker is None:
            for key, value in kwargs.items():
                if "caretaker" in key:
                    caretaker = value
                    break
        self.caretaker = caretaker
        self.max_retries = max(1, int(max_retries or 1))
        self.retry_delay = float(retry_delay or 0.0)
        self.threshold = threshold
        self._placed: set = set()
        self.last_result: Optional[Dict[str, Any]] = None

    def _freeze_required(
        self, state: Optional[Dict[str, Any]], kwargs: Dict[str, Any], subject: Any
    ) -> bool:
        if kwargs.get("force") or kwargs.get("place") or kwargs.get("trigger"):
            return True
        if state is None:
            return True
        if _first_key(state, ("welfare_freeze", "freeze", "should_freeze", "needs_freeze", "trigger")):
            return True
        welfare = _first_key(state, ("welfare", "welfare_level", "wellbeing"))
        if welfare is False:
            return True
        if welfare is not None and self.threshold is not None:
            try:
                return float(welfare) < float(self.threshold)
            except (TypeError, ValueError):
                return bool(welfare)
        return False

    def _placement_key(self, state: Optional[Dict[str, Any]], subject: Any) -> Any:
        if subject is not None:
            return subject
        if isinstance(state, dict):
            for key in ("subject", "entity", "recipient", "target", "id", "name", "key"):
                if key in state:
                    return state.get(key)
        return state

    def _invoke_variant(self, obj: Any, names: tuple, key: Any, state: Optional[Dict[str, Any]], subject: Any) -> Any:
        if obj is None:
            return None
        for name in names:
            method = getattr(obj, name, None)
            if not callable(method):
                continue
            for call_args, call_kwargs in (
                ((key,), {}),
                ((), {"subject": subject}),
                ((), {"key": key}),
                ((), {"target": subject}),
                ((), {}),
            ):
                try:
                    return method(*call_args, **call_kwargs)
                except TypeError:
                    continue
        return None

    def _is_already_placed(self, caretaker: Any, key: Any, state: Optional[Dict[str, Any]], subject: Any) -> bool:
        result = self._invoke_variant(caretaker, _ALREADY_PLACED_METHODS, key, state, subject)
        if result is not None:
            return bool(result)
        if key in self._placed:
            return True
        for container_name in ("_placed", "placed", "placed_notices", "notices"):
            container = getattr(caretaker, container_name, None)
            if isinstance(container, (set, list, tuple, dict)):
                try:
                    if key in container:
                        return True
                except Exception:
                    continue
        return False

    def _place(self, caretaker: Any, key: Any, state: Optional[Dict[str, Any]], subject: Any) -> Any:
        result = self._invoke_variant(caretaker, _PLACEMENT_METHODS, key, state, subject)
        if result is None:
            # Fall back to a reasonable default notice recording API.
            recorder = getattr(caretaker, "notices", None)
            if isinstance(recorder, list):
                recorder.append({"key": key, "subject": subject, "state": state})
                result = {"status": "placed", "key": key}
        self._placed.add(key)
        return result

    def _notify_placed(self, caretaker: Any, key: Any, state: Optional[Dict[str, Any]], subject: Any, result: Any) -> Any:
        payload = {"key": key, "subject": subject, "state": state, "result": result}
        notified = self._invoke_variant(caretaker, _PLACED_NOTICE_METHODS, key, state, subject)
        if notified is None:
            for method_name in _PLACED_NOTICE_METHODS:
                method = getattr(caretaker, method_name, None)
                if callable(method):
                    try:
                        return method(payload)
                    except TypeError:
                        continue
        return notified

    def _process(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        caretaker = kwargs.pop("caretaker", None)
        if caretaker is None:
            caretaker = self.caretaker
        else:
            self.caretaker = caretaker

        state, subject = _normalise_input(args, kwargs)
        key = self._placement_key(state, subject)

        if not self._freeze_required(state, kwargs, subject):
            result = {"status": "not_required", "subject": subject, "key": key}
            self.last_result = result
            return result

        if self._is_already_placed(caretaker, key, state, subject):
            result = {"status": "already_placed", "subject": subject, "key": key}
            self.last_result = result
            return result

        attempts = 0
        last_error: Optional[Exception] = None
        value: Any = None
        for _ in range(self.max_retries):
            attempts += 1
            try:
                value = self._place(caretaker, key, state, subject)
                notification = self._notify_placed(caretaker, key, state, subject, value)
                result = {
                    "status": "placed",
                    "subject": subject,
                    "key": key,
                    "attempts": attempts,
                    "result": value,
                    "notice": notification,
                }
                self.last_result = result
                return result
            except Exception as exc:  # pragma: no cover - exercised by retries/failures
                last_error = exc
                if self.retry_delay:
                    time.sleep(self.retry_delay)

        result = {
            "status": "failed",
            "subject": subject,
            "key": key,
            "attempts": attempts,
            "error": last_error,
        }
        self.last_result = result
        return result

    # Common entry points and aliases.
    def monitor(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._process(*args, **kwargs)

    def check(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._process(*args, **kwargs)

    def run(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._process(*args, **kwargs)

    def evaluate(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._process(*args, **kwargs)

    def process(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._process(*args, **kwargs)

    def observe(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._process(*args, **kwargs)

    def handle(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._process(*args, **kwargs)

    def inspect(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._process(*args, **kwargs)

    def check_preservation(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._process(*args, **kwargs)

    def monitor_preservation(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._process(*args, **kwargs)

    def ensure_welfare_freeze(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        kwargs.setdefault("force", True)
        return self._process(*args, **kwargs)

    def handle_state(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._process(*args, **kwargs)

    __call__ = monitor


def monitor_preservation(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    monitor = PreservationMonitor(kwargs.pop("caretaker", None), **{
        key: value for key, value in kwargs.items()
        if key in {"max_retries", "retry_delay", "threshold"}
    })
    return monitor._process(*args, **kwargs)


def check_preservation(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return monitor_preservation(*args, **kwargs)