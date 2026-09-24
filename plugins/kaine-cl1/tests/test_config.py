# SPDX-License-Identifier: LicenseRef-CAL-0.2
"""Tests for kaine_cl1.config.load_overlay."""

from pathlib import Path

import pytest
from kaine_cl1.config import load_overlay


def test_example_config_is_not_inert():
    path = Path(__file__).resolve().parents[1] / "config" / "kaine_cl1.example.toml"
    overlay = load_overlay(path)
    assert overlay.cl1_modules() == ["chronos", "soma"]
    assert overlay.territories["chronos"] == 12
    assert overlay.territories["soma"] == 12
    assert overlay.substrate.accelerated_time is True


def test_top_level_form(tmp_path):
    path = tmp_path / "top_level.toml"
    path.write_text(
        """
[substrate]
accelerated_time = true

[substrate.territories]
chronos = 4

[backends]
chronos = "cl1"
"""
    )
    overlay = load_overlay(path)
    assert overlay.cl1_modules() == ["chronos"]
    assert overlay.territories == {"chronos": 4}


def test_plugin_block_form(tmp_path):
    path = tmp_path / "plugin_block.toml"
    path.write_text(
        """
[plugins.cl1.substrate]
accelerated_time = true

[plugins.cl1.substrate.territories]
chronos = 4

[plugins.cl1.backends]
chronos = "cl1"
"""
    )
    overlay = load_overlay(path)
    assert overlay.cl1_modules() == ["chronos"]
    assert overlay.territories == {"chronos": 4}


def test_both_forms_rejected(tmp_path):
    path = tmp_path / "both_forms.toml"
    path.write_text(
        """
[backends]
chronos = "cl1"

[plugins.cl1.backends]
chronos = "cl1"
"""
    )
    with pytest.raises(ValueError):
        load_overlay(path)


def test_empty_file_is_inert(tmp_path):
    path = tmp_path / "empty.toml"
    path.write_text("")
    overlay = load_overlay(path)
    assert overlay.cl1_modules() == []
    assert overlay.territories == {}

