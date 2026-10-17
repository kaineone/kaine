# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import stat
from pathlib import Path

from kaine import legacy_names, secrets_file
from kaine.setup.dashboard_token import COMPOSE_ENV_KEY, ensure_dashboard_token

# The deprecated name of KAINE_DASHBOARD_TOKEN, read from the rename table.
_OLD_TOKEN_VAR = next(
    entry["old"] for entry in legacy_names.ENV_VARS if entry["new"] == "KAINE_DASHBOARD_TOKEN"
)


def _checkout(tmp_path: Path, *, create_compose: bool = False) -> Path:
    root = tmp_path / "root"
    (root / "config").mkdir(parents=True)
    if create_compose:
        (root / "compose").mkdir(parents=True)
    return root


def test_generated_mirrors_to_compose_env(tmp_path: Path) -> None:
    root = _checkout(tmp_path, create_compose=True)
    secrets = root / "config" / "secrets.toml"
    env_path = root / "compose" / ".env"
    buf: list[str] = []

    result = ensure_dashboard_token(secrets, out=buf.append, env={})
    assert result == "generated"

    token = secrets_file.read_toml_field(secrets, "dashboard", "operator_token")
    assert len(token) >= 32

    content = env_path.read_text(encoding="utf-8")
    assert f"{COMPOSE_ENV_KEY}={token}" in content
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600

    output = "".join(buf)
    assert token not in output


def test_kept_mirrors_existing_token(tmp_path: Path) -> None:
    root = _checkout(tmp_path, create_compose=True)
    secrets = root / "config" / "secrets.toml"
    token = "x" * 40
    secrets.write_text(
        f'[dashboard]\noperator_token = "{token}"\n', encoding="utf-8"
    )
    env_path = root / "compose" / ".env"
    buf: list[str] = []

    result = ensure_dashboard_token(secrets, out=buf.append, env={})
    assert result == "kept"

    content = env_path.read_text(encoding="utf-8")
    assert f"{COMPOSE_ENV_KEY}={token}" in content
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
    assert token not in "".join(buf)


def test_existing_legacy_token_left_unchanged(tmp_path: Path) -> None:
    root = _checkout(tmp_path, create_compose=True)
    secrets = root / "config" / "secrets.toml"
    token = "n" * 40
    env_path = root / "compose" / ".env"
    original = f"{_OLD_TOKEN_VAR}={token}\n"
    env_path.write_text(original, encoding="utf-8")
    buf: list[str] = []

    result = ensure_dashboard_token(secrets, out=buf.append, env={})
    assert result == "generated"
    assert env_path.read_text(encoding="utf-8") == original
    assert "already sets a dashboard token" in "".join(buf)
    assert token not in "".join(buf)


def test_existing_dashboard_token_left_unchanged(tmp_path: Path) -> None:
    root = _checkout(tmp_path, create_compose=True)
    secrets = root / "config" / "secrets.toml"
    existing_token = "d" * 40
    env_path = root / "compose" / ".env"
    original = f"KAINE_DASHBOARD_TOKEN={existing_token}\nOTHER=1\n"
    env_path.write_text(original, encoding="utf-8")
    buf: list[str] = []

    result = ensure_dashboard_token(secrets, out=buf.append, env={})
    assert result == "generated"
    assert env_path.read_text(encoding="utf-8") == original
    assert "already sets a dashboard token" in "".join(buf)
    assert existing_token not in "".join(buf)


def test_commented_token_is_overwritten_and_other_keys_kept(tmp_path: Path) -> None:
    root = _checkout(tmp_path, create_compose=True)
    secrets = root / "config" / "secrets.toml"
    env_path = root / "compose" / ".env"
    env_path.write_text(
        "EXISTING=keep\n# KAINE_DASHBOARD_TOKEN=x\n", encoding="utf-8"
    )
    buf: list[str] = []

    result = ensure_dashboard_token(secrets, out=buf.append, env={})
    assert result == "generated"

    token = secrets_file.read_toml_field(secrets, "dashboard", "operator_token")
    content = env_path.read_text(encoding="utf-8")
    assert "EXISTING=keep" in content
    assert "# KAINE_DASHBOARD_TOKEN=x" in content
    assert f"{COMPOSE_ENV_KEY}={token}" in content
    assert token not in "".join(buf)


def test_no_config_directory_no_mirror(tmp_path: Path) -> None:
    secrets = tmp_path / "secrets.toml"
    buf: list[str] = []

    result = ensure_dashboard_token(secrets, out=buf.append, env={})
    assert result == "generated"
    assert not (tmp_path / "compose").exists()

    token = secrets_file.read_toml_field(secrets, "dashboard", "operator_token")
    assert token not in "".join(buf)


def test_explicit_env_path_is_used(tmp_path: Path) -> None:
    secrets = tmp_path / "secrets.toml"
    custom_env = tmp_path / "custom.env"
    buf: list[str] = []

    result = ensure_dashboard_token(
        secrets, out=buf.append, env={}, env_path=custom_env
    )
    assert result == "generated"

    token = secrets_file.read_toml_field(secrets, "dashboard", "operator_token")
    content = custom_env.read_text(encoding="utf-8")
    assert f"{COMPOSE_ENV_KEY}={token}" in content
    assert stat.S_IMODE(custom_env.stat().st_mode) == 0o600
    assert token not in "".join(buf)


def test_env_token_skips_mirror(tmp_path: Path) -> None:
    root = _checkout(tmp_path, create_compose=True)
    secrets = root / "config" / "secrets.toml"
    env_path = root / "compose" / ".env"
    buf: list[str] = []

    result = ensure_dashboard_token(
        secrets,
        out=buf.append,
        env={"KAINE_DASHBOARD_TOKEN": "y" * 40},
    )
    assert result == "env"
    assert not env_path.exists()
