# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from kaine.lifecycle.identity import (
    IDENTITY_PATH,
    OWN_LIVED_ARTIFACTS,
    SIDECAR_NAME,
    EntityIdentity,
    IdentityError,
    check_sidecar_agrees,
    fork_identity,
    has_prior_lived_history_in_lineage,
    identity_of_snapshot,
    legacy_identity,
    load_identity,
    mint_identity,
    own_lived_artifacts,
    read_identity_sidecar,
    resolve_spawn_identity,
    save_identity,
    tree_digest,
    write_identity_sidecar,
)


class _FakeSnap:
    def __init__(self, metadata):
        self.metadata = metadata


def _assert_mode(path: Path) -> None:
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


def test_identity_path_is_relative():
    assert str(IDENTITY_PATH) == "state/identity/entity.json"


def test_own_lived_artifacts_listing(tmp_path):
    assert OWN_LIVED_ARTIFACTS == (
        Path("lifecycle/stage.json"),
        Path("phantasia/world_model.ckpt"),
        Path("hypnos/consolidation_divergence.json"),
        Path("perception/desired.json"),
    )
    stage = tmp_path / "lifecycle" / "stage.json"
    stage.parent.mkdir(parents=True)
    stage.write_text("{}")
    assert own_lived_artifacts(tmp_path) == [stage]


def test_legacy_identity_golden_bundle():
    source = "bundle:abc"
    expected = "legacy-" + hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]
    identity = legacy_identity(source, now=lambda: 42.0)
    assert identity.entity_id == expected
    assert identity.origin == "legacy"
    assert identity.lineage == ()
    assert identity.legacy_source == source
    assert identity.minted_at == 42.0


def test_legacy_identity_golden_tree_source():
    source = "tree:" + hashlib.sha256(b"foo").hexdigest()
    expected = "legacy-" + hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]
    identity = legacy_identity(source, now=lambda: 1.0)
    assert identity.entity_id == expected


def test_legacy_identity_rejects_empty_source():
    with pytest.raises(IdentityError):
        legacy_identity("")
    with pytest.raises(IdentityError):
        legacy_identity(None)


def test_entity_identity_rejects_bad_entity_id():
    cases = [
        ("ENT-abcdef0123456789abcdef0123456789", "minted", None),
        ("ent-abcdef0123456789", "minted", None),
        ("ent-abcdef0123456789abcdef0123456789a", "minted", None),
        ("foo-abcdef0123456789abcdef0123456789", "minted", None),
        ("legacy-ABCDEF0123456789ABCDEF01234567", "legacy", "src"),
    ]
    for entity_id, origin, source in cases:
        with pytest.raises(IdentityError):
            EntityIdentity(entity_id=entity_id, origin=origin, legacy_source=source)


def test_entity_identity_rejects_bad_lineage():
    good = "ent-abcdef0123456789abcdef0123456789"
    with pytest.raises(IdentityError):
        EntityIdentity(entity_id=good, lineage=("bad-id",))
    with pytest.raises(IdentityError):
        EntityIdentity(entity_id=good, lineage=(123,))


def test_entity_identity_rejects_bad_origin():
    good = "ent-abcdef0123456789abcdef0123456789"
    with pytest.raises(IdentityError):
        EntityIdentity(entity_id=good, origin="other")


def test_entity_identity_legacy_requires_source():
    legacy_id = "legacy-abcdef0123456789abcdef0123456789"
    with pytest.raises(IdentityError):
        EntityIdentity(entity_id=legacy_id, origin="legacy", legacy_source=None)
    with pytest.raises(IdentityError):
        EntityIdentity(entity_id=legacy_id, origin="legacy", legacy_source="")


def test_entity_identity_minted_rejects_source():
    good = "ent-abcdef0123456789abcdef0123456789"
    with pytest.raises(IdentityError):
        EntityIdentity(entity_id=good, origin="minted", legacy_source="x")


def test_entity_identity_rejects_bad_minted_at():
    good = "ent-abcdef0123456789abcdef0123456789"
    with pytest.raises(IdentityError):
        EntityIdentity(entity_id=good, minted_at="now")
    with pytest.raises(IdentityError):
        EntityIdentity(entity_id=good, minted_at=float("inf"))


def test_entity_identity_to_dict_lineage_is_list():
    root = mint_identity(now=lambda: 1.0)
    child = fork_identity(root, now=lambda: 2.0)
    d = child.to_dict()
    assert isinstance(d["lineage"], list)
    assert d["lineage"] == [root.entity_id]
    assert set(d.keys()) == {"entity_id", "lineage", "origin", "minted_at", "legacy_source"}


def test_from_dict_round_trip():
    identity = mint_identity(now=lambda: 1.0)
    assert EntityIdentity.from_dict(identity.to_dict()) == identity
    legacy = legacy_identity("bundle:x", now=lambda: 2.0)
    assert EntityIdentity.from_dict(legacy.to_dict()) == legacy


def test_from_dict_missing_field():
    good = mint_identity().to_dict()
    for key in good:
        bad = {k: v for k, v in good.items() if k != key}
        with pytest.raises(IdentityError):
            EntityIdentity.from_dict(bad)


def test_from_dict_mistyped_fields():
    good = mint_identity().to_dict()
    mutations = [
        ("entity_id", 123),
        ("lineage", "not-a-list"),
        ("origin", 123),
        ("minted_at", "not-a-number"),
        ("legacy_source", 123),
    ]
    for key, value in mutations:
        bad = dict(good)
        bad[key] = value
        with pytest.raises(IdentityError):
            EntityIdentity.from_dict(bad)


def test_from_dict_rejects_extra_keys():
    good = mint_identity().to_dict()
    good["extra"] = "value"
    with pytest.raises(IdentityError):
        EntityIdentity.from_dict(good)


def test_mint_identity_unique_and_formatted():
    ids = {mint_identity(now=lambda: 1.0).entity_id for _ in range(1000)}
    assert len(ids) == 1000
    for eid in ids:
        assert re.fullmatch(r"^ent-[0-9a-f]{32}$", eid)


def test_fork_lineage():
    a = mint_identity(now=lambda: 1.0)
    b = fork_identity(a, now=lambda: 2.0)
    assert b.entity_id != a.entity_id
    assert b.origin == "minted"
    assert b.lineage == (a.entity_id,)
    c = fork_identity(b, now=lambda: 3.0)
    assert c.lineage == (a.entity_id, b.entity_id)


def test_save_load_roundtrip(tmp_path):
    identity = mint_identity(now=lambda: 1.0)
    path = tmp_path / "entity.json"
    save_identity(identity, path)
    loaded = load_identity(path)
    assert loaded == identity
    _assert_mode(path)


def test_save_identity_refuses_different_id(tmp_path):
    a = mint_identity(now=lambda: 1.0)
    b = mint_identity(now=lambda: 2.0)
    path = tmp_path / "entity.json"
    save_identity(a, path)
    before = path.read_text()
    with pytest.raises(IdentityError):
        save_identity(b, path)
    assert path.read_text() == before


def test_save_identity_idempotent(tmp_path):
    a = mint_identity(now=lambda: 1.0)
    path = tmp_path / "entity.json"
    save_identity(a, path)
    save_identity(a, path)
    assert load_identity(path) == a


def test_load_identity_missing(tmp_path):
    assert load_identity(tmp_path / "entity.json") is None


def test_load_identity_malformed(tmp_path):
    path = tmp_path / "entity.json"
    path.write_text("not json")
    with pytest.raises(IdentityError):
        load_identity(path)


def test_identity_of_snapshot_present():
    identity = mint_identity(now=lambda: 1.0)
    snap = _FakeSnap(metadata={"identity": identity.to_dict()})
    assert identity_of_snapshot(snap) == identity


def test_identity_of_snapshot_absent():
    snap = _FakeSnap(metadata={})
    assert identity_of_snapshot(snap) is None


def test_identity_of_snapshot_malformed():
    snap = _FakeSnap(metadata={"identity": {"entity_id": "bad"}})
    with pytest.raises(IdentityError):
        identity_of_snapshot(snap)


def test_sidecar_roundtrip(tmp_path):
    identity = mint_identity(now=lambda: 1.0)
    container = tmp_path / "forks" / "snap1"
    write_identity_sidecar(container, identity)
    sidecar_path = container / SIDECAR_NAME
    raw = json.loads(sidecar_path.read_text())
    assert set(raw.keys()) == {"entity_id", "lineage"}
    assert raw["entity_id"] == identity.entity_id
    assert raw["lineage"] == list(identity.lineage)
    assert read_identity_sidecar(container) == (identity.entity_id, identity.lineage)
    _assert_mode(sidecar_path)


def test_read_identity_sidecar_malformed(tmp_path):
    container = tmp_path / "c"
    container.mkdir()
    (container / SIDECAR_NAME).write_text('{"entity_id": "bad", "lineage": []}')
    with pytest.raises(IdentityError):
        read_identity_sidecar(container)


def test_check_sidecar_agrees():
    a = mint_identity(now=lambda: 1.0)
    b = mint_identity(now=lambda: 2.0)
    c = fork_identity(b, now=lambda: 3.0)

    check_sidecar_agrees(None, a)
    check_sidecar_agrees((a.entity_id, a.lineage), None)
    check_sidecar_agrees((a.entity_id, a.lineage), a)

    with pytest.raises(IdentityError):
        check_sidecar_agrees((b.entity_id, b.lineage), a)

    with pytest.raises(IdentityError):
        # same entity_id but different lineage
        check_sidecar_agrees((b.entity_id, c.lineage), b)


def test_tree_digest_changes_with_bytes(tmp_path):
    ckpt = tmp_path / "phantasia" / "world_model.ckpt"
    ckpt.mkdir(parents=True)
    f = ckpt / "w.bin"
    f.write_bytes(b"1")
    arts = own_lived_artifacts(tmp_path)
    d1 = tree_digest(tmp_path, arts)
    f.write_bytes(b"2")
    arts = own_lived_artifacts(tmp_path)
    d2 = tree_digest(tmp_path, arts)
    assert d1 != d2


def test_tree_digest_independent_of_walk_order(tmp_path):
    ckpt = tmp_path / "phantasia" / "world_model.ckpt"
    ckpt.mkdir(parents=True)
    (ckpt / "a.bin").write_bytes(b"x")
    (ckpt / "b.bin").write_bytes(b"y")
    arts = own_lived_artifacts(tmp_path)

    d1 = tree_digest(tmp_path, arts)

    real_walk = os.walk

    def reverse_walk(*args, **kwargs):
        for dirpath, dirnames, filenames in real_walk(*args, **kwargs):
            yield dirpath, dirnames[::-1], filenames[::-1]

    with patch("kaine.lifecycle.identity.os.walk", side_effect=reverse_walk):
        d2 = tree_digest(tmp_path, arts)

    assert d1 == d2


def test_resolve_spawn_identity_empty_tree(tmp_path):
    identity = resolve_spawn_identity(tmp_path, now=lambda: 1.0)
    assert identity.origin == "minted"
    assert identity.lineage == ()
    assert (tmp_path / "identity" / "entity.json").exists()
    second = resolve_spawn_identity(tmp_path, now=lambda: 2.0)
    assert second == identity


def test_resolve_spawn_identity_foreign_records_only(tmp_path):
    foreign = mint_identity(now=lambda: 1.0)

    forks_dir = tmp_path / "forks" / "snap1"
    forks_dir.mkdir(parents=True)
    write_identity_sidecar(forks_dir, foreign)

    pres_dir = tmp_path / "preservation" / "bundle1"
    pres_dir.mkdir(parents=True)
    (pres_dir / "manifest.json").write_text(
        json.dumps({"identity": foreign.to_dict(), "data": "x"})
    )

    identity = resolve_spawn_identity(tmp_path, now=lambda: 2.0)
    assert identity.origin == "minted"
    assert (tmp_path / "identity" / "entity.json").exists()


def test_resolve_spawn_identity_legacy_from_directory_artifact(tmp_path):
    ckpt = tmp_path / "phantasia" / "world_model.ckpt"
    ckpt.mkdir(parents=True)
    (ckpt / "a.bin").write_bytes(b"alpha")
    (ckpt / "b.bin").write_bytes(b"beta")

    identity = resolve_spawn_identity(tmp_path, now=lambda: 1.0)
    assert identity.origin == "legacy"
    assert identity.legacy_source.startswith("tree:")
    assert (tmp_path / "identity" / "entity.json").exists()

    second = resolve_spawn_identity(tmp_path, now=lambda: 2.0)
    assert second == identity

    # Add a new own artifact after the identity was persisted.
    hypnos = tmp_path / "hypnos" / "consolidation_divergence.json"
    hypnos.parent.mkdir(parents=True)
    hypnos.write_text("{}")
    third = resolve_spawn_identity(tmp_path, now=lambda: 3.0)
    assert third == identity


def test_resolve_spawn_identity_existing_identity(tmp_path):
    existing = legacy_identity("bundle:existing", now=lambda: 1.0)
    path = tmp_path / "identity" / "entity.json"
    path.parent.mkdir(parents=True)
    save_identity(existing, path)

    result = resolve_spawn_identity(tmp_path, now=lambda: 2.0)
    assert result == existing


def test_history_none_counts_as_lived(tmp_path):
    assert has_prior_lived_history_in_lineage(None, tmp_path) is True


def test_history_own_sidecar(tmp_path):
    me = mint_identity(now=lambda: 1.0)
    forks_dir = tmp_path / "forks" / "snap1"
    forks_dir.mkdir(parents=True)
    write_identity_sidecar(forks_dir, me)
    assert has_prior_lived_history_in_lineage(me, tmp_path) is True


def test_history_ancestor_in_preservation_manifest(tmp_path):
    root = mint_identity(now=lambda: 1.0)
    child = fork_identity(root, now=lambda: 2.0)
    pres_dir = tmp_path / "preservation" / "bundle1"
    pres_dir.mkdir(parents=True)
    (pres_dir / "manifest.json").write_text(
        json.dumps({"identity": {"entity_id": root.entity_id}})
    )
    assert has_prior_lived_history_in_lineage(child, tmp_path) is True


def test_history_foreign_records_only(tmp_path):
    foreign = mint_identity(now=lambda: 1.0)

    forks_dir = tmp_path / "forks" / "snap1"
    forks_dir.mkdir(parents=True)
    write_identity_sidecar(forks_dir, foreign)

    pres_dir = tmp_path / "preservation" / "bundle1"
    pres_dir.mkdir(parents=True)
    (pres_dir / "manifest.json").write_text(
        json.dumps({"identity": {"entity_id": foreign.entity_id}})
    )

    me = mint_identity(now=lambda: 2.0)
    assert has_prior_lived_history_in_lineage(me, tmp_path) is False


def test_history_record_without_identity_counts_as_lived(tmp_path):
    """An unidentified bundle is ambiguous, and every ambiguity resolves to lived."""
    me = mint_identity(now=lambda: 1.0)
    pres_dir = tmp_path / "preservation" / "bundle1"
    pres_dir.mkdir(parents=True)
    (pres_dir / "manifest.json").write_text(json.dumps({"other": "data"}))
    assert has_prior_lived_history_in_lineage(me, tmp_path) is True


def test_history_corrupt_sidecar_counts_as_lived_without_raising(tmp_path, caplog):
    me = mint_identity(now=lambda: 1.0)
    forks_dir = tmp_path / "forks" / "snap1"
    forks_dir.mkdir(parents=True)
    (forks_dir / SIDECAR_NAME).write_text("not json")

    with caplog.at_level(logging.WARNING):
        assert has_prior_lived_history_in_lineage(me, tmp_path) is True
    assert "identity" in caplog.text.lower() or "unreadable" in caplog.text.lower()


def test_tree_digest_unreadable_artifact_stops_derivation(tmp_path):
    stage = tmp_path / "lifecycle" / "stage.json"
    stage.parent.mkdir(parents=True)
    stage.write_text("{}")
    stage.chmod(0o000)
    try:
        if os.access(stage, os.R_OK):
            pytest.skip("running with privileges that ignore file modes")
        with pytest.raises(IdentityError):
            resolve_spawn_identity(tmp_path, now=lambda: 1.0)
        assert not (tmp_path / "identity" / "entity.json").exists()
    finally:
        stage.chmod(0o600)


def test_history_descendant_fork_counts(tmp_path):
    me = mint_identity()
    child = fork_identity(me)
    fork_dir = tmp_path / "forks" / "c"
    fork_dir.mkdir(parents=True)
    write_identity_sidecar(fork_dir, child)
    assert has_prior_lived_history_in_lineage(me, tmp_path) is True
    bundle = tmp_path / "preservation" / "b"
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_text(
        json.dumps({"identity": {"entity_id": fork_identity(child).entity_id, "lineage": [me.entity_id, child.entity_id]}})
    )
    assert has_prior_lived_history_in_lineage(mint_identity(), tmp_path) is False
