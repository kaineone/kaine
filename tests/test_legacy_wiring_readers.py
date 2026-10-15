# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for read-side legacy-name wiring."""

import io
import json
import tarfile
from pathlib import Path

import pytest

from kaine import legacy_aliases, legacy_names
from kaine.evaluation.affect_correlation import correlate_from_log
from kaine.experiment.run_records import load_run_records
from kaine.lifecycle.preservation import (
    WORLD_MODEL_MEMBER,
    _read_bundle_members,
    extract_bundle_development,
)
from kaine.lifecycle.snapshot import ForkSnapshot
from kaine.security import crypto
from kaine.security.crypto import CryptoConfig, StateEncryptor

# The world-model bundle member under the names the code uses now.
_WM = WORLD_MODEL_MEMBER


def _plain_bundle(path: Path, members: dict[str, bytes]) -> Path:
    """Write an uncompressed tar with ``members`` at ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return path


def test_snapshot_modules_mapped_when_keys_done(monkeypatch):
    monkeypatch.setattr(legacy_names, "MODULES", {"oldwm": {"new_key": "phantasia"}})
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")
    snap = ForkSnapshot.from_dict({"modules": {"oldwm": {"a": 1}, "thymos": {"b": 2}}})
    assert snap.modules == {"phantasia": {"a": 1}, "thymos": {"b": 2}}


def test_snapshot_modules_unmapped_when_keys_pending(monkeypatch):
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "pending")
    monkeypatch.setattr(legacy_names, "MODULES", {"oldwm": {"new_key": _WM}})
    snap = ForkSnapshot.from_dict({"modules": {"oldwm": {"a": 1}, "thymos": {"b": 2}}})
    assert snap.modules == {"oldwm": {"a": 1}, "thymos": {"b": 2}}


def test_bundle_members_map_old_module_prefix(monkeypatch, tmp_path):
    monkeypatch.setattr(crypto, "_active", StateEncryptor(CryptoConfig(enabled=False)))
    monkeypatch.setattr(legacy_names, "MODULES", {"oldwm": {"new_key": _WM}})
    monkeypatch.setattr(legacy_names, "BUNDLE_MEMBERS", ())
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")
    bundle = tmp_path / "b" / "bundle.tar"
    _plain_bundle(
        bundle,
        {
            "snapshot.json": json.dumps({"id": "s", "modules": {}}).encode(),
            "oldwm/world_model.ckpt": b"old",
        },
    )
    members = _read_bundle_members(bundle.parent)
    assert members[f"{_WM}/world_model.ckpt"] == b"old"


@pytest.mark.parametrize("first, second", [("old", "new"), ("new", "old")])
def test_bundle_members_new_name_beats_old(monkeypatch, tmp_path, first, second):
    monkeypatch.setattr(crypto, "_active", StateEncryptor(CryptoConfig(enabled=False)))
    monkeypatch.setattr(legacy_names, "MODULES", {"oldwm": {"new_key": _WM}})
    monkeypatch.setattr(legacy_names, "BUNDLE_MEMBERS", ())
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")
    bundle = tmp_path / "b" / "bundle.tar"
    ordered: dict[str, bytes] = {}
    if first == "old":
        ordered["oldwm/world_model.ckpt"] = b"old"
        ordered[f"{_WM}/world_model.ckpt"] = b"new"
    else:
        ordered[f"{_WM}/world_model.ckpt"] = b"new"
        ordered["oldwm/world_model.ckpt"] = b"old"
    _plain_bundle(bundle, ordered)
    members = _read_bundle_members(bundle.parent)
    assert members[f"{_WM}/world_model.ckpt"] == b"new"


def test_bundle_members_pending_old_name_not_mapped(monkeypatch, tmp_path):
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "pending")
    monkeypatch.setattr(crypto, "_active", StateEncryptor(CryptoConfig(enabled=False)))
    monkeypatch.setattr(legacy_names, "MODULES", {"oldwm": {"new_key": _WM}})
    monkeypatch.setattr(legacy_names, "BUNDLE_MEMBERS", ())
    bundle = tmp_path / "b" / "bundle.tar"
    _plain_bundle(
        bundle,
        {
            "snapshot.json": json.dumps({"id": "s", "modules": {}}).encode(),
            "oldwm/world_model.ckpt": b"old",
        },
    )
    members = _read_bundle_members(bundle.parent)
    assert "phantasia/world_model.ckpt" not in members


def test_extract_bundle_development_maps_state_path(monkeypatch, tmp_path):
    monkeypatch.setattr(crypto, "_active", StateEncryptor(CryptoConfig(enabled=False)))
    monkeypatch.setattr(
        legacy_names,
        "BUNDLE_MEMBERS",
        ({"old": "oldgest/", "new": "development/", "scope": "keys"},),
    )
    monkeypatch.setattr(
        legacy_names,
        "STATE_PATHS",
        (
            {
                "old": "lifecycle/old_progress.json",
                "new": "lifecycle/development_progress.json",
                "scope": "persisted",
            },
        ),
    )
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "persisted", "done")
    monkeypatch.setattr(
        "kaine.lifecycle.preservation.BUNDLED_DEVELOPMENT_FILES",
        {"development_progress.json"},
    )
    bundle = tmp_path / "b" / "bundle.tar"
    _plain_bundle(bundle, {"oldgest/old_progress.json": b"{}"})
    dest = tmp_path / "dest"
    written = extract_bundle_development(bundle.parent, dest)
    assert written == ["development_progress.json"]
    assert (dest / "development_progress.json").read_bytes() == b"{}"


@pytest.mark.parametrize("first, second", [("old", "new"), ("new", "old")])
def test_extract_bundle_development_new_file_name_beats_old(monkeypatch, tmp_path, first, second):
    monkeypatch.setattr(crypto, "_active", StateEncryptor(CryptoConfig(enabled=False)))
    monkeypatch.setattr(legacy_names, "BUNDLE_MEMBERS", ())
    monkeypatch.setattr(
        legacy_names,
        "STATE_PATHS",
        (
            {
                "old": "lifecycle/old_progress.json",
                "new": "lifecycle/development_progress.json",
                "scope": "persisted",
            },
        ),
    )
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "persisted", "done")
    monkeypatch.setattr(
        "kaine.lifecycle.preservation.BUNDLED_DEVELOPMENT_FILES",
        {"development_progress.json"},
    )
    bundle = tmp_path / "b" / "bundle.tar"
    ordered: dict[str, bytes] = {}
    if first == "old":
        ordered["development/old_progress.json"] = b"old"
        ordered["development/development_progress.json"] = b"new"
    else:
        ordered["development/development_progress.json"] = b"new"
        ordered["development/old_progress.json"] = b"old"
    _plain_bundle(bundle, ordered)
    dest = tmp_path / "dest"
    written = extract_bundle_development(bundle.parent, dest)
    assert written == ["development_progress.json"]
    assert (dest / "development_progress.json").read_bytes() == b"new"


def test_load_run_records_maps_stream_and_fields(monkeypatch, tmp_path):
    monkeypatch.setattr(crypto, "_active", StateEncryptor(CryptoConfig(enabled=False)))
    monkeypatch.setattr(
        legacy_names,
        "RECORD_FIELDS",
        ({"old": "oldaffect_state", "new": "affect_state", "scope": "keys"},),
    )
    monkeypatch.setattr(legacy_names, "STREAM_NAMES", ())
    monkeypatch.setattr(legacy_names, "MODULES", {"oldaffect": {"new_key": "affect"}})
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")
    root = tmp_path / "records"
    root.mkdir()
    (root / "oldaffect-2026-01-01.jsonl").write_text(
        json.dumps({"run_id": "r", "oldaffect_state": {"v": 1}, "source": "oldaffect"}) + "\n"
    )
    records = load_run_records("r", root=root)
    assert records.by_stream == {
        "affect": [{"run_id": "r", "affect_state": {"v": 1}, "source": "affect"}]
    }


def test_correlate_from_log_maps_record_fields(monkeypatch, tmp_path):
    monkeypatch.setattr(
        legacy_names,
        "RECORD_FIELDS",
        ({"old": "oldaffect_state", "new": "affect_state", "scope": "keys"},),
    )
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")
    path = tmp_path / "affect.jsonl"
    with path.open("w") as fh:
        for x, y in ((0.1, 1.0), (0.2, 2.0), (0.3, 3.0)):
            record = {"oldaffect_state": {"valence": x}, "characteristics": {"c": y}}
            fh.write(json.dumps(record) + "\n")
    result = correlate_from_log(path)
    assert result["valence"]["c"] == pytest.approx(1.0)


def test_latest_lines_reads_old_sidecar_directory(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    from kaine.evaluation.dashboard_tab import _latest_lines

    monkeypatch.setattr(
        legacy_names,
        "SIDECAR_DIRS",
        ({"old": "oldpolicy", "new": "planning_policy", "scope": "keys"},),
    )
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")
    logs = tmp_path / "logs"
    (logs / "oldpolicy").mkdir(parents=True)
    (logs / "oldpolicy" / "oldpolicy-2026-01-01.jsonl").write_text(
        json.dumps({"ts": "t", "policy": "p"}) + "\n"
    )
    lines = _latest_lines(logs / "planning_policy", name="planning_policy")
    assert lines == [{"ts": "t", "policy": "p"}]


def test_read_maps_inert_while_pending(monkeypatch):
    for scope in ("keys", "persisted"):
        monkeypatch.setitem(legacy_names.SCOPE_STATUS, scope, "pending")
    assert (
        legacy_aliases.map_state_path("lifecycle/gestation_progress.json")
        == "lifecycle/gestation_progress.json"
    )
    assert legacy_aliases.sidecar_dir_candidates("nous_policy") == ["nous_policy"]
