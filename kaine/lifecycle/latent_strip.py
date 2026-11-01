# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The latent strip for module-state captures.

A module's serialized state holds no latent-derived value except learned
parameters that the module reads back on restore (the latent rule,
``kaine.privacy_filter``). Every capture of module states (the fork snapshot,
the preservation capture and the rolling resume checkpoint) passes its states
through ``strip_module_states``: a state that holds a key in ``LATENT_FIELDS``
at any depth loses it, the capture's metadata names the module under
``LATENT_STRIPPED_KEY`` and an error is logged.

The strip never refuses a capture. Refusing would block the welfare net's
preservation of an entity in distress over a privacy defect, and the entity's
preservation is the higher duty. A state the scan cannot walk is kept as it is,
named under ``LATENT_SCAN_FAILED_KEY`` and logged. The log names modules only,
never a value.

The strip is copy on write: a state with no latent field is the very same
object afterwards, so learned weights (lists of numbers under keys such as
``layers``) come back exactly as they went in.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from kaine.privacy_filter import without_latent_fields

log = logging.getLogger(__name__)

# Capture metadata key naming the modules whose state held a latent field.
LATENT_STRIPPED_KEY = "latent_stripped"
# Capture metadata key naming the modules whose state could not be scanned.
LATENT_SCAN_FAILED_KEY = "latent_scan_failed"


def strip_module_states(
    modules: Mapping[str, Any], *, capture: str
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Return ``(states, metadata)``: the module states without latent fields,
    and the metadata entries to merge into the capture's metadata (empty when
    every state was clean). ``capture`` names the capture in the log."""
    out: dict[str, Any] = {}
    stripped: list[str] = []
    unscanned: list[str] = []
    for name, state in modules.items():
        try:
            clean = without_latent_fields(state)
        except Exception as exc:
            # Never refuse the capture; keep the state and say so.
            log.error(
                "%s: the state of module %s could not be scanned for latent fields "
                "(%s); it is kept as serialized",
                capture,
                name,
                type(exc).__name__,
            )
            unscanned.append(name)
            out[name] = state
            continue
        if clean is not state:
            stripped.append(name)
        out[name] = clean
    metadata: dict[str, list[str]] = {}
    if stripped:
        metadata[LATENT_STRIPPED_KEY] = sorted(stripped)
        log.error(
            "%s: removed latent fields from the state of %s; a module state may "
            "hold no latent value other than learned parameters (the latent rule, "
            "kaine.privacy_filter)",
            capture,
            ", ".join(sorted(stripped)),
        )
    if unscanned:
        metadata[LATENT_SCAN_FAILED_KEY] = sorted(unscanned)
    return out, metadata
