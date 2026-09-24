# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Section-aware writer for KAINE local secret files."""

from __future__ import annotations

import contextlib
import fcntl
import os
import re
import sys
import threading
from pathlib import Path

SECRET_VALUE_RE = re.compile(r"[A-Za-z0-9_.~+/=-]+")

_ENV_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TOML_TABLE_RE = re.compile(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*")
_TOML_FIELD_RE = re.compile(r"[A-Za-z0-9_-]+")

_FILE_LOCK = threading.Lock()


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

    tmp_path = path.parent / f".{path.name}.tmp.{os.urandom(8).hex()}"
    fd: int | None = None
    dir_fd: int | None = None
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
        # Ensure the directory metadata is durable after the replace.
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        os.fsync(dir_fd)
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
        if dir_fd is not None:
            try:
                os.close(dir_fd)
            except OSError:
                pass
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


@contextlib.contextmanager
def _exclusive_lock(path: Path):
    """Acquire a per-process/thread exclusive advisory lock for ``path``."""
    lock_path = path.parent / f".{path.name}.lock"
    with _FILE_LOCK:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass


def _lines_inside_ml_strings(lines: list[str]) -> list[bool]:
    """Return whether each line is inside a multi-line string value.

    Lines that contain the opening or closing delimiter are not counted as
    inside. This is only used to avoid treating TOML syntax inside string
    values as real structure.
    """
    inside = False
    delim: str | None = None
    result: list[bool] = []
    for line in lines:
        result.append(inside)
        if inside:
            count = line.count('"""') if delim == '"' else line.count("'''")
            if count % 2 == 1:
                inside = False
                delim = None
        else:
            dcount = line.count('"""')
            scount = line.count("'''")
            if dcount % 2 == 1:
                inside = True
                delim = '"'
            elif scount % 2 == 1:
                inside = True
                delim = "'"
    return result


def _verify_toml_text(text: str, table: str, field: str, value: str) -> None:
    """Raise ValueError if ``text`` does not place ``value`` at the requested path."""
    # Imported here, not at module level: the bootstrap scripts may run this
    # module under a system python3 older than 3.11 (no tomllib), and the
    # .env path must keep working there.
    import tomllib

    try:
        data = tomllib.loads(text)
    except Exception:
        raise ValueError(
            f"refusing to write: result would not be valid TOML or the value would not be at [{table}].{field}"
        ) from None

    current: object = data
    for part in table.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ValueError(
                f"refusing to write: result would not be valid TOML or the value would not be at [{table}].{field}"
            )
        current = current[part]

    if not isinstance(current, dict) or current.get(field) != value:
        raise ValueError(
            f"refusing to write: result would not be valid TOML or the value would not be at [{table}].{field}"
        )


def upsert_env(path: Path | str, key: str, value: str) -> None:
    """Insert or update a KEY=value line in a compose/.env style file."""
    _validate_env_key(key)
    validate_value(value)

    path = Path(os.path.realpath(path))
    path.parent.mkdir(parents=True, exist_ok=True)

    with _exclusive_lock(path):
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

    path = Path(os.path.realpath(path))
    path.parent.mkdir(parents=True, exist_ok=True)

    header_re = re.compile(r"^\s*\[\s*" + re.escape(table) + r"\s*\]\s*(?:#.*)?$")
    field_re = re.compile(r"^\s*" + re.escape(field) + r"\s*=")

    import tomllib  # see _verify_toml_text

    with _exclusive_lock(path):
        text = _read_text(path)
        lines = text.splitlines(keepends=True)

        try:
            data: object = tomllib.loads(text) if text else {}
        except Exception as exc:
            raise ValueError(f"refusing to edit: {path} is not valid TOML") from exc

        table_parts = table.split(".")
        current: object = data
        table_exists = True
        for part in table_parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                table_exists = False
                break

        ml_states = _lines_inside_ml_strings(lines)

        table_start: int | None = None
        for i, line in enumerate(lines):
            if not ml_states[i] and header_re.match(line.rstrip("\r\n")):
                table_start = i
                break

        if table_exists and table_start is None:
            raise ValueError(
                f"refusing to edit: [{table}] is not a plain table header in {path}"
            )

        if table_start is None:
            if text and not text.endswith("\n"):
                lines.append("\n")
            lines.append(f"[{table}]\n")
            lines.append(f'{field} = "{value}"\n')
            new_text = "".join(lines)
            _verify_toml_text(new_text, table, field, value)
            _write_private(path, new_text)
            return

        body_end = len(lines)
        for j in range(table_start + 1, len(lines)):
            if not ml_states[j] and lines[j].lstrip().startswith("["):
                body_end = j
                break

        first_field: int | None = None
        duplicates: list[int] = []
        for i in range(table_start + 1, body_end):
            line = lines[i]
            if ml_states[i]:
                continue
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
            new_text = "".join(lines)
            _verify_toml_text(new_text, table, field, value)
            _write_private(path, new_text)
            return

        insert_after = table_start
        for i in range(body_end - 1, table_start, -1):
            if ml_states[i]:
                continue
            content = lines[i].rstrip("\r\n")
            stripped = content.strip()
            if stripped and not stripped.startswith("#"):
                insert_after = i
                break

        if not lines[insert_after].endswith("\n"):
            lines[insert_after] += "\n"
        lines.insert(insert_after + 1, f'{field} = "{value}"\n')

        new_text = "".join(lines)
        _verify_toml_text(new_text, table, field, value)
        _write_private(path, new_text)


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
    except ImportError:
        # tomllib is 3.11+; the .env subcommand works on older interpreters.
        print(
            "kaine.secrets_file: editing TOML needs Python 3.11 or newer; "
            "run it with the project's .venv/bin/python",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
