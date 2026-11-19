# SPDX-FileCopyrightText: 2024 KAINE developers
# SPDX-License-Identifier: MIT
"""Tests for the cross‑modal identity binding primitives."""

import pytest

from kaine.lifecycle.social_cognition import Identity, bind_identities


def test_identity_merge_simple() -> None:
    a = Identity(identifier="alice", modalities={"vision"}, attributes={"color": "red"})
    b = Identity(identifier="alice", modalities={"audio"}, attributes={"voice": "soft"})
    merged = a.merge(b)

    assert merged.identifier == "alice"
    assert merged.modalities == {"vision", "audio"}
    # ``b``'s attribute overrides ``a``'s only if the same key exists; here keys differ
    assert merged.attributes == {"color": "red", "voice": "soft"}


def test_bind_identities_multiple() -> None:
    ids = [
        Identity(identifier="bob", modalities={"vision"}, attributes={"eye_color": "blue"}),
        Identity(identifier="bob", modalities={"audio"}, attributes={"voice": "deep"}),
        Identity(identifier="bob", modalities={"touch"}, attributes={"hand_temp": 36.5}),
    ]
    bound = bind_identities(ids)

    assert bound.identifier == "bob"
    assert bound.modalities == {"vision", "audio", "touch"}
    # All attributes from the individual identities should be present
    assert bound.attributes == {
        "eye_color": "blue",
        "voice": "deep",
        "hand_temp": 36.5,
    }


def test_bind_identities_mismatched_identifier() -> None:
    ids = [
        Identity(identifier="carol", modalities={"vision"}),
        Identity(identifier="dave", modalities={"audio"}),
    ]
    with pytest.raises(ValueError, match="different identifiers"):
        bind_identities(ids)