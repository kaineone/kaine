# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from pathlib import Path

import pytest

from kaine.nexus.config import NexusConfig, NexusConfigError, load_nexus_config

_LONG_TOKEN = "x" * 32


def _clear_nexus_env(monkeypatch):
    for name in (
        "KAINE_NEXUS_HOST",
        "KAINE_NEXUS_PORT",
        "KAINE_NEXUS_CONVERSATION_ENABLED",
        "KAINE_NEXUS_TOKEN",
        "KAINE_NEXUS_NON_LOOPBACK_ALLOWED",
        "KAINE_NEXUS_ALLOWED_ORIGINS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_defaults():
    cfg = NexusConfig()
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8088
    assert cfg.conversation_enabled is False  # deactivated by default (base-thesis form)
    assert cfg.diagnostics_enabled is True
    assert cfg.conversation_history_lookback == 50
    assert cfg.dev_content_override is False
    assert cfg.operator_token == ""
    assert cfg.allowed_origins == (
        "http://127.0.0.1:8088",
        "http://localhost:8088",
        "http://[::1]:8088",
    )
    assert cfg.host_allowlist == ("127.0.0.1", "localhost", "::1")
    assert cfg.non_loopback_allowed is False
    assert cfg.session_idle_minutes == 720
    assert cfg.session_max_hours == 24
    assert cfg.login_max_failures == 5
    assert cfg.login_failure_window_s == 300


def test_from_mapping_overrides():
    cfg = NexusConfig.from_mapping(
        {
            "host": "0.0.0.0",
            "port": 9000,
            "conversation_enabled": False,
            "diagnostics_enabled": True,
            "conversation_history_lookback": 200,
            "dev_content_override": True,
            "operator_token": _LONG_TOKEN,
            "allowed_origins": ["http://example.com"],
            "host_allowlist": ["example.com"],
            "non_loopback_allowed": True,
            "session_max_hours": 12,
        }
    )
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9000
    assert cfg.conversation_enabled is False
    assert cfg.dev_content_override is True
    assert cfg.operator_token == _LONG_TOKEN
    assert cfg.allowed_origins == ("http://example.com",)
    assert cfg.host_allowlist == ("example.com",)
    assert cfg.non_loopback_allowed is True
    assert cfg.session_max_hours == 12


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
    # Tokens must live in secrets, not the tracked config.
    _clear_nexus_env(monkeypatch)
    config_file = tmp_path / "kaine.toml"
    config_file.write_text("[nexus]\n")
    secrets = tmp_path / "secrets.toml"
    secrets.write_text(f'[nexus]\noperator_token = "{_LONG_TOKEN}-toml"\n')
    monkeypatch.setenv("KAINE_NEXUS_TOKEN", f"{_LONG_TOKEN}-env")
    cfg = load_nexus_config(config_file, secrets_path=secrets)
    assert cfg.operator_token == f"{_LONG_TOKEN}-env"


def test_no_env_leaves_toml_token(tmp_path, monkeypatch):
    _clear_nexus_env(monkeypatch)
    config_file = tmp_path / "kaine.toml"
    config_file.write_text("[nexus]\n")
    secrets = tmp_path / "secrets.toml"
    secrets.write_text(f'[nexus]\noperator_token = "{_LONG_TOKEN}-toml"\n')
    cfg = load_nexus_config(config_file, secrets_path=secrets)
    assert cfg.operator_token == f"{_LONG_TOKEN}-toml"


def test_is_loopback_host():
    from kaine.nexus.__main__ import _is_loopback_host

    assert _is_loopback_host("127.0.0.1") is True
    assert _is_loopback_host("localhost") is True
    assert _is_loopback_host("::1") is True
    assert _is_loopback_host("192.168.1.1") is False
    assert _is_loopback_host("0.0.0.0") is False


def test_load_security_state_encryption_config_propagates_shape_error(
    monkeypatch, tmp_path: Path
):
    """A malformed operator overlay must not be interpreted as disabled encryption."""
    from kaine.config import ConfigShapeError
    from kaine.nexus.__main__ import _load_security_state_encryption_config

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "kaine.toml").write_text(
        '[modules]\nsoma = false\n[security.state_encryption]\nenabled = "true"\n'
    )
    (config_dir / "kaine.operator.toml").write_text("")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ConfigShapeError, match="security.state_encryption.enabled.*expected.*bool"):
        _load_security_state_encryption_config()


def test_build_fork_manager_returns_none_when_encryption_setup_fails(caplog):
    """Encryption setup failure must leave fork/merge state I/O unavailable."""
    import logging

    from kaine.config import ConfigShapeError
    from kaine.nexus.__main__ import _build_fork_manager

    def broken_encryption_loader():
        raise ConfigShapeError("security.state_encryption.enabled expected bool, got str")

    def lifecycle_loader():
        return {}

    with caplog.at_level(logging.ERROR, logger="kaine.nexus"):
        fm, reason = _build_fork_manager(lifecycle_loader, broken_encryption_loader)

    assert fm is None
    assert reason == "the state-encryption posture could not be installed"
    assert any(
        "state-encryption setup failed; fork/merge state operations are disabled" in rec.message
        and "ConfigShapeError" in rec.message
        for rec in caplog.records
    )


def test_build_fork_manager_returns_fork_manager_when_encryption_disabled(
    caplog, tmp_path: Path
):
    """A valid, disabled encryption posture allows ForkManager construction."""
    import logging

    from kaine.nexus.__main__ import _build_fork_manager

    def encryption_loader():
        return {"enabled": False}

    def lifecycle_loader():
        return {"snapshots_path": str(tmp_path / "forks")}

    with caplog.at_level(logging.WARNING, logger="kaine.nexus"):
        fm, reason = _build_fork_manager(lifecycle_loader, encryption_loader)

    from kaine.lifecycle.manager import ForkManager

    assert isinstance(fm, ForkManager)
    assert reason is None
    assert not any(
        "state-encryption setup failed" in rec.message for rec in caplog.records
    )


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
    config = NexusConfig(host="0.0.0.0", non_loopback_allowed=True, operator_token=_LONG_TOKEN)
    monkeypatch.setattr(nexus_main, "_build", _fake_build(fake_app, config))
    ran = []
    monkeypatch.setattr(
        nexus_main,
        "uvicorn",
        type("U", (), {"run": lambda *a, **k: ran.append((a, k))})(),
    )
    assert nexus_main.main() == 0
    assert ran


def test_token_from_secrets_toml_when_env_unset(monkeypatch, tmp_path):
    _clear_nexus_env(monkeypatch)
    base = tmp_path / "kaine.toml"
    base.write_text("[nexus]\n")
    secrets = tmp_path / "secrets.toml"
    secrets.write_text(f'[nexus]\noperator_token = "{_LONG_TOKEN}-secrets"\n')
    cfg = load_nexus_config(base, secrets_path=secrets)
    assert cfg.operator_token == f"{_LONG_TOKEN}-secrets"


def test_env_token_wins_over_secrets_toml(monkeypatch, tmp_path):
    _clear_nexus_env(monkeypatch)
    base = tmp_path / "kaine.toml"
    base.write_text("[nexus]\n")
    secrets = tmp_path / "secrets.toml"
    secrets.write_text(f'[nexus]\noperator_token = "{_LONG_TOKEN}-secrets"\n')
    monkeypatch.setenv("KAINE_NEXUS_TOKEN", f"{_LONG_TOKEN}-env")
    cfg = load_nexus_config(base, secrets_path=secrets)
    assert cfg.operator_token == f"{_LONG_TOKEN}-env"


def test_env_token_empty_falls_back_to_secrets_toml(monkeypatch, tmp_path):
    _clear_nexus_env(monkeypatch)
    base = tmp_path / "kaine.toml"
    base.write_text("[nexus]\n")
    secrets = tmp_path / "secrets.toml"
    secrets.write_text(f'[nexus]\noperator_token = "{_LONG_TOKEN}-secrets"\n')
    monkeypatch.setenv("KAINE_NEXUS_TOKEN", "   ")
    cfg = load_nexus_config(base, secrets_path=secrets)
    assert cfg.operator_token == f"{_LONG_TOKEN}-secrets"


def test_operator_token_in_kaine_toml_refused(monkeypatch, tmp_path):
    _clear_nexus_env(monkeypatch)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "kaine.toml").write_text(f'[nexus]\noperator_token = "{_LONG_TOKEN}-config"\n')
    monkeypatch.chdir(tmp_path)
    with pytest.raises(NexusConfigError) as exc_info:
        load_nexus_config()
    msg = str(exc_info.value)
    assert "kaine.toml" in msg
    assert f"{_LONG_TOKEN}-config" not in msg
    assert "config/secrets.toml" in msg
    assert "KAINE_NEXUS_TOKEN" in msg


def test_operator_token_in_explicit_path_refused(monkeypatch, tmp_path):
    _clear_nexus_env(monkeypatch)
    config_file = tmp_path / "kaine.toml"
    config_file.write_text(f'[nexus]\noperator_token = "{_LONG_TOKEN}-config"\n')
    with pytest.raises(NexusConfigError) as exc_info:
        load_nexus_config(config_file)
    msg = str(exc_info.value)
    assert "kaine.toml" in msg
    assert f"{_LONG_TOKEN}-config" not in msg
    assert "config/secrets.toml" in msg
    assert "KAINE_NEXUS_TOKEN" in msg


def test_operator_token_in_overlay_refused(monkeypatch, tmp_path):
    _clear_nexus_env(monkeypatch)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "kaine.toml").write_text("[nexus]\nport = 8088\n")
    (config_dir / "kaine.operator.toml").write_text(
        f'[nexus]\noperator_token = "{_LONG_TOKEN}-overlay"\n'
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(NexusConfigError) as exc_info:
        load_nexus_config()
    msg = str(exc_info.value)
    assert "kaine.operator.toml" in msg
    assert f"{_LONG_TOKEN}-overlay" not in msg
    assert "config/secrets.toml" in msg
    assert "KAINE_NEXUS_TOKEN" in msg


def test_overlay_nexus_values_deep_merged(monkeypatch, tmp_path):
    _clear_nexus_env(monkeypatch)
    base = tmp_path / "kaine.toml"
    base.write_text(
        '[nexus]\nport = 8088\nhost_allowlist = ["127.0.0.1", "localhost"]\n'
    )
    overlay = tmp_path / "kaine.operator.toml"
    overlay.write_text('[nexus]\nport = 9099\nhost_allowlist = ["example.com"]\n')
    cfg = load_nexus_config(base, operator_path=overlay)
    assert cfg.port == 9099
    assert cfg.host_allowlist == ("example.com",)


def test_malformed_overlay_raises(monkeypatch, tmp_path):
    _clear_nexus_env(monkeypatch)
    base = tmp_path / "kaine.toml"
    base.write_text("[nexus]\nport = 8088\n")
    overlay = tmp_path / "kaine.operator.toml"
    overlay.write_text("not valid toml [[")
    with pytest.raises(NexusConfigError) as exc_info:
        load_nexus_config(base, operator_path=overlay)
    msg = str(exc_info.value)
    assert "kaine.operator.toml" in msg
    assert "malformed" in msg.lower()


def test_malformed_secrets_raises(monkeypatch, tmp_path):
    _clear_nexus_env(monkeypatch)
    base = tmp_path / "kaine.toml"
    base.write_text("[nexus]\n")
    secrets = tmp_path / "secrets.toml"
    secrets.write_text("not valid toml [[")
    with pytest.raises(NexusConfigError) as exc_info:
        load_nexus_config(base, secrets_path=secrets)
    msg = str(exc_info.value)
    assert "secrets.toml" in msg
    assert "malformed" in msg.lower()


def test_short_env_token_refused(monkeypatch, tmp_path):
    _clear_nexus_env(monkeypatch)
    base = tmp_path / "kaine.toml"
    base.write_text("[nexus]\n")
    monkeypatch.setenv("KAINE_NEXUS_TOKEN", "tok-9f3Q")
    with pytest.raises(NexusConfigError) as exc_info:
        load_nexus_config(base)
    msg = str(exc_info.value)
    assert "operator token is shorter than 32 characters" in msg
    assert "tok-9f3Q" not in msg


def test_short_secrets_token_refused(monkeypatch, tmp_path):
    _clear_nexus_env(monkeypatch)
    base = tmp_path / "kaine.toml"
    base.write_text("[nexus]\n")
    secrets = tmp_path / "secrets.toml"
    secrets.write_text('[nexus]\noperator_token = "tok-9f3Q"\n')
    with pytest.raises(NexusConfigError) as exc_info:
        load_nexus_config(base, secrets_path=secrets)
    msg = str(exc_info.value)
    assert "operator token is shorter than 32 characters" in msg
    assert "tok-9f3Q" not in msg


def test_whitespace_stripped_env_token(monkeypatch, tmp_path):
    _clear_nexus_env(monkeypatch)
    base = tmp_path / "kaine.toml"
    base.write_text("[nexus]\n")
    monkeypatch.setenv("KAINE_NEXUS_TOKEN", f"   {_LONG_TOKEN}   ")
    cfg = load_nexus_config(base)
    assert cfg.operator_token == _LONG_TOKEN


def test_derived_allowed_origins_follow_env_port(monkeypatch, tmp_path):
    _clear_nexus_env(monkeypatch)
    base = tmp_path / "kaine.toml"
    base.write_text("[nexus]\n")
    monkeypatch.setenv("KAINE_NEXUS_PORT", "9000")
    cfg = load_nexus_config(base)
    assert cfg.allowed_origins == (
        "http://127.0.0.1:9000",
        "http://localhost:9000",
        "http://[::1]:9000",
    )


def test_env_allowed_origins_override(monkeypatch, tmp_path):
    _clear_nexus_env(monkeypatch)
    base = tmp_path / "kaine.toml"
    base.write_text('[nexus]\nallowed_origins = ["http://keep.com"]\n')
    monkeypatch.setenv("KAINE_NEXUS_ALLOWED_ORIGINS", "http://a.com, http://b.com")
    cfg = load_nexus_config(base)
    assert cfg.allowed_origins == ("http://a.com", "http://b.com")


def test_explicit_allowed_origins_kept(monkeypatch, tmp_path):
    _clear_nexus_env(monkeypatch)
    base = tmp_path / "kaine.toml"
    base.write_text('[nexus]\nallowed_origins = ["http://explicit:8088"]\n')
    monkeypatch.setenv("KAINE_NEXUS_PORT", "7777")
    cfg = load_nexus_config(base)
    assert cfg.allowed_origins == ("http://explicit:8088",)


def test_env_non_loopback_allowed(monkeypatch, tmp_path):
    _clear_nexus_env(monkeypatch)
    base = tmp_path / "kaine.toml"
    base.write_text("[nexus]\nnon_loopback_allowed = false\n")
    monkeypatch.setenv("KAINE_NEXUS_NON_LOOPBACK_ALLOWED", "1")
    cfg = load_nexus_config(base)
    assert cfg.non_loopback_allowed is True


def test_session_and_login_fields_parse_with_defaults(monkeypatch, tmp_path):
    _clear_nexus_env(monkeypatch)
    base = tmp_path / "kaine.toml"
    base.write_text(
        "[nexus]\n"
        "session_idle_minutes = 30\n"
        "session_max_hours = 12\n"
        "login_max_failures = 3\n"
        "login_failure_window_s = 60\n"
    )
    cfg = load_nexus_config(base)
    assert cfg.session_idle_minutes == 30
    assert cfg.session_max_hours == 12
    assert cfg.login_max_failures == 3
    assert cfg.login_failure_window_s == 60

    defaults = NexusConfig()
    assert defaults.session_idle_minutes == 720
    assert defaults.session_max_hours == 24
    assert defaults.login_max_failures == 5
    assert defaults.login_failure_window_s == 300


def test_main_explains_missing_bus_setup_without_traceback(monkeypatch, caplog):
    import logging

    from kaine.bus.errors import BusConfigError
    from kaine.nexus import __main__ as nexus_main

    async def _broken():
        raise BusConfigError("no Redis password found")

    monkeypatch.setattr(nexus_main, "_build", _broken)

    with caplog.at_level(logging.ERROR):
        rc = nexus_main.main()

    assert rc == 1
    assert any("bash scripts/redis-bootstrap.sh" in rec.message for rec in caplog.records)
    assert not any(rec.exc_info for rec in caplog.records)


def test_main_refuses_when_no_console_enabled(monkeypatch, caplog):
    import logging

    from kaine.nexus import __main__ as nexus_main

    config = NexusConfig(conversation_enabled=False, diagnostics_enabled=False)
    fake_app = object()

    class UvicornRecorder:
        def __init__(self):
            self.calls = []
        def run(self, app, *, host, port):
            self.calls.append((app, host, port))

    uvicorn = UvicornRecorder()
    monkeypatch.setattr(nexus_main, "_build", _fake_build(fake_app, config))
    monkeypatch.setattr(nexus_main, "uvicorn", uvicorn)

    with caplog.at_level(logging.ERROR):
        rc = nexus_main.main()

    assert rc == 1
    assert not uvicorn.calls
    assert any("no console is enabled" in rec.message for rec in caplog.records)


def test_main_serves_with_diagnostics_only(monkeypatch):
    from kaine.nexus import __main__ as nexus_main

    config = NexusConfig(conversation_enabled=False, diagnostics_enabled=True)
    fake_app = object()

    class UvicornRecorder:
        def __init__(self):
            self.calls = []
        def run(self, app, *, host, port):
            self.calls.append((app, host, port))

    uvicorn = UvicornRecorder()
    monkeypatch.setattr(nexus_main, "_build", _fake_build(fake_app, config))
    monkeypatch.setattr(nexus_main, "uvicorn", uvicorn)

    rc = nexus_main.main()

    assert rc == 0
    assert uvicorn.calls == [(fake_app, config.host, config.port)]
