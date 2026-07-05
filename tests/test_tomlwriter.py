# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Round-trip tests for the minimal TOML emitter used by the first-run wizard."""
from __future__ import annotations

import tomllib

import pytest

from kaine.setup import tomlwriter


def _roundtrip(data: dict) -> dict:
    text = tomlwriter.dumps(data)
    return tomllib.loads(text)


def test_roundtrip_scalars():
    data = {
        "section": {
            "a_string": "hello",
            "a_bool_true": True,
            "a_bool_false": False,
            "an_int": 42,
            "a_float": 3.14,
            "a_zero": 0,
        }
    }
    assert _roundtrip(data) == data


def test_roundtrip_nested_tables():
    data = {
        "modules": {"soma": True, "lingua": True, "echo": False},
        "hypnos": {"voice_alignment": {"training_device": "cuda:0"}},
        "security": {"state_encryption": {"enabled": True}},
        "research_submission": {
            "enabled": True,
            "tier": "metrics",
            "recipient": "kaine.one@tuta.com",
        },
    }
    assert _roundtrip(data) == data


def test_bool_not_emitted_as_int():
    # bool is a subclass of int — make sure True/False serialize as toml bools.
    text = tomlwriter.dumps({"t": {"flag": True}})
    assert "flag = true" in text
    assert "flag = 1" not in text


def test_float_roundtrips_exactly():
    data = {"x": {"lr": 5e-05, "neg": -0.001, "big": 1234567.0}}
    assert _roundtrip(data) == data


def test_quoted_keys_and_string_escapes():
    data = {"t": {"path": 'a\\b"c'}}
    assert _roundtrip(data) == data


def test_rejects_unsupported_value_type():
    with pytest.raises(TypeError):
        tomlwriter.dumps({"t": {"bad": [1, 2, 3]}})
    with pytest.raises(TypeError):
        tomlwriter.dumps({"t": {"bad": None}})


def test_empty_dict_emits_empty_string():
    assert tomlwriter.dumps({}) == ""
