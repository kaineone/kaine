# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""World-model identity: learned weights persist, fork, and merge with choice.

Uses the NumPy engine so the suite runs without JAX.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.lifecycle.manager import ForkManager
from kaine.lifecycle.snapshot import artifacts_dir, copy_artifacts, snapshot_dir
from kaine.modules.phantasia.encoder import VERSION, observation_dim
from kaine.modules.phantasia.module import Phantasia
from kaine.modules.phantasia.world_model import (
    CheckpointMismatchError,
    NumpyDreamerV3WorldModel,
)
from kaine.modules.registry import ModuleRegistry
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


def _enc() -> str:
    return VERSION


def _npz_arrays(blob: bytes) -> dict[str, bytes]:
    data = np.load(io.BytesIO(blob), allow_pickle=False)
    return {name: data[name].tobytes() for name in data.files}


def _small_wm(seed: int) -> NumpyDreamerV3WorldModel:
    return NumpyDreamerV3WorldModel(
        observation_dim(),
        deter_dim=8,
        stoch_dim=4,
        stoch_classes=3,
        hidden_dim=8,
        seed=seed,
    )


def _make_phantasia(
    bus: AsyncBus, tmp_path: Path, seed: int, persist: bool = True
) -> tuple[Phantasia, NumpyDreamerV3WorldModel, Path]:
    ckpt = tmp_path / f"phantasia_{seed}" / "wm.ckpt"
    wm = _small_wm(seed)
    ph = Phantasia(
        bus,
        world_model=wm,
        backend="dreamerv3",
        engine="numpy",
        persist_weights=persist,
        checkpoint_path=str(ckpt),
    )
    return ph, wm, ckpt


def _train_a_little(ph: Phantasia) -> None:
    obs_dim = observation_dim()
    traj = [[float((i + j) % 5) for j in range(obs_dim)] for i in range(8)]
    ph.world_model.train(traj)


@pytest.mark.asyncio
async def test_fork_carries_its_own_copy(bus, tmp_path):
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    reg = ModuleRegistry()
    ph, wm, ckpt_a = _make_phantasia(bus, tmp_path, seed=1, persist=True)
    await ph.initialize()
    _train_a_little(ph)
    ph.export_preservation_weights()
    reg.register(ph)

    fm = ForkManager(tmp_path / "forks")
    parent_snap = fm.snapshot(reg)
    parent_artifact = artifacts_dir(fm.root, parent_snap.id, "phantasia") / "world_model.ckpt"
    assert parent_artifact.is_file()
    parent_artifact_bytes = parent_artifact.read_bytes()
    parent_ckpt_bytes = ckpt_a.read_bytes()

    child = fm.fork(parent_snap.id)

    reg2 = ModuleRegistry()
    ph2, wm2, ckpt_b = _make_phantasia(bus, tmp_path, seed=99, persist=True)
    await ph2.initialize()
    reg2.register(ph2)
    fm.restore(child.id, reg2)

    assert _npz_arrays(wm.export_params(extra={"encoder_version": _enc()})) == (
        _npz_arrays(wm2.export_params(extra={"encoder_version": _enc()}))
    )
    assert ckpt_b.is_file()
    assert ckpt_a.read_bytes() == parent_ckpt_bytes
    assert parent_artifact.read_bytes() == parent_artifact_bytes
    assert artifacts_dir(fm.root, child.id, "phantasia") != parent_artifact.parent

    await ph.shutdown()
    await ph2.shutdown()


@pytest.mark.asyncio
async def test_fork_then_diverges(bus, tmp_path):
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    reg = ModuleRegistry()
    ph, wm, ckpt_a = _make_phantasia(bus, tmp_path, seed=1, persist=True)
    await ph.initialize()
    _train_a_little(ph)
    ph.export_preservation_weights()
    reg.register(ph)

    fm = ForkManager(tmp_path / "forks")
    parent_snap = fm.snapshot(reg)
    parent_artifact = artifacts_dir(fm.root, parent_snap.id, "phantasia") / "world_model.ckpt"
    parent_artifact_bytes = parent_artifact.read_bytes()

    child = fm.fork(parent_snap.id)

    reg2 = ModuleRegistry()
    ph2, wm2, ckpt_b = _make_phantasia(bus, tmp_path, seed=99, persist=True)
    await ph2.initialize()
    reg2.register(ph2)
    fm.restore(child.id, reg2)
    _train_a_little(ph2)
    await ph2.shutdown()

    assert parent_artifact.read_bytes() == parent_artifact_bytes
    assert ckpt_a.read_bytes() == parent_artifact_bytes
    assert ckpt_b.is_file()

    await ph.shutdown()


@pytest.mark.asyncio
async def test_two_forks_are_independent_copies(bus, tmp_path):
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    reg = ModuleRegistry()
    ph, wm, _ckpt = _make_phantasia(bus, tmp_path, seed=1, persist=True)
    await ph.initialize()
    _train_a_little(ph)
    ph.export_preservation_weights()
    reg.register(ph)

    fm = ForkManager(tmp_path / "forks")
    parent_snap = fm.snapshot(reg)
    c1 = fm.fork(parent_snap.id)
    c2 = fm.fork(parent_snap.id)

    a1 = artifacts_dir(fm.root, c1.id, "phantasia") / "world_model.ckpt"
    a2 = artifacts_dir(fm.root, c2.id, "phantasia") / "world_model.ckpt"
    parent_ckpt = artifacts_dir(fm.root, parent_snap.id, "phantasia") / "world_model.ckpt"
    original_a1 = a1.read_bytes()

    a1.write_bytes(b"modified")
    assert a2.read_bytes() == original_a1
    assert parent_ckpt.read_bytes() == original_a1

    await ph.shutdown()


@pytest.mark.asyncio
async def test_shed_drops_phantasia_artifacts(bus, tmp_path):
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    reg = ModuleRegistry()
    ph, wm, _ckpt = _make_phantasia(bus, tmp_path, seed=1, persist=True)
    await ph.initialize()
    _train_a_little(ph)
    reg.register(ph)

    fm = ForkManager(tmp_path / "forks")
    parent_snap = fm.snapshot(reg)
    child = fm.fork(parent_snap.id, shed=["phantasia"])

    assert not (snapshot_dir(fm.root, child.id) / "artifacts" / "phantasia").exists()
    assert "phantasia" not in child.modules
    assert child.metadata["shed"] == ["phantasia"]

    await ph.shutdown()


class _FailingArtifactModule:
    name = "badmodule"

    def serialize(self) -> dict[str, Any]:
        return {}

    def deserialize(self, state: dict[str, Any]) -> None:
        pass

    def export_snapshot_artifacts(self, dest_dir: Path) -> dict[str, Any]:
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_failed_export_leaves_no_snapshot(bus, tmp_path):
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    reg = ModuleRegistry()
    reg.register(_FailingArtifactModule())
    fm = ForkManager(tmp_path / "forks")
    before = fm.list_snapshots()

    with pytest.raises(RuntimeError, match="boom"):
        fm.snapshot(reg)

    assert fm.list_snapshots() == before
    # No stray snapshot directory should remain.
    for entry in fm.root.iterdir():
        assert not (entry / "snapshot.json").exists() or entry.name in before


@pytest.mark.asyncio
async def test_missing_artifact_warns_and_keeps_fresh_init(bus, tmp_path, caplog):
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    reg = ModuleRegistry()
    fm = ForkManager(tmp_path / "forks")
    snap = fm.snapshot(reg)

    reg2 = ModuleRegistry()
    ph2, wm2, _ckpt = _make_phantasia(bus, tmp_path, seed=99, persist=True)
    await ph2.initialize()
    init_arrays = _npz_arrays(wm2.export_params(extra={"encoder_version": _enc()}))
    reg2.register(ph2)

    with caplog.at_level("WARNING"):
        fm.restore(snap.id, reg2)

    assert "fresh world model" in caplog.text
    assert _npz_arrays(wm2.export_params(extra={"encoder_version": _enc()})) == init_arrays

    await ph2.shutdown()


@pytest.mark.asyncio
async def test_mismatched_artifact_fails_closed(bus, tmp_path):
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    reg = ModuleRegistry()
    ph, wm, _ckpt = _make_phantasia(bus, tmp_path, seed=1, persist=True)
    await ph.initialize()
    _train_a_little(ph)
    ph.export_preservation_weights()
    reg.register(ph)

    fm = ForkManager(tmp_path / "forks")
    snap = fm.snapshot(reg)

    reg2 = ModuleRegistry()
    ckpt_b = tmp_path / "phantasia_mismatch" / "wm.ckpt"
    wm2 = NumpyDreamerV3WorldModel(
        observation_dim(),
        deter_dim=16,
        stoch_dim=4,
        stoch_classes=3,
        hidden_dim=8,
        seed=99,
    )
    ph2 = Phantasia(
        bus,
        world_model=wm2,
        backend="dreamerv3",
        engine="numpy",
        persist_weights=True,
        checkpoint_path=str(ckpt_b),
    )
    await ph2.initialize()
    reg2.register(ph2)

    with pytest.raises((CheckpointMismatchError, RuntimeError)):
        fm.restore(snap.id, reg2)

    await ph.shutdown()
    await ph2.shutdown()


@pytest.mark.asyncio
async def test_merge_refusal_and_choice(bus, tmp_path):
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    reg_a = ModuleRegistry()
    ph_a, wm_a, _ckpt_a = _make_phantasia(bus, tmp_path, seed=1, persist=True)
    await ph_a.initialize()
    _train_a_little(ph_a)
    reg_a.register(ph_a)

    fm = ForkManager(tmp_path / "forks")
    a = fm.snapshot(reg_a)

    reg_b = ModuleRegistry()
    ph_b, wm_b, _ckpt_b = _make_phantasia(bus, tmp_path, seed=2, persist=True)
    await ph_b.initialize()
    _train_a_little(ph_b)
    _train_a_little(ph_b)
    reg_b.register(ph_b)
    b = fm.snapshot(reg_b)

    with pytest.raises(ValueError, match="world_model_from"):
        fm.merge(a.id, b.id)

    merged = fm.merge(a.id, b.id, world_model_from="b")
    b_artifact = artifacts_dir(fm.root, b.id, "phantasia") / "world_model.ckpt"
    merged_artifact = artifacts_dir(fm.root, merged.id, "phantasia") / "world_model.ckpt"
    assert merged_artifact.read_bytes() == b_artifact.read_bytes()
    assert merged.metadata["artifact_sources"]["phantasia"] == "b"

    # Only one parent carries artifacts: succeeds without a choice.
    c = fm.fork(a.id, shed=["phantasia"])
    merged2 = fm.merge(a.id, c.id)
    assert merged2.metadata["artifact_sources"]["phantasia"] == "a"

    await ph_a.shutdown()
    await ph_b.shutdown()


@pytest.mark.asyncio
async def test_pass_count_travels(bus, tmp_path):
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    reg = ModuleRegistry()
    ph, wm, ckpt_a = _make_phantasia(bus, tmp_path, seed=1, persist=True)
    await ph.initialize()
    ph.restore_training_pass_count(3)
    assert ph.successful_training_passes == 3
    reg.register(ph)

    fm = ForkManager(tmp_path / "forks")
    snap = fm.snapshot(reg)
    child = fm.fork(snap.id)

    reg2 = ModuleRegistry()
    ph2, wm2, _ckpt_b = _make_phantasia(bus, tmp_path, seed=99, persist=True)
    await ph2.initialize()
    reg2.register(ph2)
    fm.restore(child.id, reg2)
    assert ph2.successful_training_passes == 3

    # preserve_live + revive also carries the count.
    reg3 = ModuleRegistry()
    ph3, wm3, _ckpt_c = _make_phantasia(bus, tmp_path, seed=101, persist=True)
    await ph3.initialize()
    reg3.register(ph3)
    result = await fm.preserve_live(
        reg,
        reason="passcount",
        out_root=tmp_path / "backups",
        entity_name="aria",
    )
    bundle = tmp_path / "backups" / f"preservation_{result.preservation_id}_aria"
    await fm.revive(bundle, reg3)
    assert ph3.successful_training_passes == 3

    await ph.shutdown()
    await ph2.shutdown()
    await ph3.shutdown()


@pytest.mark.asyncio
async def test_revive_without_weights_warns(bus, tmp_path, caplog):
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    reg = ModuleRegistry()
    ph, wm, _ckpt = _make_phantasia(bus, tmp_path, seed=1, persist=False)
    await ph.initialize()
    reg.register(ph)

    fm = ForkManager(tmp_path / "forks")
    result = await fm.preserve_live(
        reg,
        reason="noweights",
        out_root=tmp_path / "backups",
        entity_name="aria",
    )
    bundle = tmp_path / "backups" / f"preservation_{result.preservation_id}_aria"

    reg2 = ModuleRegistry()
    ph2, wm2, _ckpt2 = _make_phantasia(bus, tmp_path, seed=99, persist=True)
    await ph2.initialize()
    reg2.register(ph2)

    with caplog.at_level("WARNING"):
        await fm.revive(bundle, reg2)

    assert "fresh world model" in caplog.text
    await ph2.shutdown()


@pytest.mark.asyncio
async def test_non_persisting_phantasia_export_writes_nothing(bus, tmp_path):
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    ph, wm, _ckpt = _make_phantasia(bus, tmp_path, seed=1, persist=False)
    await ph.initialize()
    dest = tmp_path / "artifact_dest"
    dest.mkdir(parents=True)

    record = ph.export_snapshot_artifacts(dest)

    assert record["captured"] is False
    assert not any(dest.iterdir())

    await ph.shutdown()


@pytest.mark.asyncio
async def test_symlinked_artifact_dir_is_not_copied(bus, tmp_path):
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    reg = ModuleRegistry()
    ph, wm, _ckpt = _make_phantasia(bus, tmp_path, seed=1, persist=True)
    await ph.initialize()
    _train_a_little(ph)
    ph.export_preservation_weights()
    reg.register(ph)

    fm = ForkManager(tmp_path / "forks")
    parent_snap = fm.snapshot(reg)

    # Create a real directory outside the fork root and symlink it into artifacts.
    evil_outside = tmp_path / "evil_outside"
    evil_outside.mkdir()
    (evil_outside / "stolen.txt").write_text("stolen")
    evil_link = artifacts_dir(fm.root, parent_snap.id, "evil")
    evil_link.symlink_to(evil_outside, target_is_directory=True)

    child = fm.fork(parent_snap.id)

    child_evil = artifacts_dir(fm.root, child.id, "evil")
    assert not child_evil.exists()
    assert not child_evil.is_symlink()

    with pytest.raises(ValueError, match="refusing to copy a symlinked artifact directory"):
        copy_artifacts(evil_link, tmp_path / "evil_copy")

    await ph.shutdown()


@pytest.mark.asyncio
async def test_failed_save_leaves_no_snapshot_dir(bus, tmp_path, monkeypatch):
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    reg = ModuleRegistry()
    ph, wm, _ckpt = _make_phantasia(bus, tmp_path, seed=1, persist=True)
    await ph.initialize()
    _train_a_little(ph)
    ph.export_preservation_weights()
    reg.register(ph)

    fm = ForkManager(tmp_path / "forks")
    before_dirs = {p for p in fm.root.iterdir() if p.is_dir()}

    def _fail(*args, **kwargs):
        raise RuntimeError("save failed")
    monkeypatch.setattr("kaine.lifecycle.manager.save_snapshot", _fail)

    with pytest.raises(RuntimeError, match="save failed"):
        fm.snapshot(reg)

    after_dirs = {p for p in fm.root.iterdir() if p.is_dir()}
    assert after_dirs == before_dirs

    await ph.shutdown()


@pytest.mark.asyncio
async def test_sidecar_write_failure_raises(bus, tmp_path, monkeypatch):
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    ph, wm, _ckpt = _make_phantasia(bus, tmp_path, seed=1, persist=True)
    await ph.initialize()
    _train_a_little(ph)
    ph.export_preservation_weights()

    def _fail(*args, **kwargs):
        raise OSError("sidecar write failed")
    monkeypatch.setattr("kaine.state_io.write_json_atomic", _fail)

    dest = tmp_path / "artifact_dest"
    dest.mkdir(parents=True)

    with pytest.raises(OSError, match="sidecar write failed"):
        ph.export_snapshot_artifacts(dest)

    await ph.shutdown()
