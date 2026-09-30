# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for data-root resolution in lifecycle, preservation and module defaults."""
from __future__ import annotations

import io
import json
import os

import pytest

from kaine.lifecycle.__main__ import main
from kaine.lifecycle.manager import merger_from_name
from kaine.modules.eidolon import Eidolon
from kaine.storage import set_data_root

# Helpers reused from the existing decommission CLI and preservation tests.
from tests.test_decommission_cli import (
    _scripted_input,
    _seed_state,
)
from tests.test_preservation_stage_member import _FakeBus


@pytest.fixture(autouse=True)
def _reset_data_root(monkeypatch):
    monkeypatch.delenv("KAINE_DATA_ROOT", raising=False)
    yield
    set_data_root(None)
    os.environ.pop("KAINE_DATA_ROOT", None)


@pytest.fixture(autouse=True)
def _isolated_operator_overlay(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "kaine.config.OPERATOR_CONFIG_PATH",
        tmp_path / "config" / "kaine.operator.toml",
    )


@pytest.fixture(autouse=True)
def _hermetic_liveness_signals(monkeypatch):
    monkeypatch.setattr(
        "kaine.lifecycle.__main__._bus_shows_live_entity",
        lambda config: (False, "test: no bus"),
    )
    monkeypatch.setattr(
        "kaine.lifecycle.__main__._cycle_process_running",
        lambda: False,
    )


def _root_args(tmp_path, *, dry_run=False):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "kaine.toml"
    root = tmp_path / "root"
    cfg_path.write_text(
        "# minimal config\n"
        "[storage]\n"
        f'data_root = "{root.as_posix()}"\n'
        "[research_submission]\n"
        "enabled = false\n",
        encoding="utf-8",
    )
    a = ["--config", str(cfg_path)]
    if dry_run:
        a.append("--dry-run")
    return a, root


def test_decommission_running_cycle_refusal_data_root(tmp_path, monkeypatch):
    """Gate 2 must see the runtime file resolved under the configured data root."""
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    args, root = _root_args(tmp_path)
    state_root = root / "state"
    _seed_state(state_root)
    runtime = state_root / "cycle" / "runtime.json"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    err = io.StringIO()
    rc = main(args, input_fn=_scripted_input([]), out=io.StringIO(), err=err)
    assert rc == 3
    assert "running" in err.getvalue().lower()


def test_decommission_dry_run_backup_under_data_root(tmp_path, monkeypatch):
    """A dry-run decommission must place its backup under the data root."""
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    args, root = _root_args(tmp_path, dry_run=True)
    state_root = root / "state"
    _seed_state(state_root)
    out = io.StringIO()
    rc = main(args, input_fn=_scripted_input([]), out=out, err=io.StringIO())
    assert rc == 0
    backups = list((root / "backups").glob("entity_*"))
    assert backups, f"backup not found under {root / 'backups'}; output was:\n{out.getvalue()}"


def test_merger_from_name_output_dir_under_data_root(tmp_path):
    """merger_from_name('auto') resolves its default output_dir under the root."""
    root = tmp_path / "root"
    set_data_root(root)
    merger = merger_from_name("auto")
    output_dir = getattr(getattr(merger, "cfg", None), "output_dir", None)
    if output_dir is None:
        pytest.skip("auto merger selected the no-op fake (PEFT unavailable); cannot inspect output_dir")
    assert output_dir == root / "state" / "forks" / "merged_adapters"


def test_eidolon_default_persistence_path_under_data_root(tmp_path):
    """Eidolon's default persistence path resolves under the installed data root."""
    root = tmp_path / "root"
    set_data_root(root)
    eidolon = Eidolon(_FakeBus())
    assert eidolon._persistence_path == root / "state" / "eidolon" / "self_model.json"
