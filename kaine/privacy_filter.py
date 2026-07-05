# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Shared content-stripping privacy filter primitive.

This is a low-level primitive (like ``AsyncJsonlSink``): it depends only on
``kaine.bus.schema`` and is imported by both the Nexus diagnostics layer
(``kaine.nexus.privacy`` re-exports it for backward compatibility) and the
evaluation sidecar (``kaine.evaluation.observers.research_event_observer``).

Living here rather than under ``kaine/nexus/`` keeps the evaluation package
from depending on the Nexus layer — preserving the one-directional sidecar
boundary while letting both layers share the exact same ``CONTENT_FIELDS``
definition and scrub logic.
"""
from __future__ import annotations

import copy
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
#      (per-module-pair PLV floats, nexus.js) and `payload.state.valence/arousal`
#      (console.html). A key-name allowlist would blank the coherence chart and
#      the presence visualizer.
#   2. The recursion below is LOAD-BEARING: `workspace.broadcast` embeds entire
#      downstream module payloads under `selected_events[].payload`, and the
#      recursive scrub is what strips content nested there. A top-level allowlist
#      that passed container keys through intact would reopen that nested surface.
# So this surface keeps the recursive denylist (safe against nested content at
# any depth), and the "novel content key" gap is closed two ways instead:
#   - genuinely content-bearing keys the audit found leaking are added below
#     (`description`, `statement`), matching how the research taxonomy and the
#     eval nexus tab already treat them as content; and
#   - a CI guard (tests/test_nexus_privacy.py::test_no_uncovered_content_key_in_
#     module_publishers) scans every module `publish()` payload and fails when a
#     new content-capable key is introduced without being added here.
# `agent_label` is deliberately NOT here: the research taxonomy keeps it as an
# operational familiarity label (metrics), so it is not entity-interior content.
# ---------------------------------------------------------------------------
CONTENT_FIELDS: frozenset[str] = frozenset(
    {
        "text",
        "body",
        "content",
        "internal_speech",
        "belief_text",
        "memory_text",
        "affect_reason",
        # Retired field removed: Nous no longer emits the pre-pymdp-swap field.
        "transcription",
        # Lingua's external-speech events carry these for the A/B evaluation
        # observers (raw bus access). They are content — the triggering user
        # utterance and the rendered conscious-workspace block — so they must be
        # scrubbed from the diagnostics surface.
        "user_input",
        "faithful_rendering",
        # Thymos goal events carry a free-text goal `description`; Nous belief
        # events carry a free-text `statement` (the dominant latent-factor label).
        # Both are entity-interior content — the research taxonomy and the eval
        # nexus tab already exclude/drop them — so they must not reach diagnostics.
        "description",
        "statement",
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
    they know they're seeing privileged data.
    """

    dev_content_override: bool = False
    extra_content_fields: frozenset[str] = field(default_factory=frozenset)

    def fields(self) -> frozenset[str]:
        return CONTENT_FIELDS | self.extra_content_fields

    def filter_for_diagnostics(self, event: Event) -> Event:
        if self.dev_content_override:
            return event
        scrubbed_payload = _scrub(event.payload, self.fields())
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


def _scrub(value: Any, fields: Iterable[str]) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if k in fields:
                continue
            out[k] = _scrub(v, fields)
        return out
    if isinstance(value, list):
        return [_scrub(item, fields) for item in value]
    return copy.deepcopy(value)
