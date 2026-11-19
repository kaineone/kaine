# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Shamir secret sharing over GF(2^8) (AES field).

Pure Python, no dependencies, post-quantum indifferent: the only security
property used is information-theoretic indistinguishability, which neither
Shor nor Grover can break. Byte-wise, so a share of an m-byte secret is
exactly m bytes and reconstruction needs any k of the n shares. Uses the AES
irreducible polynomial (x^8+x^4+x^3+x+1) so every value fits in a byte.

Each byte of the secret is shared independently with its own degree-(k-1)
polynomial; a share's bytes are all modulo-256 field elements.
"""

from __future__ import annotations

import secrets
from typing import List, Sequence, Tuple

#: AES field polynomial: x^8 + x^4 + x^3 + x + 1
_POLY = 0x11B

# Multiplication / log tables for GF(2^8).
_EXP: list[int] = [0] * 512
_LOG: list[int] = [0] * 256
# Use 0x03 as the generator (standard Rijndael tables). 0x02 is not a
# generator of GF(2^8) under 0x11b.
def _gf_mul_noinline(a: int, b: int) -> int:
    r = 0
    for _ in range(8):
        if b & 1:
            r ^= a
        hi = a & 0x80
        a = (a << 1) & 0xFF
        if hi:
            a ^= (_POLY & 0xFF)
        b >>= 1
    return r

_acc = 1
_GEN = 3
for _i in range(255):
    _EXP[_i] = _acc
    _LOG[_acc] = _i
    _acc = _gf_mul_noinline(_acc, _GEN)
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gfmul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _inv(a: int) -> int:
    if a == 0:
        raise ZeroDivisionError
    return _EXP[255 - _LOG[a]]


def split(secret: bytes, k: int, n: int) -> List[Tuple[int, bytes]]:
    """Split *secret* into *n* shares with threshold *k*.

    Returns a list of ``(x, share)`` pairs with x in 1..n. Any *k* shares
    reconstruct *secret* via :func:`combine`; fewer reveal nothing.
    """
    if k < 2:
        raise ValueError("threshold k must be at least 2")
    if n < k:
        raise ValueError("n must be >= k")
    if n > 255:
        raise ValueError("n must be <= 255 in GF(2^8)")
    if not secret:
        raise ValueError("secret must be non-empty")

    out_shares: List[bytearray] = [bytearray(len(secret)) for _ in range(n)]

    for pos in range(len(secret)):
        # polynomial coefs: [secret[pos]] + (k-1) random
        coefs = [secret[pos]] + [secrets.randbelow(256) for _ in range(k - 1)]

        for idx in range(n):
            x = idx + 1
            # evaluate polynomial at x over GF(2^8) via Horner
            acc = 0
            for coef in reversed(coefs):
                acc = coef ^ _gfmul(acc, x)
            out_shares[idx][pos] = acc

    return [(i + 1, bytes(s)) for i, s in enumerate(out_shares)]


def combine(shares: Sequence[Tuple[int, bytes]]) -> bytes:
    """Reconstruct the secret from any *k* shares."""
    if len(shares) < 2:
        raise ValueError("at least 2 shares required")
    length = len(shares[0][1])
    for x, sh in shares:
        if len(sh) != length:
            raise ValueError("all shares must have equal length")
        if x == 0 or x > 255:
            raise ValueError("share x coordinate must be in 1..255")

    xs = [s[0] for s in shares]
    # precompute Lagrange basis values L_i(0)
    basis = []
    for i in range(len(shares)):
        li = 1
        for j in range(len(shares)):
            if i == j:
                continue
            # L_i(0) = prod_{j != i} (0 - xj) / (xi - xj) = prod (xj)/(xi - xj) in GF(2^8) (minus = plus)
            li = _gfmul(li, _gfmul(xs[j], _inv(xs[i] ^ xs[j])))
        basis.append(li)

    out = bytearray(length)
    for pos in range(length):
        acc = 0
        for i in range(len(shares)):
            acc ^= _gfmul(shares[i][1][pos], basis[i])
        out[pos] = acc
    return bytes(out)
