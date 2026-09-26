# SPDX-License-Identifier: LicenseRef-CAL-0.2
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
from kaine.lifecycle.preservation import read_bundle_stage
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


@pytest_asyncio.fixture
async def eidolon(tmp_path):
    bus = _FakeBus()
    eid = Eidolon(bus, persistence_path=tmp_path / "sm.json", save_interval_s=60)
    await eid.initialize()
    eid._model = SelfModel(name="stage-test", values=["continuity"])
    yield eid
    try:
        await eid.shutdown()
    except Exception:
        pass


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
