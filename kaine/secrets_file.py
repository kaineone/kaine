# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Section-aware writer for KAINE local secret files."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

SECRET_VALUE_RE = re.compile(r"[A-Za-z0-9_.~+/=-]+")

_ENV_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TOML_TABLE_RE = re.compile(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*")
_TOML_FIELD_RE = re.compile(r"[A-Za-z0-9_-]+")


def validate_value(value: str) -> None:
    """Raise ValueError unless the value is in the allowed secret charset.

    The error message never contains the value.
    """
    if not SECRET_VALUE_RE.fullmatch(value):
        raise ValueError("secret value contains disallowed characters")


def _validate_env_key(key: str) -> None:
    if not _ENV_KEY_RE.fullmatch(key):
        raise ValueError("invalid env key name")


def _validate_toml_table(table: str) -> None:
    if not _TOML_TABLE_RE.fullmatch(table):
        raise ValueError("invalid TOML table name")


def _validate_toml_field(field: str) -> None:
    if not _TOML_FIELD_RE.fullmatch(field):
        raise ValueError("invalid TOML field name")


def _leading_ws(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return ""


def _read_text(path: Path) -> str:
    """Read ``path`` as UTF-8 with line endings untouched ("" if missing)."""
    if not path.exists():
        return ""
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def _write_private(path: Path | str, text: str) -> None:
    """Write text to path atomically with a 0o600 temporary file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path.parent / f".tmp.{os.urandom(8).hex()}"
    fd: int | None = None
    try:
        fd = os.open(
            str(tmp_path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        # fdopen now owns the descriptor and closes it, even on error.
        f = os.fdopen(fd, "w", encoding="utf-8", newline="")
        fd = None
        with f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(path))
    except Exception:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def upsert_env(path: Path | str, key: str, value: str) -> None:
    """Insert or update a KEY=value line in a compose/.env style file."""
    _validate_env_key(key)
    validate_value(value)

    path = Path(path)
    text = _read_text(path)
    lines = text.splitlines(keepends=True)

    prefix = f"{key}="
    first_active: int | None = None
    duplicates: list[int] = []

    for i, line in enumerate(lines):
        if line.lstrip().startswith(prefix):
            if first_active is None:
                first_active = i
            else:
                duplicates.append(i)

    if first_active is not None:
        original = lines[first_active]
        lines[first_active] = (
            f"{_leading_ws(original)}{key}={value}{_line_ending(original)}"
        )
        for i in reversed(duplicates):
            del lines[i]
    else:
        if text and not text.endswith("\n"):
            lines.append("\n")
        lines.append(f"{key}={value}\n")

    _write_private(path, "".join(lines))


def upsert_toml_field(path: Path | str, table: str, field: str, value: str) -> None:
    """Insert or update a field inside a TOML table, preserving the rest of the file."""
    _validate_toml_table(table)
    _validate_toml_field(field)
    validate_value(value)

    path = Path(path)
    text = _read_text(path)
    lines = text.splitlines(keepends=True)

    header_re = re.compile(r"^\s*\[\s*" + re.escape(table) + r"\s*\]\s*(?:#.*)?$")
    field_re = re.compile(r"^\s*" + re.escape(field) + r"\s*=")

    table_start: int | None = None
    for i, line in enumerate(lines):
        if header_re.match(line.rstrip("\r\n")):
            table_start = i
            break

    if table_start is None:
        if text and not text.endswith("\n"):
            lines.append("\n")
        lines.append(f"[{table}]\n")
        lines.append(f'{field} = "{value}"\n')
        _write_private(path, "".join(lines))
        return

    body_end = len(lines)
    for j in range(table_start + 1, len(lines)):
        if lines[j].strip().startswith("["):
            body_end = j
            break

    first_field: int | None = None
    duplicates: list[int] = []
    for i in range(table_start + 1, body_end):
        line = lines[i]
        if line.lstrip().startswith("#"):
            continue
        if field_re.match(line.rstrip("\r\n")):
            if first_field is None:
                first_field = i
            else:
                duplicates.append(i)

    if first_field is not None:
        original = lines[first_field]
        lines[first_field] = f'{field} = "{value}"{_line_ending(original)}'
        for i in reversed(duplicates):
            del lines[i]
        _write_private(path, "".join(lines))
        return

    insert_after = table_start
    for i in range(body_end - 1, table_start, -1):
        content = lines[i].rstrip("\r\n")
        stripped = content.strip()
        if stripped and not stripped.startswith("#"):
            insert_after = i
            break

    lines.insert(insert_after + 1, f'{field} = "{value}"\n')
    _write_private(path, "".join(lines))


def read_toml_field(path: Path | str, table: str, field: str) -> str | None:
    """Return a non-empty string value from a TOML file, or None.

    Missing files are treated as empty. A malformed file raises
    tomllib.TOMLDecodeError.
    """
    import tomllib

    path = Path(path)
    if not path.exists():
        return None

    with open(path, "rb") as f:
        data = tomllib.load(f)

    current: object = data
    for part in table.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]

    if isinstance(current, dict):
        val = current.get(field)
        if isinstance(val, str) and val:
            return val
    return None


def main(argv: list[str] | None = None) -> int:
    """CLI entry point used by bootstrap scripts."""
    if argv is None:
        argv = sys.argv[1:]

    usage = (
        "usage: kaine.secrets_file "
        "{env PATH KEY VALUE | toml PATH TABLE FIELD VALUE}"
    )

    if not argv or argv[0] not in ("env", "toml"):
        print(usage, file=sys.stderr)
        return 2

    def _stdin_value() -> str:
        value = sys.stdin.read()
        if value.endswith("\n"):
            value = value[:-1]
            if value.endswith("\r"):
                value = value[:-1]
        return value

    try:
        if argv[0] == "env":
            if len(argv) != 4:
                print(usage, file=sys.stderr)
                return 2
            _, path, key, value = argv
            if value == "-":
                value = _stdin_value()
            upsert_env(path, key, value)
        else:
            if len(argv) != 5:
                print(usage, file=sys.stderr)
                return 2
            _, path, table, field, value = argv
            if value == "-":
                value = _stdin_value()
            upsert_toml_field(path, table, field, value)
    except (ValueError, OSError) as exc:
        print(f"kaine.secrets_file: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
