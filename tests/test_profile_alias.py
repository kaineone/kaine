# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The old profile name thesis_test resolves to first_configuration with one deprecation warning."""

import logging

import pytest

from kaine import config as kaine_config
from kaine import legacy_names
from kaine.config import (
    canonical_profile_name,
    load_kaine_config,
    load_runtime_config,
    resolve_profile_name,
)
from kaine.setup.wizard_core import base_thesis_modules, first_configuration_modules

_OPERATOR_PATH = "/nonexistent-operator-for-tests.toml"


@pytest.fixture(autouse=True)
def _reset_alias_warned(monkeypatch):
    """Start each test with an empty alias warning set."""
    monkeypatch.setattr(kaine_config, "_profile_alias_warned", set())


def test_resolve_explicit_alias():
    assert resolve_profile_name("thesis_test", env={}) == "first_configuration"


def test_resolve_env_alias():
    env = {"KAINE_PROFILE": "thesis_test"}
    assert resolve_profile_name(None, env=env) == "first_configuration"


def test_alias_warning_once(caplog):
    caplog.set_level("WARNING", logger="kaine.config")
    resolve_profile_name("thesis_test", env={})
    resolve_profile_name("thesis_test", env={})
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    msg = warnings[0].message
    assert "thesis_test" in msg
    assert "first_configuration" in msg
    assert legacy_names.ALIAS_LAST_RELEASE in msg


def test_canonical_name_logs_nothing(caplog):
    caplog.set_level("WARNING", logger="kaine.config")
    assert canonical_profile_name("first_configuration") == "first_configuration"
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_load_alias_equals_canonical_config():
    alias_cfg = load_kaine_config(
        operator_path=_OPERATOR_PATH, profile="thesis_test"
    )
    canonical_cfg = load_kaine_config(
        operator_path=_OPERATOR_PATH, profile="first_configuration"
    )
    assert alias_cfg == canonical_cfg


def test_runtime_default_uses_first_configuration_modules():
    runtime = load_runtime_config(operator_path=_OPERATOR_PATH, env={})
    explicit = load_kaine_config(
        operator_path=_OPERATOR_PATH, profile="first_configuration"
    )
    assert runtime["modules"] == explicit["modules"]


def test_thesis_test_profile_file_missing():
    assert not (kaine_config.PROFILES_DIR / "thesis_test.toml").exists()


def test_first_configuration_profile_file_exists():
    assert (kaine_config.PROFILES_DIR / "first_configuration.toml").exists()


def test_base_thesis_modules_is_deprecated_alias():
    with pytest.warns(DeprecationWarning):
        deprecated = base_thesis_modules()
    assert deprecated == first_configuration_modules()
