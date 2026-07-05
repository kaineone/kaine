# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from kaine.nexus.config import NexusConfig, load_nexus_config


def test_defaults():
    cfg = NexusConfig()
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8088
    assert cfg.conversation_enabled is True
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
