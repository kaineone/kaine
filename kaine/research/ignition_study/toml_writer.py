# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tiny TOML writer used by the ignition-study overlay generator.

The implementation only supports the scalar and structural types the runner
needs: bool, int, finite float, str, nested dicts and lists of scalars.  Every
output string is verified by ``tomllib.loads`` before it is returned.
"""
from __future__ import annotations

import math
import re
import tomllib
from typing import Any

_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _escape_string(value: str) -> str:
    out = ['"']
    for ch in value:
        o = ord(ch)
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
        elif o < 0x20 or o == 0x7F:
            out.append(f"\\u{o:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _format_key(key: Any, key_path: list[str]) -> str:
    if not isinstance(key, str):
        raise TypeError(
            f"Unsupported key type at {'.'.join(key_path)}: {type(key).__name__}"
        )
    if _BARE_KEY.match(key):
        return key
    return _escape_string(key)


def _format_scalar(value: Any, key_path: list[str]) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError(
                f"Unsupported non-finite float at {'.'.join(key_path)}"
            )
        return repr(value)
    if isinstance(value, str):
        return _escape_string(value)
    raise TypeError(
        f"Unsupported type at {'.'.join(key_path)}: {type(value).__name__}"
    )


def _format_value(value: Any, key_path: list[str]) -> str:
    if isinstance(value, list):
        if not value:
            return "[]"
        parts = []
        for i, item in enumerate(value):
            parts.append(_format_scalar(item, key_path + [str(i)]))
        return "[" + ", ".join(parts) + "]"
    return _format_scalar(value, key_path)


def dumps(data: dict[str, Any]) -> str:
    """Serialize ``data`` to TOML and verify it with ``tomllib.loads``."""
    if not isinstance(data, dict):
        raise TypeError("dumps() expects a dict at the root")

    lines: list[str] = []

    def walk(table: dict[str, Any], path: list[str]) -> None:
        scalars: list[tuple[str, Any]] = []
        tables: list[tuple[str, dict[str, Any]]] = []
        for k, v in table.items():
            if isinstance(v, dict):
                tables.append((k, v))
            else:
                scalars.append((k, v))

        for k, v in scalars:
            lines.append(
                f"{_format_key(k, path)} = {_format_value(v, path + [k])}"
            )

        for k, v in tables:
            header = ".".join(
                _format_key(part, path) for part in path + [k]
            )
            lines.append(f"[{header}]")
            walk(v, path + [k])

    walk(data, [])
    out = "\n".join(lines)

    try:
        parsed = tomllib.loads(out)
    except Exception as exc:
        raise ValueError(f"TOML writer produced invalid TOML: {exc}") from exc

    if parsed != data:
        raise ValueError("TOML writer round-trip mismatch")

    return out
