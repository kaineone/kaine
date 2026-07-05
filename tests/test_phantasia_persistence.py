# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Phantasia world-model weight persistence (opt-in, fail-closed, encrypted).

Covers the `phantasia-weight-persistence` change:

* DreamerV3 codec round-trip (jax-gated) + fail-closed import on any
  config/shape/encoder-version mismatch.
* Module wiring: persist_weights honesty guard (the fake EMA stub cannot
  persist), load-on-initialize, save-after-successful-train,
  no-save-after-aborted-train, save-on-shutdown.
* Encryption at rest via the shared StateEncryptor.
* Decommission backup includes state/phantasia/; deletion removes it.
* Shipped config keeps persist_weights = false.
* The trajectory buffer never reaches a checkpoint or serialize().
"""
from __future__ import annotations

import base64
import json
import os
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.phantasia.encoder import observation_dim
from kaine.modules.phantasia.module import Phantasia
from kaine.modules.phantasia.world_model import (
    CheckpointMismatchError,
    FakeWorldModel,
    TrainOutcome,
)
from kaine.security.crypto import (
    CryptoConfig,
    StateEncryptor,
    is_encrypted,
    set_state_encryptor,
)

PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _event(source: str, type_: str, salience: float = 0.5) -> Event:
    return Event(
        source=source,
        type=type_,
        payload={},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _snapshot(tick: int) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=tick,
        selected_events=[("0-0", _event("soma", "soma.report", 0.5))],
    )


class _PersistableFake(FakeWorldModel):
    """FakeWorldModel + the export/import capability, for wiring tests.

    Records what was imported so tests can assert load-on-initialize without
    needing jax. NOT a model of honest persistence semantics — production
    code gates on the capability, which the plain FakeWorldModel lacks.
    """

    def __init__(self, obs_dim: int, **kw) -> None:
        super().__init__(obs_dim, **kw)
        self.imported: dict | None = None
        self.export_count = 0

    def export_params(self, *, extra=None) -> bytes:
        self.export_count += 1
        return json.dumps({"decay": self._decay, "extra": dict(extra or {})}).encode()

    def import_params(self, blob: bytes, *, extra=None) -> None:
        data = json.loads(blob)
        if data.get("extra") != dict(extra or {}):
            raise CheckpointMismatchError(
                f"extra mismatch: {data.get('extra')} != {dict(extra or {})}"
            )
        self._decay = float(data["decay"])
        self.imported = data


class _AbortingFake(_PersistableFake):
    def train(self, trajectory) -> TrainOutcome:
        return TrainOutcome(loss=float("nan"), steps=0, aborted=True, reason="forced")


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


@pytest.fixture
def plaintext_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


@pytest.fixture
def enabled_encryptor(monkeypatch):
    monkeypatch.setenv(
        "KAINE_STATE_KEY", base64.b64encode(os.urandom(32)).decode("ascii")
    )
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=True)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


def _obs(dim: int, seed: int) -> list[float]:
    return [((seed * 31 + i * 7) % 13) / 13.0 for i in range(dim)]


# ---------------------------------------------------------------------------
# DreamerV3 codec (jax-gated)
# ---------------------------------------------------------------------------


def _npz_arrays(blob: bytes) -> dict[str, bytes]:
    """Name → raw array bytes (and the header), ignoring zip timestamps."""
    import io

    import numpy as np

    data = np.load(io.BytesIO(blob), allow_pickle=False)
    return {name: data[name].tobytes() for name in data.files}


def _dreamer(obs_dim: int = 6, **kw):
    pytest.importorskip("jax")
    from kaine.modules.phantasia.world_model import DreamerV3WorldModel

    defaults = dict(
        deter_dim=8, stoch_dim=4, stoch_classes=3, hidden_dim=8, seed=kw.pop("seed", 0)
    )
    defaults.update(kw)
    return DreamerV3WorldModel(obs_dim, **defaults)


def test_dreamer_export_import_roundtrip():
    src = _dreamer(seed=0)
    for i in range(8):
        src.observe(_obs(src.obs_dim, i))
    src.train([_obs(src.obs_dim, i) for i in range(8)])
    blob = src.export_params(extra={"encoder_version": "test-v1"})

    dst = _dreamer(seed=99)  # different random init
    dst.import_params(blob, extra={"encoder_version": "test-v1"})

    # Identical params (bit-for-bit) and identical behavior after import.
    assert _npz_arrays(blob) == _npz_arrays(
        dst.export_params(extra={"encoder_version": "test-v1"})
    )
    src.reset_state()
    dst.reset_state()
    for i in range(5):
        assert src.observe(_obs(src.obs_dim, i)) == pytest.approx(
            dst.observe(_obs(dst.obs_dim, i))
        )


def test_dreamer_import_rejects_dim_mismatch():
    blob = _dreamer(obs_dim=6).export_params()
    with pytest.raises(CheckpointMismatchError, match="obs_dim"):
        _dreamer(obs_dim=7).import_params(blob)
    with pytest.raises(CheckpointMismatchError, match="deter_dim"):
        _dreamer(deter_dim=16).import_params(blob)


def test_dreamer_import_rejects_latent_kind_mismatch():
    blob = _dreamer(latent_kind="categorical").export_params()
    with pytest.raises(CheckpointMismatchError, match="latent_kind"):
        _dreamer(latent_kind="gaussian").import_params(blob)


def test_dreamer_import_rejects_encoder_version_mismatch():
    blob = _dreamer().export_params(extra={"encoder_version": "old"})
    with pytest.raises(CheckpointMismatchError, match="extra"):
        _dreamer().import_params(blob, extra={"encoder_version": "new"})


def test_dreamer_import_rejects_garbage():
    with pytest.raises(CheckpointMismatchError, match="not a readable"):
        _dreamer().import_params(b"not an npz at all")


def test_dreamer_mismatch_leaves_model_untouched():
    model = _dreamer(seed=0)
    before = model.export_params()
    bad = _dreamer(seed=1).export_params(extra={"encoder_version": "other"})
    with pytest.raises(CheckpointMismatchError):
        model.import_params(bad, extra={"encoder_version": "mine"})
    assert _npz_arrays(model.export_params()) == _npz_arrays(before)


def test_dreamer_checkpoint_contains_no_observations():
    """The blob holds weights only — no trajectory/observation data."""
    import io

    import numpy as np

    src = _dreamer()
    marker = [0.123456789] * src.obs_dim
    for _ in range(4):
        src.observe(marker)
    blob = src.export_params()
    data = np.load(io.BytesIO(blob), allow_pickle=False)
    # Every array maps to a param-tree entry; header is config-only.
    groups = set(src.parameter_names())
    for name in data.files:
        if name == "__header__":
            continue
        assert name.split("/")[0] in groups


# ---------------------------------------------------------------------------
# Module wiring (no jax needed — capability-bearing test double)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_with_fake_backend_is_config_error(bus: AsyncBus):
    with pytest.raises(ValueError, match="persist_weights"):
        Phantasia(bus, backend="fake", persist_weights=True)


@pytest.mark.asyncio
async def test_save_on_shutdown_and_load_on_initialize(
    bus: AsyncBus, tmp_path: Path, plaintext_encryptor
):
    ckpt = tmp_path / "wm.ckpt"
    wm1 = _PersistableFake(obs_dim=observation_dim())
    ph1 = Phantasia(
        bus,
        world_model=wm1,
        backend="dreamerv3",
        persist_weights=True,
        checkpoint_path=str(ckpt),
    )
    await ph1.initialize()
    assert wm1.imported is None  # no checkpoint existed yet
    await ph1.shutdown()
    assert ckpt.is_file()

    wm2 = _PersistableFake(obs_dim=observation_dim())
    ph2 = Phantasia(
        bus,
        world_model=wm2,
        backend="dreamerv3",
        persist_weights=True,
        checkpoint_path=str(ckpt),
    )
    await ph2.initialize()
    try:
        assert wm2.imported is not None
        assert wm2.imported["decay"] == pytest.approx(wm1._decay)
        assert wm2.imported["extra"]["encoder_version"]
    finally:
        await ph2.shutdown()


@pytest.mark.asyncio
async def test_save_after_successful_training_pass(
    bus: AsyncBus, tmp_path: Path, plaintext_encryptor
):
    ckpt = tmp_path / "wm.ckpt"
    wm = _PersistableFake(obs_dim=observation_dim())
    ph = Phantasia(
        bus,
        world_model=wm,
        backend="dreamerv3",
        persist_weights=True,
        checkpoint_path=str(ckpt),
        training_enabled=True,
    )
    await ph.initialize()
    try:
        for i in range(5):
            await ph.on_workspace(_snapshot(i))
        assert not ckpt.exists()
        await ph._handle_peer_event(
            "hypnos.out", _event("hypnos", "hypnos.sleep.started")
        )
        assert ckpt.is_file()
    finally:
        await ph.shutdown()


@pytest.mark.asyncio
async def test_aborted_training_does_not_overwrite_checkpoint(
    bus: AsyncBus, tmp_path: Path, plaintext_encryptor
):
    ckpt = tmp_path / "wm.ckpt"
    wm = _AbortingFake(obs_dim=observation_dim())
    ph = Phantasia(
        bus,
        world_model=wm,
        backend="dreamerv3",
        persist_weights=True,
        checkpoint_path=str(ckpt),
        training_enabled=True,
    )
    await ph.initialize()
    try:
        for i in range(5):
            await ph.on_workspace(_snapshot(i))
        outcome = await ph._maybe_train()
        assert outcome is not None and outcome.aborted
        # The aborted pass saved nothing — last-known-good stays untouched.
        assert not ckpt.exists()
        assert wm.export_count == 0
    finally:
        await ph.shutdown()
    # Graceful shutdown still checkpoints (by design).
    assert ckpt.is_file()


@pytest.mark.asyncio
async def test_incompatible_checkpoint_fails_closed_on_initialize(
    bus: AsyncBus, tmp_path: Path, plaintext_encryptor
):
    ckpt = tmp_path / "wm.ckpt"
    # A checkpoint written under a different encoder version.
    ckpt.write_bytes(
        json.dumps({"decay": 0.5, "extra": {"encoder_version": "ancient"}}).encode()
    )
    wm = _PersistableFake(obs_dim=observation_dim())
    ph = Phantasia(
        bus,
        world_model=wm,
        backend="dreamerv3",
        persist_weights=True,
        checkpoint_path=str(ckpt),
    )
    with pytest.raises(CheckpointMismatchError, match="refusing to silently discard"):
        await ph.initialize()
    # Fail-closed must not modify the checkpoint.
    assert b"ancient" in ckpt.read_bytes()


@pytest.mark.asyncio
async def test_checkpoint_encrypted_at_rest(
    bus: AsyncBus, tmp_path: Path, enabled_encryptor
):
    ckpt = tmp_path / "wm.ckpt"
    wm1 = _PersistableFake(obs_dim=observation_dim())
    ph1 = Phantasia(
        bus,
        world_model=wm1,
        backend="dreamerv3",
        persist_weights=True,
        checkpoint_path=str(ckpt),
    )
    await ph1.initialize()
    await ph1.shutdown()

    raw = ckpt.read_bytes()
    assert b'"decay"' not in raw  # not plaintext
    assert is_encrypted(base64.b64decode(raw))

    wm2 = _PersistableFake(obs_dim=observation_dim())
    ph2 = Phantasia(
        bus,
        world_model=wm2,
        backend="dreamerv3",
        persist_weights=True,
        checkpoint_path=str(ckpt),
    )
    await ph2.initialize()
    try:
        assert wm2.imported is not None  # transparently decrypted
    finally:
        await ph2.shutdown()


@pytest.mark.asyncio
async def test_serialize_reports_persistence_metadata_never_buffer(
    bus: AsyncBus, tmp_path: Path, plaintext_encryptor
):
    ckpt = tmp_path / "wm.ckpt"
    wm = _PersistableFake(obs_dim=observation_dim())
    ph = Phantasia(
        bus,
        world_model=wm,
        backend="dreamerv3",
        persist_weights=True,
        checkpoint_path=str(ckpt),
    )
    await ph.initialize()
    try:
        for i in range(10):
            await ph.on_workspace(_snapshot(i))
        state = ph.serialize()
        assert state["persist_weights"] is True
        assert state["checkpoint_path"] == str(ckpt)
        for value in state.values():
            assert not (
                isinstance(value, list) and value and isinstance(value[0], list)
            )
        # Configured path wins over restored metadata.
        ph.deserialize({"checkpoint_path": "/somewhere/else.ckpt"})
        assert ph.serialize()["checkpoint_path"] == str(ckpt)
    finally:
        await ph.shutdown()


@pytest.mark.asyncio
async def test_persistence_off_means_no_writes(bus: AsyncBus, tmp_path: Path):
    wm = _PersistableFake(obs_dim=observation_dim())
    ph = Phantasia(
        bus,
        world_model=wm,
        backend="dreamerv3",
        persist_weights=False,
        checkpoint_path=str(tmp_path / "wm.ckpt"),
        training_enabled=True,
    )
    await ph.initialize()
    try:
        for i in range(5):
            await ph.on_workspace(_snapshot(i))
        await ph._handle_peer_event(
            "hypnos.out", _event("hypnos", "hypnos.sleep.started")
        )
    finally:
        await ph.shutdown()
    assert list(tmp_path.iterdir()) == []
    assert wm.export_count == 0
    assert ph.serialize()["checkpoint_path"] is None


# ---------------------------------------------------------------------------
# Shipped config + decommission integration
# ---------------------------------------------------------------------------


def test_shipped_config_persist_weights_off():
    cfg = tomllib.loads((PROJECT_ROOT / "config" / "kaine.toml").read_text())
    assert cfg["phantasia"]["persist_weights"] is False
    assert cfg["phantasia"]["checkpoint_path"] == "state/phantasia/world_model.ckpt"


def test_decommission_backup_includes_phantasia_checkpoint(tmp_path: Path, monkeypatch):
    from kaine.lifecycle.decommission import capture_backup, delete_entity_state
    from kaine.lifecycle.divergence import DivergenceAssessment

    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    state_root = tmp_path / "state"
    (state_root / "phantasia").mkdir(parents=True)
    (state_root / "phantasia" / "world_model.ckpt").write_bytes(b"weights")

    result = capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        qdrant_cfg={},
        out_root=tmp_path / "backups",
        entity_name="testkaine",
        assessment=DivergenceAssessment(diverged=False, signals={}, summary="t"),
    )
    assert result.ok
    assert "phantasia/" in result.inventory
    copied = result.backup_path / "phantasia" / "world_model.ckpt"
    assert copied.read_bytes() == b"weights"
    manifest = json.loads((result.backup_path / "manifest.json").read_text())
    assert "state/phantasia/" in manifest["restore_notes"]

    # Deletion removes the phantasia subtree (after backup).
    deletion = delete_entity_state(
        state_root=state_root, qdrant_cfg=None, redis_cfg=None, dry_run=False
    )
    assert str(state_root / "phantasia") in deletion.removed_paths
    assert not (state_root / "phantasia").exists()
