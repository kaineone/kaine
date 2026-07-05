# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import textwrap
from pathlib import Path

import pytest

from kaine.bus.config import BusConfig, load_bus_config
from kaine.bus.errors import BusConfigError


def _write(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body), encoding="utf-8")


def test_env_var_overrides_secrets_file(tmp_path: Path):
    kaine = tmp_path / "kaine.toml"
    secrets = tmp_path / "secrets.toml"
    _write(
        kaine,
        """
        [redis]
        host = "127.0.0.1"
        port = 6379
        [bus]
        default_maxlen = 1000
        audit_required = true
        """,
    )
    _write(
        secrets,
        """
        [redis]
        password = "fileval"
        """,
    )
    cfg = load_bus_config(
        kaine_toml=kaine,
        secrets_toml=secrets,
        env={"KAINE_REDIS_PASSWORD": "envval"},
    )
    assert cfg.password == "envval"
    assert cfg.default_maxlen == 1000


def test_secrets_file_password_used_when_env_unset(tmp_path: Path):
    kaine = tmp_path / "kaine.toml"
    secrets = tmp_path / "secrets.toml"
    _write(kaine, "")
    _write(
        secrets,
        """
        [redis]
        password = "fileval"
        """,
    )
    cfg = load_bus_config(kaine_toml=kaine, secrets_toml=secrets, env={})
    assert cfg.password == "fileval"


def test_loopback_host_without_password_fails_fast(tmp_path: Path):
    kaine = tmp_path / "kaine.toml"
    secrets = tmp_path / "secrets.toml"
    _write(kaine, "[redis]\nhost = \"127.0.0.1\"\n")
    _write(secrets, "")
    with pytest.raises(BusConfigError):
        load_bus_config(kaine_toml=kaine, secrets_toml=secrets, env={})


def test_localhost_without_password_fails_fast(tmp_path: Path):
    kaine = tmp_path / "kaine.toml"
    secrets = tmp_path / "secrets.toml"
    _write(kaine, "[redis]\nhost = \"localhost\"\n")
    _write(secrets, "")
    with pytest.raises(BusConfigError):
        load_bus_config(kaine_toml=kaine, secrets_toml=secrets, env={})


def test_non_loopback_host_without_password_fails_fast(tmp_path: Path):
    kaine = tmp_path / "kaine.toml"
    secrets = tmp_path / "secrets.toml"
    _write(kaine, "[redis]\nhost = \"10.0.0.5\"\n")
    _write(secrets, "")
    with pytest.raises(BusConfigError):
        load_bus_config(kaine_toml=kaine, secrets_toml=secrets, env={})


def test_url_override_skips_password_requirement(tmp_path: Path):
    kaine = tmp_path / "kaine.toml"
    _write(kaine, "")
    cfg = load_bus_config(
        kaine_toml=kaine,
        secrets_toml=tmp_path / "absent.toml",
        env={"KAINE_REDIS_URL": "redis://:hidden@127.0.0.1:6379/0"},
    )
    assert cfg.url == "redis://:hidden@127.0.0.1:6379/0"


def test_bus_config_url_builds_with_password():
    cfg = BusConfig(password="abc")
    assert cfg.url == "redis://:abc@127.0.0.1:6379/0"


def test_bus_config_url_builds_with_username_and_password():
    cfg = BusConfig(username="default", password="abc")
    assert cfg.url == "redis://default:abc@127.0.0.1:6379/0"
