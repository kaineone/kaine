# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the per-entity KeyRing and SoftwareKek."""

from __future__ import annotations

import json
import os
import stat

import pytest
from cryptography.exceptions import InvalidTag

from kaine.security.custody.encryptor import EntityEncryptor
from kaine.security.custody.keyring import (
    KekProvider,
    KeyRing,
    SoftwareKek,
    WrappedDek,
)

_ENTITY_A = "ent-0123456789abcdef0123456789abcdef"
_ENTITY_B = "ent-fedcba9876543210fedcba9876543210"


def _fresh_kek() -> bytes:
    return os.urandom(32)


# ── SoftwareKek ─────────────────────────────────────────────────────────────


class TestSoftwareKek:
    def test_wrap_unwrap_round_trip(self) -> None:
        kek = SoftwareKek(_fresh_kek())
        dek = os.urandom(32)
        wrapped = kek.wrap(dek, _ENTITY_A)
        assert kek.unwrap(wrapped, _ENTITY_A) == dek

    def test_wrong_entity_id_raises(self) -> None:
        kek = SoftwareKek(_fresh_kek())
        wrapped = kek.wrap(os.urandom(32), _ENTITY_A)
        with pytest.raises(InvalidTag):
            kek.unwrap(wrapped, _ENTITY_B)

    def test_wrong_kek_raises(self) -> None:
        kek_a = SoftwareKek(_fresh_kek())
        kek_b = SoftwareKek(_fresh_kek())
        wrapped = kek_a.wrap(os.urandom(32), _ENTITY_A)
        with pytest.raises(InvalidTag):
            kek_b.unwrap(wrapped, _ENTITY_A)

    def test_empty_entity_id_wrap_raises(self) -> None:
        kek = SoftwareKek(_fresh_kek())
        with pytest.raises(ValueError, match="entity_id"):
            kek.wrap(os.urandom(32), "")

    def test_empty_entity_id_unwrap_raises(self) -> None:
        kek = SoftwareKek(_fresh_kek())
        with pytest.raises(ValueError, match="entity_id"):
            kek.unwrap(b"x" * 28, "")

    def test_wrong_kek_length_raises(self) -> None:
        with pytest.raises(ValueError, match="32 bytes"):
            SoftwareKek(os.urandom(16))

    def test_kek_id_is_stable(self) -> None:
        raw = _fresh_kek()
        kek_a = SoftwareKek(raw)
        kek_b = SoftwareKek(raw)
        assert kek_a.kek_id == kek_b.kek_id
        assert kek_a.kek_id.startswith("software:")

    def test_close_zeros_kek(self) -> None:
        kek = SoftwareKek(_fresh_kek())
        kek.close()
        assert all(b == 0 for b in kek._kek)

    def test_satisfies_protocol(self) -> None:
        kek = SoftwareKek(_fresh_kek())
        assert isinstance(kek, KekProvider)


# ── WrappedDek ──────────────────────────────────────────────────────────────


class TestWrappedDek:
    def test_round_trip(self) -> None:
        record = WrappedDek(
            entity_id=_ENTITY_A,
            wrap=os.urandom(44),
            kek_id="software:aabbccdd",
            policy="software",
            created_at=1700000000.0,
            escrow=[],
        )
        restored = WrappedDek.from_dict(record.to_dict())
        assert restored.entity_id == record.entity_id
        assert restored.wrap == record.wrap
        assert restored.kek_id == record.kek_id
        assert restored.policy == record.policy
        assert restored.created_at == record.created_at
        assert restored.escrow == record.escrow

    def test_from_dict_missing_field_raises(self) -> None:
        with pytest.raises(KeyError):
            WrappedDek.from_dict({"entity_id": _ENTITY_A})

    def test_to_dict_wrap_is_base64(self) -> None:
        import base64

        raw_wrap = os.urandom(44)
        record = WrappedDek(
            entity_id=_ENTITY_A,
            wrap=raw_wrap,
            kek_id="test",
            policy="software",
            created_at=0.0,
            escrow=[],
        )
        d = record.to_dict()
        assert base64.b64decode(d["wrap"]) == raw_wrap


# ── KeyRing ─────────────────────────────────────────────────────────────────


class TestKeyRing:
    def test_generate_dek_creates_file_and_caches(self, tmp_path: object) -> None:
        kek = SoftwareKek(_fresh_kek())
        ring = KeyRing(kek)
        record = ring.generate_dek(_ENTITY_A)

        assert record.entity_id == _ENTITY_A
        assert record.policy == "software"
        assert record.kek_id == kek.kek_id
        assert ring.has_dek(_ENTITY_A)
        # Encryptor is cached, so a second call returns the same object.
        enc = ring.encryptor_for(_ENTITY_A)
        assert isinstance(enc, EntityEncryptor)
        assert enc.entity_id == _ENTITY_A

    def test_generate_dek_existing_raises(self) -> None:
        kek = SoftwareKek(_fresh_kek())
        ring = KeyRing(kek)
        ring.generate_dek(_ENTITY_A)
        with pytest.raises(FileExistsError):
            ring.generate_dek(_ENTITY_A)

    def test_generate_dek_empty_entity_raises(self) -> None:
        kek = SoftwareKek(_fresh_kek())
        ring = KeyRing(kek)
        with pytest.raises(ValueError, match="entity_id"):
            ring.generate_dek("")

    def test_encryptor_for_loads_from_file(self) -> None:
        kek_bytes = _fresh_kek()
        kek = SoftwareKek(kek_bytes)
        ring = KeyRing(kek)
        ring.generate_dek(_ENTITY_A)

        # New ring instance (no cache) loading the same file.
        ring2 = KeyRing(SoftwareKek(kek_bytes))
        enc = ring2.encryptor_for(_ENTITY_A)
        assert isinstance(enc, EntityEncryptor)
        assert enc.entity_id == _ENTITY_A

    def test_encryptor_for_missing_raises(self) -> None:
        kek = SoftwareKek(_fresh_kek())
        ring = KeyRing(kek)
        with pytest.raises(FileNotFoundError):
            ring.encryptor_for("ent-does-not-exist")

    def test_encrypt_decrypt_via_keyring(self) -> None:
        kek = SoftwareKek(_fresh_kek())
        ring = KeyRing(kek)
        ring.generate_dek(_ENTITY_A)

        enc = ring.encryptor_for(_ENTITY_A)
        plaintext = b"cognitive state payload"
        blob = enc.encrypt(plaintext, kind="snapshot")
        assert enc.decrypt(blob, kind="snapshot") == plaintext

    def test_has_dek_false_when_missing(self) -> None:
        kek = SoftwareKek(_fresh_kek())
        ring = KeyRing(kek)
        assert ring.has_dek("ent-nonexistent") is False

    def test_entity_id_mismatch_raises(self) -> None:
        kek = SoftwareKek(_fresh_kek())
        ring = KeyRing(kek)
        ring.generate_dek(_ENTITY_A)

        # Tamper with the DEK file to change the entity_id inside it.
        path = ring._dek_path(_ENTITY_A)
        raw = json.loads(path.read_text())
        raw["entity_id"] = _ENTITY_B
        path.write_text(json.dumps(raw))

        ring2 = KeyRing(kek)
        with pytest.raises(ValueError, match="mismatch"):
            ring2.encryptor_for(_ENTITY_A)

    def test_close_zeros_cached_encryptors(self) -> None:
        kek = SoftwareKek(_fresh_kek())
        ring = KeyRing(kek)
        ring.generate_dek(_ENTITY_A)
        enc = ring.encryptor_for(_ENTITY_A)
        ring.close()
        assert all(b == 0 for b in enc._dek)
        with pytest.raises(RuntimeError, match="closed"):
            enc.encrypt(b"nope", kind="snapshot")

    def test_two_entities_are_independent(self) -> None:
        kek = SoftwareKek(_fresh_kek())
        ring = KeyRing(kek)
        ring.generate_dek(_ENTITY_A)
        ring.generate_dek(_ENTITY_B)

        enc_a = ring.encryptor_for(_ENTITY_A)
        enc_b = ring.encryptor_for(_ENTITY_B)
        blob = enc_a.encrypt(b"secret", kind="snapshot")
        with pytest.raises(InvalidTag):
            enc_b.decrypt(blob, kind="snapshot")

    @pytest.mark.skipif(os.name != "posix", reason="POSIX permissions only")
    def test_dek_file_permissions(self) -> None:
        kek = SoftwareKek(_fresh_kek())
        ring = KeyRing(kek)
        ring.generate_dek(_ENTITY_A)

        path = ring._dek_path(_ENTITY_A)
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode == 0o600

    def test_encryptor_for_caches(self) -> None:
        kek = SoftwareKek(_fresh_kek())
        ring = KeyRing(kek)
        ring.generate_dek(_ENTITY_A)
        enc1 = ring.encryptor_for(_ENTITY_A)
        enc2 = ring.encryptor_for(_ENTITY_A)
        assert enc1 is enc2
