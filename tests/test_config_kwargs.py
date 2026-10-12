# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for config-to-constructor keyword argument mapping."""
from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import pytest

from kaine import legacy_names
from kaine.boot.config_kwargs import config_kwargs, parameter_for_config_key


def _make_target(param: str) -> Callable[..., Any]:
    def target(**kwargs: Any) -> dict[str, Any]:
        return kwargs

    target.__signature__ = inspect.Signature(
        [
            inspect.Parameter(param, inspect.Parameter.KEYWORD_ONLY, default=None),
            inspect.Parameter("rate", inspect.Parameter.KEYWORD_ONLY, default=0),
        ]
    )
    return target


def test_parameter_for_config_key_renames_component() -> None:
    assert legacy_names.MODULES
    old, entry = next(iter(legacy_names.MODULES.items()))
    new = entry["new_key"]
    assert parameter_for_config_key(f"{old}_stream", {f"{new}_stream"}) == f"{new}_stream"


def test_parameter_for_config_key_prefers_key_when_accepted() -> None:
    old, entry = next(iter(legacy_names.MODULES.items()))
    new = entry["new_key"]
    assert (
        parameter_for_config_key(
            f"{old}_stream", {f"{old}_stream", f"{new}_stream"}
        )
        == f"{old}_stream"
    )


def test_parameter_for_config_key_unknown_unchanged() -> None:
    assert parameter_for_config_key("unknown_key", set()) == "unknown_key"


def test_parameter_for_config_key_no_module_component() -> None:
    assert (
        parameter_for_config_key("drift_rate_per_s", {"drift_rate_per_s"})
        == "drift_rate_per_s"
    )


def test_config_kwargs_maps_keys_to_parameters() -> None:
    assert legacy_names.MODULES
    old, entry = next(iter(legacy_names.MODULES.items()))
    new = entry["new_key"]
    target = _make_target(f"{new}_stream")
    result = config_kwargs(
        {f"{old}_stream": "x", "rate": 3, "unused": 1},
        (f"{old}_stream", "rate"),
        target,
    )
    assert result == {f"{new}_stream": "x", "rate": 3}


def test_config_kwargs_convert_applies_to_values() -> None:
    old, entry = next(iter(legacy_names.MODULES.items()))
    new = entry["new_key"]
    target = _make_target(f"{new}_stream")
    result = config_kwargs(
        {f"{old}_stream": "x", "rate": 3, "unused": 1},
        (f"{old}_stream", "rate"),
        target,
        convert=str,
    )
    assert result == {f"{new}_stream": "x", "rate": "3"}
    assert isinstance(result["rate"], str)


def test_parameter_for_config_key_renames_developmental_component():
    from kaine import legacy_names

    old, entry = next(iter(legacy_names.DEVELOPMENTAL.items()))
    new = entry["new_key"]
    assert (
        parameter_for_config_key(f"{old}_budget_seconds", {f"{new}_budget_seconds"})
        == f"{new}_budget_seconds"
    )


def test_old_config_key_reaches_renamed_params_field():
    from kaine.modules.stimulus_source_signal import StimulusSourceParams

    params = StimulusSourceParams.from_sections(
        {"birth_transition_seconds": 7.5}, None, None
    )
    assert params.maturation_transition_seconds == 7.5


def test_params_validation_names_the_config_key():
    from kaine.modules.stimulus_source_signal import StimulusSourceParams

    with pytest.raises(ValueError) as exc:
        StimulusSourceParams.from_sections({"birth_transition_seconds": 99.0}, None, None)
    assert "birth_transition_seconds" in str(exc.value)
    assert "maturation_transition_seconds" not in str(exc.value)
