# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""require_encryption is ENFORCED at the preservation write boundary.

Paper §3.7: cognitive-state serialization for preservation is protected by
AES-256-GCM and "fails closed when enabled without a key". §3.6: a capture that
cannot be honestly saved raises rather than writing a partial/complete-looking
bundle.

These tests pin the runtime half of the contract: when
``[preservation].require_encryption`` is set but state-at-rest encryption is not
active, ``preserve_live`` RAISES and writes NO plaintext artifact (no snapshot,
no bundle). With encryption properly enabled+keyed it succeeds and the bundle is
the encrypted ``bundle.tar.enc`` (never a plaintext ``bundle.tar``).
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest

from kaine.lifecycle.manager import ForkManager
from kaine.lifecycle.preservation import PreservationError
from kaine.modules.eidolon import Eidolon, SelfModel
from kaine.modules.registry import ModuleRegistry
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor

KEY = base64.b64encode(os.urandom(32)).decode("ascii")


@pytest.fixture(autouse=True)
def restore_default_encryptor():
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


class _NullBus:
    async def publish(self, *a, **k):
        return "0-0"

    async def read_entries(self, *a, **k):
        return [], None

    async def read(self, *a, **k):
        return []

    def subscribe_workspace(self, *a, **k):
        async def _empty():
            return
            yield

        return _empty()

    async def current_workspace_id(self) -> str:
        return "0-0"


async def _make_registry(tmp_path: Path) -> ModuleRegistry:
    reg = ModuleRegistry()
    eid = Eidolon(_NullBus(), persistence_path=tmp_path / "sm.json", save_interval_s=60)
    await eid.initialize()
    eid._model = SelfModel(name="probe", values=["continuity"])
    reg.register(eid)
    return reg


def _no_plaintext_on_disk(fork_root: Path, out_root: Path) -> None:
    """Assert nothing — encrypted or plaintext — was written by a failed preserve."""
    snapshots = list(fork_root.glob("*/snapshot.json")) if fork_root.exists() else []
    assert snapshots == [], f"a snapshot leaked despite fail-closed: {snapshots}"
    bundles = list(out_root.glob("preservation_*")) if out_root.exists() else []
    assert bundles == [], f"a preservation bundle leaked despite fail-closed: {bundles}"


@pytest.mark.asyncio
async def test_require_encryption_refuses_when_encryption_disabled(tmp_path: Path):
    # Encryption off (shipped default) but require_encryption=True → fail closed.
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    reg = await _make_registry(tmp_path)
    fork_root = tmp_path / "forks"
    out_root = tmp_path / "backups"
    fm = ForkManager(fork_root)

    with pytest.raises(PreservationError) as exc:
        await fm.preserve_live(
            reg,
            reason="individuation",
            out_root=out_root,
            entity_name="probe",
            require_encryption=True,
        )
    assert "require_encryption" in str(exc.value)
    # The load-bearing safety property: NOTHING was written in the clear.
    _no_plaintext_on_disk(fork_root, out_root)


@pytest.mark.asyncio
async def test_require_encryption_succeeds_when_encryption_enabled(
    tmp_path: Path, monkeypatch
):
    # Encryption properly enabled + keyed → preserve succeeds, bundle is encrypted.
    monkeypatch.setenv("KAINE_STATE_KEY", KEY)
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=True)))
    reg = await _make_registry(tmp_path)
    fork_root = tmp_path / "forks"
    out_root = tmp_path / "backups"
    fm = ForkManager(fork_root)

    result = await fm.preserve_live(
        reg,
        reason="individuation",
        out_root=out_root,
        entity_name="probe",
        require_encryption=True,
    )
    assert result.ok
    bundle = out_root / f"preservation_{result.preservation_id}_probe"
    # Encrypted archive present; plaintext archive absent.
    assert (bundle / "bundle.tar.enc").is_file()
    assert not (bundle / "bundle.tar").exists()
    assert result.manifest["encrypted"] is True


@pytest.mark.asyncio
async def test_no_require_encryption_allows_plaintext(tmp_path: Path):
    # Backward-compatible default: require_encryption=False writes a plaintext
    # bundle when encryption is off (the historic at-rest posture).
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    reg = await _make_registry(tmp_path)
    out_root = tmp_path / "backups"
    fm = ForkManager(tmp_path / "forks")

    result = await fm.preserve_live(
        reg, reason="individuation", out_root=out_root, entity_name="probe"
    )
    assert result.ok
    bundle = out_root / f"preservation_{result.preservation_id}_probe"
    assert (bundle / "bundle.tar").is_file()
    assert not (bundle / "bundle.tar.enc").exists()
