# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Each wired config reader maps old names once the keys step is done; each test fails if its call site loses the mapping."""

import io

import pytest

from kaine import legacy_aliases, legacy_names
from kaine.bus import config as bus_config
from kaine.research.ignition_study import overlay as study_overlay
from kaine.setup import __main__ as setup_main
from kaine.setup import wizard_core
from kaine.setup.web import app as setup_web_app


def _keys_done(monkeypatch):
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")


def test_study_overlay_loader_maps_old_names(tmp_path, monkeypatch):
    """_load_toml maps legacy names when keys step is done."""
    _keys_done(monkeypatch)
    path = tmp_path / "overlay.toml"
    path.write_text('[thymos]\nsoma_stream = "soma.out"\n', encoding="utf-8")
    result = study_overlay._load_toml(path)
    assert result == {"affect": {"interoception_stream": "interoception.out"}}


def test_setup_web_loader_maps_old_names(tmp_path, monkeypatch):
    """_load_existing maps legacy names when keys step is done."""
    _keys_done(monkeypatch)
    path = tmp_path / "operator.toml"
    path.write_text('[thymos]\nsoma_stream = "soma.out"\n', encoding="utf-8")
    result = setup_web_app._load_existing(path)
    assert result == {"affect": {"interoception_stream": "interoception.out"}}


def test_setup_cli_merges_onto_mapped_operator_file(tmp_path, monkeypatch):
    """main passes a normalized operator file to run_wizard."""
    _keys_done(monkeypatch)

    class _Stop(Exception):
        pass

    captured = {}

    def fake_run_wizard(*, existing_config, **kwargs):
        captured["existing_config"] = existing_config
        raise _Stop()

    monkeypatch.setattr(setup_main, "run_wizard", fake_run_wizard)
    monkeypatch.setattr(setup_main, "_describe_host_with_cpu", lambda: None)
    monkeypatch.setattr(setup_main, "install_data_root", lambda *args, **kwargs: None)

    op = tmp_path / "operator.toml"
    op.write_text('[thymos]\nsoma_stream = "soma.out"\n', encoding="utf-8")

    out = io.StringIO()
    with pytest.raises(_Stop):
        setup_main.main(["--defaults", "--operator-path", str(op)], out=out)

    assert captured["existing_config"] == {"affect": {"interoception_stream": "interoception.out"}}


def test_first_configuration_profile_maps_old_module_names(tmp_path, monkeypatch):
    """first_configuration_modules maps legacy module keys when keys step is done."""
    _keys_done(monkeypatch)
    profiles_dir = tmp_path / "profiles"
    profile = profiles_dir / "first_configuration.toml"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text("[modules]\nsoma = true\nthymos = false\n", encoding="utf-8")
    monkeypatch.setattr(wizard_core, "MODULE_ORDER", [legacy_aliases.map_module_key(m) for m in wizard_core.MODULE_ORDER])
    result = wizard_core.first_configuration_modules(profiles_dir=profiles_dir)
    assert result[legacy_aliases.map_module_key("soma")] is True
    assert result[legacy_aliases.map_module_key("thymos")] is False
    assert "soma" not in result


def test_bus_config_maps_old_stream_caps(tmp_path, monkeypatch):
    """load_bus_config maps legacy stream names in per_stream_maxlen."""
    _keys_done(monkeypatch)

    kaine_file = tmp_path / "kaine.toml"
    secrets_file = tmp_path / "secrets.toml"
    operator_file = tmp_path / "operator.toml"

    kaine_file.write_text(
        '[redis]\nhost = "127.0.0.1"\nport = 6379\n[bus.per_stream_maxlen]\n"soma.out" = 7\n',
        encoding="utf-8",
    )
    secrets_file.write_text('[redis]\npassword = "x"\n', encoding="utf-8")
    operator_file.write_text(
        '[bus.per_stream_maxlen]\n"thymos.out" = 9\n', encoding="utf-8"
    )

    cfg = bus_config.load_bus_config(
        kaine_toml=kaine_file,
        secrets_toml=secrets_file,
        env={},
        operator_toml=operator_file,
    )

    assert cfg.per_stream_maxlen["interoception.out"] == 7
    assert cfg.per_stream_maxlen["affect.out"] == 9
