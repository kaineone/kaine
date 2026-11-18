"""Interactive configuration writer for KAINE's operator overlay."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib  # type: ignore[no-redef]

from kaine.config import OPERATOR_CONFIG_PATH, SHIPPED_CONFIG_PATH, list_all_defaults


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


def _dump_toml(value: Any, indent: int = 0) -> str:
    pad = "  " * indent
    lines: list[str] = []
    if isinstance(value, dict):
        # scalar leaves first
        for key in sorted(value):
            if not isinstance(value[key], dict):
                lines.append(f"{pad}{key} = {_toml_scalar(value[key])}")
        for key in sorted(value):
            if isinstance(value[key], dict):
                lines.append(f"\n{pad}[{key}]")
                lines.append(_dump_toml(value[key], indent))
    return "\n".join(lines)


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_scalar(v) for v in value) + "]"
    return '""'


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
    args = argv if argv is not None else sys.argv[1:]
    out_path = OPERATOR_CONFIG_PATH
    if args:
        out_path = args[0]

    shipped = list_all_defaults()
    current = _load_operator(out_path)
    merged: dict[str, Any] = dict(current)

    print("KAINE operator configuration")
    print("Press Enter to keep the shown current value.\n")

    for dotted, default_value in _flatten(shipped):
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