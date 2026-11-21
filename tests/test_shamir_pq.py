# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for Shamir secret sharing over GF(2^8)."""

from __future__ import annotations

import itertools
import os

from kaine.security.custody.shamir import combine, split


def test_roundtrip_thresholds() -> None:
    secret = os.urandom(32)
    for k, n in ((2, 2), (2, 4), (3, 5), (4, 7)):
        shares = split(secret, k, n)
        assert len(shares) == n
        assert all(len(s[1]) == len(secret) for s in shares)
        for subset in itertools.combinations(range(n), k):
            assert combine([shares[i] for i in subset]) == secret


def test_one_share_reveals_nothing_about_length() -> None:
    secret = os.urandom(32)
    shares = split(secret, 3, 5)
    for x, sh in shares:
        assert len(sh) == len(secret)


def test_empty_secret_rejected() -> None:
    import pytest

    with pytest.raises(ValueError):
        split(b"", 2, 3)


def test_below_threshold_reconstructs_wrong() -> None:
    secret = os.urandom(16)
    shares = split(secret, 3, 5)
    # combining only 2 shares must not yield the secret
    bad = combine(shares[:2])
    assert bad != secret
