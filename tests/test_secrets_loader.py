# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import logging
import os
import tomllib
from pathlib import Path

import pytest

from kaine import secrets_file
from kaine.bus.config import load_bus_config, resolve_redis_auth


@pytest.fixture(autouse=True)
def _reset_warnings():
    secrets_file._reset_unreadable_warnings()
    yield
    secrets_file._reset_unreadable_warnings()


def test_missing_file_is_empty_and_silent(caplog):
    caplog.set_level(logging.WARNING, logger="kaine.secrets_file")
    missing = Path("/nonexistent/path/secrets.toml")
    assert secrets_file.load_secrets_doc(missing) == {}
    assert not caplog.records


def test_readable_private_file_returns_values(tmp_path):
    path = tmp_path / "secrets.toml"
    path.write_text('[redis]\npassword = "filepw"\n')
    path.chmod(0o600)
    assert secrets_file.load_secrets_doc(path) == {"redis": {"password": "filepw"}}


def test_group_readable_file_warns_and_returns_values(tmp_path, capsys):
    path = tmp_path / "secrets.toml"
    path.write_text('[redis]\npassword = "filepw"\n')
    path.chmod(0o644)
    result = secrets_file.load_secrets_doc(path)
    assert result == {"redis": {"password": "filepw"}}
    captured = capsys.readouterr()
    assert (
        f"warning: {path} mode 0o644 is world/group-readable; recommend chmod 600"
        in captured.err
    )


def test_unreadable_file_is_empty_with_one_warning(tmp_path, caplog):
    if os.geteuid() == 0:
        pytest.skip("root can read unreadable files")
    path = tmp_path / "secrets.toml"
    path.write_text('[redis]\npassword = "supersecret"\n')
    path.chmod(0o000)
    caplog.set_level(logging.WARNING, logger="kaine.secrets_file")
    try:
        assert secrets_file.load_secrets_doc(path, tolerate_unreadable=True) == {}
        # The default tolerates an unreadable file too.
        assert secrets_file.load_secrets_doc(path) == {}
    finally:
        path.chmod(0o600)
    assert len(caplog.records) == 1
    record = caplog.records[0]
    message = record.getMessage()
    assert "secrets must come from the environment" in message
    assert "PermissionError" in message
    assert str(path) in message
    assert "supersecret" not in message


def test_unreadable_file_raises_when_not_tolerated(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root can read unreadable files")
    path = tmp_path / "secrets.toml"
    path.write_text('[redis]\npassword = "supersecret"\n')
    path.chmod(0o000)
    try:
        with pytest.raises(PermissionError):
            secrets_file.load_secrets_doc(path, tolerate_unreadable=False)
    finally:
        path.chmod(0o600)


def test_malformed_toml_raises(tmp_path):
    path = tmp_path / "secrets.toml"
    path.write_text("not = valid [toml\n")
    path.chmod(0o600)
    with pytest.raises(tomllib.TOMLDecodeError):
        secrets_file.load_secrets_doc(path)


def test_read_toml_field_unreadable_default_raises(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root can read unreadable files")
    path = tmp_path / "secrets.toml"
    path.write_text('[redis]\npassword = "supersecret"\n')
    path.chmod(0o000)
    try:
        with pytest.raises(PermissionError):
            secrets_file.read_toml_field(path, "redis", "password")
    finally:
        path.chmod(0o600)


def test_read_toml_field_unreadable_tolerated_returns_none(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root can read unreadable files")
    path = tmp_path / "secrets.toml"
    path.write_text('[redis]\npassword = "supersecret"\n')
    path.chmod(0o000)
    try:
        assert (
            secrets_file.read_toml_field(
                path, "redis", "password", tolerate_unreadable=True
            )
            is None
        )
    finally:
        path.chmod(0o600)


def test_bus_config_env_url_over_unreadable_secrets(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root can read unreadable files")
    secrets = tmp_path / "secrets.toml"
    secrets.write_text('[redis]\npassword = "shouldnotread"\n')
    secrets.chmod(0o000)
    kaine = tmp_path / "kaine.toml"
    kaine.write_text("")
    operator = tmp_path / "operator.toml"
    env = {"KAINE_REDIS_URL": "redis://:pw@127.0.0.1:6379/0"}
    try:
        config = load_bus_config(
            kaine_toml=kaine,
            secrets_toml=secrets,
            env=env,
            operator_toml=operator,
        )
        assert config.url == "redis://:pw@127.0.0.1:6379/0"
    finally:
        secrets.chmod(0o600)


def test_resolve_redis_auth_env_password_over_unreadable_secrets(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root can read unreadable files")
    secrets = tmp_path / "secrets.toml"
    secrets.write_text('[redis]\npassword = "shouldnotread"\n')
    secrets.chmod(0o000)
    try:
        assert resolve_redis_auth(
            env={"KAINE_REDIS_PASSWORD": "pw"}, secrets_toml=secrets
        ) == (None, "pw")
    finally:
        secrets.chmod(0o600)


def test_resolve_redis_auth_reads_readable_secrets_file(tmp_path):
    secrets = tmp_path / "secrets.toml"
    secrets.write_text('[redis]\npassword = "filepw"\n')
    secrets.chmod(0o600)
    assert resolve_redis_auth(env={}, secrets_toml=secrets) == (None, "filepw")
