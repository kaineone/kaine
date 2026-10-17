# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Every reader of config/secrets.toml goes through kaine.secrets_file.load_secrets_doc."""

from pathlib import Path

import pytest

from kaine import legacy_names, secrets_file
from kaine.bus import config as bus_config

# The deprecated name of KAINE_DASHBOARD_TOKEN, read from the rename table.
_OLD_TOKEN_VAR = next(
    entry["old"] for entry in legacy_names.ENV_VARS if entry["new"] == "KAINE_DASHBOARD_TOKEN"
)


class _Spy:
    def __init__(self):
        self.paths = []

    def __call__(self, path, *, tolerate_unreadable=True):
        self.paths.append(Path(path))
        return {
            "redis": {"password": "spypw"},
            "qdrant": {"api_key": "spykey"},
            "dashboard": {"operator_token": "s" * 40},
            "caretaker": {"tokens": {"ntfy": "spytoken"}},
        }


@pytest.fixture
def spy(monkeypatch):
    replacement = _Spy()
    monkeypatch.setattr(secrets_file, "load_secrets_doc", replacement)
    return replacement


@pytest.fixture(autouse=True)
def _clear_secrets_env(monkeypatch):
    for name in (
        "KAINE_REDIS_PASSWORD",
        "KAINE_REDIS_USERNAME",
        "KAINE_REDIS_URL",
        "KAINE_QDRANT_API_KEY",
        "KAINE_DASHBOARD_TOKEN",
        _OLD_TOKEN_VAR,
        "KAINE_CARETAKER_TOKEN_NTFY",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def secrets_path(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return config_dir / "secrets.toml"


def test_resolve_redis_auth(spy, secrets_path):
    result = bus_config.resolve_redis_auth(env={}, secrets_toml=secrets_path)
    assert result == (None, "spypw")
    assert secrets_path in spy.paths


def test_load_bus_config(spy, secrets_path, tmp_path):
    kaine_toml = tmp_path / "kaine.toml"
    kaine_toml.write_text("")
    cfg = bus_config.load_bus_config(
        kaine_toml=kaine_toml,
        secrets_toml=secrets_path,
        env={},
        operator_toml=tmp_path / "absent.toml",
    )
    assert cfg.password == "spypw"
    assert secrets_path in spy.paths


def test_bus_config_load_secrets_doc_default(spy, tmp_path):
    doc = bus_config.load_secrets_doc()
    assert doc == {
        "redis": {"password": "spypw"},
        "qdrant": {"api_key": "spykey"},
        "dashboard": {"operator_token": "s" * 40},
        "caretaker": {"tokens": {"ntfy": "spytoken"}},
    }
    assert len(spy.paths) == 1
    assert spy.paths[0].name == "secrets.toml"
    assert spy.paths[0].parent.name == "config"


def test_merge_qdrant_secret(spy, secrets_path):
    from kaine.cycle.__main__ import _merge_qdrant_secret

    config = {"episodic_memory": {"qdrant": {}}}
    _merge_qdrant_secret(config, secrets_path=secrets_path, env={})
    assert config["episodic_memory"]["qdrant"]["api_key"] == "spykey"
    assert secrets_path in spy.paths


def test_load_dashboard_config(spy, secrets_path, tmp_path):
    from kaine.dashboard import config as dashboard_config

    kaine_toml = tmp_path / "kaine.toml"
    kaine_toml.write_text("[dashboard]\n")
    cfg = dashboard_config.load_dashboard_config(
        kaine_toml,
        operator_path=tmp_path / "absent.toml",
        secrets_path=secrets_path,
    )
    assert cfg.operator_token == "s" * 40
    assert secrets_path in spy.paths


def test_load_health_prober(spy, secrets_path, tmp_path):
    from kaine.dashboard.health import config as health_config

    kaine_toml = tmp_path / "kaine.toml"
    kaine_toml.write_text("[dashboard]\n")
    prober = health_config.load_health_prober(
        kaine_toml=kaine_toml,
        secrets_toml=secrets_path,
    )
    assert prober is not None
    assert secrets_path in spy.paths


def test_caretaker_load_token(spy, secrets_path):
    from kaine.cycle import caretaker

    token = caretaker.load_token("ntfy", secrets_path=secrets_path, env={})
    assert token == "spytoken"
    assert secrets_path in spy.paths


def test_ensure_dashboard_token(spy, secrets_path, tmp_path):
    from kaine.setup import dashboard_token

    status = dashboard_token.ensure_dashboard_token(
        secrets_path,
        out=[].append,
        env={},
        env_path=tmp_path / "compose.env",
    )
    assert status == "kept"
    assert secrets_path in spy.paths


def test_decommission_qdrant_api_key(spy, secrets_path):
    from kaine.lifecycle import decommission

    key = decommission._qdrant_api_key({}, env={}, secrets_path=secrets_path)
    assert key == "spykey"
    assert secrets_path in spy.paths
