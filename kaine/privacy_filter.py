# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Shared content-stripping privacy filter primitive.

This is a low-level primitive (like ``AsyncJsonlSink``): it depends only on
``kaine.bus.schema`` and is imported by both the dashboard diagnostics layer
(``kaine.dashboard.privacy`` re-exports it for backward compatibility) and the
evaluation sidecar (``kaine.evaluation.observers.research_event_observer``).

Living here rather than under ``kaine/dashboard/`` keeps the evaluation package
from depending on the dashboard layer — preserving the one-directional sidecar
boundary while letting both layers share the exact same ``CONTENT_FIELDS``
definition and scrub logic.

The latent rule
---------------
A value is *latent-derived* when it is computed from a perceptual latent (an
encoder output: the vision module's ``latent``, ``peripheral`` and ``foveal``,
the audition module's acoustic embedding) or from another latent-derived value,
and it keeps per-dimension information: a vector in an encoder's latent space or
in any learned space computed from one, or a per-dimension statistic of such
vectors over any window. A content code, a decoder's prediction (an 8-number one
included), a residual vector, a code-space gradient and the mean of the last 16
clip latents are latent-derived. Scalar reductions over all dimensions (a norm,
a distance, a mean squared error, a ratio, an information gain), counts, source
names and tick indices are not. Learned parameters are not values under this
rule: a weight matrix trained on latents is identity and follows the identity
rules (persist, encrypt, copy into forks, never logged).

Latent-derived values travel only inside a mapping under ``LATENT_DERIVED_KEY``
(``"latent_derived"``), at any depth. Perceptual latents keep their own names.
``LATENT_FIELDS`` holds both, and ``strip_latent`` removes them from a record at
any depth regardless of length. Every record writer applies it: the JSONL sink,
the encrypted JSONL writer, the organ's renderers and the module-state captures.
Latent-derived content may live in working state and in learned weights; it is
never logged, never stored as an episode and never written to a record.

A worked example of the closure: once interoception's blend includes a
prediction decoded from a content code, its residual vector is latent-derived
(the input minus a latent-derived prediction, keeping per-dimension
information), so it is published only under the tag. Its per-channel expected
error state is computed from latent-derived values too, but it may stay in
module state because a learning rule updates it and the module reads it back on
restore: it is a learned statistic. Its scalar ``unexpected_error`` is a scalar
reduction and may be published anywhere. To apply the rule, follow a value
back: if any input is latent-derived and the value keeps per-dimension
information, it is latent-derived; then ask whether it is a learned parameter
that the module reads back on restore.
"""
from __future__ import annotations

import copy
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Iterable

from kaine.bus.schema import Event

# ---------------------------------------------------------------------------
# Denylist vs. allowlist — a deliberate, documented choice for THIS surface.
#
# `harden-security-boundaries` task 3 evaluated inverting this content denylist
# into a per-event-type ALLOWLIST for the diagnostics SSE. That inversion is the
# established pattern for the *export-eligible* research surface
# (kaine.evaluation.observers.research_event_observer._TAXONOMY) — but it is NOT
# safe to graft onto the live diagnostics dashboard without a running-entity boot
# to verify against, for two reasons found in the code audit:
#   1. The diagnostics consumers read DYNAMIC nested keys that cannot be
#      enumerated statically — e.g. `payload.metadata.coherence.<pair-label>`
#      (per-module-pair PLV floats, dashboard.js) and `payload.state.valence/arousal`
#      (console.html). A key-name allowlist would blank the coherence chart and
#      the presence visualizer.
#   2. The recursion below is LOAD-BEARING: `workspace.broadcast` embeds entire
#      downstream module payloads under `selected[].payload`, and the recursive
#      scrub is what strips content nested there. A top-level allowlist that
#      passed container keys through intact would reopen that nested surface.
# So this surface keeps the recursive denylist (safe against nested content at
# any depth), and the "novel content key" gap is closed two ways instead:
#   - genuinely content-bearing keys the audit found leaking are added below
#     (`description`, `statement`), matching how the research taxonomy and the
#     eval dashboard tab already treat them as content; and
#   - a CI guard (tests/test_dashboard_privacy.py::test_no_uncovered_content_key_in_
#     module_publishers) scans every module `publish()` payload and fails when a
#     new content-capable key is introduced without being added here.
# `agent_label` is deliberately NOT here: the research taxonomy keeps it as an
# operational familiarity label (metrics), so it is not entity-interior content.
# ---------------------------------------------------------------------------

# The reserved key under which every latent-derived value travels (the latent
# rule in the module docstring). It is a vector field, so the diagnostics filter
# (dev mode included) and ``strip_vectors`` remove it at any length.
LATENT_DERIVED_KEY: str = "latent_derived"

# Perceptual/latent embeddings (vision clip embeddings 768/384-dim; sequence
# CfC hidden state 32-dim and 24-dim feature vector) and the latent-derived tag;
# never displayed by the dashboard; persisting them would break zero
# raw-sense-data persistence.
VECTOR_FIELDS: frozenset[str] = frozenset(
    {
        "latent",
        "peripheral",
        "foveal",
        "temporal_context",
        "feature_vector",
        LATENT_DERIVED_KEY,
    }
)

# The keys every record writer removes (``strip_latent``). The same set as
# ``VECTOR_FIELDS``, exported under its own name so callers say what they mean.
LATENT_FIELDS: frozenset[str] = VECTOR_FIELDS

# The version of the latent rule. A component that produces latent-derived
# values refuses to start when this is missing or lower than the version it was
# reviewed against.
LATENT_RULE_VERSION: int = 1

# Backstop for embeddings published under a name not in VECTOR_FIELDS. 16 sits
# above the longest small numeric list on the diagnostics streams (5-element
# affect appraisal scores, 3-element proprioceptive position) and below the
# shortest embedding (the 24-element sequence feature vector).
VECTOR_BACKSTOP_MIN_LEN: int = 16

# Reviewed non-embedding numeric lists of unbounded length (sleep ignition-audit
# saliences, world model per-step magnitudes); adding a key here is a reviewed
# change with a test.
VECTOR_EXEMPT_KEYS: frozenset[str] = frozenset({"saliences", "step_magnitudes"})

# The self-model module's values and norms are entity-interior text; the language module reads them
# from the raw bus, and no diagnostics consumer does.
CONTENT_FIELDS: frozenset[str] = frozenset(
    {
        "text",
        "body",
        "content",
        "internal_speech",
        "belief_text",
        "memory_text",
        "affect_reason",
        # Retired field removed: the planning module no longer emits the pre-pymdp-swap field.
        "transcription",
        # the language module's external-speech events carry these for the A/B evaluation
        # observers (raw bus access). They are content - the triggering user
        # utterance and the rendered workspace-access block - so they must be
        # scrubbed from the diagnostics surface.
        "user_input",
        "faithful_rendering",
        # The affect module's goal events carry a free-text goal `description`; the planning module's belief
        # events carry a free-text `statement` (the dominant latent-factor label).
        # Both are entity-interior content — the research taxonomy and the eval
        # the dashboard tab already exclude/drop them — so they must not reach diagnostics.
        "description",
        "statement",
        "values",
        "behavioral_norms",
        # The facts the entity is told about its situation are entity-interior text.
        "situation_facts",
    }
)


@dataclass(frozen=True)
class PrivacyFilter:
    """Strips content from events crossing the privacy boundary.

    Every SSE surface is content-stripped (the diagnostics policy): there is
    no unfiltered surface anywhere. The ``surface`` keyword is retained only
    for call-site compatibility — it no longer selects a less-filtered path.
    When ``dev_content_override`` is True, content passes through on the
    diagnostics surface and operators see a "dev mode" banner on the page so
    they know they're seeing privileged data. Vector fields and large numeric
    lists are always stripped, even in dev mode.
    """

    dev_content_override: bool = False
    extra_content_fields: frozenset[str] = field(default_factory=frozenset)

    def fields(self) -> frozenset[str]:
        return CONTENT_FIELDS | self.extra_content_fields

    def filter_for_diagnostics(self, event: Event) -> Event:
        if self.dev_content_override:
            # Content passes, but vectors are still removed.
            scrubbed_payload = _scrub(
                event.payload, frozenset(), vector_fields=VECTOR_FIELDS
            )
        else:
            scrubbed_payload = _scrub(
                event.payload, self.fields(), vector_fields=VECTOR_FIELDS
            )
        return Event(
            source=event.source,
            type=event.type,
            payload=scrubbed_payload,
            salience=event.salience,
            timestamp=event.timestamp,
            causal_parent=event.causal_parent,
        )

    def filter(self, event: Event, *, surface: str = "diagnostics") -> Event:
        # There is no unfiltered surface: every surface is content-stripped via
        # the diagnostics policy. ``surface`` is accepted for call-site
        # compatibility but does not select a less-filtered path.
        return self.filter_for_diagnostics(event)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_numeric_vector(value: Any) -> bool:
    if not isinstance(value, (list, tuple)):
        return False
    if len(value) < VECTOR_BACKSTOP_MIN_LEN:
        return False
    return all(_is_number(item) for item in value)


def _scrub(
    value: Any,
    fields: Iterable[str],
    *,
    vector_fields: Iterable[str] = VECTOR_FIELDS,
) -> Any:
    """Recursively remove content-bearing and vector-bearing keys.

    The vector rule is on by default: a key in ``VECTOR_FIELDS`` is always
    removed, and so is any other dict key whose value is a list/tuple of length
    ``VECTOR_BACKSTOP_MIN_LEN`` or more containing only numbers (excluding
    bools) — this backstop alone exempts the keys in ``VECTOR_EXEMPT_KEYS``. Within lists and
    tuples, any item that is itself a numeric vector is dropped. Content
    keys in ``fields`` are also removed. Tuples that survive come back as
    lists.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if k in vector_fields:
                continue
            if k in fields:
                continue
            if _is_numeric_vector(v) and k not in VECTOR_EXEMPT_KEYS:
                continue
            out[k] = _scrub(v, fields, vector_fields=vector_fields)
        return out

    if isinstance(value, (list, tuple)):
        return [
            _scrub(item, fields, vector_fields=vector_fields)
            for item in value
            if not _is_numeric_vector(item)
        ]

    return copy.deepcopy(value)


def _numpy_array_type() -> type | None:
    # numpy is never imported here: when no caller has imported it, no value
    # can be an ndarray, and the filter stays free of the dependency.
    np = sys.modules.get("numpy")
    return getattr(np, "ndarray", None) if np is not None else None


def strip_latent(value: Any) -> Any:
    """A copy of ``value`` with every key in ``LATENT_FIELDS`` removed at any depth.

    It walks mappings, lists and tuples (tuples stay tuples), removes nothing
    else (no length backstop, no content keys) and converts every numpy array it
    meets to Python numbers with ``tolist()`` before walking it, so an array
    under a latent key is removed with its key and an array under any other key
    is written as exact numbers rather than by numpy's elided ``str()``. Every
    record writer applies it before encoding.
    """
    return _strip_latent(value, _numpy_array_type())


def _strip_latent(value: Any, ndarray: type | None) -> Any:
    if ndarray is not None and isinstance(value, ndarray):
        value = value.tolist()
    if isinstance(value, Mapping):
        return {
            k: _strip_latent(v, ndarray)
            for k, v in value.items()
            if k not in LATENT_FIELDS
        }
    if isinstance(value, list):
        return [_strip_latent(item, ndarray) for item in value]
    if isinstance(value, tuple):
        return tuple(_strip_latent(item, ndarray) for item in value)
    return value


def without_latent_derived(value: Any) -> Any:
    """``value`` with every ``LATENT_DERIVED_KEY`` mapping removed at any depth.

    Copy on write: when no mapping at any depth holds the key, the very same
    object is returned, so a payload with no latent-derived value passes
    unchanged. Only the containers on the path to a removed key are rebuilt
    (tuples stay tuples). The perceptual latents are left in place; this is the
    narrower strip for a payload that still travels on the bus.
    """
    return _without_keys(value, _LATENT_DERIVED_ONLY)


def without_latent_fields(value: Any) -> Any:
    """``value`` with every key in ``LATENT_FIELDS`` removed at any depth, copy
    on write like ``without_latent_derived``: when no mapping holds such a key
    the very same object is returned, and nothing else (numpy arrays included)
    is converted. This is the strip for module states, whose learned
    parameters must come back exactly as they went in."""
    return _without_keys(value, LATENT_FIELDS)


_LATENT_DERIVED_ONLY: frozenset[str] = frozenset({LATENT_DERIVED_KEY})


def _without_keys(value: Any, keys: frozenset[str]) -> Any:
    if isinstance(value, Mapping):
        changed = False
        out: dict[Any, Any] = {}
        for k, v in value.items():
            if k in keys:
                changed = True
                continue
            nv = _without_keys(v, keys)
            changed = changed or nv is not v
            out[k] = nv
        return out if changed else value
    if isinstance(value, (list, tuple)):
        items = [_without_keys(item, keys) for item in value]
        if all(a is b for a, b in zip(items, value)):
            return value
        return items if isinstance(value, list) else tuple(items)
    return value


def holds_latent_field(value: Any) -> bool:
    """True when a mapping at any depth of ``value`` (inside lists, tuples and
    object arrays included) holds a key in ``LATENT_FIELDS``."""
    return _holds_latent_field(value, _numpy_array_type())


def _holds_latent_field(value: Any, ndarray: type | None) -> bool:
    if isinstance(value, Mapping):
        return any(
            k in LATENT_FIELDS or _holds_latent_field(v, ndarray)
            for k, v in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_holds_latent_field(item, ndarray) for item in value)
    if ndarray is not None and isinstance(value, ndarray):
        # Only an object array can hold a mapping; a numeric array is a leaf.
        if value.dtype == object:
            return _holds_latent_field(value.tolist(), ndarray)
    return False


def strip_vectors(payload: Any) -> Any:
    """Strip vector fields and long numeric lists from *payload*.

    This is the one vector rule shared by the diagnostics surface and the episodic memory module
    memory text: it removes every named vector field (``VECTOR_FIELDS``) and
    any numeric list of ``VECTOR_BACKSTOP_MIN_LEN`` or more items, but keeps
    all content keys intact.
    """
    return _scrub(payload, frozenset(), vector_fields=VECTOR_FIELDS)
