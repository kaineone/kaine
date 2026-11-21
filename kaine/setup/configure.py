# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Interactive configuration writer for KAINE's operator overlay."""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib  # type: ignore[no-redef]

from kaine.config import OPERATOR_CONFIG_PATH, list_all_defaults, tier_for_key


def _load_operator(path: str | os.PathLike[str]) -> dict[str, Any]:
    try:
        if not Path(path).exists():
            return {}
        with Path(path).open("rb") as fh:
            return tomllib.load(fh) or {}
    except Exception:
        return {}


def _flatten(obj: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            out.extend(_flatten(value, f"{prefix}.{key}" if prefix else key))
    else:
        out.append((prefix, obj))
    return out


def _set_path(root: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cursor = root
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value


def _toml_key(key: str) -> str:
    """A bare key when TOML allows one, else a quoted key."""
    if key and all(c.isascii() and (c.isalnum() or c in "_-") for c in key):
        return key
    return json.dumps(key, ensure_ascii=False)


def _dump_toml(value: dict[str, Any], _path: tuple[str, ...] = ()) -> str:
    """Serialize a nested mapping to TOML that parses back to the same mapping.

    Tables are written with their full dotted header (``[security.state_encryption]``),
    so a nested table never lands at the top level.
    """
    lines: list[str] = []
    scalars = [k for k in sorted(value) if not isinstance(value[k], dict)]
    tables = [k for k in sorted(value) if isinstance(value[k], dict)]
    for key in scalars:
        lines.append(f"{_toml_key(str(key))} = {_toml_scalar(value[key])}")
    for key in tables:
        path = (*_path, str(key))
        if lines:
            lines.append("")
        lines.append("[" + ".".join(_toml_key(p) for p in path) + "]")
        body = _dump_toml(value[key], path)
        if body:
            lines.append(body)
    return "\n".join(lines)


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        # JSON string escapes are valid TOML basic-string escapes.
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return repr(value)
    if isinstance(value, list):
        if any(isinstance(v, dict) for v in value):
            raise ValueError("arrays of tables are not supported by this writer")
        return "[" + ", ".join(_toml_scalar(v) for v in value) + "]"
    raise ValueError(f"cannot write a {type(value).__name__} value to TOML")


def _prompt(label: str, current: Any) -> Any:
    response = input(f"{label} [current={current!r}] (enter to keep): ").strip()
    if not response:
        return current
    low = response.lower()
    if low in {"true", "false"}:
        return low == "true"
    try:
        return int(response)
    except ValueError:
        pass
    try:
        return float(response)
    except ValueError:
        pass
    return response


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    out_path = OPERATOR_CONFIG_PATH
    full = False
    filtered: list[str] = []
    for arg in args:
        if arg == "--full":
            full = True
        else:
            filtered.append(arg)
    args = filtered
    if args:
        out_path = args[0]

    shipped = list_all_defaults()
    current = _load_operator(out_path)
    merged: dict[str, Any] = dict(current)

    covered_tiers = {"basic", "standard", "advanced"} if full else {"basic"}

    print("KAINE operator configuration")
    print("Press Enter to keep the shown current value.\n")

    for dotted, default_value in _flatten(shipped):
        if tier_for_key(dotted) not in covered_tiers:
            continue
        current_value = current
        for part in dotted.split("."):
            current_value = current_value.get(part) if isinstance(current_value, dict) else None
        if current_value is None:
            current_value = default_value
        new_value = _prompt(dotted, current_value)
        _set_path(merged, dotted, new_value)

    serialized = _dump_toml(merged).strip() + "\n"
    Path(out_path).write_text(serialized, encoding="utf-8")
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
