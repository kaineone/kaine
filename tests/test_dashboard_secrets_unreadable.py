# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import os
from pathlib import Path

import pytest

from kaine import legacy_names, secrets_file
from kaine.dashboard.config import DashboardConfigError, load_dashboard_config
from kaine.dashboard.health.config import load_health_prober

# The deprecated name of KAINE_DASHBOARD_TOKEN, read from the rename table.
_OLD_TOKEN_VAR = next(
    entry["old"] for entry in legacy_names.ENV_VARS if entry["new"] == "KAINE_DASHBOARD_TOKEN"
)

pytestmark = pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses mode 000 files")

TOKEN = "x" * 40


def _write_kaine_toml(tmp_path: Path) -> Path:
    kaine_toml = tmp_path / "kaine.toml"
    kaine_toml.write_text("[dashboard]\n", encoding="utf-8")
    return kaine_toml


def _write_secrets(path: Path, content: str, mode: int = 0o600) -> None:
    path.write_text(content, encoding="utf-8")
    os.chmod(path, mode)


@pytest.fixture(autouse=True)
def _reset_secrets_warnings(monkeypatch):
    secrets_file._reset_unreadable_warnings()
    monkeypatch.delenv("KAINE_DASHBOARD_TOKEN", raising=False)
    monkeypatch.delenv(_OLD_TOKEN_VAR, raising=False)
    yield
    secrets_file._reset_unreadable_warnings()
    monkeypatch.delenv("KAINE_DASHBOARD_TOKEN", raising=False)
    monkeypatch.delenv(_OLD_TOKEN_VAR, raising=False)


def test_unreadable_secrets_env_token(tmp_path, monkeypatch):
    kaine_toml = _write_kaine_toml(tmp_path)
    secrets = tmp_path / "secrets.toml"
    _write_secrets(secrets, f'[dashboard]\noperator_token = "{TOKEN}"\n', mode=0o000)
    monkeypatch.setenv("KAINE_DASHBOARD_TOKEN", TOKEN)
    try:
        cfg = load_dashboard_config(
            kaine_toml,
            secrets_path=secrets,
            operator_path=tmp_path / "absent.toml",
        )
    finally:
        os.chmod(secrets, 0o600)
    assert cfg.operator_token == TOKEN


def test_unreadable_secrets_no_env_token(tmp_path):
    kaine_toml = _write_kaine_toml(tmp_path)
    secrets = tmp_path / "secrets.toml"
    _write_secrets(secrets, f'[dashboard]\noperator_token = "{TOKEN}"\n', mode=0o000)
    try:
        cfg = load_dashboard_config(
            kaine_toml,
            secrets_path=secrets,
            operator_path=tmp_path / "absent.toml",
        )
    finally:
        os.chmod(secrets, 0o600)
    assert cfg.operator_token == ""


def test_readable_secrets_still_read(tmp_path):
    kaine_toml = _write_kaine_toml(tmp_path)
    secrets = tmp_path / "secrets.toml"
    _write_secrets(secrets, f'[dashboard]\noperator_token = "{TOKEN}"\n', mode=0o600)
    cfg = load_dashboard_config(
        kaine_toml,
        secrets_path=secrets,
        operator_path=tmp_path / "absent.toml",
    )
    assert cfg.operator_token == TOKEN


def test_malformed_secrets_raises(tmp_path):
    kaine_toml = _write_kaine_toml(tmp_path)
    secrets = tmp_path / "secrets.toml"
    _write_secrets(secrets, "this is not valid toml", mode=0o600)
    with pytest.raises(DashboardConfigError):
        load_dashboard_config(
            kaine_toml,
            secrets_path=secrets,
            operator_path=tmp_path / "absent.toml",
        )


def test_health_prober_unreadable_secrets(tmp_path):
    kaine_toml = _write_kaine_toml(tmp_path)
    secrets = tmp_path / "secrets.toml"
    _write_secrets(secrets, f'[dashboard]\noperator_token = "{TOKEN}"\n', mode=0o000)
    try:
        prober = load_health_prober(
            kaine_toml=kaine_toml,
            secrets_toml=secrets,
        )
    finally:
        os.chmod(secrets, 0o600)
    assert prober is not None
    assert prober.dependencies
