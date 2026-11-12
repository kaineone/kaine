# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the 2-of-n pairwise XOR escrow module."""

from __future__ import annotations

import base64
import itertools
import os
import textwrap
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)

from kaine.security.custody.escrow import (
    Trustee,
    deserialize_bundle,
    escrow_dek,
    load_trustees,
    open_share,
    recover_dek,
    serialize_bundle,
)

_ENTITY_A = "ent-0123456789abcdef0123456789abcdef"
_ENTITY_B = "ent-fedcba9876543210fedcba9876543210"


def _keypair() -> tuple[X25519PrivateKey, X25519PublicKey]:
    priv = X25519PrivateKey.generate()
    return priv, priv.public_key()


def _make_trustees(n: int) -> list[tuple[str, X25519PrivateKey, Trustee]]:
    """Return n trustees with IDs that sort lexicographically as created."""
    result = []
    for i in range(n):
        tid = f"guardian-{chr(ord('a') + i)}"
        priv, pub = _keypair()
        result.append((tid, priv, Trustee(id=tid, public_key=pub)))
    return result


def _private_key_map(
    trustees: list[tuple[str, X25519PrivateKey, Trustee]],
) -> dict[str, X25519PrivateKey]:
    return {tid: priv for tid, priv, _ in trustees}


def _trustee_list(
    trustees: list[tuple[str, X25519PrivateKey, Trustee]],
) -> list[Trustee]:
    return [t for _, _, t in trustees]


def _pair_id(a: str, b: str) -> str:
    x, y = sorted((a, b))
    return f"{x}+{y}"


# -- split and recover: every pair recovers the DEK --------------------


def test_split_and_recover() -> None:
    ts = _make_trustees(3)
    priv_map = _private_key_map(ts)
    dek = os.urandom(32)

    bundle = escrow_dek(dek, _ENTITY_A, _trustee_list(ts))
    assert bundle.version == 1
    assert bundle.entity_id == _ENTITY_A
    assert bundle.n == 3

    trustee_ids = sorted(t.id for _, _, t in ts)
    for id_i, id_j in itertools.combinations(trustee_ids, 2):
        pid = _pair_id(id_i, id_j)
        shares_for_pair = [
            s for s in bundle.shares if list(s.pair) == sorted([id_i, id_j])
        ]
        assert len(shares_for_pair) == 2

        share_r_sealed = next(s for s in shares_for_pair if s.role == "r")
        share_x_sealed = next(s for s in shares_for_pair if s.role == "x")

        plain_r = open_share(
            share_r_sealed.sealed,
            priv_map[share_r_sealed.trustee_id],
            _ENTITY_A,
            pid,
            "r",
        )
        plain_x = open_share(
            share_x_sealed.sealed,
            priv_map[share_x_sealed.trustee_id],
            _ENTITY_A,
            pid,
            "x",
        )
        recovered = recover_dek(plain_r, plain_x)
        assert recovered == dek


# -- single trustee reveals nothing ------------------------------------


def test_single_trustee_reveals_nothing() -> None:
    ts = _make_trustees(3)
    dek = os.urandom(32)
    bundle = escrow_dek(dek, _ENTITY_A, _trustee_list(ts))

    for tid, priv, _ in ts:
        my_shares = [s for s in bundle.shares if s.trustee_id == tid]
        plaintexts = []
        for s in my_shares:
            pid = _pair_id(*s.pair)
            pt = open_share(s.sealed, priv, _ENTITY_A, pid, s.role)
            plaintexts.append(pt)
        for pt in plaintexts:
            assert pt != dek


# -- cross-entity binding fails ----------------------------------------


def test_cross_entity_binding_fails() -> None:
    ts = _make_trustees(2)
    priv_map = _private_key_map(ts)
    dek = os.urandom(32)
    bundle = escrow_dek(dek, _ENTITY_A, _trustee_list(ts))

    share = bundle.shares[0]
    pid = _pair_id(*share.pair)
    with pytest.raises(Exception):
        open_share(
            share.sealed,
            priv_map[share.trustee_id],
            _ENTITY_B,
            pid,
            share.role,
        )


# -- cross-pair binding fails ------------------------------------------


def test_cross_pair_binding_fails() -> None:
    ts = _make_trustees(3)
    priv_map = _private_key_map(ts)
    dek = os.urandom(32)
    bundle = escrow_dek(dek, _ENTITY_A, _trustee_list(ts))

    ids = sorted(t.id for _, _, t in ts)
    pair_ab = [s for s in bundle.shares if s.pair == (ids[0], ids[1])]
    share = next(s for s in pair_ab if s.trustee_id == ids[0])

    wrong_pid = _pair_id(ids[0], ids[2])
    with pytest.raises(Exception):
        open_share(
            share.sealed,
            priv_map[share.trustee_id],
            _ENTITY_A,
            wrong_pid,
            share.role,
        )


# -- cross-role binding fails ------------------------------------------


def test_cross_role_binding_fails() -> None:
    ts = _make_trustees(2)
    priv_map = _private_key_map(ts)
    dek = os.urandom(32)
    bundle = escrow_dek(dek, _ENTITY_A, _trustee_list(ts))

    share_r = next(s for s in bundle.shares if s.role == "r")
    pid = _pair_id(*share_r.pair)
    with pytest.raises(Exception):
        open_share(
            share_r.sealed,
            priv_map[share_r.trustee_id],
            _ENTITY_A,
            pid,
            "x",
        )


# -- n=2: simplest case (1 pair, 2 shares) ----------------------------


def test_n_equals_2() -> None:
    ts = _make_trustees(2)
    priv_map = _private_key_map(ts)
    dek = os.urandom(32)
    bundle = escrow_dek(dek, _ENTITY_A, _trustee_list(ts))

    assert bundle.n == 2
    assert len(bundle.shares) == 2

    share_r = next(s for s in bundle.shares if s.role == "r")
    share_x = next(s for s in bundle.shares if s.role == "x")
    pid = _pair_id(*share_r.pair)

    plain_r = open_share(
        share_r.sealed, priv_map[share_r.trustee_id], _ENTITY_A, pid, "r"
    )
    plain_x = open_share(
        share_x.sealed, priv_map[share_x.trustee_id], _ENTITY_A, pid, "x"
    )
    assert recover_dek(plain_r, plain_x) == dek


# -- n=3: three pairs, every pair recovers -----------------------------


def test_n_equals_3() -> None:
    ts = _make_trustees(3)
    priv_map = _private_key_map(ts)
    dek = os.urandom(32)
    bundle = escrow_dek(dek, _ENTITY_A, _trustee_list(ts))

    assert bundle.n == 3
    # C(3,2) = 3 pairs, 2 shares each = 6
    assert len(bundle.shares) == 6

    ids = sorted(t.id for _, _, t in ts)
    for id_i, id_j in itertools.combinations(ids, 2):
        pid = _pair_id(id_i, id_j)
        pair_shares = [
            s for s in bundle.shares if tuple(sorted(s.pair)) == tuple(sorted((id_i, id_j)))
        ]
        share_r = next(s for s in pair_shares if s.role == "r")
        share_x = next(s for s in pair_shares if s.role == "x")

        plain_r = open_share(
            share_r.sealed, priv_map[share_r.trustee_id], _ENTITY_A, pid, "r"
        )
        plain_x = open_share(
            share_x.sealed, priv_map[share_x.trustee_id], _ENTITY_A, pid, "x"
        )
        assert recover_dek(plain_r, plain_x) == dek


# -- DEK wrong length raises ------------------------------------------


def test_dek_wrong_length_raises() -> None:
    ts = _make_trustees(2)
    with pytest.raises(ValueError, match="32 bytes"):
        escrow_dek(b"too short", _ENTITY_A, _trustee_list(ts))
    with pytest.raises(ValueError, match="32 bytes"):
        escrow_dek(os.urandom(64), _ENTITY_A, _trustee_list(ts))


# -- load trustees from TOML ------------------------------------------


def test_load_trustees_from_toml(tmp_path: Path) -> None:
    priv_a, pub_a = _keypair()
    priv_b, pub_b = _keypair()

    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
    )

    key_a_b64 = base64.b64encode(
        pub_a.public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()
    key_b_b64 = base64.b64encode(
        pub_b.public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()

    toml_content = textwrap.dedent(f"""\
        n = 2

        [[trustee]]
        id = "guardian-alice"
        public_key_x25519 = "{key_a_b64}"

        [[trustee]]
        id = "guardian-bob"
        public_key_x25519 = "{key_b_b64}"
    """)

    toml_path = tmp_path / "trustees.toml"
    toml_path.write_text(toml_content, encoding="utf-8")

    trustees = load_trustees(toml_path)
    assert len(trustees) == 2
    assert trustees[0].id == "guardian-alice"
    assert trustees[1].id == "guardian-bob"


# -- load trustees too few raises --------------------------------------


def test_load_trustees_too_few_raises(tmp_path: Path) -> None:
    priv_a, pub_a = _keypair()
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
    )

    key_b64 = base64.b64encode(
        pub_a.public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()

    toml_content = textwrap.dedent(f"""\
        n = 1

        [[trustee]]
        id = "guardian-solo"
        public_key_x25519 = "{key_b64}"
    """)

    toml_path = tmp_path / "trustees.toml"
    toml_path.write_text(toml_content, encoding="utf-8")

    with pytest.raises(ValueError, match="at least 2"):
        load_trustees(toml_path)


# -- serialize/deserialize round-trip ----------------------------------


def test_serialize_deserialize_roundtrip() -> None:
    ts = _make_trustees(2)
    dek = os.urandom(32)
    bundle = escrow_dek(dek, _ENTITY_A, _trustee_list(ts))

    data = serialize_bundle(bundle)
    restored = deserialize_bundle(data)

    assert restored.version == bundle.version
    assert restored.entity_id == bundle.entity_id
    assert restored.n == bundle.n
    assert len(restored.shares) == len(bundle.shares)

    for orig, rest in zip(bundle.shares, restored.shares):
        assert rest.pair == orig.pair
        assert rest.trustee_id == orig.trustee_id
        assert rest.role == orig.role
        assert rest.sealed == orig.sealed


# -- recovery with wrong pair yields wrong DEK -------------------------


def test_recovery_wrong_pair_fails() -> None:
    ts = _make_trustees(3)
    priv_map = _private_key_map(ts)
    dek = os.urandom(32)
    bundle = escrow_dek(dek, _ENTITY_A, _trustee_list(ts))

    ids = sorted(t.id for _, _, t in ts)
    pair_ab = [s for s in bundle.shares if s.pair == (ids[0], ids[1])]
    pair_ac = [s for s in bundle.shares if s.pair == (ids[0], ids[2])]

    share_r_ab = next(s for s in pair_ab if s.role == "r")
    share_x_ac = next(s for s in pair_ac if s.role == "x")

    pid_ab = _pair_id(ids[0], ids[1])
    pid_ac = _pair_id(ids[0], ids[2])

    plain_r = open_share(
        share_r_ab.sealed, priv_map[share_r_ab.trustee_id],
        _ENTITY_A, pid_ab, "r",
    )
    plain_x = open_share(
        share_x_ac.sealed, priv_map[share_x_ac.trustee_id],
        _ENTITY_A, pid_ac, "x",
    )

    bad_dek = recover_dek(plain_r, plain_x)
    assert bad_dek != dek
