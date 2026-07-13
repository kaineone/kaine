# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from kaine.nexus.config import NexusConfig, load_nexus_config


def test_defaults():
    cfg = NexusConfig()
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8088
    assert cfg.conversation_enabled is False  # deactivated by default (base-thesis form)
    assert cfg.diagnostics_enabled is True
    assert cfg.conversation_history_lookback == 50
    assert cfg.dev_content_override is False


def test_from_mapping_overrides():
    cfg = NexusConfig.from_mapping(
        {
            "host": "0.0.0.0",
            "port": 9000,
            "conversation_enabled": False,
            "diagnostics_enabled": True,
            "conversation_history_lookback": 200,
            "dev_content_override": True,
        }
    )
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9000
    assert cfg.conversation_enabled is False
    assert cfg.dev_content_override is True


def test_from_mapping_none_returns_defaults():
    cfg = NexusConfig.from_mapping(None)
    assert cfg == NexusConfig()


def test_load_nexus_config_reads_kaine_toml(tmp_path):
    config_file = tmp_path / "kaine.toml"
    config_file.write_text(
        """
        [nexus]
        port = 9001
        dev_content_override = true
        """
    )
    cfg = load_nexus_config(config_file)
    assert cfg.port == 9001
    assert cfg.dev_content_override is True


def test_load_nexus_config_missing_returns_defaults(tmp_path):
    cfg = load_nexus_config(tmp_path / "nope.toml")
    assert cfg == NexusConfig()


def test_env_host_overrides_toml(tmp_path, monkeypatch):
    # Containers reach Nexus via a published port that cannot reach a server bound
    # to the container's own 127.0.0.1 (the shipped default). KAINE_NEXUS_HOST lets
    # the deployment bind all interfaces without editing the baked config.
    config_file = tmp_path / "kaine.toml"
    config_file.write_text("[nexus]\nhost = \"127.0.0.1\"\nport = 8088\n")
    monkeypatch.setenv("KAINE_NEXUS_HOST", "0.0.0.0")
    monkeypatch.delenv("KAINE_NEXUS_PORT", raising=False)
    cfg = load_nexus_config(config_file)
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 8088  # unchanged when only host is overridden


def test_env_port_overrides_toml(tmp_path, monkeypatch):
    config_file = tmp_path / "kaine.toml"
    config_file.write_text("[nexus]\nhost = \"127.0.0.1\"\nport = 8088\n")
    monkeypatch.delenv("KAINE_NEXUS_HOST", raising=False)
    monkeypatch.setenv("KAINE_NEXUS_PORT", "9099")
    cfg = load_nexus_config(config_file)
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 9099


def test_env_override_applies_without_toml(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_NEXUS_HOST", "0.0.0.0")
    cfg = load_nexus_config(tmp_path / "nope.toml")
    assert cfg.host == "0.0.0.0"


def test_no_env_leaves_toml_host(tmp_path, monkeypatch):
    config_file = tmp_path / "kaine.toml"
    config_file.write_text("[nexus]\nhost = \"127.0.0.1\"\n")
    monkeypatch.delenv("KAINE_NEXUS_HOST", raising=False)
    monkeypatch.delenv("KAINE_NEXUS_PORT", raising=False)
    cfg = load_nexus_config(config_file)
    assert cfg.host == "127.0.0.1"
