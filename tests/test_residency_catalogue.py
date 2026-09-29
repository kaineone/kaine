# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json

import pytest

from kaine.residency.catalogue import (
    CatalogueError,
    FootprintCatalogue,
    FootprintEntry,
    load_catalogue,
    save_catalogue,
)


def _entry(**kwargs) -> FootprintEntry:
    defaults = {
        "component": "lingua",
        "backend": "llamacpp",
        "model_id": "small",
        "peak_bytes": 1 << 30,
        "device_peak_bytes": None,
        "weights_mapped": None,
        "host_class": "desktop",
        "measured_at": "2026-01-01T00:00:00Z",
        "kaine_version": "0.0.1",
        "source": "calibration",
    }
    defaults.update(kwargs)
    return FootprintEntry(**defaults)


def test_catalogue_round_trip(tmp_path):
    entry = _entry(peak_bytes=2 << 30)
    catalogue = FootprintCatalogue(()).merge(entry)
    path = tmp_path / "footprints.json"
    save_catalogue(path, catalogue)
    loaded = load_catalogue(path)
    assert loaded.get("lingua", "llamacpp", "small", "desktop") == entry


def test_catalogue_merge_keeps_larger_peak():
    entry_a = _entry(peak_bytes=1 << 30, measured_at="2026-01-01T00:00:00Z")
    entry_b = _entry(
        peak_bytes=2 << 30,
        device_peak_bytes=512 << 20,
        measured_at="2026-01-02T00:00:00Z",
    )
    catalogue = FootprintCatalogue(()).merge(entry_a).merge(entry_b)
    entry = catalogue.get("lingua", "llamacpp", "small", "desktop")
    assert entry is not None
    assert entry.peak_bytes == 2 << 30
    assert entry.device_peak_bytes == 512 << 20


def test_catalogue_rejects_unknown_key():
    raw = {
        "component": "lingua",
        "backend": "llamacpp",
        "model_id": "small",
        "peak_bytes": 1 << 30,
        "device_peak_bytes": None,
        "weights_mapped": None,
        "host_class": "desktop",
        "measured_at": "2026-01-01T00:00:00Z",
        "kaine_version": "0.0.1",
        "source": "calibration",
        "text": "extra field",
    }
    with pytest.raises(ValueError, match="invalid footprint key: 'text'"):
        FootprintEntry.from_dict(raw)


def test_catalogue_rejects_negative_bytes():
    # Validation lives in the entry, so a negative figure never reaches a catalogue.
    with pytest.raises(ValueError, match="peak_bytes"):
        _entry(peak_bytes=-1)


def test_catalogue_bad_version_raises(tmp_path):
    path = tmp_path / "footprints.json"
    path.write_text(json.dumps({"version": 2, "entries": []}))
    with pytest.raises(CatalogueError, match="unsupported version"):
        load_catalogue(path)


def test_catalogue_missing_file_is_empty(tmp_path):
    path = tmp_path / "does_not_exist.json"
    catalogue = load_catalogue(path)
    assert catalogue.entries == ()
