# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for ``kaine.config.list_all_defaults``."""

import tomllib

from kaine.config import SHIPPED_CONFIG_PATH, list_all_defaults


def _sorted(value):
    if isinstance(value, dict):
        return {key: _sorted(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sorted(item) for item in value]
    return value


def test_list_all_defaults_returns_sorted_dict():
    result = list_all_defaults()
    assert isinstance(result, dict)
    assert list(result.keys()) == sorted(result.keys())
    for nested in result.values():
        if isinstance(nested, dict):
            assert list(nested.keys()) == sorted(nested.keys())


def test_list_all_defaults_matches_shipped_config():
    with SHIPPED_CONFIG_PATH.open("rb") as fh:
        raw = tomllib.load(fh)
    assert list_all_defaults() == _sorted(raw)


def test_list_all_defaults_includes_modules_table():
    result = list_all_defaults()
    assert "modules" in result
    assert isinstance(result["modules"], dict)
    assert "recorder" in result["modules"]
    # shipped config disables every module by default
    assert all(value is False for value in result["modules"].values())
