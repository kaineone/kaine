# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The launch name lives in the entity identity (openspec launch-name-at-first-boot)."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pytest

from kaine.cycle.__main__ import (
    _apply_revive,
    _persist_revived_identity,
    _resolve_boot_identity,
)
from kaine.cycle.revive_boot import RevivePlan, prepare_revive
from kaine.experiment.run_context import RunContext, set_run_context
from kaine.lifecycle.identity import (
    EntityIdentity,
    IdentityError,
    check_sidecar_agrees,
    fork_identity,
    load_identity,
    mint_identity,
    read_identity_sidecar,
    resolve_spawn_identity,
    save_identity,
    write_identity_sidecar,
)
from kaine.lifecycle.manager import ForkManager
from kaine.lifecycle.preservation import preserve_live
from kaine.lifecycle.snapshot import ForkSnapshot, snapshot_dir
from kaine.modules.self_model import document as sm_document
from kaine.modules.self_model.document import SelfModelDocument, load, save_atomic
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor


@pytest.fixture(autouse=True)
def _plaintext_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


@pytest.fixture(autouse=True)
def _run_context():
    set_run_context(
        RunContext(
            run_id="testrun0123456789",
            seed=7,
            started_at=datetime.now(timezone.utc).isoformat(),
            git_sha=None,
        )
    )
    yield
    set_run_context(None)


def _surname_of(name: str) -> str:
    first, _, surname = name.partition(" ")
    assert first == "Kaine"
    return surname


def _write_doc(path: Path, name: str) -> None:
    save_atomic(path, SelfModelDocument(name=name))


_FIVE = {
    "entity_id": "ent-" + "a" * 32,
    "lineage": [],
    "origin": "minted",
    "minted_at": 12.5,
    "legacy_source": None,
}


# ---- format -------------------------------------------------------------


def test_unnamed_identity_file_bytes_match_the_pre_name_format(tmp_path):
    identity = EntityIdentity(entity_id="ent-" + "a" * 32, minted_at=12.5)
    path = tmp_path / "identity" / "entity.json"
    save_identity(identity, path)
    expected = (
        "{\n"
        '  "entity_id": "ent-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",\n'
        '  "legacy_source": null,\n'
        '  "lineage": [],\n'
        '  "minted_at": 12.5,\n'
        '  "origin": "minted"\n'
        "}"
    )
    assert path.read_bytes() == expected.encode("utf-8")
    assert "name" not in identity.to_dict()


def test_named_identity_round_trip(tmp_path):
    identity = EntityIdentity(entity_id="ent-" + "b" * 32, minted_at=1.0, name="Kaine Nova")
    path = tmp_path / "entity.json"
    save_identity(identity, path)
    assert json.loads(path.read_text())["name"] == "Kaine Nova"
    assert load_identity(path) == identity


def test_from_dict_with_and_without_name():
    assert EntityIdentity.from_dict(dict(_FIVE)).name is None
    assert EntityIdentity.from_dict({**_FIVE, "name": "Kaine Nova"}).name == "Kaine Nova"


def test_from_dict_rejects_other_extra_keys():
    with pytest.raises(IdentityError):
        EntityIdentity.from_dict({**_FIVE, "nickname": "x"})
    with pytest.raises(IdentityError):
        EntityIdentity.from_dict({**_FIVE, "name": "Kaine Nova", "nickname": "x"})


@pytest.mark.parametrize("bad", ["", "   ", "Kaine\nNova", "Kaine\tNova", 5, None])
def test_from_dict_rejects_bad_names(bad):
    with pytest.raises(IdentityError):
        EntityIdentity.from_dict({**_FIVE, "name": bad})


@pytest.mark.parametrize("bad", ["", "  ", "a\nb"])
def test_constructor_rejects_bad_names(bad):
    with pytest.raises(IdentityError):
        EntityIdentity(entity_id="ent-" + "a" * 32, name=bad)


def test_save_refuses_a_different_name_and_leaves_the_file(tmp_path):
    base = EntityIdentity(entity_id="ent-" + "c" * 32, minted_at=1.0)
    path = tmp_path / "entity.json"
    save_identity(EntityIdentity(**{**base.__dict__, "name": "Kaine Nova"}), path)
    before = path.read_bytes()
    with pytest.raises(IdentityError):
        save_identity(EntityIdentity(**{**base.__dict__, "name": "Kaine Aurora"}), path)
    assert path.read_bytes() == before
    with pytest.raises(IdentityError):
        save_identity(base, path)  # dropping the name is also a replacement
    assert path.read_bytes() == before
    save_identity(EntityIdentity(**{**base.__dict__, "name": "Kaine Nova"}), path)  # same name: fine


def test_save_allows_adding_a_name_to_an_unnamed_file(tmp_path):
    base = EntityIdentity(entity_id="ent-" + "d" * 32, minted_at=1.0)
    path = tmp_path / "entity.json"
    save_identity(base, path)
    save_identity(EntityIdentity(**{**base.__dict__, "name": "Kaine Nova"}), path)
    assert load_identity(path).name == "Kaine Nova"


# ---- boot ---------------------------------------------------------------


def test_fresh_spawn_mints_a_name_and_keeps_it(tmp_path):
    state_root = tmp_path / "state"
    first = _resolve_boot_identity(state_root, None)
    assert first.name is not None
    assert first.name == f"Kaine {_surname_of(first.name)}"
    assert _surname_of(first.name) in sm_document._SURNAMES
    assert json.loads((state_root / "identity" / "entity.json").read_text())["name"] == first.name
    second = _resolve_boot_identity(state_root, None)
    assert second == first


def test_unnamed_identity_adopts_the_self_model_documents_name(tmp_path):
    state_root = tmp_path / "state"
    unnamed = mint_identity()
    save_identity(unnamed, state_root / "identity" / "entity.json")
    _write_doc(state_root / "self_model" / "self_model.json", "Kaine Nova")
    resolved = resolve_spawn_identity(state_root)
    assert resolved.name == "Kaine Nova"
    assert resolved.entity_id == unnamed.entity_id
    assert load_identity(state_root / "identity" / "entity.json").name == "Kaine Nova"


def test_adoption_honours_a_configured_document_path(tmp_path):
    state_root = tmp_path / "state"
    save_identity(mint_identity(), state_root / "identity" / "entity.json")
    custom = tmp_path / "elsewhere" / "doc.json"
    _write_doc(custom, "Kaine Aurora")
    assert _resolve_boot_identity(state_root, None, self_model_path=custom).name == "Kaine Aurora"


def test_unnamed_identity_without_a_document_mints(tmp_path):
    state_root = tmp_path / "state"
    save_identity(mint_identity(), state_root / "identity" / "entity.json")
    resolved = resolve_spawn_identity(state_root)
    assert resolved.name is not None
    assert _surname_of(resolved.name) in sm_document._SURNAMES


def test_unnamed_identity_with_a_nameless_document_mints(tmp_path):
    state_root = tmp_path / "state"
    save_identity(mint_identity(), state_root / "identity" / "entity.json")
    save_atomic(state_root / "self_model" / "self_model.json", SelfModelDocument())
    assert resolve_spawn_identity(state_root).name is not None


def test_an_existing_name_is_never_overwritten_by_the_document(tmp_path):
    state_root = tmp_path / "state"
    named = EntityIdentity(entity_id="ent-" + "e" * 32, minted_at=1.0, name="Kaine Nova")
    save_identity(named, state_root / "identity" / "entity.json")
    _write_doc(state_root / "self_model" / "self_model.json", "Kaine Aurora")
    assert resolve_spawn_identity(state_root).name == "Kaine Nova"


@dataclass
class _Rev:
    plan: RevivePlan


def test_revive_keeps_the_bundles_name(tmp_path):
    named = EntityIdentity(entity_id="ent-" + "f" * 32, minted_at=1.0, name="Kaine Nova")
    revive = _Rev(RevivePlan(bundle=tmp_path / "b", preservation_id=None, stage=None, identity=named))
    state_root = tmp_path / "state"
    assert _resolve_boot_identity(state_root, revive).name == "Kaine Nova"
    assert load_identity(state_root / "identity" / "entity.json") is None
    _persist_revived_identity(state_root, named)
    assert load_identity(state_root / "identity" / "entity.json").name == "Kaine Nova"


def test_revived_unnamed_identity_takes_the_revived_self_model_name(tmp_path):
    state_root = tmp_path / "state"
    unnamed = mint_identity()
    saved = _persist_revived_identity(state_root, unnamed, self_model_name="Kaine Nova")
    assert saved.name == "Kaine Nova"
    assert load_identity(state_root / "identity" / "entity.json").name == "Kaine Nova"


def _tree_identity(state_root, base, name):
    ident = EntityIdentity(entity_id=base.entity_id, minted_at=base.minted_at, name=name)
    save_identity(ident, state_root / "identity" / "entity.json")


def test_revive_bundle_name_beats_a_different_same_id_tree_name(tmp_path, caplog):
    state_root = tmp_path / "state"
    base = mint_identity()
    _tree_identity(state_root, base, "Kaine Aurora")
    bundle = EntityIdentity(entity_id=base.entity_id, minted_at=1.0, name="Kaine Nova")
    with caplog.at_level("WARNING"):
        saved = _persist_revived_identity(state_root, bundle, self_model_name="Kaine Zed")
    assert saved.name == "Kaine Nova"
    assert load_identity(state_root / "identity" / "entity.json").name == "Kaine Nova"
    assert "Kaine Aurora" in caplog.text and "Kaine Nova" in caplog.text


def test_revive_nameless_bundle_self_model_name_beats_tree_name(tmp_path):
    state_root = tmp_path / "state"
    base = mint_identity()
    _tree_identity(state_root, base, "Kaine Aurora")
    saved = _persist_revived_identity(
        state_root, EntityIdentity(entity_id=base.entity_id), self_model_name="Kaine Nova"
    )
    assert saved.name == "Kaine Nova"
    assert load_identity(state_root / "identity" / "entity.json").name == "Kaine Nova"


def test_revive_nameless_bundle_keeps_same_id_tree_name(tmp_path):
    state_root = tmp_path / "state"
    base = mint_identity()
    _tree_identity(state_root, base, "Kaine Aurora")
    saved = _persist_revived_identity(state_root, EntityIdentity(entity_id=base.entity_id))
    assert saved.name == "Kaine Aurora"


def test_revive_with_nothing_named_mints(tmp_path):
    state_root = tmp_path / "state"
    saved = _persist_revived_identity(state_root, mint_identity())
    assert saved.name is not None
    assert _surname_of(saved.name) in sm_document._SURNAMES


def test_revive_into_a_different_id_tree_is_refused_and_name_not_adopted(tmp_path):
    state_root = tmp_path / "state"
    _tree_identity(state_root, mint_identity(), "Kaine Aurora")
    before = (state_root / "identity" / "entity.json").read_bytes()
    with pytest.raises(IdentityError):
        _persist_revived_identity(state_root, mint_identity())
    assert (state_root / "identity" / "entity.json").read_bytes() == before


def test_save_identity_without_the_keyword_still_refuses_a_rename(tmp_path):
    path = tmp_path / "entity.json"
    base = mint_identity()
    save_identity(EntityIdentity(entity_id=base.entity_id, name="Kaine Nova"), path)
    with pytest.raises(IdentityError):
        save_identity(EntityIdentity(entity_id=base.entity_id, name="Kaine Aurora"), path)
    save_identity(
        EntityIdentity(entity_id=base.entity_id, name="Kaine Aurora"), path, replace_name=True
    )
    assert load_identity(path).name == "Kaine Aurora"


@pytest.mark.asyncio
async def test_apply_revive_has_the_running_self_model_adopt_the_final_name(bus, tmp_path):
    from kaine.modules.registry import ModuleRegistry
    from kaine.modules.self_model import SelfModel

    state_root = tmp_path / "state"
    path = tmp_path / "sm.json"
    module = SelfModel(bus, persistence_path=path)  # no identity name: mints its own
    await module.initialize()
    registry = ModuleRegistry()
    registry.register(module)
    unnamed = mint_identity()

    class _Landing:
        plan = RevivePlan(bundle=tmp_path / "b", preservation_id=None, stage=None, identity=unnamed)

        async def revive(self, reg):
            # the revived state carries a name of its own
            module.deserialize({"model": SelfModelDocument(name="Kaine Nova").to_json()})

    try:
        assert await _apply_revive(_Landing(), registry, state_root) is None
        assert load_identity(state_root / "identity" / "entity.json").name == "Kaine Nova"
        assert module.entity_name == "Kaine Nova"
        assert registry.identity_name == "Kaine Nova"
        assert load(path).name == "Kaine Nova"
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_apply_revive_with_no_name_anywhere_mints_and_module_adopts(bus, tmp_path):
    from kaine.modules.registry import ModuleRegistry
    from kaine.modules.self_model import SelfModel

    state_root = tmp_path / "state"
    path = tmp_path / "sm.json"
    module = SelfModel(bus, persistence_path=path)
    await module.initialize()
    registry = ModuleRegistry()
    registry.register(module)
    unnamed = mint_identity()

    class _Landing:
        plan = RevivePlan(bundle=tmp_path / "b", preservation_id=None, stage=None, identity=unnamed)

        async def revive(self, reg):
            module.deserialize({"model": SelfModelDocument().to_json()})

    try:
        assert await _apply_revive(_Landing(), registry, state_root) is None
        name = load_identity(state_root / "identity" / "entity.json").name
        assert name is not None
        assert module.entity_name == name and load(path).name == name
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_apply_revive_names_an_unnamed_bundle_identity(tmp_path):
    state_root = tmp_path / "state"
    unnamed = mint_identity()

    class _Landing:
        plan = RevivePlan(bundle=tmp_path / "b", preservation_id=None, stage=None, identity=unnamed)

        async def revive(self, registry):
            return None

    class _Reg:
        def all_modules(self):
            return []

    assert await _apply_revive(_Landing(), _Reg(), state_root) is None
    assert load_identity(state_root / "identity" / "entity.json").name is not None


# ---- fork ---------------------------------------------------------------


def test_fork_gets_a_different_name_and_keeps_lineage(monkeypatch):
    monkeypatch.setattr(sm_document, "_SURNAMES", ("Nova", "Aurora"))
    parent = EntityIdentity(entity_id="ent-" + "1" * 32, minted_at=1.0, name="Kaine Nova")
    for seed in range(20):
        child = fork_identity(parent, rng=random.Random(seed))
        assert child.name == "Kaine Aurora"
        assert child.lineage == (parent.entity_id,)
        assert child.entity_id != parent.entity_id


def test_fork_of_an_unnamed_parent_is_named():
    parent = mint_identity()
    child = fork_identity(parent)
    assert child.name is not None and parent.name is None


def test_generate_launch_name_exclude(monkeypatch):
    monkeypatch.setattr(sm_document, "_SURNAMES", ("Nova", "Aurora"))
    for seed in range(20):
        assert (
            sm_document.generate_launch_name(rng=random.Random(seed), exclude="Kaine Aurora")
            == "Kaine Nova"
        )


@dataclass
class _Mod:
    name: str = "testmod"

    def serialize(self) -> dict[str, Any]:
        return {"v": 1}

    def deserialize(self, state: dict[str, Any]) -> None:
        pass


class _Registry:
    def all_modules(self) -> Iterable[_Mod]:
        return [_Mod()]


def test_forkmanager_fork_names_the_child_and_not_from_the_parent(tmp_path):
    parent_identity = EntityIdentity(entity_id="ent-" + "2" * 32, minted_at=1.0, name="Kaine Nova")
    fm = ForkManager(tmp_path / "forks", identity_source=lambda: parent_identity)
    parent = fm.snapshot(_Registry())
    child = fm.fork(parent.id)
    child_identity = EntityIdentity.from_dict(child.metadata["identity"])
    assert child_identity.name not in (None, "Kaine Nova")
    assert child_identity.lineage == (parent_identity.entity_id,)
    # The plaintext sidecar keeps entity_id and lineage only.
    sidecar = json.loads((snapshot_dir(fm.root, child.id) / "identity.json").read_text())
    assert set(sidecar) == {"entity_id", "lineage"}


# ---- self-model module --------------------------------------------------


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig

    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


@pytest.mark.asyncio
async def test_self_model_adopts_identity_name_over_a_copied_document(bus, tmp_path):
    from kaine.modules.self_model import SelfModel

    path = tmp_path / "self_model.json"
    _write_doc(path, "Kaine Nova")  # the parent's name, copied into the fork
    module = SelfModel(bus, persistence_path=path, identity_name="Kaine Aurora")
    await module.initialize()
    try:
        assert module.model.name == "Kaine Aurora"
        assert load(path).name == "Kaine Aurora"
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_self_model_adopts_identity_name_for_an_empty_document(bus, tmp_path):
    from kaine.modules.self_model import SelfModel

    path = tmp_path / "self_model.json"
    module = SelfModel(bus, persistence_path=path, identity_name="Kaine Aurora")
    await module.initialize()
    try:
        assert load(path).name == "Kaine Aurora"
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_self_model_without_identity_name_still_mints(bus, tmp_path):
    from kaine.modules.self_model import SelfModel

    path = tmp_path / "self_model.json"
    module = SelfModel(bus, persistence_path=path)
    await module.initialize()
    try:
        assert module.model.name.startswith("Kaine ")
        assert load(path).name == module.model.name
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_self_model_restored_state_takes_the_identity_name(bus, tmp_path):
    from kaine.modules.self_model import SelfModel

    parent_state = SelfModel(bus, persistence_path=tmp_path / "p.json")
    parent_state._model = SelfModelDocument(name="Kaine Nova")
    state = parent_state.serialize()
    child = SelfModel(bus, persistence_path=tmp_path / "c.json", identity_name="Kaine Aurora")
    child.deserialize(state)
    assert child.model.name == "Kaine Aurora"


@pytest.mark.asyncio
async def test_factory_passes_the_identity_name(bus, tmp_path):
    from kaine.boot.factories.self_model import make_self_model

    module = make_self_model(
        bus, {"persistence_path": str(tmp_path / "sm.json"), "_identity_name": "Kaine Nova"}
    )
    await module.initialize()
    try:
        assert module.model.name == "Kaine Nova"
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_construct_module_reads_the_registry_identity_name(bus, tmp_path):
    from kaine.boot.registry import construct_module
    from kaine.modules.registry import ModuleRegistry

    registry = ModuleRegistry()
    registry.identity_name = "Kaine Nova"
    module = construct_module(
        "self_model", bus, {"self_model": {"persistence_path": str(tmp_path / "sm.json")}},
        registry=registry,
    )
    await module.initialize()
    try:
        assert module.model.name == "Kaine Nova"
    finally:
        await module.shutdown()


# ---- preservation and agreement ----------------------------------------


@pytest.mark.asyncio
async def test_preservation_bundle_carries_the_name_and_manifest_does_not(tmp_path):
    identity = EntityIdentity(entity_id="ent-" + "3" * 32, minted_at=1.0, name="Kaine Nova")
    fork_root = tmp_path / "forks"
    out_root = tmp_path / "backups"
    result = await preserve_live(
        _Registry(),
        fork_root=fork_root,
        out_root=out_root,
        entity_name="testentity",
        reason="test",
        identity=identity,
    )
    bundle = next(p for p in out_root.iterdir() if (p / "manifest.json").is_file())
    manifest = json.loads((bundle / "manifest.json").read_text())
    assert manifest["identity"] == {"entity_id": identity.entity_id, "lineage": []}
    snap = ForkSnapshot.from_dict(
        json.loads((fork_root / result.snapshot_id / "snapshot.json").read_text())
    )
    assert snap.metadata["identity"]["name"] == "Kaine Nova"
    assert prepare_revive(bundle).identity == identity


def test_named_identity_agrees_with_an_unnamed_plaintext_record(tmp_path):
    identity = EntityIdentity(
        entity_id="ent-" + "4" * 32, lineage=("ent-" + "5" * 32,), minted_at=1.0, name="Kaine Nova"
    )
    write_identity_sidecar(tmp_path, identity)
    assert set(json.loads((tmp_path / "identity.json").read_text())) == {"entity_id", "lineage"}
    check_sidecar_agrees(read_identity_sidecar(tmp_path), identity)


def test_decommission_backup_carries_the_identity_file_with_its_name(tmp_path):
    from kaine.lifecycle.decommission import capture_backup
    from kaine.lifecycle.divergence import DivergenceAssessment

    state_root = tmp_path / "state"
    identity = EntityIdentity(entity_id="ent-" + "6" * 32, minted_at=1.0, name="Kaine Nova")
    save_identity(identity, state_root / "identity" / "entity.json")
    result = capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        qdrant_cfg={
            "episodic_memory": {"backend": "inmemory"},
            "social_cognition": {"backend": "inmemory"},
        },
        out_root=tmp_path / "backups",
        entity_name="test",
        assessment=DivergenceAssessment(diverged=False, signals={}, summary="test"),
    )
    assert result.ok
    manifest = json.loads((result.backup_path / "manifest.json").read_text())
    assert manifest["identity"] == {"entity_id": identity.entity_id, "lineage": []}
    copies = [
        p for p in result.backup_path.rglob("entity.json") if "identity" in p.parts
    ]
    assert copies, list(result.backup_path.rglob("*"))
    assert json.loads(copies[0].read_text())["name"] == "Kaine Nova"
