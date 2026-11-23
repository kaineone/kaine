# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for post-quantum escrow (Shamir + ML-KEM-768)."""

from __future__ import annotations

import base64
import os
import tempfile

from cryptography.hazmat.primitives import serialization

from kaine.security.custody.pq_escrow import (
    deserialize_bundle,
    escrow_dek,
    gen_trustee_keypair,
    load_trustees,
    open_share,
    recover_dek,
    serialize_bundle,
)


def _trustees() -> tuple[list, object, object]:
    pub1, priv_pem1 = gen_trustee_keypair()
    pub2, priv_pem2 = gen_trustee_keypair()
    import pathlib

    toml = (
        '[[trustee]]\nid="t1"\npublic_key_mlkem768="'
        + base64.b64encode(pub1).decode()
        + '"\n[[trustee]]\nid="t2"\npublic_key_mlkem768="'
        + base64.b64encode(pub2).decode()
        + '"\n'
    )
    p = pathlib.Path(tempfile.mkdtemp()) / "trustees.toml"
    p.write_text(toml)
    trustees = load_trustees(p)
    priv1 = serialization.load_pem_private_key(priv_pem1, password=None)
    priv2 = serialization.load_pem_private_key(priv_pem2, password=None)
    return trustees, priv1, priv2


def test_escrow_roundtrip() -> None:
    trustees, priv1, priv2 = _trustees()
    dek = os.urandom(32)
    bundle = escrow_dek(dek, "entity-abc", trustees, threshold=2)
    ser = serialize_bundle(bundle)
    des = deserialize_bundle(ser)
    priv_map = {"t1": priv1, "t2": priv2}
    opened = []
    for sh in des.shares:
        x, b = open_share(sh, priv_map[sh.trustee_id])
        opened.append((x, b))
    recovered = recover_dek(opened)
    assert recovered == dek


def test_single_share_rejected() -> None:
    import pytest

    trustees, priv1, priv2 = _trustees()
    dek = os.urandom(32)
    bundle = escrow_dek(dek, "entity-abc", trustees, threshold=2)
    priv_map = {"t1": priv1, "t2": priv2}
    first = bundle.shares[0]
    x, b = open_share(first, priv_map[first.trustee_id])
    with pytest.raises(ValueError):
        recover_dek([(x, b)])


def test_wrong_trustee_cannot_open() -> None:
    import pytest

    trustees, priv1, priv2 = _trustees()
    dek = os.urandom(32)
    bundle = escrow_dek(dek, "entity-abc", trustees, threshold=2)
    # t1's share encrypted to t1's pubkey; t2's private key must fail.
    t1_share = next(s for s in bundle.shares if s.trustee_id == "t1")
    with pytest.raises(Exception):
        open_share(t1_share, priv2)
