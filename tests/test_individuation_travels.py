# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from kaine.cycle import research_gate
from kaine.cycle.revive_boot import ReviveSession, prepare_revive
from kaine.lifecycle.decommission import capture_backup, delete_entity_state
from kaine.lifecycle.divergence import DivergenceAssessment
from kaine.lifecycle.individuation_store import (
    IndividuationPaths,
    Ledger,
    load_ledger,
    save_ledger,
)
from kaine.lifecycle.preservation import (
    PreservationError,
    ReviveError,
    bundle_dir_for,
    extract_bundle_individuation,
    preserve_live,
)
from kaine.modules.eidolon import Eidolon, SelfModel
from kaine.modules.registry import ModuleRegistry
from kaine.security.crypto import (
    CryptoConfig,
    StateEncryptor,
    set_state_encryptor,
)


class _FakeBus:
    async def publish(self, *args, **kwargs):
        return "0-0"

    async def read_entries(self, *args, **kwargs):
        return [], None

    async def read(self, *args, **kwargs):
        return []

    def subscribe_workspace(self, *args, **kwargs):
        async def _empty():
            return
            yield  # type: ignore[unreachable]

        return _empty()

    async def current_workspace_id(self) -> str:
        return "0-0"


@pytest.fixture
def real_encryptor(monkeypatch):
    # The same key setup as tests/test_decommission_backup.py.
    monkeypatch.setenv("KAINE_STATE_KEY", "0" * 32)
    enc = StateEncryptor(CryptoConfig(enabled=True, key_env_var="KAINE_STATE_KEY"))
    set_state_encryptor(enc)
    try:
        yield enc
    finally:
        set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


async def _make_eidolon_registry(tmp_path: Path):
    bus = _FakeBus()
    reg = ModuleRegistry()
    eid = Eidolon(
        bus, persistence_path=tmp_path / "sm.json", save_interval_s=60
    )
    await eid.initialize()
    eid._model = SelfModel(name="probe", values=["continuity"])
    reg.register(eid)
    return reg


@pytest.mark.asyncio
async def test_bundle_and_revive(real_encryptor, tmp_path):
    reg = await _make_eidolon_registry(tmp_path)

    ind_root = tmp_path / "ind"
    ipaths = IndividuationPaths(root=ind_root)
    save_ledger(ipaths, Ledger(reference_id="birth-ref", individuated=True))
    (ind_root / "reports").mkdir(parents=True)
    (ind_root / "reports" / "x.jsonl").write_bytes(b'{"entry":1}\n')

    result = await preserve_live(
        reg,
        fork_root=tmp_path / "forks",
        out_root=tmp_path / "out",
        entity_name="t",
        reason="test",
        individuation_root=ind_root,
        require_encryption=True,
    )
    assert result.ok
    bundle = bundle_dir_for(tmp_path / "out", result.preservation_id, "t")
    assert (bundle / "bundle.tar.enc").is_file()
    assert not (bundle / "individuation").exists()

    extracted = extract_bundle_individuation(bundle, tmp_path / "restored")
    assert extracted is True

    restored_paths = IndividuationPaths(root=tmp_path / "restored")
    ledger = load_ledger(restored_paths)
    assert ledger.individuated is True
    assert ledger.reference_id == "birth-ref"
    assert (tmp_path / "restored" / "reports" / "x.jsonl").read_bytes() == b'{"entry":1}\n'


@pytest.mark.asyncio
async def test_bundle_without_evidence(real_encryptor, tmp_path):
    reg = await _make_eidolon_registry(tmp_path)

    result = await preserve_live(
        reg,
        fork_root=tmp_path / "forks",
        out_root=tmp_path / "out",
        entity_name="t",
        reason="test",
        individuation_root=tmp_path / "missing",
    )
    assert result.ok
    bundle = bundle_dir_for(tmp_path / "out", result.preservation_id, "t")

    assert extract_bundle_individuation(bundle, tmp_path / "restored") is False
    assert not (tmp_path / "restored").exists()


@pytest.mark.asyncio
async def test_bundle_copy_failure(real_encryptor, monkeypatch, tmp_path):
    reg = await _make_eidolon_registry(tmp_path)

    real_copytree = __import__("shutil").copytree

    def _fake_copytree(src, dst, **kwargs):
        if "individuation" in str(src) or "individuation" in str(dst):
            raise OSError("simulated individuation copy failure")
        return real_copytree(src, dst, **kwargs)

    (tmp_path / "ind").mkdir()
    (tmp_path / "ind" / "ledger.json").write_text("x", encoding="utf-8")
    monkeypatch.setattr("shutil.copytree", _fake_copytree)

    with pytest.raises(
        PreservationError, match="could not copy individuation evidence"
    ):
        await preserve_live(
            reg,
            fork_root=tmp_path / "forks",
            out_root=tmp_path / "out",
            entity_name="t",
            reason="test",
            individuation_root=tmp_path / "ind",
        )


def test_extract_path_traversal(tmp_path):
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    bundle = tmp_path / "evil_bundle"
    bundle.mkdir()
    with tarfile.open(bundle / "bundle.tar", "w") as tf:
        data = b"evil"
        info = tarfile.TarInfo(name="individuation/../evil")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))

    with pytest.raises(ReviveError):
        extract_bundle_individuation(bundle, tmp_path / "dest")

    assert not (tmp_path / "evil").exists()
    assert not (tmp_path / "dest").exists()


@pytest.mark.asyncio
async def test_revive_session_restores_individuation(real_encryptor, tmp_path):
    reg = await _make_eidolon_registry(tmp_path)

    ind_root = tmp_path / "ind"
    save_ledger(
        IndividuationPaths(root=ind_root),
        Ledger(reference_id="revive-ref", individuated=True),
    )

    result = await preserve_live(
        reg,
        fork_root=tmp_path / "forks",
        out_root=tmp_path / "out",
        entity_name="t",
        reason="test",
        individuation_root=ind_root,
        require_encryption=True,
    )
    assert result.ok
    bundle = bundle_dir_for(tmp_path / "out", result.preservation_id, "t")

    target = tmp_path / "state_ind"
    target.mkdir(parents=True)
    (target / "marker.txt").write_text("old")

    reg2 = await _make_eidolon_registry(tmp_path / "reg2")

    plan = prepare_revive(bundle)
    session = ReviveSession(
        plan,
        stage_path=tmp_path / "stage.json",
        individuation_root=target,
    )
    await session.revive(reg2)

    ledger = load_ledger(IndividuationPaths(root=target))
    assert ledger.individuated is True
    assert ledger.reference_id == "revive-ref"

    replaced = list(tmp_path.glob("state_ind.replaced-*"))
    assert len(replaced) == 1
    assert (replaced[0] / "marker.txt").read_text() == "old"
    assert not (target / "marker.txt").exists()


@pytest.mark.asyncio
async def test_decommission_backup_and_delete(real_encryptor, tmp_path):
    state_root = tmp_path / "state"
    ind_root = state_root / "individuation"
    ind_root.mkdir(parents=True)
    save_ledger(
        IndividuationPaths(root=ind_root),
        Ledger(reference_id="decom-ref", individuated=True),
    )
    edge = state_root / "preservation" / "divergence_edge.json"
    edge.parent.mkdir(parents=True)
    edge.write_text('{"edge":1}', encoding="utf-8")

    assessment = DivergenceAssessment(
        diverged=True, signals={}, summary="test backup"
    )
    result = capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        qdrant_cfg=None,
        out_root=tmp_path / "backups",
        entity_name="decom",
        assessment=assessment,
    )
    assert result.ok
    assert "individuation/" in result.inventory

    dresult = delete_entity_state(
        state_root=state_root, qdrant_cfg=None, dry_run=False
    )
    assert str(state_root / "individuation") in dresult.removed_paths
    assert str(edge) in dresult.removed_paths


def test_research_gate_requires_individuation(monkeypatch):
    monkeypatch.setattr(
        "kaine.cycle.research_gate.run_preflight_self_check",
        lambda **kwargs: (True, None),
    )

    result = research_gate.evaluate_research_gate(
        preservation_enabled=True,
        welfare_response_wired=True,
        logging_active=True,
        self_check_passed=True,
        encryption_satisfied=True,
        individuation_enabled=False,
    )
    assert not result.ok
    assert result.checks["individuation_enabled"] is False
    assert any("[individuation]" in failure for failure in result.failures)

    config = {"modules": {"lingua": True, "eidolon": True}}
    result2 = research_gate.evaluate_safety_net(config)
    assert not result2.ok
    assert result2.checks["individuation_enabled"] is False
    assert any("[individuation]" in failure for failure in result2.failures)
