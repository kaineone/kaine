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

Supported value types: ``str``, ``bool``, ``int``, ``float``. Nested ``dict``
values become sub-tables (``[parent.child]``). Lists/None/other types are
rejected so a caller never silently emits something this writer cannot
round-trip.
"""
from __future__ import annotations

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
