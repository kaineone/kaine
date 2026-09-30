# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import os
import types
from pathlib import Path

import pytest

from kaine import preboot
from kaine.experiment.manifest import write_manifest
from kaine.model_paths import models_dir
from kaine.modules.mnemos.storage import SqliteVecStorage
from kaine.setup.organ import read_revision_state, served_gguf_path, write_revision_state
from kaine.storage import set_data_root


@pytest.fixture(autouse=True)
def _reset_storage_root(monkeypatch):
    set_data_root(None)
    monkeypatch.delenv("KAINE_DATA_ROOT", raising=False)
    monkeypatch.delenv("KAINE_MODELS_DIR", raising=False)
    yield
    set_data_root(None)


def test_models_dir_under_data_root(tmp_path):
    set_data_root(tmp_path / "root")
    assert models_dir() == tmp_path / "root" / "state" / "models"


def test_models_dir_env_override_skips_root(tmp_path, monkeypatch):
    monkeypatch.setenv("KAINE_MODELS_DIR", str(tmp_path / "custom"))
    set_data_root(tmp_path / "root")
    assert models_dir() == tmp_path / "custom"


def test_served_gguf_path_under_data_root(tmp_path):
    set_data_root(tmp_path / "root")
    assert served_gguf_path() == (
        tmp_path / "root" / "state" / "models" / "Qwen3.5-4B-abliterated-GGUF"
        / "KAINE-Qwen3.5-4B-abliterated.Q4_K_M.gguf"
    )


def test_revision_state_round_trip_under_data_root(tmp_path):
    set_data_root(tmp_path / "root")
    results = [types.SimpleNamespace(repo="kaineone/organ-GGUF", ok=True, revision="rev-abc")]
    written = write_revision_state(results)
    assert written is not None
    assert read_revision_state() == {"kaineone/organ-GGUF": "rev-abc"}
    assert (tmp_path / "root" / "state/model-server/organ_revisions.json").is_file()


def test_sqlite_vec_storage_db_path_under_data_root(tmp_path):
    set_data_root(tmp_path / "root")
    storage = SqliteVecStorage(latent_dim=4)
    assert storage._db_path == str(tmp_path / "root" / "state" / "mnemos" / "mnemos.db")


def test_write_manifest_under_data_root(tmp_path):
    set_data_root(tmp_path / "root")
    ctx = types.SimpleNamespace(
        run_id="r1", to_dict=lambda: {"run_id": "r1"}
    )
    path = write_manifest(ctx)
    assert path.parent == tmp_path / "root" / "data" / "evaluation" / "runs" / "r1"
    assert path.name == "manifest.json"
    assert path.exists()


def test_durable_paths_under_data_root(tmp_path):
    set_data_root(tmp_path / "root")
    root = tmp_path / "root"
    paths = preboot.durable_paths({})
    assert paths
    for label, p in paths:
        assert p.is_relative_to(root), f"{label}: {p} is not under {root}"


def test_no_root_preserves_relative_defaults():
    set_data_root(None)
    os.environ.pop("KAINE_DATA_ROOT", None)
    os.environ.pop("KAINE_MODELS_DIR", None)
    assert models_dir() == Path("state/models")
    assert not served_gguf_path().is_absolute()
