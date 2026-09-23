# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for merged configuration shape validation."""
from __future__ import annotations

from pathlib import Path

import pytest

from kaine.config import ConfigShapeError, ProfileError, load_kaine_config

REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_config(tmp_path: Path, base_text: str, operator_text: str) -> tuple[Path, Path]:
    shipped = tmp_path / "kaine.toml"
    shipped.write_text(base_text)
    op = tmp_path / "kaine.operator.toml"
    op.write_text(operator_text)
    return shipped, op


def test_config_shape_error_is_profile_error():
    assert issubclass(ConfigShapeError, ProfileError)


def test_modules_must_be_table(tmp_path: Path):
    shipped, op = _write_config(
        tmp_path,
        '[modules]\nsoma = false\n',
        'modules = []\n',
    )
    with pytest.raises(ConfigShapeError, match=r"modules.*expected.*table"):
        load_kaine_config(shipped, op, strict_operator=True)


def test_modules_toggle_string_rejected(tmp_path: Path):
    shipped, op = _write_config(
        tmp_path,
        '[modules]\nsoma = false\n',
        '[modules]\nsoma = "SECRETVOICE"\n',
    )
    with pytest.raises(ConfigShapeError, match=r"modules\.soma.*expected.*bool") as exc_info:
        load_kaine_config(shipped, op, strict_operator=True)
    assert "SECRETVOICE" not in str(exc_info.value)


def test_modules_toggle_int_rejected(tmp_path: Path):
    shipped, op = _write_config(
        tmp_path,
        '[modules]\nsoma = false\n',
        '[modules]\nsoma = 1\n',
    )
    with pytest.raises(ConfigShapeError, match=r"modules\.soma.*expected.*bool") as exc_info:
        load_kaine_config(shipped, op, strict_operator=True)
    assert "1" not in str(exc_info.value)


def test_tier_must_be_table(tmp_path: Path):
    shipped, op = _write_config(
        tmp_path,
        '[modules]\nsoma = false\n',
        'tier = "tier0"\n',
    )
    with pytest.raises(ConfigShapeError, match=r"tier.*expected.*table"):
        load_kaine_config(shipped, op, strict_operator=True)


def test_tier_name_must_be_string(tmp_path: Path):
    shipped, op = _write_config(
        tmp_path,
        '[modules]\nsoma = false\n',
        '[tier]\nname = 123\nunsupported_modules = []\noscillator_supported = false\n',
    )
    with pytest.raises(ConfigShapeError, match=r"tier\.name.*expected.*string") as exc_info:
        load_kaine_config(shipped, op, strict_operator=True)
    assert "123" not in str(exc_info.value)


def test_tier_unsupported_modules_must_be_list(tmp_path: Path):
    shipped, op = _write_config(
        tmp_path,
        '[modules]\nsoma = false\n',
        '[tier]\nname = "tier0"\nunsupported_modules = "SECRETVOICE"\noscillator_supported = false\n',
    )
    with pytest.raises(ConfigShapeError, match=r"tier\.unsupported_modules.*expected.*list") as exc_info:
        load_kaine_config(shipped, op, strict_operator=True)
    assert "SECRETVOICE" not in str(exc_info.value)


def test_tier_unsupported_modules_elements_must_be_strings(tmp_path: Path):
    shipped, op = _write_config(
        tmp_path,
        '[modules]\nsoma = false\n',
        '[tier]\nname = "tier0"\nunsupported_modules = ["lingua", 123]\noscillator_supported = false\n',
    )
    with pytest.raises(ConfigShapeError, match=r"tier\.unsupported_modules.*expected.*string") as exc_info:
        load_kaine_config(shipped, op, strict_operator=True)
    assert "123" not in str(exc_info.value)


def test_tier_oscillator_supported_must_be_bool(tmp_path: Path):
    shipped, op = _write_config(
        tmp_path,
        '[modules]\nsoma = false\n',
        '[tier]\nname = "tier0"\nunsupported_modules = []\noscillator_supported = "true"\n',
    )
    with pytest.raises(ConfigShapeError, match=r"tier\.oscillator_supported.*expected.*bool") as exc_info:
        load_kaine_config(shipped, op, strict_operator=True)
    assert "true" not in str(exc_info.value)


def test_oscillator_must_be_table(tmp_path: Path):
    shipped, op = _write_config(
        tmp_path,
        '[modules]\nsoma = false\n',
        'oscillator = true\n',
    )
    with pytest.raises(ConfigShapeError, match=r"oscillator.*expected.*table"):
        load_kaine_config(shipped, op, strict_operator=True)


def test_oscillator_enabled_must_be_bool(tmp_path: Path):
    shipped, op = _write_config(
        tmp_path,
        '[modules]\nsoma = false\n',
        '[oscillator]\nenabled = "SECRETVOICE"\n',
    )
    with pytest.raises(ConfigShapeError, match=r"oscillator\.enabled.*expected.*bool") as exc_info:
        load_kaine_config(shipped, op, strict_operator=True)
    assert "SECRETVOICE" not in str(exc_info.value)


def test_deployment_tier_must_be_string(tmp_path: Path):
    shipped, op = _write_config(
        tmp_path,
        '[modules]\nsoma = false\n',
        '[deployment]\ntier = 2\n',
    )
    with pytest.raises(ConfigShapeError, match=r"deployment\.tier.*expected.*string") as exc_info:
        load_kaine_config(shipped, op, strict_operator=True)
    assert "2" not in str(exc_info.value)


def test_security_state_encryption_enabled_must_be_bool(tmp_path: Path):
    shipped, op = _write_config(
        tmp_path,
        '[modules]\nsoma = false\n',
        '[security.state_encryption]\nenabled = "SECRETVOICE"\n',
    )
    with pytest.raises(ConfigShapeError, match=r"security\.state_encryption\.enabled.*expected.*bool") as exc_info:
        load_kaine_config(shipped, op, strict_operator=True)
    assert "SECRETVOICE" not in str(exc_info.value)


def test_unknown_sections_pass_through(tmp_path: Path):
    shipped, op = _write_config(
        tmp_path,
        '[modules]\nsoma = false\n',
        '[foo]\nbar = 123\nbaz = "hello"\n',
    )
    cfg = load_kaine_config(shipped, op, strict_operator=True)
    assert cfg["foo"]["bar"] == 123
    assert cfg["foo"]["baz"] == "hello"


def test_real_configs_and_profiles_validate(tmp_path: Path):
    """Shipped config, every profile as a profile, and every tier file as a tier pass shape validation."""
    profiles_dir = REPO_ROOT / "config" / "profiles"
    profile_paths = sorted(profiles_dir.glob("*.toml"))
    assert profile_paths
    for p in profile_paths:
        name = p.stem
        # As a module profile.
        load_kaine_config(
            REPO_ROOT / "config" / "kaine.toml",
            tmp_path / "nonexistent-operator.toml",
            profile=name,
            tier=None,
            profiles_dir=profiles_dir,
            strict_operator=True,
        )
        # As a tier only if the file actually carries the advisory [tier] table.
        text = p.read_text()
        if "[tier]" in text:
            load_kaine_config(
                REPO_ROOT / "config" / "kaine.toml",
                tmp_path / "nonexistent-operator.toml",
                profile=None,
                tier=name,
                profiles_dir=profiles_dir,
                strict_operator=True,
            )
