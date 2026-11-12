# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Integration tests: ForkManager + KeyRing entity encryption."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from kaine.security.custody.encryptor import EntityEncryptor

import pytest

from kaine.boot.security import build_keyring
from kaine.lifecycle.identity import (
    EntityIdentity,
    mint_identity,
    read_identity_sidecar,
)
from kaine.lifecycle.manager import ForkManager
from kaine.lifecycle.snapshot import (
    ForkSnapshot,
    load_snapshot,
    reencrypt_artifacts,
    save_snapshot,
    snapshot_dir,
)
from kaine.security.crypto import CryptoConfigError
from kaine.security.custody.keyring import KeyRing, SoftwareKek

_ENTITY_A = "ent-0123456789abcdef0123456789abcdef"
_ENTITY_B = "ent-fedcba9876543210fedcba9876543210"


def _fresh_kek() -> bytes:
    return os.urandom(32)


def _make_keyring(tmp_path: Path) -> KeyRing:
    kek = SoftwareKek(_fresh_kek())
    return KeyRing(kek, state_root=tmp_path / "identity-keys")


def _make_identity(entity_id: str = _ENTITY_A) -> EntityIdentity:
    return EntityIdentity(entity_id=entity_id, lineage=(), origin="minted", minted_at=1.0)


@dataclass
class _FakeModule:
    name: str = "testmod"
    value: int = 0

    def serialize(self) -> dict[str, Any]:
        return {"value": self.value}

    def deserialize(self, state: dict[str, Any]) -> None:
        self.value = state["value"]


class _Registry:
    def __init__(self, value: int = 0) -> None:
        self.mod = _FakeModule(value=value)

    def all_modules(self) -> Iterable[_FakeModule]:
        return [self.mod]


# ── ForkManager + KeyRing: snapshot round-trip ────────────────────────────


def test_snapshot_roundtrip_encrypted(tmp_path: Path) -> None:
    keyring = _make_keyring(tmp_path)
    identity = mint_identity()
    keyring.generate_dek(identity.entity_id)

    fm = ForkManager(
        tmp_path / "forks",
        identity_source=lambda: identity,
        keyring=keyring,
    )
    snap = fm.snapshot(_Registry(value=42), label="encrypted-test")

    raw_on_disk = (snapshot_dir(fm.root, snap.id) / "snapshot.json").read_bytes()
    with pytest.raises(Exception):
        json.loads(raw_on_disk)

    loaded = fm.load(snap.id)
    assert loaded.id == snap.id
    assert loaded.modules["testmod"]["value"] == 42
    assert loaded.label == "encrypted-test"


def test_snapshot_encrypted_content_differs_from_plaintext(tmp_path: Path) -> None:
    keyring = _make_keyring(tmp_path)
    identity = mint_identity()
    keyring.generate_dek(identity.entity_id)

    fm = ForkManager(
        tmp_path / "forks",
        identity_source=lambda: identity,
        keyring=keyring,
    )
    snap = fm.snapshot(_Registry(value=99))

    raw = (snapshot_dir(fm.root, snap.id) / "snapshot.json").read_bytes()
    assert b'"value": 99' not in raw


# ── ForkManager + KeyRing: fork creates child DEK ────────────────────────


def test_fork_creates_child_dek(tmp_path: Path) -> None:
    keyring = _make_keyring(tmp_path)
    parent_identity = mint_identity()
    keyring.generate_dek(parent_identity.entity_id)

    fm = ForkManager(
        tmp_path / "forks",
        identity_source=lambda: parent_identity,
        keyring=keyring,
    )
    parent = fm.snapshot(_Registry(value=10))
    child = fm.fork(parent.id)

    child_identity_data = child.metadata.get("identity")
    assert child_identity_data is not None
    child_eid = child_identity_data["entity_id"]
    assert child_eid != parent_identity.entity_id

    assert keyring.has_dek(child_eid)


def test_fork_child_encrypted_under_child_key(tmp_path: Path) -> None:
    keyring = _make_keyring(tmp_path)
    parent_identity = mint_identity()
    keyring.generate_dek(parent_identity.entity_id)

    fm = ForkManager(
        tmp_path / "forks",
        identity_source=lambda: parent_identity,
        keyring=keyring,
    )
    parent = fm.snapshot(_Registry(value=10))
    child = fm.fork(parent.id)

    child_eid = child.metadata["identity"]["entity_id"]
    child_enc = keyring.encryptor_for(child_eid)
    parent_enc = keyring.encryptor_for(parent_identity.entity_id)

    child_raw = (snapshot_dir(fm.root, child.id) / "snapshot.json").read_bytes()
    child_text = child_enc.maybe_decrypt(child_raw, kind="snapshot").decode("utf-8")
    child_data = json.loads(child_text)
    assert child_data["modules"]["testmod"]["value"] == 10

    with pytest.raises(Exception):
        parent_dec = parent_enc.maybe_decrypt(child_raw, kind="snapshot")
        json.loads(parent_dec.decode("utf-8"))


def test_fork_parent_snapshot_unchanged(tmp_path: Path) -> None:
    keyring = _make_keyring(tmp_path)
    parent_identity = mint_identity()
    keyring.generate_dek(parent_identity.entity_id)

    fm = ForkManager(
        tmp_path / "forks",
        identity_source=lambda: parent_identity,
        keyring=keyring,
    )
    parent = fm.snapshot(_Registry(value=7))
    parent_raw_before = (snapshot_dir(fm.root, parent.id) / "snapshot.json").read_bytes()

    fm.fork(parent.id)

    parent_raw_after = (snapshot_dir(fm.root, parent.id) / "snapshot.json").read_bytes()
    assert parent_raw_before == parent_raw_after

    loaded_parent = fm.load(parent.id)
    assert loaded_parent.modules["testmod"]["value"] == 7


# ── ForkManager + KeyRing: merge re-encrypts ─────────────────────────────


def test_merge_encrypted_under_surviving_entity(tmp_path: Path) -> None:
    keyring = _make_keyring(tmp_path)
    parent_identity = mint_identity()
    keyring.generate_dek(parent_identity.entity_id)

    fm = ForkManager(
        tmp_path / "forks",
        identity_source=lambda: parent_identity,
        keyring=keyring,
    )
    parent = fm.snapshot(_Registry(value=1))

    child_a = fm.fork(parent.id)
    child_b = fm.fork(parent.id)

    merged = fm.merge(child_a.id, child_b.id, label="merge-test")

    sidecar = read_identity_sidecar(snapshot_dir(fm.root, merged.id))
    assert sidecar is not None
    merged_eid = sidecar[0]
    child_a_eid = child_a.metadata["identity"]["entity_id"]
    assert merged_eid == child_a_eid

    loaded = fm.load(merged.id)
    assert loaded.id == merged.id
    assert loaded.modules["testmod"]["value"] == 1


def test_merge_result_decryptable(tmp_path: Path) -> None:
    keyring = _make_keyring(tmp_path)
    parent_identity = mint_identity()
    keyring.generate_dek(parent_identity.entity_id)

    fm = ForkManager(
        tmp_path / "forks",
        identity_source=lambda: parent_identity,
        keyring=keyring,
    )
    parent = fm.snapshot(_Registry(value=55))
    child_a = fm.fork(parent.id)
    child_b = fm.fork(parent.id)
    merged = fm.merge(child_a.id, child_b.id)

    enc_a = keyring.encryptor_for(child_a.metadata["identity"]["entity_id"])
    raw = (snapshot_dir(fm.root, merged.id) / "snapshot.json").read_bytes()
    text = enc_a.maybe_decrypt(raw, kind="snapshot").decode("utf-8")
    data = json.loads(text)
    assert data["modules"]["testmod"]["value"] == 55


# ── build_keyring config tests ───────────────────────────────────────────


def test_build_keyring_disabled_by_default() -> None:
    assert build_keyring({}) is None


def test_build_keyring_disabled_explicitly() -> None:
    config = {"security": {"custody": {"enabled": False}}}
    assert build_keyring(config) is None


def test_build_keyring_no_security_section() -> None:
    assert build_keyring({"other": "stuff"}) is None


def test_build_keyring_enabled_with_kek(monkeypatch: pytest.MonkeyPatch) -> None:
    kek_hex = os.urandom(32).hex()
    monkeypatch.setenv("KAINE_CUSTODY_KEK", kek_hex)
    config = {"security": {"custody": {"enabled": True}}}
    kr = build_keyring(config)
    assert isinstance(kr, KeyRing)


def test_build_keyring_enabled_custom_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    kek_hex = os.urandom(32).hex()
    monkeypatch.setenv("MY_CUSTOM_KEK", kek_hex)
    config = {"security": {"custody": {"enabled": True, "kek_env_var": "MY_CUSTOM_KEK"}}}
    kr = build_keyring(config)
    assert isinstance(kr, KeyRing)


def test_build_keyring_fails_on_missing_kek(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KAINE_CUSTODY_KEK", raising=False)
    config = {"security": {"custody": {"enabled": True}}}
    with pytest.raises(CryptoConfigError, match="not set or empty"):
        build_keyring(config)


def test_build_keyring_fails_on_bad_hex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAINE_CUSTODY_KEK", "not-hex-at-all")
    config = {"security": {"custody": {"enabled": True}}}
    with pytest.raises(CryptoConfigError, match="not valid hex"):
        build_keyring(config)


def test_build_keyring_fails_on_tpm() -> None:
    config = {"security": {"custody": {"enabled": True, "kek_source": "tpm"}}}
    with pytest.raises(CryptoConfigError, match="not yet implemented"):
        build_keyring(config)


def test_build_keyring_fails_on_unknown_source() -> None:
    config = {"security": {"custody": {"enabled": True, "kek_source": "magic"}}}
    with pytest.raises(CryptoConfigError, match="not recognized"):
        build_keyring(config)


# ── Backward compatibility: keyring=None ─────────────────────────────────


def test_no_keyring_snapshot_roundtrip(tmp_path: Path) -> None:
    fm = ForkManager(tmp_path / "forks")
    snap = fm.snapshot(_Registry(value=77), label="plain")
    loaded = fm.load(snap.id)
    assert loaded.modules["testmod"]["value"] == 77
    assert loaded.label == "plain"


def test_no_keyring_fork_roundtrip(tmp_path: Path) -> None:
    fm = ForkManager(tmp_path / "forks")
    parent = fm.snapshot(_Registry(value=3))
    child = fm.fork(parent.id)
    loaded = fm.load(child.id)
    assert loaded.modules["testmod"]["value"] == 3
    assert loaded.parent_id == parent.id


def test_no_keyring_merge_roundtrip(tmp_path: Path) -> None:
    fm = ForkManager(tmp_path / "forks")
    parent = fm.snapshot(_Registry(value=5))
    a = fm.fork(parent.id)
    b = fm.fork(parent.id)
    merged = fm.merge(a.id, b.id, label="merged")
    loaded = fm.load(merged.id)
    assert loaded.modules["testmod"]["value"] == 5
    assert loaded.label == "merged"


# ── Low-level snapshot + encryptor tests ───────────────────────────────────


def _make_encryptor(tmp_path: Path, entity_id: str) -> EntityEncryptor:
    """Create a KeyRing, generate a DEK, return the EntityEncryptor."""

    kek = SoftwareKek(_fresh_kek())
    ring = KeyRing(kek, state_root=tmp_path / "kr-state")
    ring.generate_dek(entity_id)
    return ring.encryptor_for(entity_id)


def test_save_load_snapshot_direct_with_encryptor(tmp_path: Path) -> None:
    """save_snapshot + load_snapshot round-trip with EntityEncryptor."""
    enc = _make_encryptor(tmp_path, _ENTITY_A)
    snap = ForkSnapshot(
        parent_id=None,
        label="direct-enc",
        modules={"interoception": {"wellness": 0.8}},
        adapters=["state/sleep/adapters/a"],
        metadata={"note": "encrypted"},
    )
    snap_root = tmp_path / "direct-snaps"
    save_snapshot(snap_root, snap, encryptor=enc)

    loaded = load_snapshot(snap_root, snap.id, encryptor=enc)
    assert loaded.id == snap.id
    assert loaded.modules == snap.modules
    assert loaded.adapters == snap.adapters
    assert loaded.metadata == snap.metadata

    # On-disk file must NOT be valid JSON (it is encrypted).
    disk = snap_root / snap.id / "snapshot.json"
    raw = disk.read_text()
    with pytest.raises((json.JSONDecodeError, ValueError)):
        json.loads(raw)


def test_reencrypt_artifacts_transfers_between_keys(tmp_path: Path) -> None:
    """reencrypt_artifacts re-encrypts under a different entity key."""
    from cryptography.exceptions import InvalidTag

    enc_a = _make_encryptor(tmp_path, _ENTITY_A)
    enc_b = _make_encryptor(tmp_path, _ENTITY_B)

    src_dir = tmp_path / "artifacts" / "src"
    dst_dir = tmp_path / "artifacts" / "dst"
    src_dir.mkdir(parents=True)

    plaintext = b"cognitive-state-payload-for-test"
    ciphertext_a = enc_a.encrypt(plaintext, kind="artifact")
    (src_dir / "data.bin").write_bytes(ciphertext_a)

    reencrypt_artifacts(
        src_dir, dst_dir, src_encryptor=enc_a, dst_encryptor=enc_b
    )

    dst_blob = (dst_dir / "data.bin").read_bytes()
    assert enc_b.maybe_decrypt(dst_blob, kind="artifact") == plaintext

    with pytest.raises((InvalidTag, ValueError)):
        enc_a.decrypt(dst_blob, kind="artifact")


def test_save_snapshot_without_encryptor_is_plaintext(tmp_path: Path) -> None:
    """Backward compat: save/load without encryptor keeps plaintext JSON."""
    snap = ForkSnapshot(
        parent_id=None,
        label="plain-direct",
        modules={"sequence": {"steps": 7}},
        adapters=[],
        metadata={},
    )
    snap_root = tmp_path / "plain-snaps"
    save_snapshot(snap_root, snap)
    loaded = load_snapshot(snap_root, snap.id)
    assert loaded.id == snap.id
    assert loaded.modules == snap.modules

    disk = snap_root / snap.id / "snapshot.json"
    parsed = json.loads(disk.read_text())
    assert parsed["modules"]["sequence"]["steps"] == 7
