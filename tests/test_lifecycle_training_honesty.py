# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the lifecycle-training-honesty audit fixes.

Covers five findings:
  H6 — adapter merge refuses / surfaces when FakeAdapterMerger runs with both
        parents having adapters.
  H8 — FakeTrainer must not be silently installed when voice_alignment is
        enabled, operator-approved, and [training] extras are missing.
  M1 — decommission backup: encryption failure → ok=False (not ok=True).
  M2 — research bundle: encryption_error set distinctly when encryption
        was enabled but failed (not just plaintext_note).
  L4 — decommission Qdrant delete: get_collections() failure → error recorded,
        deletion skipped (not assumed-present and proceeded).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# H6 — Adapter merge refuses on unmerged adapters
# ---------------------------------------------------------------------------


class _FakeModule:
    def __init__(self, name: str) -> None:
        self.name = name

    def serialize(self) -> dict[str, Any]:
        return {"v": 1}

    def deserialize(self, state: dict[str, Any]) -> None:
        pass


class _FakeRegistry:
    def __init__(self, modules: list[_FakeModule]) -> None:
        self._modules = list(modules)

    def all_modules(self):
        return iter(self._modules)


def test_h6_merge_refuses_when_both_parents_have_adapters(tmp_path):
    """ForkManager.merge() MUST raise UnmergedAdaptersError when both parents
    have adapters and only FakeAdapterMerger is available."""
    from kaine.lifecycle.manager import ForkManager, UnmergedAdaptersError

    mgr = ForkManager(tmp_path)
    reg = _FakeRegistry([_FakeModule("soma")])
    a = mgr.snapshot(reg, adapters=["state/hypnos/adapters/a"])
    b = mgr.snapshot(reg, adapters=["state/hypnos/adapters/b"])

    with pytest.raises(UnmergedAdaptersError) as exc_info:
        mgr.merge(a.id, b.id)

    # Error message must name both parents and the reason.
    msg = str(exc_info.value)
    assert a.id in msg
    assert b.id in msg
    assert "no merger configured" in msg or "adapter_merge_skipped" in msg or "ties_dare" in msg


def test_h6_merge_proceeds_with_allow_flag(tmp_path):
    """allow_unmerged_adapters=True bypasses the refusal and records the skip."""
    from kaine.lifecycle.manager import ForkManager

    mgr = ForkManager(tmp_path)
    reg = _FakeRegistry([_FakeModule("soma")])
    a = mgr.snapshot(reg, adapters=["state/hypnos/adapters/a"])
    b = mgr.snapshot(reg, adapters=["state/hypnos/adapters/b"])

    merged = mgr.merge(a.id, b.id, allow_unmerged_adapters=True)
    assert "state/hypnos/adapters/a" in merged.adapters
    assert "state/hypnos/adapters/b" in merged.adapters
    # Metadata records the skip so the operator-visible record is preserved.
    assert merged.metadata.get("adapter_merge_skipped") == "no merger configured"


def test_h6_merge_no_refusal_when_only_one_parent_has_adapters(tmp_path):
    """When only one parent has adapters (trivial case), no error is raised."""
    from kaine.lifecycle.manager import ForkManager

    mgr = ForkManager(tmp_path)
    reg = _FakeRegistry([_FakeModule("soma")])
    a = mgr.snapshot(reg, adapters=["state/hypnos/adapters/a"])
    b = mgr.snapshot(reg, adapters=[])

    merged = mgr.merge(a.id, b.id)
    assert "state/hypnos/adapters/a" in merged.adapters


def test_h6_merge_no_refusal_when_neither_parent_has_adapters(tmp_path):
    """No adapters on either side → no error raised (trivial case)."""
    from kaine.lifecycle.manager import ForkManager

    mgr = ForkManager(tmp_path)
    reg = _FakeRegistry([_FakeModule("soma")])
    a = mgr.snapshot(reg, adapters=[])
    b = mgr.snapshot(reg, adapters=[])

    merged = mgr.merge(a.id, b.id)
    assert merged.adapters == []


# ---------------------------------------------------------------------------
# H8 — FakeTrainer must not be silently installed when enabled + approved +
#       extras missing
# ---------------------------------------------------------------------------


def _make_voice_config(tmp_path: Path, enabled: bool = True):
    from kaine.modules.hypnos.voice_alignment import VoiceAlignmentConfig

    return VoiceAlignmentConfig(
        enabled=enabled,
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
    )


def test_h8_raises_when_enabled_approved_extras_missing(tmp_path, monkeypatch):
    """_resolve_trainer must raise VoiceAlignmentConfigError — not silently
    return None / install FakeTrainer — when voice_alignment is enabled,
    operator-approved, and [training] extras are missing."""
    import sys
    import importlib
    from kaine.boot import VoiceAlignmentConfigError, _resolve_trainer

    monkeypatch.setenv("KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED", "1")

    voice_cfg = _make_voice_config(tmp_path, enabled=True)

    # Simulate missing extras by temporarily hiding 'unsloth' from sys.modules
    # and making the import attempt raise ImportError.
    orig_unsloth = sys.modules.get("unsloth", None)
    sys.modules["unsloth"] = None  # type: ignore[assignment]
    try:
        with pytest.raises(VoiceAlignmentConfigError) as exc_info:
            _resolve_trainer(voice_cfg)
    finally:
        if orig_unsloth is None:
            sys.modules.pop("unsloth", None)
        else:
            sys.modules["unsloth"] = orig_unsloth

    msg = str(exc_info.value)
    assert "training" in msg.lower() or "unsloth" in msg.lower() or "extras" in msg.lower()
    assert "kaine[training]" in msg or "pip install" in msg or "disable" in msg


def test_h8_returns_none_when_disabled(tmp_path, monkeypatch):
    """When voice_alignment is disabled, _resolve_trainer returns None honestly."""
    from kaine.boot import _resolve_trainer

    monkeypatch.setenv("KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED", "1")

    voice_cfg = _make_voice_config(tmp_path, enabled=False)
    result = _resolve_trainer(voice_cfg)
    assert result is None


def test_h8_returns_none_when_not_approved(tmp_path, monkeypatch):
    """When operator approval env var is absent, _resolve_trainer returns None."""
    from kaine.boot import _resolve_trainer

    monkeypatch.delenv("KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED", raising=False)

    voice_cfg = _make_voice_config(tmp_path, enabled=True)
    result = _resolve_trainer(voice_cfg)
    assert result is None


def test_h8_returns_none_when_voice_config_is_none():
    """None voice_config → return None (no voice alignment configured at all)."""
    from kaine.boot import _resolve_trainer

    assert _resolve_trainer(None) is None


# ---------------------------------------------------------------------------
# M1 — Decommission backup: encryption failure → ok=False
# ---------------------------------------------------------------------------


def _seed_backup_state(state_root: Path) -> None:
    (state_root / "eidolon").mkdir(parents=True, exist_ok=True)
    (state_root / "eidolon" / "self_model.json").write_text(
        json.dumps({"name": "Test"}), encoding="utf-8"
    )


def _assessment():
    from kaine.lifecycle.divergence import DivergenceAssessment

    return DivergenceAssessment(diverged=True, signals={}, summary="test")


def test_m1_backup_encryption_failure_returns_not_ok(tmp_path, monkeypatch):
    """When encryption is enabled and fails, ok must be False and
    encryption_failed must be True — not ok=True with a plaintext bundle."""
    from kaine.lifecycle.decommission import capture_backup
    from kaine.security.crypto import (
        CryptoConfig,
        StateEncryptor,
        get_state_encryptor,
        set_state_encryptor,
    )

    # Set the env var BEFORE constructing the encryptor (key resolution happens
    # at construction time).
    monkeypatch.setenv("KAINE_STATE_KEY", "0" * 32)

    # Install an encryptor that always raises on encrypt.
    class BoomEncryptor(StateEncryptor):
        def encrypt(self, data: bytes) -> bytes:
            raise RuntimeError("simulated encrypt failure")

    enc = BoomEncryptor(CryptoConfig(enabled=True, key_env_var="KAINE_STATE_KEY"))
    prev = get_state_encryptor()
    set_state_encryptor(enc)
    try:
        state_root = tmp_path / "state"
        _seed_backup_state(state_root)

        result = capture_backup(
            state_root=state_root,
            fork_root=tmp_path / "forks",
            qdrant_cfg={},
            out_root=tmp_path / "backups",
            entity_name="Test",
            assessment=_assessment(),
        )

        assert result.ok is False, (
            "Backup must report ok=False when encryption was enabled and failed; "
            "a plaintext bundle exists but the operator believes it is encrypted."
        )
        assert result.encryption_failed is True
        assert result.encrypted is False
        assert any("encryption" in e.lower() for e in result.errors)
    finally:
        set_state_encryptor(prev)


def test_m1_backup_encryption_success_still_ok(tmp_path, monkeypatch):
    """Positive control: when encryption succeeds, ok=True and encrypted=True."""
    from kaine.lifecycle.decommission import capture_backup
    from kaine.security.crypto import (
        CryptoConfig,
        StateEncryptor,
        get_state_encryptor,
        set_state_encryptor,
    )

    # Set env var before constructing the encryptor.
    monkeypatch.setenv("KAINE_STATE_KEY", "0" * 32)
    enc = StateEncryptor(CryptoConfig(enabled=True, key_env_var="KAINE_STATE_KEY"))
    prev = get_state_encryptor()
    set_state_encryptor(enc)
    try:
        state_root = tmp_path / "state"
        _seed_backup_state(state_root)

        result = capture_backup(
            state_root=state_root,
            fork_root=tmp_path / "forks",
            qdrant_cfg={},
            out_root=tmp_path / "backups",
            entity_name="Test",
            assessment=_assessment(),
        )

        assert result.ok is True
        assert result.encrypted is True
        assert result.encryption_failed is False
    finally:
        set_state_encryptor(prev)


def test_m1_backup_plaintext_when_encryption_disabled_is_ok(tmp_path):
    """When encryption is disabled (not configured), ok=True + encrypted=False
    is the honest outcome (not a failure)."""
    from kaine.lifecycle.decommission import capture_backup

    state_root = tmp_path / "state"
    _seed_backup_state(state_root)

    result = capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        qdrant_cfg={},
        out_root=tmp_path / "backups",
        entity_name="Test",
        assessment=_assessment(),
    )

    assert result.ok is True
    assert result.encrypted is False
    assert result.encryption_failed is False


# ---------------------------------------------------------------------------
# M2 — Research bundle: encryption_error set when encryption enabled + failed
# ---------------------------------------------------------------------------


def _make_eval_root(tmp_path: Path) -> Path:
    eval_root = tmp_path / "evaluation"
    d = eval_root / "ab_divergence"
    d.mkdir(parents=True)
    (d / "ab-2026-06-09.jsonl").write_text('{"value": 0.1}\n', encoding="utf-8")
    return eval_root


def test_m2_bundle_encryption_error_set_on_failure(tmp_path, monkeypatch):
    """When encryption is enabled and fails, bundle.encryption_error must be
    set (not None) so callers can distinguish enabled-but-failed from
    encryption-disabled plaintext."""
    from kaine.research.submission import build_research_bundle
    from kaine.security.crypto import (
        CryptoConfig,
        StateEncryptor,
        get_state_encryptor,
        set_state_encryptor,
    )

    class BoomEncryptor(StateEncryptor):
        def encrypt(self, data: bytes) -> bytes:
            raise RuntimeError("simulated encrypt failure")

    monkeypatch.setenv("KAINE_STATE_KEY", "0" * 32)
    enc = BoomEncryptor(CryptoConfig(enabled=True, key_env_var="KAINE_STATE_KEY"))
    prev = get_state_encryptor()
    set_state_encryptor(enc)
    try:
        eval_root = _make_eval_root(tmp_path)
        bundle = build_research_bundle(
            eval_root=eval_root,
            out_dir=tmp_path / "out",
        )

        assert bundle.encryption_error is not None, (
            "bundle.encryption_error must be set when encryption was enabled "
            "and failed — not None as if encryption was simply disabled."
        )
        assert bundle.encrypted is False
        # The plaintext_note is also set (for human display), but encryption_error
        # is the machine-readable signal.
        assert bundle.plaintext_note != ""
    finally:
        set_state_encryptor(prev)


def test_m2_bundle_encryption_error_none_when_disabled(tmp_path):
    """When encryption is disabled by config, encryption_error must be None
    (ordinary plaintext, not a failure)."""
    from kaine.research.submission import build_research_bundle

    eval_root = _make_eval_root(tmp_path)
    bundle = build_research_bundle(
        eval_root=eval_root,
        out_dir=tmp_path / "out",
    )

    assert bundle.encryption_error is None, (
        "encryption_error must be None when encryption is simply disabled — "
        "do not conflate disabled with failed."
    )
    assert bundle.encrypted is False


def test_m2_bundle_encryption_error_none_on_success(tmp_path, monkeypatch):
    """When encryption succeeds, encryption_error must be None."""
    from kaine.research.submission import build_research_bundle
    from kaine.security.crypto import (
        CryptoConfig,
        StateEncryptor,
        get_state_encryptor,
        set_state_encryptor,
    )

    monkeypatch.setenv("KAINE_STATE_KEY", "0" * 32)
    enc = StateEncryptor(CryptoConfig(enabled=True, key_env_var="KAINE_STATE_KEY"))
    prev = get_state_encryptor()
    set_state_encryptor(enc)
    try:
        eval_root = _make_eval_root(tmp_path)
        bundle = build_research_bundle(
            eval_root=eval_root,
            out_dir=tmp_path / "out",
        )

        assert bundle.encrypted is True
        assert bundle.encryption_error is None
    finally:
        set_state_encryptor(prev)


# ---------------------------------------------------------------------------
# L4 — Decommission Qdrant delete: get_collections() failure → error recorded,
#       deletion skipped (not assumed-present)
# ---------------------------------------------------------------------------


def test_l4_get_collections_failure_records_error_and_skips_delete(tmp_path):
    """When get_collections() raises, the error is recorded in result.errors
    and no collections are deleted (not assumed-present)."""
    from kaine.lifecycle.decommission import delete_entity_state

    class FailingQdrantClient:
        def get_collections(self):
            raise ConnectionError("qdrant unavailable")

        def delete_collection(self, *, collection_name: str) -> None:
            raise AssertionError(
                f"delete_collection must not be called when probe failed; "
                f"got collection_name={collection_name!r}"
            )

        def close(self) -> None:
            pass

    state_root = tmp_path / "state"
    state_root.mkdir(parents=True, exist_ok=True)

    with mock.patch(
        "kaine.lifecycle.decommission._qdrant_client",
        return_value=FailingQdrantClient(),
    ):
        result = delete_entity_state(
            state_root=state_root,
            qdrant_cfg={"host": "127.0.0.1", "port": 6533},
            dry_run=False,
        )

    # Must record the probe failure in errors.
    assert any(
        "get_collections" in e or "probe" in e.lower() or "unconfirmed" in e.lower()
        for e in result.errors
    ), f"Expected probe-failure error in result.errors; got: {result.errors}"

    # Must not have deleted anything.
    assert result.dropped_collections == []


def test_l4_get_collections_success_deletes_normally(tmp_path):
    """Positive control: when get_collections() succeeds, matching collections
    are deleted and no spurious error is recorded."""
    from kaine.lifecycle.decommission import delete_entity_state, _mnemos_collection_names

    deleted: list[str] = []
    expected_collections = _mnemos_collection_names(None)

    class SuccessQdrantClient:
        class _Coll:
            def __init__(self, name: str) -> None:
                self.name = name

        class _Resp:
            def __init__(self, names: list[str]) -> None:
                self.collections = [
                    SuccessQdrantClient._Coll(n) for n in names
                ]

        def get_collections(self):
            return self._Resp(expected_collections)

        def delete_collection(self, *, collection_name: str) -> None:
            deleted.append(collection_name)

        def close(self) -> None:
            pass

    state_root = tmp_path / "state"
    state_root.mkdir(parents=True, exist_ok=True)

    with mock.patch(
        "kaine.lifecycle.decommission._qdrant_client",
        return_value=SuccessQdrantClient(),
    ):
        result = delete_entity_state(
            state_root=state_root,
            qdrant_cfg={"host": "127.0.0.1", "port": 6533},
            dry_run=False,
        )

    assert set(result.dropped_collections) == set(expected_collections)
    assert not any("probe" in e.lower() or "get_collections" in e for e in result.errors), (
        f"Unexpected probe errors: {result.errors}"
    )
