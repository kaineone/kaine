# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for kaine.lifecycle.manager.merger_from_name selection."""
from __future__ import annotations

from pathlib import Path

import pytest

from kaine.lifecycle.manager import FakeAdapterMerger, merger_from_name


def test_fake_name_returns_fake_merger():
    m = merger_from_name("fake")
    assert isinstance(m, FakeAdapterMerger)


def test_ties_dare_name_returns_ties_dare_merger(tmp_path: Path):
    from kaine.lifecycle.adapter_merge import TiesDareAdapterMerger

    m = merger_from_name(
        "ties_dare",
        config_section={
            "output_dir": str(tmp_path / "merged"),
            "combination_type": "dare_ties",
            "density": 0.5,
            "base_model_path": str(tmp_path / "base"),
        },
    )
    assert isinstance(m, TiesDareAdapterMerger)


def test_ties_dare_honors_combination_type(tmp_path: Path):
    from kaine.lifecycle.adapter_merge import TiesDareAdapterMerger

    m = merger_from_name(
        "ties_dare",
        config_section={
            "combination_type": "ties",
            "density": 0.7,
            "base_model_path": str(tmp_path / "base"),
        },
    )
    assert isinstance(m, TiesDareAdapterMerger)
    assert m._config.combination_type == "ties"
    assert m._config.density == pytest.approx(0.7)


def test_ties_dare_invalid_combination_type_raises(tmp_path: Path):
    with pytest.raises(ValueError):
        merger_from_name(
            "ties_dare",
            config_section={"combination_type": "garbage"},
        )


def test_unknown_name_raises():
    with pytest.raises(ValueError) as exc:
        merger_from_name("nonsense")
    assert "known values" in str(exc.value)


def test_ties_dare_empty_section_uses_defaults(tmp_path: Path):
    from kaine.lifecycle.adapter_merge import TiesDareAdapterMerger

    m = merger_from_name("ties_dare", config_section=None)
    assert isinstance(m, TiesDareAdapterMerger)
    assert m._config.combination_type == "dare_ties"
    assert m._config.density == pytest.approx(0.5)
    assert m._config.base_model_path is None


def test_ties_dare_with_blank_base_model_path(tmp_path: Path):
    from kaine.lifecycle.adapter_merge import TiesDareAdapterMerger

    m = merger_from_name(
        "ties_dare",
        config_section={"base_model_path": "   "},
    )
    assert isinstance(m, TiesDareAdapterMerger)
    assert m._config.base_model_path is None
