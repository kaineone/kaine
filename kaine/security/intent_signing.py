# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Provenance signatures for executive ``act`` intents (Mechanism B).

KAINE runs single-process today: every module is an asyncio task sharing one
Redis connection and one bus credential. That means the bus cannot tell *which*
module published an event — a compromised or prompt-injected peripheral module
(Lingua is the most exposed, being LLM-output-driven) could ``XADD`` a crafted
``{kind: "act", effector, params}`` onto ``volition.out`` and have Praxis realize
it, bypassing Syneidesis's threshold and Volition's inhibition gate entirely.

This module closes that boundary cryptographically. A per-boot secret, generated
by and held ONLY in the cycle process (never published to the bus, never
persisted, never logged), is injected into BOTH the action-selection step
(Volition, which SIGNS each ``act`` intent) and Praxis (which VERIFIES the
signature before any effector runs). A forged intent from any writer that does
not hold the secret fails verification and is dropped.

The signature covers a stable canonical serialization of the exact fields that
determine what the action does — ``kind``, ``effector``, ``params`` — plus a
``run_id`` and a monotonic ``seq`` so a captured signed intent cannot be
replayed (Praxis rejects a ``(run_id, seq)`` pair it has already realized).

This is a SECOND boundary. The operator effector-enablement whitelist + the
per-effector sandbox/command whitelist remain the PRIMARY enforced gate; this
change makes inhibition/provenance a real boundary at the Praxis interface in
addition to that gate, not a replacement for it.

Threat note: the secret lives in-process, so a full compromise of the cycle
process defeats it — but such an attacker already controls Volition, so the
boundary still holds against the realistic threat (a compromised *peripheral*
module). Per-process Redis ACLs (Option A in the design) are the direction once
services split; that is out of scope here.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

# Bytes of entropy in a per-boot signing secret. 32 bytes (256 bits) matches the
# SHA-256 block security level; drawn from os.urandom, never derived from
# anything guessable or persisted.
_SECRET_BYTES = 32


def generate_intent_secret() -> bytes:
    """Return a fresh per-boot HMAC secret (32 cryptographically-random bytes).

    Called once by the cycle composition root. The returned bytes are held only
    in-process and handed to Volition (to sign) and Praxis (to verify). They are
    NEVER published to the bus, written to disk, or logged.
    """
    return os.urandom(_SECRET_BYTES)


def _canonical(kind: str, effector: str, params: dict[str, Any], run_id: str, seq: int) -> bytes:
    """Deterministic serialization of the exact signed fields.

    Key order and separators are pinned (``sort_keys`` + compact separators) so
    the signer and verifier hash byte-identical input regardless of dict
    insertion order or json defaults — mirroring the audit log's ``_canonical``.
    """
    body = {
        "kind": kind,
        "effector": effector,
        "params": params,
        "run_id": run_id,
        "seq": seq,
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_intent_signature(
    secret: bytes,
    *,
    kind: str,
    effector: str,
    params: dict[str, Any],
    run_id: str,
    seq: int,
) -> str:
    """``HMAC-SHA256(secret, canonical(kind, effector, params, run_id, seq))``."""
    return hmac.new(
        secret, _canonical(kind, effector, params, run_id, seq), hashlib.sha256
    ).hexdigest()


def verify_intent_signature(
    secret: bytes,
    *,
    kind: str,
    effector: str,
    params: dict[str, Any],
    run_id: str,
    seq: int,
    signature: str,
) -> bool:
    """Constant-time verification of an act-intent signature.

    Recomputes the HMAC over the presented fields and compares it to
    ``signature`` with :func:`hmac.compare_digest` (constant-time, so a mismatch
    leaks no timing information). Returns ``False`` — never raises — on any
    malformed input, so the caller treats a bad signature as a plain rejection.
    """
    if not isinstance(signature, str) or not signature:
        return False
    try:
        expected = compute_intent_signature(
            secret,
            kind=kind,
            effector=effector,
            params=params,
            run_id=run_id,
            seq=seq,
        )
    except Exception:
        return False
    return hmac.compare_digest(expected, signature)


class IntentSigner:
    """Signs executive ``act`` intents with a per-boot secret.

    Holds the shared secret, the run's ``run_id``, and a monotonic ``seq``
    counter minted per signed intent. Injected into Volition at the composition
    root. Each :meth:`sign` call returns the ``(run_id, seq, signature)`` triple
    the intent must carry so Praxis can verify provenance and reject replays.
    """

    def __init__(self, secret: bytes, run_id: str) -> None:
        if not secret:
            raise ValueError("IntentSigner requires a non-empty secret")
        self._secret = secret
        self._run_id = str(run_id)
        self._seq = 0

    @property
    def run_id(self) -> str:
        return self._run_id

    def sign(
        self, *, kind: str, effector: str, params: dict[str, Any]
    ) -> tuple[str, int, str]:
        """Mint the next ``seq`` and return ``(run_id, seq, signature)``.

        ``seq`` is monotonic per signer (per boot), so no two intents from this
        run share a ``(run_id, seq)`` pair — that is what makes a captured intent
        non-replayable at the verifier.
        """
        seq = self._seq
        self._seq += 1
        signature = compute_intent_signature(
            self._secret,
            kind=kind,
            effector=effector,
            params=params,
            run_id=self._run_id,
            seq=seq,
        )
        return self._run_id, seq, signature


__all__ = [
    "generate_intent_secret",
    "compute_intent_signature",
    "verify_intent_signature",
    "IntentSigner",
]
