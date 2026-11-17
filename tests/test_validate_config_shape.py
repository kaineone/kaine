# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Direct unit tests for ``kaine.config.validate_config_shape``."""

from __future__ import annotations

import pytest

from kaine.config import ConfigShapeError, validate_config_shape


def test_empty_config_validates():
    validate_config_shape({})


def test_none_sections_validates():
    validate_config_shape(
        {"embedding": None, "modules": None, "tier": None, "oscillator": None}
    )


def test_embedding_must_be_table():
    with pytest.raises(ConfigShapeError, match=r"embedding expected table, got str"):
        validate_config_shape({"embedding": "x"})


def test_embedding_values_must_be_strings():
    for key in ("backend", "model_id", "device", "model_path"):
        with pytest.raises(
            ConfigShapeError, match=rf"embedding\.{key} expected string"
        ):
            validate_config_shape({"embedding": {key: 123}})


def test_modules_must_be_table():
    with pytest.raises(ConfigShapeError, match=r"modules expected table, got list"):
        validate_config_shape({"modules": [True]})


def test_modules_values_must_be_bool():
    with pytest.raises(
        ConfigShapeError, match=r"modules\.interoception expected bool"
    ):
        validate_config_shape({"modules": {"interoception": "yes"}})


def test_social_cognition_operator_sources_type():
    with pytest.raises(
        ConfigShapeError, match=r"social_cognition\.operator_sources expected list"
    ):
        validate_config_shape({"social_cognition": {"operator_sources": "live_mic"}})


def test_social_cognition_operator_sources_elements():
    with pytest.raises(
        ConfigShapeError, match=r"social_cognition\.operator_sources\[0\] expected string"
    ):
        validate_config_shape({"social_cognition": {"operator_sources": [1]}})


def test_tier_must_be_table():
    with pytest.raises(ConfigShapeError, match=r"tier expected table, got str"):
        validate_config_shape({"tier": "tier0"})


def test_oscillator_enabled_must_be_bool():
    with pytest.raises(
        ConfigShapeError, match=r"oscillator\.enabled expected bool"
    ):
        validate_config_shape({"oscillator": {"enabled": "true"}})


def test_plugins_enabled_must_be_list_of_strings():
    with pytest.raises(ConfigShapeError, match=r"plugins expected table, got list"):
        validate_config_shape({"plugins": []})
    with pytest.raises(ConfigShapeError, match=r"plugins\.enabled expected list"):
        validate_config_shape({"plugins": {"enabled": "cl"}})


def test_security_must_be_table():
    with pytest.raises(ConfigShapeError, match=r"security expected table, got bool"):
        validate_config_shape({"security": False})


def test_deployment_tier_must_be_string():
    with pytest.raises(
        ConfigShapeError, match=r"deployment\.tier expected string"
    ):
        validate_config_shape({"deployment": {"tier": 2}})


def test_hardware_cpu_threads_validation():
    with pytest.raises(
        ConfigShapeError, match=r"hardware\.cpu_threads expected integer >= 1"
    ):
        validate_config_shape({"hardware": {"cpu_threads": True}})
    with pytest.raises(
        ConfigShapeError, match=r"hardware\.cpu_threads expected integer >= 1"
    ):
        validate_config_shape({"hardware": {"cpu_threads": "4"}})


def test_storage_data_root_validation():
    with pytest.raises(
        ConfigShapeError, match=r"storage\.data_root expected non-empty string"
    ):
        validate_config_shape({"storage": {"data_root": ""}})
    with pytest.raises(
        ConfigShapeError, match=r"storage\.data_root expected non-empty string"
    ):
        validate_config_shape({"storage": {"data_root": 7}})


def test_services_must_be_table_of_tables():
    with pytest.raises(ConfigShapeError, match=r"services expected table, got str"):
        validate_config_shape({"services": "x"})
    with pytest.raises(
        ConfigShapeError, match=r"services\.x expected table, got int"
    ):
        validate_config_shape({"services": {"x": 5}})


def test_residency_reserve_bytes_validation():
    with pytest.raises(
        ConfigShapeError, match=r"residency\.reserve_bytes expected int"
    ):
        validate_config_shape({"residency": {"reserve_bytes": True}})
    with pytest.raises(
        ConfigShapeError, match=r"residency\.reserve_bytes must be > 0"
    ):
        validate_config_shape({"residency": {"reserve_bytes": 0}})


def test_unknown_keys_pass_through():
    cfg = {"totally_unknown": {"a": 1, "b": "s"}}
    validate_config_shape(cfg)
    assert cfg["totally_unknown"]["a"] == 1


def test_offending_value_not_in_message():
    with pytest.raises(ConfigShapeError) as exc_info:
        validate_config_shape({"modules": {"interoception": "SECRETVALUE"}})
    assert "SECRETVALUE" not in str(exc_info.value)