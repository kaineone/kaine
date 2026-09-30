# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import textwrap
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig, load_bus_config
from kaine.bus.errors import BusConfigError


def _write(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body), encoding="utf-8")


def test_default_max_connections_is_1024(tmp_path: Path):
    kaine = tmp_path / "kaine.toml"
    secrets = tmp_path / "secrets.toml"
    _write(kaine, "")
    _write(secrets, '[redis]\npassword = "x"\n')
    cfg = load_bus_config(kaine_toml=kaine, secrets_toml=secrets, env={})
    assert cfg.max_connections == 1024
    assert BusConfig().max_connections == 1024


def test_max_connections_can_be_set_to_64(tmp_path: Path):
    kaine = tmp_path / "kaine.toml"
    secrets = tmp_path / "secrets.toml"
    _write(
        kaine,
        """
        [bus]
        max_connections = 64
        """,
    )
    _write(secrets, '[redis]\npassword = "x"\n')
    cfg = load_bus_config(kaine_toml=kaine, secrets_toml=secrets, env={})
    assert cfg.max_connections == 64


def test_max_connections_zero_rejected(tmp_path: Path):
    kaine = tmp_path / "kaine.toml"
    secrets = tmp_path / "secrets.toml"
    _write(
        kaine,
        """
        [bus]
        max_connections = 0
        """,
    )
    _write(secrets, '[redis]\npassword = "x"\n')
    with pytest.raises(BusConfigError):
        load_bus_config(kaine_toml=kaine, secrets_toml=secrets, env={})


def test_max_connections_negative_rejected(tmp_path: Path):
    kaine = tmp_path / "kaine.toml"
    secrets = tmp_path / "secrets.toml"
    _write(
        kaine,
        """
        [bus]
        max_connections = -1
        """,
    )
    _write(secrets, '[redis]\npassword = "x"\n')
    with pytest.raises(BusConfigError):
        load_bus_config(kaine_toml=kaine, secrets_toml=secrets, env={})


def test_max_connections_bool_rejected(tmp_path: Path):
    kaine = tmp_path / "kaine.toml"
    secrets = tmp_path / "secrets.toml"
    _write(
        kaine,
        """
        [bus]
        max_connections = true
        """,
    )
    _write(secrets, '[redis]\npassword = "x"\n')
    with pytest.raises(BusConfigError):
        load_bus_config(kaine_toml=kaine, secrets_toml=secrets, env={})


def test_max_connections_string_rejected(tmp_path: Path):
    kaine = tmp_path / "kaine.toml"
    secrets = tmp_path / "secrets.toml"
    _write(
        kaine,
        """
        [bus]
        max_connections = "64"
        """,
    )
    _write(secrets, '[redis]\npassword = "x"\n')
    with pytest.raises(BusConfigError):
        load_bus_config(kaine_toml=kaine, secrets_toml=secrets, env={})


def test_max_connections_too_large_rejected(tmp_path: Path):
    kaine = tmp_path / "kaine.toml"
    secrets = tmp_path / "secrets.toml"
    _write(
        kaine,
        """
        [bus]
        max_connections = 100001
        """,
    )
    _write(secrets, '[redis]\npassword = "x"\n')
    with pytest.raises(BusConfigError):
        load_bus_config(kaine_toml=kaine, secrets_toml=secrets, env={})


def test_bus_client_passes_max_connections_to_from_url(monkeypatch):
    captured = {}

    def fake_from_url(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr("kaine.bus.client.aioredis.from_url", fake_from_url)
    config = BusConfig(max_connections=512, password="x")
    bus = AsyncBus(config)
    assert bus.config.max_connections == 512
    assert captured["kwargs"]["max_connections"] == 512
    assert captured["kwargs"]["decode_responses"] is True
