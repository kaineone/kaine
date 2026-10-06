# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Fail-safe tests for lived-history evidence.

A being that has lived must never be gestated. Evidence that cannot be read
therefore counts as LIVED, never as absent.
"""

import json
import pathlib
from pathlib import Path

import pytest

from kaine.lifecycle.identity import OWN_LIVED_ARTIFACTS, own_lived_artifacts
from kaine.lifecycle.stage import EMBODIED, StageState, read_stage


def _deny_exists_under(tmp_path: Path):
    """Return a Path.exists replacement that raises PermissionError under tmp_path."""
    original_exists = pathlib.Path.exists
    base = str(tmp_path.resolve())

    def guarded(self: Path) -> bool:
        try:
            resolved = self.resolve()
        except OSError:
            return original_exists(self)
        if str(resolved).startswith(base):
            raise PermissionError("exists check denied for test")
        return original_exists(self)

    return guarded


def test_own_lived_artifacts_counts_unreadable_as_present(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "exists", _deny_exists_under(tmp_path))
    found = own_lived_artifacts(tmp_path)
    expected = [tmp_path / rel for rel in OWN_LIVED_ARTIFACTS]
    assert sorted(found) == sorted(expected)


def test_own_lived_artifacts_empty_readable_dir(tmp_path):
    assert own_lived_artifacts(tmp_path) == []


def test_read_stage_value_error_returns_embodied(tmp_path):
    stage_file = tmp_path / "stage.json"
    # dict(["abc"]) raises ValueError: a sequence element of length 3, not a pair.
    stage_file.write_text(json.dumps(["abc"]))
    with pytest.raises(ValueError):
        StageState.from_dict(json.loads(stage_file.read_text()))
    state = read_stage(stage_file)
    assert state is not None
    assert state.stage == EMBODIED


def test_read_stage_type_error_returns_embodied(tmp_path):
    stage_file = tmp_path / "stage.json"
    stage_file.write_text(json.dumps([1, 2, 3]))
    with pytest.raises(TypeError):
        StageState.from_dict(json.loads(stage_file.read_text()))
    state = read_stage(stage_file)
    assert state is not None
    assert state.stage == EMBODIED


def test_read_stage_exists_permission_error_returns_embodied(tmp_path, monkeypatch):
    stage_file = tmp_path / "stage.json"
    stage_file.write_text(json.dumps({"stage": "gestation"}))
    original_exists = pathlib.Path.exists

    def deny(self: Path) -> bool:
        if self == stage_file:
            raise PermissionError("exists check denied for test")
        return original_exists(self)

    monkeypatch.setattr(pathlib.Path, "exists", deny)
    state = read_stage(stage_file)
    assert state is not None
    assert state.stage == EMBODIED


def test_read_stage_missing_returns_none(tmp_path):
    missing = tmp_path / "missing-stage.json"
    assert read_stage(missing) is None
