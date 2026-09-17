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
    assert cfg.operator_token == ""
    assert cfg.allowed_origins == ("http://127.0.0.1:8088", "http://localhost:8088")
    assert cfg.host_allowlist == ("127.0.0.1", "localhost")
    assert cfg.non_loopback_allowed is False


def test_from_mapping_overrides():
    cfg = NexusConfig.from_mapping(
        {
            "host": "0.0.0.0",
            "port": 9000,
            "conversation_enabled": False,
            "diagnostics_enabled": True,
            "conversation_history_lookback": 200,
            "dev_content_override": True,
            "operator_token": "op-token",
            "allowed_origins": ["http://example.com"],
            "host_allowlist": ["example.com"],
            "non_loopback_allowed": True,
        }
    )
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9000
    assert cfg.conversation_enabled is False
    assert cfg.dev_content_override is True
    assert cfg.operator_token == "op-token"
    assert cfg.allowed_origins == ("http://example.com",)
    assert cfg.host_allowlist == ("example.com",)
    assert cfg.non_loopback_allowed is True


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
    config_file.write_text('[nexus]\nhost = "127.0.0.1"\nport = 8088\n')
    monkeypatch.setenv("KAINE_NEXUS_HOST", "0.0.0.0")
    monkeypatch.delenv("KAINE_NEXUS_PORT", raising=False)
    cfg = load_nexus_config(config_file)
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 8088  # unchanged when only host is overridden


def test_env_port_overrides_toml(tmp_path, monkeypatch):
    config_file = tmp_path / "kaine.toml"
    config_file.write_text('[nexus]\nhost = "127.0.0.1"\nport = 8088\n')
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
    config_file.write_text('[nexus]\nhost = "127.0.0.1"\n')
    monkeypatch.delenv("KAINE_NEXUS_HOST", raising=False)
    monkeypatch.delenv("KAINE_NEXUS_PORT", raising=False)
    cfg = load_nexus_config(config_file)
    assert cfg.host == "127.0.0.1"


def test_env_conversation_enables_over_toml(tmp_path, monkeypatch):
    # A container mounts the baked kaine.toml (conversation off in the base-thesis
    # form) and turns the surface on via the environment, so no parallel full-config
    # copy has to be hand-maintained just to flip this one flag.
    config_file = tmp_path / "kaine.toml"
    config_file.write_text("[nexus]\nconversation_enabled = false\n")
    monkeypatch.setenv("KAINE_NEXUS_CONVERSATION_ENABLED", "true")
    cfg = load_nexus_config(config_file)
    assert cfg.conversation_enabled is True


def test_env_conversation_disables_over_toml(tmp_path, monkeypatch):
    config_file = tmp_path / "kaine.toml"
    config_file.write_text("[nexus]\nconversation_enabled = true\n")
    monkeypatch.setenv("KAINE_NEXUS_CONVERSATION_ENABLED", "false")
    cfg = load_nexus_config(config_file)
    assert cfg.conversation_enabled is False


def test_no_env_leaves_toml_conversation(tmp_path, monkeypatch):
    config_file = tmp_path / "kaine.toml"
    config_file.write_text("[nexus]\nconversation_enabled = true\n")
    monkeypatch.delenv("KAINE_NEXUS_CONVERSATION_ENABLED", raising=False)
    cfg = load_nexus_config(config_file)
    assert cfg.conversation_enabled is True


def test_env_token_overrides_toml(tmp_path, monkeypatch):
    config_file = tmp_path / "kaine.toml"
    config_file.write_text('[nexus]\noperator_token = "toml-token"\n')
    monkeypatch.setenv("KAINE_NEXUS_TOKEN", "env-token")
    cfg = load_nexus_config(config_file)
    assert cfg.operator_token == "env-token"


def test_no_env_leaves_toml_token(tmp_path, monkeypatch):
    config_file = tmp_path / "kaine.toml"
    config_file.write_text('[nexus]\noperator_token = "toml-token"\n')
    monkeypatch.delenv("KAINE_NEXUS_TOKEN", raising=False)
    cfg = load_nexus_config(config_file)
    assert cfg.operator_token == "toml-token"


def test_is_loopback_host():
    from kaine.nexus.__main__ import _is_loopback_host

    assert _is_loopback_host("127.0.0.1") is True
    assert _is_loopback_host("localhost") is True
    assert _is_loopback_host("::1") is True
    assert _is_loopback_host("192.168.1.1") is False
    assert _is_loopback_host("0.0.0.0") is False


def _fake_build(app, config):
    async def _build():
        return app, config

    return _build


def test_main_rejects_non_loopback_without_opt_in(monkeypatch):
    from kaine.nexus import __main__ as nexus_main

    fake_app = object()
    config = NexusConfig(host="0.0.0.0", non_loopback_allowed=False)
    monkeypatch.setattr(nexus_main, "_build", _fake_build(fake_app, config))
    monkeypatch.setattr(nexus_main, "uvicorn", object())
    assert nexus_main.main() == 1


def test_main_rejects_non_loopback_without_token(monkeypatch):
    from kaine.nexus import __main__ as nexus_main

    fake_app = object()
    config = NexusConfig(host="0.0.0.0", non_loopback_allowed=True, operator_token="")
    monkeypatch.setattr(nexus_main, "_build", _fake_build(fake_app, config))
    monkeypatch.setattr(nexus_main, "uvicorn", object())
    assert nexus_main.main() == 1


def test_main_accepts_non_loopback_with_opt_in_and_token(monkeypatch):
    from kaine.nexus import __main__ as nexus_main

    fake_app = object()
    config = NexusConfig(host="0.0.0.0", non_loopback_allowed=True, operator_token="s3cret")
    monkeypatch.setattr(nexus_main, "_build", _fake_build(fake_app, config))
    ran = []
    monkeypatch.setattr(
        nexus_main,
        "uvicorn",
        type("U", (), {"run": lambda *a, **k: ran.append((a, k))})(),
    )
    assert nexus_main.main() == 0
    assert ran
