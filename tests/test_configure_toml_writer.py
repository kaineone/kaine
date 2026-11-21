# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""The operator-overlay writer in kaine.setup.configure round-trips through tomllib."""

from __future__ import annotations

import math
import tomllib

import pytest

from kaine.setup.configure import _dump_toml


def test_nested_tables_keep_their_full_path():
    src = {
        "security": {"state_encryption": {"enabled": True}},
        "storage": {"min_free_gb": 20},
        "modules": {"affect": True, "vision": False},
    }
    out = _dump_toml(src)
    assert "[security.state_encryption]" in out
    assert tomllib.loads(out) == src


def test_scalars_keys_and_strings_round_trip():
    src = {
        "top": 1,
        "language": {
            "chat_url": "http://127.0.0.1:11434/v1",
            "persona_external": 'Line one\nsays "hi" \\ back\ttab',
            "temperature": 0.7,
            "stops": ["a", "b"],
        },
        "odd keys": {"key.with.dots": "x", "ünï": 2},
    }
    assert tomllib.loads(_dump_toml(src)) == src


def test_infinities_round_trip():
    out = tomllib.loads(_dump_toml({"t": {"hi": math.inf, "lo": -math.inf}}))
    assert out == {"t": {"hi": math.inf, "lo": -math.inf}}


def test_unsupported_values_raise_instead_of_writing_an_empty_string():
    with pytest.raises(ValueError):
        _dump_toml({"t": {"when": object()}})
    with pytest.raises(ValueError):
        _dump_toml({"t": {"rows": [{"a": 1}]}})
