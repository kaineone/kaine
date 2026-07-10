# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unit tests for the act-intent provenance crypto core (Mechanism B).

Exercises the signing/verification primitives in
``kaine.security.intent_signing`` directly — canonicalization stability, a
round-trip verify, rejection of every tampered field, wrong-secret rejection,
malformed-signature handling (returns False, never raises), and the
``IntentSigner`` monotonic ``seq`` that makes a captured intent non-replayable.
These are the guarantees Praxis relies on when it authenticates an intent's
provenance before running any effector.
"""
from __future__ import annotations

from kaine.security.intent_signing import (
    IntentSigner,
    compute_intent_signature,
    generate_intent_secret,
    verify_intent_signature,
)

_SECRET = b"unit-test-provenance-secret-32by"
_FIELDS = dict(
    kind="act",
    effector="file_write",
    params={"name": "note.txt", "content": "hi"},
    run_id="run-abc",
    seq=0,
)


def test_generate_secret_is_random_and_32_bytes():
    a = generate_intent_secret()
    b = generate_intent_secret()
    assert isinstance(a, bytes) and len(a) == 32
    # Two draws are overwhelmingly unlikely to collide.
    assert a != b


def test_sign_verify_round_trip():
    sig = compute_intent_signature(_SECRET, **_FIELDS)
    assert isinstance(sig, str) and sig
    assert verify_intent_signature(_SECRET, signature=sig, **_FIELDS) is True


def test_signature_is_deterministic_regardless_of_param_key_order():
    sig1 = compute_intent_signature(
        _SECRET,
        kind="act",
        effector="file_write",
        params={"name": "note.txt", "content": "hi"},
        run_id="run-abc",
        seq=0,
    )
    sig2 = compute_intent_signature(
        _SECRET,
        kind="act",
        effector="file_write",
        params={"content": "hi", "name": "note.txt"},  # reordered
        run_id="run-abc",
        seq=0,
    )
    assert sig1 == sig2


def test_wrong_secret_fails():
    sig = compute_intent_signature(_SECRET, **_FIELDS)
    assert verify_intent_signature(b"a-different-secret-of-32-bytes!!", signature=sig, **_FIELDS) is False


def test_each_tampered_field_fails_verification():
    sig = compute_intent_signature(_SECRET, **_FIELDS)
    tampers = [
        {"kind": "speak"},
        {"effector": "shell"},
        {"params": {"name": "note.txt", "content": "HACKED"}},
        {"params": {"name": "other.txt", "content": "hi"}},
        {"run_id": "run-xyz"},
        {"seq": 1},
    ]
    for tamper in tampers:
        fields = {**_FIELDS, **tamper}
        assert verify_intent_signature(_SECRET, signature=sig, **fields) is False, tamper


def test_malformed_signature_returns_false_never_raises():
    for bad in ("", "not-hex", "deadbeef"):
        assert verify_intent_signature(_SECRET, signature=bad, **_FIELDS) is False


def test_intent_signer_requires_non_empty_secret():
    try:
        IntentSigner(b"", "run-1")
    except ValueError:
        pass
    else:  # pragma: no cover - explicit failure path
        raise AssertionError("IntentSigner must reject an empty secret")


def test_intent_signer_mints_monotonic_seq_and_valid_signatures():
    signer = IntentSigner(_SECRET, "run-1")
    assert signer.run_id == "run-1"
    seen: list[int] = []
    for _ in range(3):
        run_id, seq, sig = signer.sign(
            kind="act", effector="notify", params={"summary": "x"}
        )
        assert run_id == "run-1"
        seen.append(seq)
        # Each minted signature verifies against the same secret and fields.
        assert verify_intent_signature(
            _SECRET,
            kind="act",
            effector="notify",
            params={"summary": "x"},
            run_id=run_id,
            seq=seq,
            signature=sig,
        ) is True
    # seq is strictly increasing from 0 — no two intents share a (run_id, seq).
    assert seen == [0, 1, 2]
