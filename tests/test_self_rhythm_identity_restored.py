# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

pytest.importorskip("snntorch")

from kaine.oscillator.module_oscillator import make_self_rhythm_oscillator

HEX_DIGITS = set("0123456789abcdef")


def test_fresh_oscillator_identity_is_not_restored():
    osc = make_self_rhythm_oscillator(seed=1)
    assert osc is not None
    assert osc.identity_restored is False
    assert len(osc.identity) == 32
    assert all(ch in HEX_DIGITS for ch in osc.identity)


def test_fresh_oscillators_draw_distinct_identities():
    a = make_self_rhythm_oscillator(seed=1)
    b = make_self_rhythm_oscillator(seed=2)
    assert a is not None
    assert b is not None
    assert a.identity != b.identity


def test_deserialize_restores_identity_and_sets_restored_flag():
    a = make_self_rhythm_oscillator(seed=1)
    b = make_self_rhythm_oscillator(seed=2)
    assert a is not None
    assert b is not None
    b.deserialize(a.serialize())
    assert b.identity == a.identity
    assert b.identity_restored is True


def test_non_v2_state_leaves_identity_unrestored():
    a = make_self_rhythm_oscillator(seed=1)
    b = make_self_rhythm_oscillator(seed=2)
    assert a is not None
    assert b is not None
    state = a.serialize()
    state["version"] = 1
    original_identity = b.identity
    b.deserialize(state)
    assert b.identity == original_identity
    assert b.identity_restored is False


def test_v2_state_without_identity_leaves_identity_unrestored():
    a = make_self_rhythm_oscillator(seed=1)
    b = make_self_rhythm_oscillator(seed=2)
    assert a is not None
    assert b is not None
    state = a.serialize()
    del state["identity"]
    original_identity = b.identity
    b.deserialize(state)
    assert b.identity == original_identity
    assert b.identity_restored is False
