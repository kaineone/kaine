# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Post-quantum hardened escrow for entity keys.

Drop-in sibling of :mod:`kaine.security.custody.escrow` (which uses X25519 and
the pairwise-XOR scheme).  This module swaps the key transport for ML-KEM-768
(NIST FIPS 203, Kyber) and the secret organisation for Shamir's secret
sharing over GF(2^8), so the resulting custody bundle is quantum-resistant
with no new dependencies: ML-KEM, HKDF-SHA256 and AES-256-GCM all ship in
:cryptography:`cryptography` >= 50.0, and Shamir lives next door in
:mod:`kaine.security.custody.shamir`.

The operator holds zero shares.  Trustees (kaine.one + an independent
guardian by default) store their encrypted share bundles anywhere durable —
a private GitHub repo via ``gh`` is the recommended free tier; the encrypted
blob is all anyone else can read.  Recovery combines k-of-n shares locally
on a trustee's machine; the DEK never touches the operator.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import mlkem
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from kaine.security.custody.shamir import combine as shamir_combine
from kaine.security.custody.shamir import split as shamir_split

log = logging.getLogger(__name__)

_DEK_BYTES = 32
_KDF_INFO = b"kaine/pq-escrow/v1"


@dataclass(frozen=True)
class PQTrustee:
    id: str
    public_key: mlkem.MLKEM768PublicKey
    key_serialized: bytes


@dataclass(frozen=True)
class PQShare:
    trustee_id: str
    share_index: int
    # (encapsulated secret, nonce, AES-GCM ciphertext including tag)
    encapsulated: bytes
    nonce: bytes
    ciphertext: bytes


@dataclass
class PQEscrowBundle:
    version: int = 1
    entity_id: str = ""
    n: int = 0
    k: int = 2
    shares: list[PQShare] = field(default_factory=list)


def load_trustees(path: Path) -> list[PQTrustee]:
    """Load ML-KEM trustees from a TOML file.

    Schema:

        [[trustee]]
        id = "kaineone"
        public_key_mlkem768 = "<base64 of pub.public_bytes(Encoding.Raw)>"
    """
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    entries = raw.get("trustee", [])
    if len(entries) < 2:
        raise ValueError(f"at least 2 trustees required, got {len(entries)}")
    trustees: list[PQTrustee] = []
    for entry in entries:
        tid = entry.get("id", "")
        if not tid:
            raise ValueError("trustee entry missing 'id'")
        b64 = entry.get("public_key_mlkem768", "")
        if not b64:
            raise ValueError(f"trustee {tid!r} missing 'public_key_mlkem768'")
        pub_bytes = base64.b64decode(b64)
        pub = mlkem.MLKEM768PublicKey.from_public_bytes(pub_bytes)
        trustees.append(PQTrustee(id=tid, public_key=pub, key_serialized=pub_bytes))
    ids = [t.id for t in trustees]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate trustee IDs")
    log.info("loaded %d ML-KEM trustees", len(trustees))
    return trustees


def gen_trustee_keypair() -> tuple[bytes, bytes]:
    """Return (public_raw_bytes, private_key_pem) for one trustee.

    The private key is PKCS#8 PEM so it reloads via
    ``serialization.load_pem_private_key`` on any host.
    """
    from cryptography.hazmat.primitives import serialization

    priv = mlkem.MLKEM768PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pub_bytes, priv_pem


def _wrap_share(shared_secret: bytes, plaintext: bytes) -> tuple[bytes, bytes]:
    """HKDF + AES-256-GCM wrap *plaintext* with *shared_secret*."""
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_KDF_INFO).derive(shared_secret)
    aes = AESGCM(key)
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, plaintext, None)
    return nonce, ct


def _unwrap_share(shared_secret: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_KDF_INFO).derive(shared_secret)
    return AESGCM(key).decrypt(nonce, ciphertext, None)


def escrow_dek(
    dek: bytes,
    entity_id: str,
    trustees: list[PQTrustee],
    threshold: int = 2,
) -> PQEscrowBundle:
    """Split *dek* into *n* Shamir shares and wrap each to its trustee."""
    if len(dek) != _DEK_BYTES:
        raise ValueError(f"DEK must be {_DEK_BYTES} bytes, got {len(dek)}")
    if not entity_id:
        raise ValueError("entity_id must not be empty")
    if len(trustees) < threshold or threshold < 2:
        raise ValueError("need at least threshold trustees, threshold >= 2")
    n = len(trustees)
    if n > 255:
        raise ValueError("too many trustees for Shamir (max 255)")

    # Shamir split over the raw DEK byte string.
    shares = shamir_split(dek, threshold, n)

    # Build one (index -> trustee) mapping: share i goes to trustee i.
    # ML-KEM wrap per trustee.
    ordered = sorted(trustees, key=lambda t: t.id)
    sealed: list[PQShare] = []
    for idx, t in enumerate(ordered):
        x, share_bytes = shares[idx]
        # x is 1-based position within the Shamir set; store separately not needed,
        # but we wrap (x, share_bytes) so recovery knows the x coordinate.
        payload = bytes([x]) + share_bytes
        ss, ct = t.public_key.encapsulate()
        nonce, wrapped = _wrap_share(ss, payload)
        sealed.append(PQShare(
            trustee_id=t.id,
            share_index=idx,
            encapsulated=ct,
            nonce=nonce,
            ciphertext=wrapped,
        ))
    # Attach the symmetric secret (encapsulation result) -- but ct is public;
    # ss is private (recovered by trustee private key at decapsulate). Store only
    # public artifacts in the bundle; trustees recompute ss from encapsulated
    # + their private key at recovery.
    # NOTE: PQShare.encapsulated holds the ML-KEM ciphertext publicly; the
    # trustee's ML-KEM private key decapsulates it to ss at recovery time.
    # Shamir combine happens after all trustees have unwrapped their shares,
    # so we must also recover the x coordinate. It is stored inside the payload.

    log.info("PQ-escrowed DEK for entity %s across %d trustees", entity_id, n)
    return PQEscrowBundle(version=1, entity_id=entity_id, n=n, k=threshold, shares=sealed)


def open_share(
    share: PQShare,
    private_key: mlkem.MLKEM768PrivateKey,
) -> tuple[int, bytes]:
    """ML-KEM decapsulate + AES-GCM unwrap. Returns (x, shamir_share_bytes)."""
    ss = private_key.decapsulate(share.encapsulated)
    payload = _unwrap_share(ss, share.nonce, share.ciphertext)
    x = payload[0]
    share_bytes = payload[1:]
    return x, share_bytes


def recover_dek(opened: list[tuple[int, bytes]]) -> bytes:
    """Combine opened Shamir shares to recover the DEK."""
    return shamir_combine(opened)


def serialize_bundle(bundle: PQEscrowBundle) -> dict:
    return {
        "version": bundle.version,
        "entity_id": bundle.entity_id,
        "n": bundle.n,
        "k": bundle.k,
        "shares": [
            {
                "trustee_id": s.trustee_id,
                "share_index": s.share_index,
                "encapsulated": base64.b64encode(s.encapsulated).decode("ascii"),
                "nonce": base64.b64encode(s.nonce).decode("ascii"),
                "ciphertext": base64.b64encode(s.ciphertext).decode("ascii"),
            }
            for s in bundle.shares
        ],
    }


def deserialize_bundle(data: dict) -> PQEscrowBundle:
    return PQEscrowBundle(
        version=data["version"],
        entity_id=data["entity_id"],
        n=data["n"],
        k=data["k"],
        shares=[
            PQShare(
                trustee_id=s["trustee_id"],
                share_index=s["share_index"],
                encapsulated=base64.b64decode(s["encapsulated"]),
                nonce=base64.b64decode(s["nonce"]),
                ciphertext=base64.b64decode(s["ciphertext"]),
            )
            for s in data["shares"]
        ],
    )


def publish_to_github(repo: str, entity_id: str, bundle: PQEscrowBundle) -> None:
    """Publish a bundle as an encrypted blob to a GitHub private repo via gh CLI.

    Requires ``gh`` authenticated with push access to *repo*.  The bundle is
    JSON-encoded and committed; no plaintext secret material leaves the host.
    """
    body = json.dumps(serialize_bundle(bundle), indent=2)
    tmp = Path("/tmp/opencode") / f"pq_escrow_{entity_id}.json"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(body, encoding="utf-8")
    msg = f"escrow: {entity_id}"
    subprocess.run(
        ["gh", "api", f"repos/{repo}/contents/escrow/{entity_id}.json",
         "-X", "PUT",
         "-f", "message=" + msg,
         "-f", "content=" + base64.b64encode(body.encode()).decode("ascii")],
        check=True,
    )
    log.info("published PQ escrow bundle for %s to %s", entity_id, repo)
