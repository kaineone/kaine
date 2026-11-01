# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Identity-bound content: the one latent-derived value a trace may hold.

Under the ruling on ``latent-content-privacy`` open question 2 (option b,
2026-11-01), a stored trace MAY hold one content code, as the entity's own
memory, and only in the structured field ``latent_derived.identity_bound`` of
its record: ``{"code": [...], "code_id": ..., "generation": ...}``. Never in
the trace text that is embedded and rendered, never in a recall or replay
event, never on a persisted bus stream, in a log, a research record, the
intent log or the organ's corpus or prompt. Every strip point removes it
because it sits under ``latent_derived``; only the episodic store keeps it,
and the module-state captures exempt exactly this field of this module
(``kaine.lifecycle.latent_strip``), so a preservation carries it with the
store and decommission removes it with the store.

The field fails closed. The store writes it only when state encryption is in
effect and the store's files are encrypted at rest. Neither episodic backend
encrypts at the application layer today (the store is protected at the OS
layer only), so no trace can hold one until a backend that does declares it
(``encrypts_at_rest = True``). Recall ignores a stored code whose code id
differs from the running content code's: two codes learned from different
lives do not share coordinates (after a merge the store holds both parents'
traces). No component writes the field until the content-bearing traces of
build item 9(d) are built; this module fixes the rule they follow.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Optional

from kaine.privacy_filter import IDENTITY_BOUND_KEY, LATENT_DERIVED_KEY, identity_bound_value

log = logging.getLogger(__name__)



class IdentityBoundRefused(RuntimeError):
    """The store may not hold an identity-bound code; the message names why."""


def store_encrypts_at_rest(storage: Any) -> bool:
    """True only when the storage backend declares application-layer
    encryption of its files (no shipped backend does)."""
    return getattr(storage, "encrypts_at_rest", False) is True


def identity_bound_refusals(storage: Any, encryptor: Optional[Any] = None) -> list[str]:
    """Every reason the store may not write an identity-bound code."""
    reasons: list[str] = []
    if encryptor is None:
        from kaine.security.crypto import get_state_encryptor

        encryptor = get_state_encryptor()
    if not getattr(encryptor, "enabled", False):
        reasons.append("state encryption is not in effect")
    if not store_encrypts_at_rest(storage):
        reasons.append("the episodic store's files are not encrypted at rest")
    return reasons


def with_identity_bound(
    payload: Mapping[str, Any],
    *,
    code: Any,
    code_id: str,
    generation: int,
    storage: Any,
    encryptor: Optional[Any] = None,
) -> dict[str, Any]:
    """``payload`` with the identity-bound code attached, through the store's
    own rule (``stored_payload``): without it, an error logged by reason only,
    when the store may not hold one or the code is not a finite vector."""
    candidate = dict(payload)
    latent = dict(candidate.get(LATENT_DERIVED_KEY) or {})
    latent[IDENTITY_BOUND_KEY] = {"code": code, "code_id": code_id, "generation": generation}
    candidate[LATENT_DERIVED_KEY] = latent
    return stored_payload(candidate, storage=storage, encryptor=encryptor)


def recalled_code(payload: Mapping[str, Any], running_code_id: Optional[str]) -> Optional[list[float]]:
    """The stored code of a trace, or None when it has none, it is malformed,
    or its code id is not the running content code's."""
    latent = payload.get(LATENT_DERIVED_KEY) if isinstance(payload, Mapping) else None
    bound = identity_bound_value(latent.get(IDENTITY_BOUND_KEY)) if isinstance(latent, Mapping) else None
    if bound is None or running_code_id is None or bound["code_id"] != running_code_id:
        return None
    return list(bound["code"])


def stored_payload(
    payload: Mapping[str, Any], *, storage: Any, encryptor: Optional[Any] = None
) -> dict[str, Any]:
    """A trace payload as the store keeps it, enforced at the store
    (``EpisodicMemoryCore.store`` and the revive import).

    Every latent field is removed at any depth. A top-level
    ``latent_derived.identity_bound`` is kept only when the store may hold one
    (``identity_bound_refusals``) and it is exactly a well-formed field, rebuilt
    from ``code``, ``code_id`` and ``generation`` (anything else inside it,
    nested latent fields included, is dropped); otherwise it is dropped and an
    error logged by reason only.
    """
    from kaine.privacy_filter import strip_latent

    latent = payload.get(LATENT_DERIVED_KEY) if isinstance(payload, Mapping) else None
    has_bound = isinstance(latent, Mapping) and IDENTITY_BOUND_KEY in latent
    out = strip_latent(dict(payload))
    if not has_bound:
        return out
    bound = identity_bound_value(latent[IDENTITY_BOUND_KEY])
    reasons = identity_bound_refusals(storage, encryptor)
    if bound is None:
        reasons.append("it is not a well-formed {code, code_id, generation} field")
    if reasons:
        log.error(
            "episodic memory: an identity-bound code was not stored: %s", "; ".join(reasons)
        )
        return out
    out[LATENT_DERIVED_KEY] = {IDENTITY_BOUND_KEY: bound}
    return out
