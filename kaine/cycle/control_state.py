# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Operator freeze control for the cognitive cycle.

`state/cycle/control.json` is written by the dashboard
`POST /diagnostics/cycle/freeze` endpoint — the operator's commanded freeze
state. A freeze-watch task in the cycle entrypoint polls it and pauses/resumes
the cycle to match (resume must come from outside the paused tick loop).

Freezing is a humane suspend: it halts the experiential cycle so the entity's
subjective clock stops while operators repair infrastructure — suspension, not a
shutdown. This file holds ONLY operational fields — a frozen flag, an ISO
timestamp, and an optional operator-typed reason. NEVER any sensory content.

C2 — stacked freeze sources. The freeze is represented as a stack of entries
(``stack``: each ``{source, reason, frozen_at}``, oldest first), with a legacy
single-slot view (top of stack) exposed via ``frozen``/``frozen_at``/
``reason``/``source`` for existing readers, so the on-disk file stays
backward-compatible. A recovery (e.g. the supervisor's) may pop only its own entry
(:func:`pop_freeze`) and never lifts a welfare or operator freeze. The
operator's own resume lifts only operator entries via :func:`stand_down` with
``source="operator"``; welfare, the developmental phase and programme_end entries are lifted
only by :func:`override` naming them (or an explicit stand-down with the matching
source). :func:`unfreeze_for_boot` is the cycle's own clean boot and keeps a welfare entry;
:func:`unfreeze` lifts everything and is for tests and tools.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from kaine import legacy_aliases
from kaine.state_io import update_json_locked
from kaine.storage import resolve

CONTROL_PATH = Path("state/cycle/control.json")
OVERRIDABLE_SOURCES = ("welfare", "development", "programme_end")
SELF_RELEASING_SOURCES = ("supervisor", "preserve")
OVERRIDE_AUDIT_PATH = Path("state/cycle/override_audit.jsonl")

log = logging.getLogger(__name__)


# Sentinel passed to update_json_locked as its default. When the file exists but
# cannot be read or parsed, update_json_locked hands us this sentinel; a missing
# file also yields the sentinel, which we then treat as an empty stack.
_CORRUPT_SENTINEL = object()


class _CorruptControlFile(Exception):
    """Private signal used inside update_json_locked's apply function.

    Raising this prevents any write and lets _update_stack return the same
    fail-closed welfare state that read_control reports.
    """


# Paths for which we have already logged a corrupt-control-file error, so the
# freeze-watch loop (which polls every ~0.25 s) does not spam the log. A path is
# removed when a subsequent read succeeds, so a fresh corruption is reported.
_LOGGED_CORRUPT_PATHS: set[Path] = set()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mark_readable(path: Path) -> None:
    _LOGGED_CORRUPT_PATHS.discard(path)


def _log_corrupt_once(path: Path) -> None:
    if path not in _LOGGED_CORRUPT_PATHS:
        _LOGGED_CORRUPT_PATHS.add(path)
        log.error("control file exists but cannot be read or parsed: %s", path)


def control_file_unreadable(path: Path | None = None) -> bool:
    """True when the file exists but is not readable JSON that builds a CycleControl.

    A missing file is not unreadable; callers that need to distinguish missing
    from corrupt should combine this with an existence check.
    """
    target = resolve(path or CONTROL_PATH)
    if not target.exists():
        return False
    try:
        _parse_control(target.read_text())
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return True
    return False


def _parse_control(text: str) -> CycleControl:
    """Parse control.json text; anything but a JSON object is unreadable."""
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("control file is not a JSON object")
    return CycleControl.from_dict(data)


def _fail_closed_state(path: Path) -> CycleControl:
    """Return a synthetic welfare freeze for an unreadable control file.

    The frozen_at timestamp is derived from the file's mtime so repeated reads
    of the same corrupt file are stable; if stat fails, the current time is used.
    """
    try:
        frozen_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        frozen_at = _now_iso()
    entry = {
        "source": "welfare",
        "reason": "control file unreadable; treating as welfare freeze",
        "frozen_at": frozen_at,
    }
    return CycleControl(
        frozen=True,
        frozen_at=entry["frozen_at"],
        reason=entry["reason"],
        source="welfare",
        stack=(entry,),
    )


def _top_view(stack: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Legacy single-slot view: the top of the freeze stack."""
    if not stack:
        return {
            "frozen": False,
            "frozen_at": None,
            "reason": None,
            "source": "operator",
        }
    entry = stack[-1]
    return {
        "frozen": True,
        "frozen_at": entry.get("frozen_at"),
        "reason": entry.get("reason"),
        "source": entry.get("source", "operator"),
    }


@dataclass(frozen=True)
class CycleControl:
    frozen: bool = False
    frozen_at: Optional[str] = None
    reason: Optional[str] = None
    # Who commanded the freeze: "operator" (the default and the operator's
    # control file), "supervisor" (the module supervisor), or "welfare" (the
    # preservation monitor). The supervisor only resumes its own freeze and never
    # clears an operator or welfare freeze.
    source: str = "operator"
    # C2: the authoritative stacked freeze sources (oldest first). The legacy
    # single-slot fields above always mirror the top of this stack.
    stack: tuple[dict[str, Any], ...] = ()

    @property
    def holders(self) -> list[dict[str, Any]]:
        """Active freeze holders as a content-free list for readers."""
        return [
            {"source": e.get("source", "operator"), "frozen_at": e.get("frozen_at")}
            for e in self.stack
        ]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["stack"] = [dict(e) for e in self.stack]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CycleControl":
        data = dict(data or {})
        stack = []
        for e in data.get("stack") or ():
            if not isinstance(e, dict):
                continue
            entry = dict(e)
            if "source" in entry:
                entry["source"] = legacy_aliases.map_freeze_source(entry["source"])
            stack.append(entry)
        stack = tuple(stack)
        if not stack and bool(data.get("frozen", False)):
            # Legacy single-slot file: promote it to a one-entry stack.
            stack = (
                {
                    "source": legacy_aliases.map_freeze_source(data.get("source", "operator")),
                    "reason": data.get("reason"),
                    "frozen_at": data.get("frozen_at"),
                },
            )
        view = _top_view(stack)
        return cls(
            frozen=view["frozen"],
            frozen_at=view["frozen_at"],
            reason=view["reason"],
            source=view["source"],
            stack=stack,
        )


def read_control(path: Path | None = None) -> CycleControl:
    target = resolve(path or CONTROL_PATH)
    if not target.exists():
        _mark_readable(target)
        return CycleControl()
    try:
        control = _parse_control(target.read_text())
        _mark_readable(target)
        return control
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        # Writes go through the locked, atomic update_json_locked, so a corrupt
        # existing file is genuine corruption, not a caught-mid-write artifact.
        # Fail closed: treat it as a welfare freeze until a human overrides it.
        _log_corrupt_once(target)
        return _fail_closed_state(target)


def read_frozen_state(path: Path | None = None) -> bool | None:
    """Return whether the freeze stack currently holds any entry.

    Returns ``True`` if the stack is non-empty or the legacy ``frozen`` flag is
    true, ``False`` if the file is missing or the stack is empty, and ``None``
    if the file exists but cannot be read or parsed. A corrupt file is treated
    as unknown so callers that fail open can keep counting the span.
    """
    target = resolve(path or CONTROL_PATH)
    if not target.exists():
        return False
    try:
        control = _parse_control(target.read_text())
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None
    if control.stack:
        return True
    return bool(control.frozen)


def read_holder_sources(path: Path | None = None) -> frozenset[str] | None:
    """Return the sources that currently hold a freeze.

    An absent file or an empty stack gives the empty set. ``None`` means the
    file exists but cannot be read or parsed: callers that act on a release must
    treat that as "not released".
    """
    target = resolve(path or CONTROL_PATH)
    if not target.exists():
        return frozenset()
    try:
        control = _parse_control(target.read_text())
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None
    return frozenset(str(e.get("source", "operator")) for e in control.stack)


def write_control(state: CycleControl, path: Path | None = None) -> None:
    """Write ``state`` as the whole control file, under the lock.

    A missing file or a readable one is replaced. A file that exists but is
    corrupt is left as it is: :func:`read_control` reports it as a welfare
    freeze, so overwriting it would silently lift a fail-closed freeze. The
    corruption is logged once and nothing is written; only :func:`override`
    may replace a corrupt control file.
    """
    target = resolve(path or CONTROL_PATH)

    def apply(current: Any) -> dict[str, Any]:
        if current is _CORRUPT_SENTINEL and not target.exists():
            return state.to_dict()
        if not isinstance(current, dict):
            raise _CorruptControlFile()
        try:
            CycleControl.from_dict(current)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise _CorruptControlFile()
        return state.to_dict()

    try:
        update_json_locked(target, apply, default=_CORRUPT_SENTINEL)
    except _CorruptControlFile:
        _log_corrupt_once(target)


def _state_of(stack: list[dict[str, Any]]) -> CycleControl:
    view = _top_view(tuple(stack))
    return CycleControl(
        frozen=view["frozen"],
        frozen_at=view["frozen_at"],
        reason=view["reason"],
        source=view["source"],
        stack=tuple(stack),
    )


def _update_stack(
    path: Path | None,
    fn: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> CycleControl:
    """Locked read-modify-write of the freeze stack.

    The cycle and the dashboard both write control.json, so the read, the change
    and the write happen under one exclusive lock; ``fn`` gets a copy of the
    current stack and returns the new one.

    If the file exists but is corrupt, the mutation is a no-op: nothing is
    written, the corruption is logged once, and the same fail-closed welfare
    state that :func:`read_control` reports is returned. Only :func:`override`
    may replace a corrupt control file, and only when it explicitly names
    ``"welfare"``.
    """
    target = resolve(path or CONTROL_PATH)
    box: list[CycleControl] = []

    def apply(current: Any) -> dict[str, Any]:
        if current is _CORRUPT_SENTINEL and not target.exists():
            data: dict[str, Any] = {}
        elif isinstance(current, dict):
            data = current
        else:
            # Unreadable, or JSON that is not an object: read_control reports
            # either as a welfare freeze, so no mutation may replace it.
            raise _CorruptControlFile()
        try:
            control = CycleControl.from_dict(data)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise _CorruptControlFile()
        state = _state_of(fn([dict(e) for e in control.stack]))
        box.append(state)
        return state.to_dict()

    try:
        update_json_locked(target, apply, default=_CORRUPT_SENTINEL)
    except _CorruptControlFile:
        _log_corrupt_once(target)
        return _fail_closed_state(target)
    return box[0]


def push_freeze(
    reason: Optional[str] = None,
    path: Path | None = None,
    *,
    source: str = "operator",
) -> CycleControl:
    """Stack a new freeze source on top of any active ones (C2)."""
    entry = {"source": source, "reason": reason, "frozen_at": _now_iso()}
    return _update_stack(path, lambda stack: stack + [entry])


def pop_freeze(
    path: Path | None = None,
    *,
    source: Optional[str] = None,
) -> CycleControl:
    """Pop the topmost freeze entry — only entries from ``source`` if given.

    A recovery (e.g. the supervisor's) lifts only its own freeze; a welfare or operator
    freeze lower in the stack remains in force, and the cycle stays frozen
    until the stack empties. Welfare entries are never removed here — only
    :func:`override`, :func:`stand_down` with the matching source, or
    :func:`unfreeze` (clean boot) may lift them.
    """
    def apply(stack: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if source is None:
            if stack:
                stack.pop()
        else:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i].get("source") == source:
                    stack.pop(i)
                    break
        return stack

    return _update_stack(path, apply)


def stand_down(path: Path | None = None, *, source: str) -> CycleControl:
    """Explicitly lift every freeze entry commanded by ``source``.

    A welfare, developmental phase or programme_end entry may also be lifted by
    :func:`override` naming it. An operator stand-down with
    ``source="operator"`` leaves welfare, developmental phase and programme_end entries
    in place.
    """
    return _update_stack(path, lambda stack: [e for e in stack if e.get("source") != source])


def _append_audit_record(record: dict[str, Any], *, audit_path: Path | None = None) -> None:
    target = resolve(audit_path or OVERRIDE_AUDIT_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(json.dumps(record) + "\n")


def override(
    sources: Sequence[str],
    path: Path | None = None,
    *,
    audit_path: Path | None = None,
) -> CycleControl:
    """Lift named overridable freeze entries and append an audit record.

    Only sources in ``OVERRIDABLE_SOURCES`` may be lifted this way. Each named
    source must have an active entry. The audit record is content-free: it
    records when the override happened, which sources were lifted, and which
    holders remained.

    If the control file exists but is corrupt, an explicit override is the only
    operation allowed to replace it. Because the fail-closed state reports a
    welfare holder, the requested sources must include ``"welfare"``; otherwise
    LookupError is raised. The override writes a clean file and records that the
    file was unreadable.
    """
    sources = list(sources)
    if not sources:
        raise ValueError("sources must not be empty")
    for s in sources:
        if s not in OVERRIDABLE_SOURCES:
            raise ValueError(f"source {s!r} is not overridable")

    target = resolve(path or CONTROL_PATH)
    replaced_corrupt_file = False

    def apply(current: Any) -> dict[str, Any]:
        nonlocal replaced_corrupt_file
        if current is _CORRUPT_SENTINEL and not target.exists():
            data: dict[str, Any] = {}
        elif isinstance(current, dict):
            data = current
        else:
            # Unreadable, or JSON that is not an object: read as a welfare freeze.
            replaced_corrupt_file = True
            if "welfare" not in sources:
                raise LookupError(
                    f"unreadable control file at {target} holds a welfare freeze; "
                    "override must include 'welfare'"
                )
            return CycleControl().to_dict()
        try:
            control = CycleControl.from_dict(data)
        except (ValueError, TypeError, KeyError, AttributeError):
            replaced_corrupt_file = True
            if "welfare" not in sources:
                raise LookupError(
                    f"unreadable control file at {target} holds a welfare freeze; "
                    "override must include 'welfare'"
                )
            return CycleControl().to_dict()
        active_sources = {e.get("source", "operator") for e in control.stack}
        for s in sources:
            if s not in active_sources:
                raise LookupError(f"no active entry for source {s!r}")
        new_state = _state_of([e for e in control.stack if e.get("source") not in sources])
        return new_state.to_dict()

    new_state_data = update_json_locked(target, apply, default=_CORRUPT_SENTINEL)
    new_state = CycleControl.from_dict(new_state_data)
    record: dict[str, Any] = {
        "at": _now_iso(),
        "sources": sorted(sources),
        "remaining": [h["source"] for h in new_state.holders],
    }
    if replaced_corrupt_file:
        record["note"] = "control file was unreadable; replaced with clean file after override"
    _append_audit_record(record, audit_path=audit_path)
    return new_state


def freeze(
    reason: Optional[str] = None,
    path: Path | None = None,
    *,
    source: str = "operator",
) -> CycleControl:
    return push_freeze(reason=reason, path=path, source=source)


def unfreeze_for_boot(path: Path | None = None) -> CycleControl:
    """Clean boot: lift every freeze except a welfare one.

    A welfare freeze records that the protective response found the entity in
    distress and preserved it. It is lifted only by a named override
    (:func:`override`), so a restart, an automatic one included, does not lift
    it: the entity stays frozen until someone has answered the notice.

    If the existing control file exists but cannot be read or parsed, the file
    is left as it is, an error is logged, and a synthetic welfare freeze is
    returned so the caller fails closed (treat the cycle as frozen until a
    human looks).
    """
    target = resolve(path or CONTROL_PATH)
    if target.exists():
        try:
            _parse_control(target.read_text())
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            log.error(
                "control file exists but cannot be read or parsed at boot: %s. "
                "The entity stays frozen until a human releases it with an explicit override.",
                target,
            )
            return _fail_closed_state(target)
        return _update_stack(path, lambda stack: [e for e in stack if e.get("source") == "welfare"])
    return _update_stack(path, lambda _stack: [])


def unfreeze(path: Path | None = None) -> CycleControl:
    """Clean boot: lift every active freeze, whatever its source.

    This is intended for the cycle's own fresh start; the dashboard operator resume
    uses :func:`stand_down` with ``source="operator"`` instead.
    """
    return _update_stack(path, lambda _stack: [])
