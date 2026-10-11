# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the operator-chosen data root resolver."""
from __future__ import annotations

from pathlib import Path

import pytest

from kaine.storage import (
    DATA_ROOT_ENV,
    configured_data_root,
    normalize_storage_paths,
    resolve_under,
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv(DATA_ROOT_ENV, raising=False)


def test_configured_data_root_absent():
    assert configured_data_root({}) is None
    assert configured_data_root({"storage": {}}) is None
    assert configured_data_root({"storage": {"data_root": ""}}) is None


def test_configured_data_root_from_config(tmp_path):
    root = tmp_path / "data"
    config = {"storage": {"data_root": str(root)}}
    assert configured_data_root(config) == root.resolve()


def test_configured_data_root_env_wins(tmp_path, monkeypatch):
    env_root = tmp_path / "env_root"
    cfg_root = tmp_path / "cfg_root"
    monkeypatch.setenv(DATA_ROOT_ENV, str(env_root))
    config = {"storage": {"data_root": str(cfg_root)}}
    assert configured_data_root(config) == env_root.resolve()


def test_configured_data_root_relative_resolves(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = {"storage": {"data_root": "data"}}
    assert configured_data_root(config) == (tmp_path / "data").resolve()


def test_configured_data_root_blank_env_ignored(tmp_path, monkeypatch):
    cfg_root = tmp_path / "cfg_root"
    monkeypatch.setenv(DATA_ROOT_ENV, "   ")
    assert configured_data_root({"storage": {"data_root": str(cfg_root)}}) == cfg_root.resolve()
    assert configured_data_root({}) is None


def test_resolve_under_with_root():
    root = Path("/data")
    assert resolve_under(root, "foo") == "/data/foo"
    assert resolve_under(root, "a/b") == "/data/a/b"


def test_resolve_under_returns_absolute_unchanged():
    root = Path("/data")
    assert resolve_under(root, "/abs") == "/abs"
    assert resolve_under(root, "~/x") == "~/x"


def test_resolve_under_without_root():
    assert resolve_under(None, "foo") == "foo"
    assert resolve_under(Path("/data"), "") == ""


def test_normalize_storage_paths_returns_same_object_when_no_root():
    config = {"evaluation": {"paths": {"trajectory_dir": "traj"}}}
    assert normalize_storage_paths(config) is config


def test_normalize_storage_paths_resolves_relative_keys(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    config = {
        "storage": {"data_root": str(root)},
        "evaluation": {"paths": {"trajectory_dir": "traj", "evaluation_logs": "/var/log"}},
        "preboot": {"extra_disk_paths": ["disk1", "/abs_disk"]},
        "praxis": {"sandbox_path": 123},
    }
    original = config.copy()
    result = normalize_storage_paths(config)

    assert result is not config
    assert config == original
    assert result["storage"]["data_root"] == str(root.resolve())
    assert result["evaluation"]["paths"]["trajectory_dir"] == str(root / "traj")
    assert result["evaluation"]["paths"]["evaluation_logs"] == "/var/log"
    assert result["preboot"]["extra_disk_paths"] == [str(root / "disk1"), "/abs_disk"]
    assert result["praxis"]["sandbox_path"] == 123
    assert "vox" not in result


def test_normalize_storage_paths_creates_storage_for_env_root(tmp_path, monkeypatch):
    root = tmp_path / "env_root"
    root.mkdir()
    monkeypatch.setenv(DATA_ROOT_ENV, str(root))
    config = {"evaluation": {"paths": {"trajectory_dir": "traj"}}}
    result = normalize_storage_paths(config)
    assert result["storage"]["data_root"] == str(root.resolve())
    assert result["evaluation"]["paths"]["trajectory_dir"] == str(root / "traj")


def test_load_kaine_config_resolves_data_root(tmp_path):
    shipped = tmp_path / "kaine.toml"
    shipped.write_text("")
    op = tmp_path / "kaine.operator.toml"
    data_root = tmp_path / "data"
    op.write_text(
        f'[storage]\ndata_root = "{data_root}"\n\n[evaluation.paths]\ntrajectory_dir = "traj"\n'
    )
    from kaine.config import load_kaine_config

    config = load_kaine_config(shipped, op, strict_operator=True)
    assert config["evaluation"]["paths"]["trajectory_dir"] == str(data_root / "traj")


def test_load_kaine_config_leaves_paths_unchanged_without_storage(tmp_path):
    shipped = tmp_path / "kaine.toml"
    shipped.write_text("")
    op = tmp_path / "kaine.operator.toml"
    op.write_text('[evaluation.paths]\ntrajectory_dir = "traj"\n')
    from kaine.config import load_kaine_config

    config = load_kaine_config(shipped, op, strict_operator=True)
    assert config["evaluation"]["paths"]["trajectory_dir"] == "traj"
