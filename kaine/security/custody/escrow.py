# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""2-of-n pairwise XOR escrow with HPKE-sealed shares.

For every unordered trustee pair {i, j}, an independent random value r is
drawn.  Trustee i (lexicographically lower ID) receives r, trustee j receives
r XOR DEK.  Any two trustees in a pair can XOR their shares to recover the
DEK; a single trustee's shares are uniformly random and reveal nothing.

Each share is HPKE-sealed (X25519, HKDF-SHA256, AES-256-GCM) to its trustee's
public key with an info string binding entity, pair and role, so a share
sealed for one context fails to open in any other.

Recovery requires TPM attestation (task 1.2, ``tpm.py``).  This module
provides the cryptographic primitives: ``open_share`` unseals one share and
``recover_dek`` XORs two shares.  The attested key-transport and re-sealing
flow lives in ``tpm.py`` once that task lands.
"""

from __future__ import annotations

import base64
import itertools
import logging
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.hpke import AEAD, KDF, KEM, Suite

log = logging.getLogger(__name__)

_DEK_BYTES = 32
_SUITE = Suite(KEM.X25519, KDF.HKDF_SHA256, AEAD.AES_256_GCM)


@dataclass(frozen=True)
class Trustee:
    id: str
    public_key: X25519PublicKey


@dataclass(frozen=True)
class SealedShare:
    pair: tuple[str, str]
    trustee_id: str
    role: str
    sealed: bytes


@dataclass(frozen=True)
class EscrowBundle:
    version: int
    entity_id: str
    n: int
    shares: list[SealedShare]


def _build_info(entity_id: str, pair_id: str, role: str) -> bytes:
    return (
        b"kaine/escrow|"
        + entity_id.encode("utf-8")
        + b"|"
        + pair_id.encode("utf-8")
        + b"|"
        + role.encode("utf-8")
    )


def _pair_id(id_a: str, id_b: str) -> str:
    a, b = sorted((id_a, id_b))
    return f"{a}+{b}"


def _xor_bytes(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def load_trustees(path: Path) -> list[Trustee]:
    """Load trustees from a TOML config file.

    Raises ``ValueError`` if the file holds fewer than 2 trustees or any
    entry is malformed.  Raises ``FileNotFoundError`` if *path* does not
    exist.
    """
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    entries = raw.get("trustee", [])
    if len(entries) < 2:
        raise ValueError(
            f"at least 2 trustees required, got {len(entries)}"
        )
    trustees: list[Trustee] = []
    for entry in entries:
        tid = entry.get("id", "")
        if not tid:
            raise ValueError("trustee entry missing 'id'")
        key_b64 = entry.get("public_key_x25519", "")
        if not key_b64:
            raise ValueError(f"trustee {tid!r} missing 'public_key_x25519'")
        key_bytes = base64.b64decode(key_b64)
        if len(key_bytes) != 32:
            raise ValueError(
                f"trustee {tid!r}: X25519 public key must be 32 bytes, "
                f"got {len(key_bytes)}"
            )
        pub = X25519PublicKey.from_public_bytes(key_bytes)
        trustees.append(Trustee(id=tid, public_key=pub))

    ids = [t.id for t in trustees]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate trustee IDs")
    log.info("loaded %d trustees", len(trustees))
    return trustees


def escrow_dek(
    dek: bytes, entity_id: str, trustees: list[Trustee]
) -> EscrowBundle:
    """Split a 32-byte DEK into 2-of-n pairwise XOR shares.

    For every unordered pair of trustees, draws a random share and seals
    both halves to their respective trustees via HPKE.
    """
    if len(dek) != _DEK_BYTES:
        raise ValueError(
            f"DEK must be exactly {_DEK_BYTES} bytes, got {len(dek)}"
        )
    if not entity_id:
        raise ValueError("entity_id must not be empty")
    if len(trustees) < 2:
        raise ValueError("at least 2 trustees required")

    shares: list[SealedShare] = []

    for t_i, t_j in itertools.combinations(
        sorted(trustees, key=lambda t: t.id), 2
    ):
        pid = _pair_id(t_i.id, t_j.id)
        r_ij = os.urandom(_DEK_BYTES)
        share_x = _xor_bytes(r_ij, dek)

        info_r = _build_info(entity_id, pid, "r")
        info_x = _build_info(entity_id, pid, "x")

        sealed_r = _SUITE.encrypt(r_ij, t_i.public_key, info_r)
        sealed_x = _SUITE.encrypt(share_x, t_j.public_key, info_x)

        shares.append(SealedShare(
            pair=(t_i.id, t_j.id),
            trustee_id=t_i.id,
            role="r",
            sealed=sealed_r,
        ))
        shares.append(SealedShare(
            pair=(t_i.id, t_j.id),
            trustee_id=t_j.id,
            role="x",
            sealed=sealed_x,
        ))

    log.info("escrowed DEK for entity across %d trustees", len(trustees))
    return EscrowBundle(
        version=1,
        entity_id=entity_id,
        n=len(trustees),
        shares=shares,
    )


def open_share(
    sealed: bytes,
    private_key: X25519PrivateKey,
    entity_id: str,
    pair_id: str,
    role: str,
) -> bytes:
    """HPKE-open one sealed share.

    Raises on info-binding mismatch (wrong entity, pair or role).  The
    actual attested recovery flow (generating a TPM key, verifying
    attestation, re-sealing to the receiving host) is in ``tpm.py``
    (task 1.2).
    """
    info = _build_info(entity_id, pair_id, role)
    return _SUITE.decrypt(sealed, private_key, info)


def recover_dek(share_r: bytes, share_x: bytes) -> bytes:
    """XOR two shares to recover the DEK.

    The caller must have obtained both shares through the attested
    recovery flow in ``tpm.py``.  This function performs only the
    recombination step.
    """
    if len(share_r) != _DEK_BYTES:
        raise ValueError(
            f"share_r must be {_DEK_BYTES} bytes, got {len(share_r)}"
        )
    if len(share_x) != _DEK_BYTES:
        raise ValueError(
            f"share_x must be {_DEK_BYTES} bytes, got {len(share_x)}"
        )
    return _xor_bytes(share_r, share_x)


def serialize_bundle(bundle: EscrowBundle) -> dict:
    """Serialize an ``EscrowBundle`` to a JSON-safe dict."""
    return {
        "version": bundle.version,
        "entity_id": bundle.entity_id,
        "n": bundle.n,
        "shares": [
            {
                "pair": list(s.pair),
                "trustee_id": s.trustee_id,
                "role": s.role,
                "sealed": base64.b64encode(s.sealed).decode("ascii"),
            }
            for s in bundle.shares
        ],
    }


def deserialize_bundle(data: dict) -> EscrowBundle:
    """Deserialize an ``EscrowBundle`` from a JSON-loaded dict."""
    return EscrowBundle(
        version=data["version"],
        entity_id=data["entity_id"],
        n=data["n"],
        shares=[
            SealedShare(
                pair=tuple(s["pair"]),
                trustee_id=s["trustee_id"],
                role=s["role"],
                sealed=base64.b64decode(s["sealed"]),
            )
            for s in data["shares"]
        ],
    )
