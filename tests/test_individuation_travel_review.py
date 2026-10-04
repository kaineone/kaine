# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from pathlib import Path

import pytest

from kaine.cycle.individuation_runtime import IndividuationConfig
from kaine.cycle.revive_boot import ReviveRefused, ReviveSession, prepare_revive
from kaine.lifecycle.decommission import capture_backup
from kaine.lifecycle.divergence import DivergenceAssessment
from kaine.lifecycle.individuation_store import IndividuationPaths, Ledger, save_ledger
from kaine.lifecycle.preservation import (
    PreservationError,
    bundle_dir_for,
    preserve_live,
)
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor
from tests.test_individuation_travels import _make_eidolon_registry


@pytest.fixture
def real_encryptor(monkeypatch):
    # The same key setup as tests/test_individuation_travels.py.
    monkeypatch.setenv("KAINE_STATE_KEY", "0" * 32)
    enc = StateEncryptor(CryptoConfig(enabled=True, key_env_var="KAINE_STATE_KEY"))
    set_state_encryptor(enc)
    try:
        yield enc
    finally:
        set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


def test_config_refuses_state_dir():
    with pytest.raises(ValueError, match="unknown \\[individuation\\] keys: state_dir"):
        IndividuationConfig.from_dict({"state_dir": "x"})


def test_shipped_config_has_no_state_dir():
    import tomllib

    root = Path(__file__).resolve().parents[1]
    text = (root / "config" / "kaine.toml").read_text(encoding="utf-8")
    cfg = tomllib.loads(text)
    assert "state_dir" not in cfg.get("individuation", {})


@pytest.mark.asyncio
async def test_failed_extraction_leaves_evidence(real_encryptor, monkeypatch, tmp_path):
    reg = await _make_eidolon_registry(tmp_path)

    result = await preserve_live(
        reg,
        fork_root=tmp_path / "forks",
        out_root=tmp_path / "out",
        entity_name="t",
        reason="test",
        individuation_root=tmp_path / "missing",
        require_encryption=True,
    )
    assert result.ok
    bundle = bundle_dir_for(tmp_path / "out", result.preservation_id, "t")

    target = tmp_path / "state_ind"
    target.mkdir(parents=True)
    (target / "ledger.json").write_text("old ledger")
    (target / "marker.txt").write_text("keep me")

    from kaine.lifecycle import preservation

    original_extract = preservation.extract_bundle_individuation

    def _boom(bundle, dest):
        raise preservation.ReviveError("boom")

    monkeypatch.setattr(preservation, "extract_bundle_individuation", _boom)

    plan = prepare_revive(bundle)
    session = ReviveSession(plan, individuation_root=target)

    with pytest.raises(ReviveRefused, match="boom"):
        await session.revive(reg)

    assert target.exists()
    assert (target / "marker.txt").read_text() == "keep me"
    assert not list(tmp_path.glob("state_ind.replaced-*"))
    assert not (tmp_path / "state_ind.revived").exists()

    monkeypatch.setattr(preservation, "extract_bundle_individuation", original_extract)


@pytest.mark.asyncio
async def test_failed_swap_rolls_back(real_encryptor, monkeypatch, tmp_path):
    reg = await _make_eidolon_registry(tmp_path)

    ind_root = tmp_path / "ind"
    save_ledger(
        IndividuationPaths(root=ind_root),
        Ledger(reference_id="revive-ref", individuated=True),
    )
    (ind_root / "marker.txt").write_text("new evidence")

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
    (target / "ledger.json").write_text("old ledger")
    (target / "marker.txt").write_text("keep me")

    real_replace = __import__("os").replace

    def _failing_replace(src, dst):
        if str(src).endswith(".revived"):
            raise OSError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr("kaine.cycle.revive_boot.os.replace", _failing_replace)

    plan = prepare_revive(bundle)
    session = ReviveSession(plan, individuation_root=target)

    with pytest.raises(ReviveRefused, match="disk full"):
        await session.revive(reg)

    assert target.exists()
    assert (target / "marker.txt").read_text() == "keep me"
    assert not list(tmp_path.glob("state_ind.replaced-*"))


@pytest.mark.asyncio
async def test_bundle_without_evidence_moves_aside(real_encryptor, tmp_path):
    reg = await _make_eidolon_registry(tmp_path)

    result = await preserve_live(
        reg,
        fork_root=tmp_path / "forks",
        out_root=tmp_path / "out",
        entity_name="t",
        reason="test",
        individuation_root=tmp_path / "missing",
        require_encryption=True,
    )
    assert result.ok
    bundle = bundle_dir_for(tmp_path / "out", result.preservation_id, "t")

    target = tmp_path / "state_ind"
    target.mkdir(parents=True)
    (target / "ledger.json").write_text("old ledger")
    (target / "marker.txt").write_text("keep me")

    plan = prepare_revive(bundle)
    session = ReviveSession(plan, individuation_root=target)

    await session.revive(reg)

    assert not target.exists()
    replaced = list(tmp_path.glob("state_ind.replaced-*"))
    assert len(replaced) == 1
    assert (replaced[0] / "marker.txt").read_text() == "keep me"


@pytest.mark.asyncio
async def test_decommission_failed_evidence_copy(real_encryptor, monkeypatch, tmp_path):
    state_root = tmp_path / "state"
    ind_root = state_root / "individuation"
    ind_root.mkdir(parents=True)
    save_ledger(
        IndividuationPaths(root=ind_root),
        Ledger(reference_id="decom-ref", individuated=True),
    )

    real_copytree = __import__("shutil").copytree

    def _fake_copytree(src, dst, **kwargs):
        if "individuation" in str(src) or "individuation" in str(dst):
            raise OSError("simulated individuation copy failure")
        return real_copytree(src, dst, **kwargs)

    monkeypatch.setattr("shutil.copytree", _fake_copytree)

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
    assert not result.ok
    assert any("individuation" in e for e in result.errors)


@pytest.mark.asyncio
async def test_preservation_plaintext_not_removed(real_encryptor, monkeypatch, tmp_path):
    reg = await _make_eidolon_registry(tmp_path)

    ind_root = tmp_path / "ind"
    ind_root.mkdir(parents=True)
    save_ledger(
        IndividuationPaths(root=ind_root),
        Ledger(reference_id="birth-ref", individuated=True),
    )

    real_rmtree = __import__("shutil").rmtree

    def _fake_rmtree(path, ignore_errors=False):
        if "individuation" in str(path):
            return None
        return real_rmtree(path, ignore_errors=ignore_errors)

    monkeypatch.setattr("shutil.rmtree", _fake_rmtree)

    with pytest.raises(PreservationError, match="could not remove plaintext"):
        await preserve_live(
            reg,
            fork_root=tmp_path / "forks",
            out_root=tmp_path / "out",
            entity_name="t",
            reason="test",
            individuation_root=ind_root,
            require_encryption=True,
        )
