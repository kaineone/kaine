from __future__ import annotations

import pytest

from kaine.config import validate_config_shape


def test_valid_config_passes() -> None:
    config = {"modules": {"interoception": {"enabled": True}}}
    validate_config_shape(config)


def test_unknown_key_warns(caplog: pytest.LogCaptureFixture) -> None:
    config = {"bogus_table": {"x": 1}}
    with pytest.warns(UserWarning):
        validate_config_shape(config)


def test_out_of_bounds_error() -> None:
    config = {"modules": {"interoception": {"enabled": True, "weight": 99.0}}}
    with pytest.raises(ValueError):
        validate_config_shape(config)


def test_missing_required_key_error() -> None:
    config = {"modules": {}}
    with pytest.raises(ValueError):
        validate_config_shape(config)
