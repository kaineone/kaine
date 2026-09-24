# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import stat
import subprocess
import sys
from pathlib import Path

import pytest

from kaine.secrets_file import (
    read_toml_field,
    upsert_env,
    upsert_toml_field,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

EXAMPLE_TOML = """\
# Copy this file to config/secrets.toml and fill in the actual values.
# config/secrets.toml is gitignored.
# Recommended permissions: chmod 600 config/secrets.toml
#
# Env vars override values here:
#   KAINE_REDIS_URL       — full redis:// URL, including auth
#   KAINE_REDIS_PASSWORD  — Redis password only
#   KAINE_REDIS_USERNAME  — Redis username only (ACL setups)
#   KAINE_QDRANT_API_KEY  — Qdrant API key

[redis]
# Output of: openssl rand -hex 32
password = "REPLACE-ME-WITH-THE-PASSWORD-IN-compose-env"

# username = "default"  # only needed if Redis ACLs are in use
# url = "redis://:<password>@127.0.0.1:6379/0"  # full URL form, optional

[qdrant]
# Output of: openssl rand -hex 32
api_key = "REPLACE-ME-WITH-THE-KEY-IN-compose-env"
# host = "127.0.0.1"
# port = 6533

[nexus]
# Operator token for the Nexus web UI / diagnostics. Must be at least 32 characters.
# Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"
# operator_token = "<32+ random characters>"

[other]
password = "keep-me"
"""


def _read(path):
    # Path.read_text(newline=...) needs Python 3.13; KAINE supports 3.11+.
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


# --- .env tests ---


def test_env_unrelated_key_survives(tmp_path):
    path = tmp_path / ".env"
    path.write_text("KAINE_QDRANT_API_KEY=abc\n", newline="")
    upsert_env(path, "KAINE_REDIS_PASSWORD", "redis-secret")
    text = _read(path)
    assert "KAINE_QDRANT_API_KEY=abc\n" in text
    assert "KAINE_REDIS_PASSWORD=redis-secret\n" in text


def test_env_upsert_twice_leaves_one_active_line(tmp_path):
    path = tmp_path / ".env"
    path.write_text("KAINE_REDIS_PASSWORD=old\n", newline="")
    upsert_env(path, "KAINE_REDIS_PASSWORD", "one")
    upsert_env(path, "KAINE_REDIS_PASSWORD", "two")
    lines = _read(path).splitlines()
    active = [ln for ln in lines if ln.lstrip().startswith("KAINE_REDIS_PASSWORD=")]
    assert active == ["KAINE_REDIS_PASSWORD=two"]


def test_env_commented_line_stays_and_active_appended(tmp_path):
    path = tmp_path / ".env"
    path.write_text("# KAINE_REDIS_PASSWORD=old\n", newline="")
    upsert_env(path, "KAINE_REDIS_PASSWORD", "new")
    lines = _read(path).splitlines()
    assert "# KAINE_REDIS_PASSWORD=old" in lines
    active = [ln for ln in lines if ln.lstrip().startswith("KAINE_REDIS_PASSWORD=")]
    assert active == ["KAINE_REDIS_PASSWORD=new"]
    assert lines[-1] == "KAINE_REDIS_PASSWORD=new"


def test_env_duplicate_active_lines_collapse(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "KAINE_REDIS_PASSWORD=first\nKAINE_REDIS_PASSWORD=second\n",
        newline="",
    )
    upsert_env(path, "KAINE_REDIS_PASSWORD", "third")
    lines = _read(path).splitlines()
    active = [ln for ln in lines if ln.lstrip().startswith("KAINE_REDIS_PASSWORD=")]
    assert active == ["KAINE_REDIS_PASSWORD=third"]


# --- TOML tests ---


def test_toml_upsert_redis_password_only(tmp_path):
    path = tmp_path / "secrets.toml"
    path.write_text(EXAMPLE_TOML, newline="")
    upsert_toml_field(path, "redis", "password", "new-redis-pass")

    original_lines = EXAMPLE_TOML.splitlines()
    new_lines = _read(path).splitlines()

    redis_idx = next(
        i
        for i, ln in enumerate(original_lines)
        if ln.lstrip().startswith("password =")
    )
    expected = original_lines[:]
    expected[redis_idx] = 'password = "new-redis-pass"'

    assert new_lines == expected

    other_idx = next(
        i
        for i, ln in enumerate(new_lines)
        if ln.lstrip().startswith("password =") and i != redis_idx
    )
    assert new_lines[other_idx] == 'password = "keep-me"'


def test_toml_upsert_nexus_token_parses_and_comment_remains(tmp_path):
    path = tmp_path / "secrets.toml"
    path.write_text(EXAMPLE_TOML, newline="")
    token = "tok_" + "a" * 40
    upsert_toml_field(path, "nexus", "operator_token", token)

    assert read_toml_field(path, "nexus", "operator_token") == token

    lines = _read(path).splitlines()
    comment_lines = [ln for ln in lines if ln.strip().startswith("# operator_token")]
    assert comment_lines
    field_lines = [ln for ln in lines if ln.lstrip().startswith("operator_token =")]
    assert len(field_lines) == 1
    assert field_lines[0] == f'operator_token = "{token}"'


def test_toml_missing_table_appended(tmp_path):
    path = tmp_path / "secrets.toml"
    path.write_text(EXAMPLE_TOML, newline="")
    upsert_toml_field(path, "newtable", "newfield", "newvalue")
    text = _read(path)
    assert text.endswith('\n[newtable]\nnewfield = "newvalue"\n')
    assert read_toml_field(path, "newtable", "newfield") == "newvalue"


def test_toml_dotted_table_works(tmp_path):
    path = tmp_path / "secrets.toml"
    path.write_text(EXAMPLE_TOML, newline="")
    upsert_toml_field(path, "mnemos.qdrant", "api_key", "dotted-key")
    assert read_toml_field(path, "mnemos.qdrant", "api_key") == "dotted-key"
    text = _read(path)
    assert "[mnemos.qdrant]" in text
    assert 'api_key = "dotted-key"' in text


def test_toml_original_lines_preserved_except_target(tmp_path):
    path = tmp_path / "secrets.toml"
    path.write_text(EXAMPLE_TOML, newline="")
    upsert_toml_field(path, "redis", "password", "x")

    original_lines = EXAMPLE_TOML.splitlines()
    new_lines = _read(path).splitlines()

    redis_idx = next(
        i
        for i, ln in enumerate(original_lines)
        if ln.lstrip().startswith("password =")
    )
    expected = original_lines[:]
    expected[redis_idx] = 'password = "x"'

    assert new_lines == expected


# --- validation tests ---


@pytest.mark.parametrize(
    "bad_value",
    # Each bad value carries a distinctive marker so the no-echo check is
    # meaningful (a bare " " would match any message with a space in it).
    ['zq9"zq9', "zq9\\zq9", "zq9$zq9", "zq9 zq9", "zq9\nzq9"],
)
def test_validate_value_rejects_bad_characters(tmp_path, bad_value):
    path = tmp_path / ".env"
    path.write_text("KEY=old\n", newline="")
    with pytest.raises(ValueError) as excinfo:
        upsert_env(path, "KEY", bad_value)
    assert "zq9" not in str(excinfo.value)
    assert _read(path) == "KEY=old\n"


# --- mode tests ---


def test_new_file_is_mode_600(tmp_path):
    path = tmp_path / "new.toml"
    upsert_toml_field(path, "redis", "password", "secret")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_existing_644_becomes_600(tmp_path):
    path = tmp_path / ".env"
    path.write_text("KEY=old\n", newline="")
    path.chmod(0o644)
    upsert_env(path, "KEY", "newvalue")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


# --- read_toml_field tests ---


def test_read_toml_missing_file(tmp_path):
    assert read_toml_field(tmp_path / "missing.toml", "redis", "password") is None


def test_read_toml_missing_table(tmp_path):
    path = tmp_path / "secrets.toml"
    path.write_text('[redis]\npassword = "x"\n', newline="")
    assert read_toml_field(path, "qdrant", "api_key") is None


def test_read_toml_commented_field(tmp_path):
    path = tmp_path / "secrets.toml"
    path.write_text('[nexus]\n# operator_token = "x"\n', newline="")
    assert read_toml_field(path, "nexus", "operator_token") is None


def test_read_toml_after_upsert(tmp_path):
    path = tmp_path / "secrets.toml"
    upsert_toml_field(path, "redis", "password", "p")
    assert read_toml_field(path, "redis", "password") == "p"


# --- CLI tests ---


def test_cli_toml_stdin_stores_value_without_echo(tmp_path):
    path = tmp_path / "secrets.toml"
    value = "tok_" + "a" * 40
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "kaine.secrets_file",
            "toml",
            str(path),
            "nexus",
            "operator_token",
            "-",
        ],
        input=value + "\n",
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0
    assert value not in result.stdout
    assert value not in result.stderr
    assert read_toml_field(path, "nexus", "operator_token") == value


def test_cli_bad_value_exits_two_without_echo(tmp_path):
    path = tmp_path / "secrets.toml"
    value = "bad value"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "kaine.secrets_file",
            "toml",
            str(path),
            "nexus",
            "operator_token",
            value,
        ],
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 2
    assert value not in result.stdout
    assert value not in result.stderr
    assert not path.exists()
