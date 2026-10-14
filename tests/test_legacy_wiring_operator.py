# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for legacy-name wiring readers in operator-facing seams."""

import argparse
import logging
import shutil
from pathlib import Path

import pytest

from kaine import legacy_aliases, legacy_names
from kaine.config import (
    ProfileError,
    _load_merged_config,
    validate_config_shape,
)
from kaine.cycle import __main__ as cycle_main
from kaine.dashboard.config import DashboardConfigError, load_dashboard_config
from kaine.modules.embodiment.module import operator_approved
from kaine.plugins import PluginError, load_plugins
from kaine.research.ignition_study.__main__ import _build_parser
from kaine.setup.dashboard_token import ensure_dashboard_token


class FakeDist:
    def __init__(self, name: str, version: str):
        self.name = name
        self.version = version


class FakeEP:
    def __init__(self, name: str, factory, dist=None):
        self.name = name
        self._factory = factory
        self.dist = dist

    def load(self):
        return self._factory


class _ConfigurablePlugin:
    def __init__(self, name, seams, injections=None, maker=None):
        self.name = name
        self._seams = frozenset(seams)
        self._injections = injections or {}
        self._maker = maker
        self.inject_calls = 0
        self.make_calls = 0
        self.seen_config = None

    def seams(self, config):
        self.seen_config = config
        return self._seams

    def injections(self, module, config):
        self.inject_calls += 1
        return self._injections.get(module, {})

    def make_oscillator(self, module, config, defaults):
        self.make_calls += 1
        if callable(self._maker):
            return self._maker(module, config, defaults)
        return self._maker


def _eps(*eps):
    return lambda group="kaine.plugins": list(eps)


_REPO_ROOT = Path(__file__).resolve().parent.parent
_SHIPPED_CONFIG = _REPO_ROOT / "config" / "kaine.toml"


def _hermetic_cwd(tmp_path: Path, monkeypatch) -> None:
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_SHIPPED_CONFIG, cfg_dir / "kaine.toml")
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def _noop_shape(monkeypatch):
    """Disable strict shape validation for minimal synthetic config files."""
    monkeypatch.setattr(validate_config_shape, "__call__", lambda self, cfg: None)
    monkeypatch.setattr("kaine.config.validate_config_shape", lambda cfg: None)


def test_config_table_alias_normalized(tmp_path, monkeypatch, caplog, _noop_shape):
    monkeypatch.setattr(
        legacy_names,
        "CONFIG_TABLES",
        ({"old": "oldnexus", "new": "nexus", "scope": "keys"},),
    )
    monkeypatch.setattr(legacy_names, "CONFIG_KEYS", ())
    monkeypatch.setattr(legacy_names, "CONFIG_VALUES", ())
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")

    shipped = tmp_path / "kaine.toml"
    shipped.write_text("[nexus]\nport = 1\n")
    operator = tmp_path / "kaine.operator.toml"
    operator.write_text("[oldnexus]\nport = 2\n")

    with caplog.at_level(logging.WARNING, logger="kaine.legacy"):
        merged = _load_merged_config(
            path=shipped,
            operator_path=operator,
            profiles_dir=tmp_path,
            studies_dir=tmp_path,
        )

    assert merged["nexus"]["port"] == 2
    assert "oldnexus" not in merged
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert str(operator) in warnings[0].message


def test_config_table_alias_conflict(tmp_path, monkeypatch, _noop_shape):
    monkeypatch.setattr(
        legacy_names,
        "CONFIG_TABLES",
        ({"old": "oldnexus", "new": "nexus", "scope": "keys"},),
    )
    monkeypatch.setattr(legacy_names, "CONFIG_KEYS", ())
    monkeypatch.setattr(legacy_names, "CONFIG_VALUES", ())
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")

    shipped = tmp_path / "kaine.toml"
    shipped.write_text("[nexus]\nport = 1\n")
    operator = tmp_path / "kaine.operator.toml"
    operator.write_text("[oldnexus]\nport = 2\n\n[nexus]\nport = 3\n")

    with pytest.raises(ProfileError) as exc_info:
        _load_merged_config(
            path=shipped,
            operator_path=operator,
            profiles_dir=tmp_path,
            studies_dir=tmp_path,
        )
    msg = str(exc_info.value)
    assert "oldnexus" in msg
    assert "nexus" in msg


def test_study_table_alias_allowed_after_normalization(tmp_path, monkeypatch, _noop_shape):
    monkeypatch.setattr(
        legacy_names,
        "CONFIG_TABLES",
        ({"old": "oldlingua", "new": "lingua", "scope": "keys"},),
    )
    monkeypatch.setattr(legacy_names, "CONFIG_KEYS", ())
    monkeypatch.setattr(legacy_names, "CONFIG_VALUES", ())
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")
    monkeypatch.setattr("kaine.config.STUDY_ALLOWED_TABLES", {"lingua"})
    monkeypatch.setattr("kaine.config.STUDY_ALLOWED_KEYS", {})

    shipped = tmp_path / "kaine.toml"
    shipped.write_text("[lingua]\n")
    study_file = tmp_path / "s.toml"
    study_file.write_text("[oldlingua]\nx = 1\n")

    merged = _load_merged_config(
        path=shipped,
        operator_path=tmp_path / "missing.operator.toml",
        profiles_dir=tmp_path,
        study="s",
        studies_dir=tmp_path,
    )

    assert merged["lingua"]["x"] == 1


def _current_key(old: str) -> str:
    """The module key the code uses now: the new key once the keys step is done."""
    if legacy_names.SCOPE_STATUS.get("keys") == "done":
        return legacy_names.MODULES[old]["new_key"]
    return old


_DASHBOARD = _current_key("nexus")
_INTEROCEPTION = _current_key("soma")


def test_dashboard_config_table_alias(tmp_path, monkeypatch):
    monkeypatch.setattr(
        legacy_names,
        "CONFIG_TABLES",
        ({"old": "oldnexus", "new": _DASHBOARD, "scope": "keys"},),
    )
    monkeypatch.setattr(legacy_names, "CONFIG_KEYS", ())
    monkeypatch.setattr(legacy_names, "CONFIG_VALUES", ())
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")

    shipped = tmp_path / "kaine.toml"
    shipped.write_text(f"[{_DASHBOARD}]\nport = 8088\n")
    overlay = tmp_path / "kaine.operator.toml"
    overlay.write_text("[oldnexus]\nport = 9100\n")

    cfg = load_dashboard_config(
        path=shipped,
        operator_path=overlay,
        secrets_path=tmp_path / "none.toml",
    )
    assert cfg.port == 9100


def test_dashboard_env_alias_conflict(monkeypatch, tmp_path):
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "operator", "done")
    monkeypatch.setattr(legacy_aliases, "_env_warnings_seen", set())

    shipped = tmp_path / "kaine.toml"
    shipped.write_text("[nexus]\nport = 8088\n")
    secrets = tmp_path / "none.toml"

    monkeypatch.setenv("KAINE_NEXUS_PORT", "9200")
    monkeypatch.delenv("KAINE_DASHBOARD_PORT", raising=False)
    cfg = load_dashboard_config(path=shipped, secrets_path=secrets)
    assert cfg.port == 9200

    monkeypatch.setenv("KAINE_DASHBOARD_PORT", "9300")
    with pytest.raises(DashboardConfigError) as exc_info:
        load_dashboard_config(path=shipped, secrets_path=secrets)
    msg = str(exc_info.value)
    assert "KAINE_NEXUS_PORT" in msg
    assert "KAINE_DASHBOARD_PORT" in msg
    assert "9200" not in msg
    assert "9300" not in msg


def test_embodiment_operator_approved_alias(monkeypatch):
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "operator", "done")
    monkeypatch.setattr(legacy_aliases, "_env_warnings_seen", set())
    monkeypatch.delenv("KAINE_MUNDUS_OPERATOR_APPROVED", raising=False)
    monkeypatch.delenv("KAINE_EMBODIMENT_OPERATOR_APPROVED", raising=False)

    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    assert operator_approved() is True

    monkeypatch.setenv("KAINE_EMBODIMENT_OPERATOR_APPROVED", "0")
    with pytest.raises(legacy_aliases.LegacyNameConflict) as exc_info:
        operator_approved()
    msg = str(exc_info.value)
    assert "KAINE_MUNDUS_OPERATOR_APPROVED" in msg
    assert "KAINE_EMBODIMENT_OPERATOR_APPROVED" in msg


def test_cycle_refuses_env_conflict(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        legacy_names,
        "ENV_VARS",
        (
            {
                "old": "KAINE_OLDMUNDUS_APPROVED",
                "new": "KAINE_MUNDUS_OPERATOR_APPROVED",
                "scope": "operator",
            },
        ),
    )
    monkeypatch.setattr(legacy_names, "COMPOSE_VARS", ())
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "operator", "done")
    monkeypatch.setattr(legacy_aliases, "_env_warnings_seen", set())

    _hermetic_cwd(tmp_path, monkeypatch)
    monkeypatch.setenv("KAINE_CYCLE_OPERATOR_PRESENT", "1")
    monkeypatch.setenv("KAINE_OLDMUNDUS_APPROVED", "1")
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "0")

    calls = []

    async def fake_boot(*args, **kwargs):
        calls.append((args, kwargs))
        return 0

    monkeypatch.setattr(cycle_main, "_boot_and_run", fake_boot)

    result = cycle_main.main([])
    assert result == 1
    err = capsys.readouterr().err
    assert "configuration error" in err
    assert "KAINE_OLDMUNDUS_APPROVED" in err
    assert "KAINE_MUNDUS_OPERATOR_APPROVED" in err
    assert not calls


def test_setup_token_reads_old_env(monkeypatch, tmp_path):
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "operator", "done")
    monkeypatch.setattr(legacy_aliases, "_env_warnings_seen", set())

    lines = []
    token = "x" * 40
    source = ensure_dashboard_token(
        tmp_path / "secrets.toml",
        out=lines.append,
        env={"KAINE_NEXUS_TOKEN": token},
    )
    assert source == "env"


def test_cli_flag_alias(monkeypatch):
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "operator", "done")

    args = _build_parser().parse_args(
        ["init", "--study-id", "s", "--programme-manifest", "m.json", "--db-gestation", "7"]
    )
    assert args.db_development == 7

    parser = _build_parser()
    sub_action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    init_parser = sub_action.choices["init"]
    assert "--db-gestation" not in init_parser.format_help()


def test_cli_flag_alias_pending_rejected(monkeypatch):
    monkeypatch.setattr(
        legacy_names,
        "CLI_FLAGS",
        ({"old": "--db-oldname", "new": "--db-gestation", "scope": "operator"},),
    )
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "operator", "pending")

    with pytest.raises(SystemExit):
        _build_parser().parse_args(
            ["init", "--study-id", "s", "--programme-manifest", "m.json", "--db-oldname", "7"]
        )


def test_plugin_seam_alias(monkeypatch):
    monkeypatch.setattr(
        legacy_names,
        "PLUGIN_SEAMS",
        ({"old": "oldsoma.forward_model", "new": f"{_INTEROCEPTION}.forward_model", "scope": "keys"},),
    )
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")

    forward_model = object()
    plugin = _ConfigurablePlugin(
        "p",
        seams={"oldsoma.forward_model"},
        injections={"oldsoma": {"forward_model": forward_model}},
    )

    loaded = load_plugins(
        {"plugins": {"enabled": ["p"]}},
        known_modules=[_INTEROCEPTION],
        entry_points=_eps(FakeEP("p", lambda: plugin)),
    )

    assert loaded.manifest_entry()["p"]["seams"] == [f"{_INTEROCEPTION}.forward_model"]
    assert loaded.injections_for(_INTEROCEPTION) == {"forward_model": forward_model}


def test_plugin_seam_alias_pending_rejected(monkeypatch):
    monkeypatch.setattr(
        legacy_names,
        "PLUGIN_SEAMS",
        ({"old": "oldsoma.forward_model", "new": f"{_INTEROCEPTION}.forward_model", "scope": "keys"},),
    )
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "pending")

    forward_model = object()
    plugin = _ConfigurablePlugin(
        "p",
        seams={"oldsoma.forward_model"},
        injections={"oldsoma": {"forward_model": forward_model}},
    )

    with pytest.raises(PluginError, match="unknown seam"):
        load_plugins(
            {"plugins": {"enabled": ["p"]}},
            known_modules=[_INTEROCEPTION],
            entry_points=_eps(FakeEP("p", lambda: plugin)),
        )


def test_wiring_inert_while_pending(monkeypatch):
    for scope in list(legacy_names.SCOPE_STATUS):
        monkeypatch.setitem(legacy_names.SCOPE_STATUS, scope, "pending")

    layer = {"thymos": {"x": 1}}
    assert legacy_aliases.normalize_config_layer(layer, "f") is layer
    legacy_aliases.check_environment(environ={"KAINE_NEXUS_PORT": "1", "KAINE_DASHBOARD_PORT": "2"})


def test_setup_token_conflict_is_reported_not_raised(monkeypatch, tmp_path):
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "operator", "done")
    monkeypatch.setattr(legacy_aliases, "_env_warnings_seen", set())

    lines = []
    env = {
        "KAINE_NEXUS_TOKEN": "a" * 40,
        "KAINE_DASHBOARD_TOKEN": "b" * 40,
    }
    source = ensure_dashboard_token(
        tmp_path / "secrets.toml",
        out=lines.append,
        env=env,
    )
    assert source == "conflict"
    output = "".join(lines)
    assert "KAINE_NEXUS_TOKEN" in output
    assert "KAINE_DASHBOARD_TOKEN" in output
    assert "a" * 40 not in output
    assert "b" * 40 not in output
    assert not (tmp_path / "secrets.toml").exists()
