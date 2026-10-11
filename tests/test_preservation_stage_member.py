# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the stage.json member added to preservation bundles."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest
import pytest_asyncio

from kaine.lifecycle import stage
from kaine.lifecycle.manager import ForkManager
from kaine.lifecycle.preservation import (
    extract_bundle_gestation,
    read_bundle_stage,
    set_aside_gestation_files,
)
from kaine.modules.eidolon import Eidolon, SelfModel
from kaine.modules.registry import ModuleRegistry
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor


class _FakeBus:
    async def publish(self, *args, **kwargs):
        pass

    async def current_workspace_id(self) -> str:
        return "0"

    async def close(self):
        pass


@pytest.fixture(autouse=True)
def _plaintext_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


@pytest.fixture(autouse=True)
def _restore_stage_path(monkeypatch):
    """These tests assign stage.STAGE_PATH directly; restore it afterwards so
    the redirect never leaks into later tests."""
    monkeypatch.setattr(stage, "STAGE_PATH", stage.STAGE_PATH)


@pytest_asyncio.fixture
async def eidolon(tmp_path):
    bus = _FakeBus()
    eid = Eidolon(bus, persistence_path=tmp_path / "sm.json", save_interval_s=60)
    await eid.initialize()
    eid._model = SelfModel(name="stage-test", values=["continuity"])
    yield eid
    try:
        await eid.shutdown()
    except Exception as exc:  # teardown of an already-shut-down fixture
        print(f"eidolon teardown ignored: {exc!r}")


async def _preserve_bundle(tmp_path, eidolon, *, monkeypatch_stage: Path | None = None):
    if monkeypatch_stage is not None:
        stage.STAGE_PATH = monkeypatch_stage
    reg = ModuleRegistry()
    reg.register(eidolon)
    fork_root = tmp_path / "forks"
    out_root = tmp_path / "backups"
    fm = ForkManager(fork_root)
    result = await fm.preserve_live(
        reg,
        reason="stage-member-test",
        label="stage",
        out_root=out_root,
        entity_name="stage-entity",
    )
    assert result.ok
    bundle = out_root / f"preservation_{result.preservation_id}_stage-entity"
    return bundle, result


@pytest.mark.asyncio
async def test_read_bundle_stage_returns_stage(tmp_path, eidolon):
    stage_path = tmp_path / "stage.json"
    stage_path.write_text(
        json.dumps(
            {
                "stage": "gestation",
                "gestation_started_at": "2026-01-01T00:00:00+00:00",
                "lived_seconds": 12.5,
                "sleep_count": 3,
            }
        )
    )
    bundle, _ = await _preserve_bundle(tmp_path, eidolon, monkeypatch_stage=stage_path)
    stage_dict = read_bundle_stage(bundle)
    assert stage_dict is not None
    assert stage_dict["stage"] == "gestation"
    assert stage_dict["gestation_started_at"] == "2026-01-01T00:00:00+00:00"
    assert stage_dict["lived_seconds"] == 12.5
    assert stage_dict["sleep_count"] == 3


@pytest.mark.asyncio
async def test_read_bundle_stage_returns_none_without_stage(tmp_path, eidolon):
    stage.STAGE_PATH = tmp_path / "no-stage.json"
    bundle, _ = await _preserve_bundle(tmp_path, eidolon)
    assert read_bundle_stage(bundle) is None


@pytest.mark.asyncio
async def test_read_bundle_stage_with_encryption(tmp_path, eidolon, monkeypatch):
    # The key comes from the environment, as in production; no skip: an
    # encrypted bundle must carry and return the stage.
    monkeypatch.setenv(
        "KAINE_STATE_KEY", base64.b64encode(os.urandom(32)).decode("ascii")
    )
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=True)))

    stage_path = tmp_path / "stage.json"
    stage_path.write_text(json.dumps({"stage": "embodied", "born_at": "2026-02-01T00:00:00+00:00"}))
    bundle, _ = await _preserve_bundle(tmp_path, eidolon, monkeypatch_stage=stage_path)

    try:
        stage_dict = read_bundle_stage(bundle)
    finally:
        set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))

    assert (bundle / "bundle.tar.enc").is_file()
    assert not (bundle / "bundle.tar").exists()
    assert not (bundle / "stage.json").exists()
    assert stage_dict is not None
    assert stage_dict["stage"] == "embodied"
    assert stage_dict["born_at"] == "2026-02-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_bundle_carries_gestation_progress_not_verdict(tmp_path, eidolon):
    lifecycle_dir = tmp_path / "lifecycle"
    lifecycle_dir.mkdir()
    progress = {"k": {"awake_seconds": 120.0}}
    readout = {"baselines": 1}
    viability = {"verdict": "unviable"}

    (lifecycle_dir / "stage.json").write_text(json.dumps({"stage": "gestation"}))
    (lifecycle_dir / "gestation_progress.json").write_text(json.dumps(progress))
    (lifecycle_dir / "gestation_readout.json").write_text(json.dumps(readout))
    (lifecycle_dir / "gestation_viability.json").write_text(json.dumps(viability))

    stage_path = lifecycle_dir / "stage.json"
    bundle, _ = await _preserve_bundle(tmp_path, eidolon, monkeypatch_stage=stage_path)

    restored = extract_bundle_gestation(bundle, tmp_path / "revived")
    assert restored == ["gestation_progress.json", "gestation_readout.json"]
    assert (
        json.loads((tmp_path / "revived" / "gestation_progress.json").read_text())
        == progress
    )
    assert (
        json.loads((tmp_path / "revived" / "gestation_readout.json").read_text())
        == readout
    )
    assert not (tmp_path / "revived" / "gestation_viability.json").exists()
    assert not (bundle / "gestation").exists()


@pytest.mark.asyncio
async def test_bundle_without_gestation_files_restores_nothing(tmp_path, eidolon):
    lifecycle_dir = tmp_path / "lifecycle"
    lifecycle_dir.mkdir()
    (lifecycle_dir / "stage.json").write_text(json.dumps({"stage": "embodied"}))

    bundle, _ = await _preserve_bundle(
        tmp_path, eidolon, monkeypatch_stage=lifecycle_dir / "stage.json"
    )
    assert extract_bundle_gestation(bundle, tmp_path / "revived") == []


@pytest.mark.asyncio
async def test_gestation_files_travel_encrypted(tmp_path, eidolon, monkeypatch):
    # The key comes from the environment, as in production; no skip: an
    # encrypted bundle must carry and return the gestation progress.
    monkeypatch.setenv(
        "KAINE_STATE_KEY", base64.b64encode(os.urandom(32)).decode("ascii")
    )
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=True)))

    lifecycle_dir = tmp_path / "lifecycle"
    lifecycle_dir.mkdir()
    progress = {"k": {"awake_seconds": 120.0}}
    (lifecycle_dir / "stage.json").write_text(json.dumps({"stage": "gestation"}))
    (lifecycle_dir / "gestation_progress.json").write_text(json.dumps(progress))

    try:
        bundle, _ = await _preserve_bundle(
            tmp_path, eidolon, monkeypatch_stage=lifecycle_dir / "stage.json"
        )
        restored = extract_bundle_gestation(bundle, tmp_path / "revived")
    finally:
        set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))

    assert (bundle / "bundle.tar.enc").is_file()
    assert restored == ["gestation_progress.json"]
    assert (
        json.loads((tmp_path / "revived" / "gestation_progress.json").read_text())
        == progress
    )
    assert not (bundle / "gestation").exists()

def test_set_aside_gestation_files_keeps_them(tmp_path):
    dest = tmp_path / "lifecycle"
    dest.mkdir()
    (dest / "gestation_progress.json").write_text("{}")
    (dest / "gestation_viability.json").write_text("{}")

    originals = {"gestation_progress.json", "gestation_viability.json"}
    moved = set_aside_gestation_files(dest)
    assert len(moved) == 2
    for original in originals:
        assert not (dest / original).exists()
    for p in moved:
        assert p.exists()
        assert any(p.name.startswith(f"{original}.replaced-") for original in originals)

    assert set_aside_gestation_files(tmp_path / "missing") == []
