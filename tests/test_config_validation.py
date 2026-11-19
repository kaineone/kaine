# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import pytest

from kaine.config import ConfigShapeError, validate_config_shape


def test_valid_config_passes() -> None:
    config = {"modules": {"interoception": True}}
    validate_config_shape(config)


def test_unknown_key_passes_through() -> None:
    # Unknown sections/keys pass through untouched (documented contract).
    config = {"bogus_table": {"x": 1}}
    validate_config_shape(config)


def test_wrong_type_raises() -> None:
    config = {"modules": {"interoception": "yes"}}
    with pytest.raises(ConfigShapeError):
        validate_config_shape(config)


def test_non_dict_modules_raises() -> None:
    config = {"modules": ["interoception"]}
    with pytest.raises(ConfigShapeError):
        validate_config_shape(config)
