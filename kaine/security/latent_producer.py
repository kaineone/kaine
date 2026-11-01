# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The boot check for components that produce latent-derived values.

Latent-derived content may live in working state and in learned weights, and
learned weights persist only encrypted (the latent rule, ``kaine.privacy_filter``).
"Encrypted" holds only if it fails closed: the code defaults of
``[security.state_encryption] enabled`` and of the preservation path's
``require_encryption`` are off, and an operator can turn either off, so a
latent producer checks the effective values itself and refuses to start,
naming every failed condition, unless all of these hold:

- ``kaine.privacy_filter.LATENT_RULE_VERSION`` exists and is at least the
  version the component was reviewed against;
- the installed state encryptor is enabled and its key round-trips a probe;
- ``[preservation].require_encryption`` is explicitly ``true``.

A module declares itself a producer with the class attribute
``produces_latent_derived = True``; the boot runs this check when any enabled
module declares it (``kaine.boot.registry.build_registry``). A component built
outside the module registry (the workspace content code) calls
``check_latent_producer`` itself.
"""

from __future__ import annotations

import importlib
from typing import Any, Mapping, Optional

# The latent-rule version this check was written against.
REQUIRED_LATENT_RULE_VERSION = 1

_PROBE = b"latent-producer-encryption-probe"


class LatentProducerRefused(RuntimeError):
    """A latent producer may not start; the message names every failed condition."""

    def __init__(self, component: str, reasons: list[str]) -> None:
        self.component = component
        self.reasons = list(reasons)
        super().__init__(
            f"refusing to start {component}, a producer of latent-derived values: "
            + "; ".join(self.reasons)
        )


def require_encryption_setting(kaine_config: Mapping[str, Any]) -> Any:
    """The raw ``[preservation].require_encryption`` value (``None`` when absent)."""
    section = kaine_config.get("preservation") or {}
    if not isinstance(section, Mapping):
        return None
    return section.get("require_encryption")


def latent_producer_refusals(
    *,
    require_encryption: Any,
    required_rule_version: int = REQUIRED_LATENT_RULE_VERSION,
    encryptor: Optional[Any] = None,
) -> list[str]:
    """Every condition a latent producer needs that does not hold, as reasons."""
    reasons: list[str] = []

    privacy_filter = importlib.import_module("kaine.privacy_filter")
    version = getattr(privacy_filter, "LATENT_RULE_VERSION", None)
    if isinstance(version, bool) or not isinstance(version, int):
        reasons.append(
            "the latent rule is missing (kaine.privacy_filter.LATENT_RULE_VERSION)"
        )
    elif version < required_rule_version:
        reasons.append(
            f"the latent rule is version {version}, below the required "
            f"{required_rule_version} (kaine.privacy_filter.LATENT_RULE_VERSION)"
        )

    if encryptor is None:
        from kaine.security.crypto import get_state_encryptor

        encryptor = get_state_encryptor()
    if not getattr(encryptor, "enabled", False):
        reasons.append(
            "state encryption is not in effect ([security.state_encryption] enabled "
            "with a resolvable key)"
        )
    else:
        try:
            ok = encryptor.decrypt(encryptor.encrypt(_PROBE)) == _PROBE
        except Exception as exc:
            ok = False
            detail = type(exc).__name__
        else:
            detail = "the round trip changed the probe"
        if not ok:
            reasons.append(
                f"state encryption is enabled but its key does not round-trip ({detail})"
            )

    if require_encryption is not True:
        reasons.append(
            "[preservation].require_encryption is not true "
            f"(it is {require_encryption!r})"
        )
    return reasons


def check_latent_producer(
    component: str,
    *,
    require_encryption: Any,
    required_rule_version: int = REQUIRED_LATENT_RULE_VERSION,
    encryptor: Optional[Any] = None,
) -> None:
    """Raise ``LatentProducerRefused`` unless every condition holds."""
    reasons = latent_producer_refusals(
        require_encryption=require_encryption,
        required_rule_version=required_rule_version,
        encryptor=encryptor,
    )
    if reasons:
        raise LatentProducerRefused(component, reasons)
