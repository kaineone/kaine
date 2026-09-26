# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import datetime

import pytest

from kaine.research.ignition_study.toml_writer import dumps


def test_roundtrip_nested_table():
    data = {
        "title": "Ignition study",
        "enabled": True,
        "count": 7,
        "rate": 1.5,
        "tags": ["research", "ignition"],
        "modules": {"soma": True, "mnemos": False},
        "perception_feed": {"mode": "playlist", "playlist_manifest": "/x.toml"},
    }
    out = dumps(data)
    assert "title = " in out
    assert "enabled = true" in out
    assert "count = 7" in out
    assert "[modules]" in out
    assert "soma = true" in out
    assert "mnemos = false" in out
    assert "[perception_feed]" in out
    assert 'mode = "playlist"' in out


def test_string_escapes():
    data = {"s": 'a\\b"c\nd\te\x07f'}
    out = dumps(data)
    assert "\\\\" in out
    assert '\\"' in out
    assert "\\n" in out
    assert "\\t" in out
    assert r"\u0007" in out


def test_bare_and_quoted_keys():
    data = {"a-b": 1, "foo.bar": 2, "key with space": 3}
    out = dumps(data)
    assert "a-b = 1" in out
    assert '"foo.bar" = 2' in out
    assert '"key with space" = 3' in out


def test_empty_dict():
    assert dumps({}) == ""


def test_reject_none():
    with pytest.raises(TypeError, match="Unsupported type at a"):
        dumps({"a": None})


def test_reject_datetime():
    with pytest.raises(TypeError):
        dumps({"a": datetime.datetime.now()})


def test_reject_list_of_dicts():
    with pytest.raises(TypeError):
        dumps({"a": [{"b": 1}]})


def test_reject_nan():
    with pytest.raises(TypeError):
        dumps({"a": float("nan")})
