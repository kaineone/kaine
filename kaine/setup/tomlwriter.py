# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""A minimal TOML emitter for the first-run wizard.

The wizard writes a small, well-defined slice of TOML — a handful of top-level
and nested tables holding scalar values (str, bool, int, float). Rather than
add a ``tomli-w`` runtime dependency for that, this module serializes exactly
that limited structure.

Round-trip contract: anything :func:`dumps` writes MUST parse back with
:mod:`tomllib` to the same Python values. The test suite enforces this for
strings, bools, ints, floats, and nested tables.

Supported value types: ``str``, ``bool``, ``int``, ``float``, and flat ``list``
values containing only those scalar types (rendered as inline TOML arrays). Nested
``dict`` values become sub-tables (``[parent.child]``). ``None``/other types, and lists
containing non-scalars, are rejected so a caller never silently emits something this
writer cannot round-trip.
"""
from __future__ import annotations

import copy
import tomllib
from typing import Any


# Bare keys that need no quoting per the TOML spec (A-Za-z0-9_-).
def _format_key(key: str) -> str:
    if key and all(c.isalnum() or c in "_-" for c in key):
        return key
    # Quote and escape anything else as a basic string key.
    return _format_str(key)


def _format_str(value: str) -> str:
    # Basic string: escape backslash, double-quote, and the control chars TOML
    # requires escaped. Sufficient for the identifiers/paths/emails the wizard
    # writes; round-trips through tomllib.
    out = []
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _format_scalar(value: Any) -> str:
    # bool MUST be checked before int (bool is a subclass of int).
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # repr round-trips floats exactly via tomllib's float parser.
        return repr(value)
    if isinstance(value, str):
        return _format_str(value)
    # Only flat lists of scalars are supported (e.g. [plugins].enabled = ["cl1"]).
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            if not isinstance(item, (bool, int, float, str)):
                raise TypeError(
                    f"tomlwriter cannot serialize value of type {type(item).__name__!r}: {item!r}"
                )
            items.append(_format_scalar(item))
        return "[" + ", ".join(items) + "]"
    raise TypeError(
        f"tomlwriter cannot serialize value of type {type(value).__name__!r}: {value!r}"
    )


def _emit_table(
    data: dict[str, Any],
    prefix: list[str],
    lines: list[str],
) -> None:
    """Emit a table's scalar keys, then recurse into nested-dict sub-tables."""
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in data.items() if isinstance(v, dict)}

    if prefix:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(f"[{'.'.join(_format_key(p) for p in prefix)}]")

    for key, value in scalars.items():
        lines.append(f"{_format_key(key)} = {_format_scalar(value)}")

    for key, sub in tables.items():
        _emit_table(sub, prefix + [key], lines)


def dumps(data: dict[str, Any]) -> str:
    """Serialize ``data`` to a TOML document string.

    Top-level scalar keys (rare for the wizard) are emitted first, then each
    top-level table and its nested sub-tables.
    """
    if not isinstance(data, dict):
        raise TypeError("tomlwriter.dumps expects a dict")
    lines: list[str] = []
    _emit_table(data, [], lines)
    text = "\n".join(lines).strip("\n")
    return text + "\n" if text else ""


def _set_dotted(cfg: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = cfg
    for p in parts[:-1]:
        nxt = cur.get(p)
        if nxt is None:
            nxt = {}
            cur[p] = nxt
        elif not isinstance(nxt, dict):
            # Never replace an existing value with a table: that would drop it.
            raise ValueError(f"cannot set {dotted}: {p!r} holds a non-table value")
        cur = nxt
    cur[parts[-1]] = value


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in data.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten(value, dotted))
        else:
            out[dotted] = value
    return out


def _validate_emittable(data: dict[str, Any], prefix: str = "") -> None:
    for key, value in data.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if value is None:
            raise ValueError(
                f"cannot serialize existing value at {dotted}: None is not supported"
            )
        if isinstance(value, list):
            if any(isinstance(item, (dict, list)) for item in value):
                raise ValueError(
                    f"cannot serialize existing value at {dotted}: "
                    "arrays of tables or nested arrays are not supported"
                )
            for item in value:
                if not isinstance(item, (bool, int, float, str)):
                    raise ValueError(
                        f"cannot serialize existing value at {dotted}: "
                        f"list item of type {type(item).__name__!r} is not supported"
                    )
        elif isinstance(value, dict):
            _validate_emittable(value, dotted)
        elif not isinstance(value, (bool, int, float, str)):
            raise ValueError(
                f"cannot serialize existing value at {dotted}: "
                f"type {type(value).__name__!r} is not supported"
            )


def merge_owned(existing: dict, updates: dict, owned: frozenset[str]) -> dict:
    """Return a deep copy of ``existing`` with every owned dotted key in
    ``updates`` replaced.

    Unowned keys and tables in ``existing`` are preserved untouched.  A dotted
    key in ``updates`` that is not owned raises ``ValueError``.  If the merged
    document contains a value that :func:`dumps` cannot emit, ``ValueError`` is
    raised naming the offending key so the caller can refuse to save.
    """
    if not isinstance(existing, dict) or not isinstance(updates, dict):
        raise TypeError("merge_owned expects dicts")

    merged = copy.deepcopy(existing)

    for dotted, value in _flatten(updates).items():
        if dotted not in owned:
            raise ValueError(f"refusing to write unowned config key: {dotted}")
        _set_dotted(merged, dotted, value)

    _validate_emittable(merged)

    # Defensive round-trip check: anything we are about to write must parse back.
    if tomllib.loads(dumps(merged)) != merged:
        raise ValueError("merge result does not round-trip through tomllib")

    return merged
