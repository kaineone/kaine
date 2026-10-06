# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for kaine.residency.catalogue."""

from __future__ import annotations

import json

import pytest

from kaine.residency import catalogue
from kaine.residency.catalogue import (
    Entry,
    footprint_bytes,
    load_catalogue,
    upsert,
    write_catalogue,
)
from kaine.setup.hardware_steps import load_footprint_catalogue


def test_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(
        catalogue, "kaine_version_str", "0.0-test"
    )
    entry = Entry(
        component="lingua",
        backend="llama.cpp",
        model_id="test-model",
        bytes=2 * GIB,
        device=None,
        device_bytes=None,
        mapped=True,
        quantization="Q4_K_M",
        weights_sha256=None,
        host_class="unified",
        measured_at="2026-01-01T00:00:00+00:00",
        kaine_version="0.0-test",
    )
    path = write_catalogue((entry,), path=tmp_path / "footprints.json")
    loaded = load_catalogue(path)
    assert len(loaded) == 1
    assert loaded[0] == entry


def test_from_dict_rejects_unknown_key():
    d = _valid_dict()
    d["extra"] = "value"
    with pytest.raises(ValueError, match="unknown keys"):
        Entry.from_dict(d)


def test_from_dict_rejects_negative_bytes():
    d = _valid_dict()
    d["bytes"] = -1
    with pytest.raises(ValueError, match="non-negative"):
        Entry.from_dict(d)


def test_from_dict_rejects_missing_field():
    d = _valid_dict()
    del d["backend"]
    with pytest.raises(ValueError, match="missing field"):
        Entry.from_dict(d)


def test_load_catalogue_missing_file(tmp_path):
    assert load_catalogue(tmp_path / "missing.json") == ()


def test_load_catalogue_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json")
    assert load_catalogue(p) == ()


def test_load_catalogue_skips_bad_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(catalogue, "kaine_version_str", "0.0-test")
    p = tmp_path / "mixed.json"
    good = _valid_dict()
    bad = _valid_dict()
    bad["component"] = 123  # wrong type
    p.write_text(json.dumps([good, bad]))
    entries = load_catalogue(p)
    assert len(entries) == 1
    assert entries[0].component == "lingua"


def test_upsert_replace_and_append():
    e1 = _make_entry("lingua", "llama.cpp", "a", "cpu", GIB)
    e2 = _make_entry("audition", "sherpa_onnx", "b", "cpu", 2 * GIB)
    result = upsert((e1,), e2)
    assert len(result) == 2
    assert result[1].component == "audition"

    e2_new = _make_entry("audition", "sherpa_onnx", "b", "cpu", 3 * GIB)
    result2 = upsert(result, e2_new)
    assert len(result2) == 2
    assert result2[1].bytes == 3 * GIB


def test_footprint_bytes_max_over_matches():
    e1 = _make_entry("lingua", "llama.cpp", "a", "cpu", GIB)
    e2 = _make_entry("lingua", "llama.cpp", "a", "cpu", 2 * GIB)
    e3 = _make_entry("lingua", "llama.cpp", "b", "cpu", 512 * MIB)
    assert footprint_bytes((e1, e2, e3), "lingua") == 2 * GIB
    assert footprint_bytes((e1, e2, e3), "lingua", model_id="b") == 512 * MIB
    assert footprint_bytes((e1, e2, e3), "audition") is None


def test_compatibility_with_hardware_steps_loader(tmp_path, monkeypatch):
    monkeypatch.setattr(catalogue, "kaine_version_str", "0.0-test")
    e1 = _make_entry("lingua", "llama.cpp", "a", "unified", 2 * GIB)
    e2 = _make_entry("audition", "sherpa_onnx", "b", "unified", 512 * MIB)
    e3 = _make_entry("lingua", "llama.cpp", "a", "unified", 3 * GIB)  # larger duplicate
    path = write_catalogue((e1, e2, e3), path=tmp_path / "footprints.json")
    mapping = load_footprint_catalogue(path)
    assert mapping == {"lingua": 3 * GIB, "audition": 512 * MIB}


def _valid_dict():
    return {
        "component": "lingua",
        "backend": "llama.cpp",
        "model_id": "test-model",
        "bytes": 2 * GIB,
        "device": None,
        "device_bytes": None,
        "mapped": True,
        "quantization": "Q4_K_M",
        "weights_sha256": None,
        "host_class": "unified",
        "measured_at": "2026-01-01T00:00:00+00:00",
        "kaine_version": "0.0-test",
    }


def _make_entry(component, backend, model_id, host_class, bytes_):
    return Entry(
        component=component,
        backend=backend,
        model_id=model_id,
        bytes=bytes_,
        device=None,
        device_bytes=None,
        mapped=False,
        quantization=None,
        weights_sha256=None,
        host_class=host_class,
        measured_at="2026-01-01T00:00:00+00:00",
        kaine_version="0.0-test",
    )


GIB = 1 << 30
MIB = 1 << 20
