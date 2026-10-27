# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The hearing stage file is keyed to the entity and rides every lifecycle path."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from kaine.boot import _install_shared_stimulus_source_clock
from kaine.lifecycle import decommission
from kaine.lifecycle.divergence import DivergenceAssessment
from kaine.lifecycle.identity import OWN_LIVED_ARTIFACTS, own_lived_artifacts
from kaine.lifecycle.preservation import (
    BUNDLED_DEVELOPMENT_FILES,
    DEVELOPMENT_STATE_FILES,
    extract_bundle_development,
    set_aside_development_files,
)
from kaine.modules.audition.hearing_band import HearingBandParams
from kaine.modules.audition.hearing_stage_state import HearingStageState
from tests.test_preservation_stage_member import (  # noqa: F401
    _plaintext_encryptor,
    _preserve_bundle,
    _restore_stage_path,
    self_model,
)

PARAMS = HearingBandParams()
ME = "ent-" + "a" * 32
PARENT = "ent-" + "b" * 32
GRANDPARENT = "ent-" + "c" * 32
STRANGER = "ent-" + "d" * 32


def _write(path: Path, entity_id, stage=2, dwell=1234.0) -> Path:
    payload = {"version": 1, "stage": stage, "dwell_seconds": dwell}
    if entity_id is not None:
        payload["entity_id"] = entity_id
    path.write_text(json.dumps(payload))
    return path


def test_own_file_is_adopted(tmp_path):
    path = _write(tmp_path / "hearing_stage.json", ME)
    state = HearingStageState.load(PARAMS, path=path, entity_id=ME)
    assert (state.stage, state.dwell_seconds) == (2, 1234.0)


def test_fork_adopts_a_file_written_by_an_ancestor(tmp_path):
    path = _write(tmp_path / "hearing_stage.json", GRANDPARENT)
    state = HearingStageState.load(
        PARAMS, path=path, entity_id=ME, lineage=(GRANDPARENT, PARENT)
    )
    assert (state.stage, state.dwell_seconds) == (2, 1234.0)


def test_foreign_file_is_not_adopted(tmp_path, caplog):
    path = _write(tmp_path / "hearing_stage.json", STRANGER)
    with caplog.at_level(logging.WARNING):
        state = HearingStageState.load(PARAMS, path=path, entity_id=ME, lineage=(PARENT,))
    assert (state.stage, state.dwell_seconds) == (0, 0.0)
    assert any("starting at stage 0" in r.message for r in caplog.records)


def test_ancestor_does_not_adopt_a_descendants_file(tmp_path):
    path = _write(tmp_path / "hearing_stage.json", ME)
    state = HearingStageState.load(PARAMS, path=path, entity_id=PARENT)
    assert state.stage == 0


def test_unkeyed_file_is_not_adopted_when_an_id_is_expected(tmp_path, caplog):
    path = _write(tmp_path / "hearing_stage.json", None)
    with caplog.at_level(logging.WARNING):
        state = HearingStageState.load(PARAMS, path=path, entity_id=ME)
    assert (state.stage, state.dwell_seconds) == (0, 0.0)
    assert any("no entity id" in r.message for r in caplog.records)


def test_corrupt_file_is_not_adopted(tmp_path, caplog):
    path = tmp_path / "hearing_stage.json"
    path.write_text("{not json")
    with caplog.at_level(logging.WARNING):
        state = HearingStageState.load(PARAMS, path=path, entity_id=ME)
    assert state.stage == 0
    assert any("unusable" in r.message for r in caplog.records)


def test_without_an_id_a_keyed_file_is_not_adopted_and_an_unkeyed_one_is(tmp_path):
    keyed = _write(tmp_path / "keyed.json", ME)
    unkeyed = _write(tmp_path / "unkeyed.json", None, stage=3)
    assert HearingStageState.load(PARAMS, path=keyed).stage == 0
    assert HearingStageState.load(PARAMS, path=unkeyed).stage == 3


def test_save_writes_the_entity_id_and_next_save_replaces_a_foreign_file(tmp_path):
    path = _write(tmp_path / "hearing_stage.json", STRANGER, stage=4)
    state = HearingStageState.load(PARAMS, path=path, entity_id=ME)
    state.save()
    saved = json.loads(path.read_text())
    assert saved["entity_id"] == ME
    assert saved["stage"] == 0


def test_reload_adopts_a_file_that_arrived_after_the_owner_was_built(tmp_path):
    path = tmp_path / "hearing_stage.json"
    state = HearingStageState.load(PARAMS, path=path, entity_id=ME)
    assert state.stage == 0
    _write(path, ME, stage=3, dwell=50.0)
    assert state.reload() is True
    assert (state.stage, state.dwell_seconds) == (3, 50.0)


def test_install_passes_the_identity_through(tmp_path):
    stage_dir = tmp_path / "lifecycle"
    stage_dir.mkdir()
    _write(stage_dir / "hearing_stage.json", GRANDPARENT, stage=2)
    feed = {"_entity_id": ME, "_entity_lineage": [GRANDPARENT]}
    config = {"perception_feed": dict(feed)}
    _install_shared_stimulus_source_clock(
        feed, config, None, stage_path=stage_dir / "stage.json"
    )
    assert feed["_hearing_stage_state"].stage == 2

    stranger_feed = {"_entity_id": STRANGER, "_entity_lineage": []}
    _install_shared_stimulus_source_clock(
        stranger_feed, None, None, stage_path=stage_dir / "stage.json"
    )
    assert stranger_feed["_hearing_stage_state"].stage == 0

    no_id_feed: dict = {}
    _install_shared_stimulus_source_clock(
        no_id_feed, None, None, stage_path=stage_dir / "stage.json"
    )
    assert no_id_feed["_hearing_stage_state"].stage == 0


def test_the_file_is_a_bundled_development_file():
    assert "hearing_stage.json" in BUNDLED_DEVELOPMENT_FILES
    assert "hearing_stage.json" in DEVELOPMENT_STATE_FILES


@pytest.mark.asyncio
async def test_revive_round_trip_keeps_the_stage(tmp_path, self_model):  # noqa: F811
    lifecycle_dir = tmp_path / "lifecycle"
    lifecycle_dir.mkdir()
    (lifecycle_dir / "stage.json").write_text(json.dumps({"stage": "development"}))
    _write(lifecycle_dir / "hearing_stage.json", ME, stage=3, dwell=77.0)

    bundle, _ = await _preserve_bundle(
        tmp_path, self_model, monkeypatch_stage=lifecycle_dir / "stage.json"
    )
    target = tmp_path / "revived"
    target.mkdir()
    # An older file left in the target is set aside, then the bundle's copy lands.
    _write(target / "hearing_stage.json", STRANGER, stage=1)
    set_aside_development_files(target)
    assert not (target / "hearing_stage.json").exists()
    restored = extract_bundle_development(bundle, target)
    assert "hearing_stage.json" in restored

    state = HearingStageState.load(PARAMS, path=target / "hearing_stage.json", entity_id=ME)
    assert (state.stage, state.dwell_seconds) == (3, 77.0)


@pytest.mark.asyncio
async def test_bundle_from_before_the_file_existed_restores_the_others(tmp_path, self_model):  # noqa: F811
    lifecycle_dir = tmp_path / "lifecycle"
    lifecycle_dir.mkdir()
    (lifecycle_dir / "stage.json").write_text(json.dumps({"stage": "development"}))
    (lifecycle_dir / "development_progress.json").write_text("{}")
    bundle, _ = await _preserve_bundle(
        tmp_path, self_model, monkeypatch_stage=lifecycle_dir / "stage.json"
    )
    assert extract_bundle_development(bundle, tmp_path / "revived") == [
        "development_progress.json"
    ]


def test_decommission_backs_the_file_up_then_deletes_it(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    rel = "lifecycle/hearing_stage.json"
    target = state_root / rel
    target.parent.mkdir(parents=True)
    _write(target, ME, stage=3)
    secret = target.read_text()
    no_qdrant = {
        "episodic_memory": {"backend": "inmemory"},
        "social_cognition": {"backend": "inmemory"},
    }

    monkeypatch.setattr(decommission, "checkpoint_sqlite", lambda path: None)
    backup = decommission.capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        qdrant_cfg=no_qdrant,
        out_root=tmp_path / "backups",
        entity_name="Hearing",
        assessment=DivergenceAssessment(diverged=False, signals={}, summary="x"),
    )
    assert backup.ok
    texts = {
        p.read_text(errors="replace")
        for p in Path(backup.backup_path).rglob("*")
        if p.is_file()
    }
    assert secret in texts

    result = decommission.delete_entity_state(
        state_root=state_root,
        qdrant_cfg=no_qdrant,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        dry_run=False,
    )
    assert result.errors == []
    assert not target.exists()


def test_lived_artifact_detection_counts_the_file(tmp_path):
    assert Path("lifecycle/hearing_stage.json") in OWN_LIVED_ARTIFACTS
    assert own_lived_artifacts(tmp_path) == []
    (tmp_path / "lifecycle").mkdir()
    _write(tmp_path / "lifecycle" / "hearing_stage.json", ME)
    assert own_lived_artifacts(tmp_path) == [tmp_path / "lifecycle" / "hearing_stage.json"]


@pytest.mark.asyncio
async def test_preserve_bundles_the_current_dwell(tmp_path, self_model):  # noqa: F811
    lifecycle_dir = tmp_path / "lifecycle"
    lifecycle_dir.mkdir()
    (lifecycle_dir / "stage.json").write_text(json.dumps({"stage": "development"}))
    state = HearingStageState(PARAMS, path=lifecycle_dir / "hearing_stage.json", entity_id=ME)
    state.observe(0.0, None)
    state.observe(10.0, None)  # 10 s of dwell: under the 30 s autosave step
    assert not (lifecycle_dir / "hearing_stage.json").exists()

    bundle, _ = await _preserve_bundle(
        tmp_path,
        self_model,
        monkeypatch_stage=lifecycle_dir / "stage.json",
        hearing_stage_state=state,
    )
    target = tmp_path / "revived"
    target.mkdir()
    extract_bundle_development(bundle, target)
    restored = HearingStageState.load(PARAMS, path=target / "hearing_stage.json", entity_id=ME)
    assert restored.dwell_seconds == 10.0
