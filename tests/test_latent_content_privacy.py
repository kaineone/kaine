# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Guards for the latent-content privacy rule.

The architecture program mandates: latent-derived content is never logged,
never an episode, and stripped by the privacy filter.  These tests enforce
that rule structurally so that option F's review starts with the constraint
already in place.
"""
from __future__ import annotations

from kaine.privacy_filter import CONTENT_FIELDS, LATENT_CONTENT_FIELDS, VECTOR_FIELDS, PrivacyFilter


def test_latent_fields_stripped_by_privacy_filter():
    """PrivacyFilter.fields() is a superset of LATENT_CONTENT_FIELDS."""
    pf = PrivacyFilter()
    assert LATENT_CONTENT_FIELDS <= pf.fields()


def test_no_latent_field_in_research_taxonomy():
    """No key in LATENT_CONTENT_FIELDS appears in any research-event taxonomy
    entry's kept-keys set.  A latent field added to the taxonomy would leak
    the entity's cognitive content into the research event log."""
    from kaine.evaluation.observers.research_event_observer import _TAXONOMY

    for event_type, allowed_keys in _TAXONOMY.items():
        overlap = LATENT_CONTENT_FIELDS & allowed_keys
        assert not overlap, (
            f"research taxonomy {event_type!r} allows latent content field(s): "
            f"{overlap!r} — remove them from the taxonomy or from LATENT_CONTENT_FIELDS"
        )


def test_no_latent_field_event_type_in_internal_event_types():
    """No event type whose payload schema includes a LATENT_CONTENT_FIELDS key
    is in INTERNAL_EVENT_TYPES.

    INTERNAL_EVENT_TYPES gates which event payloads the episodic memory module
    stores.  If a type whose payload carries latent content were added to that
    set, the entity's cognitive interior would be persisted in episodic traces.

    Since LATENT_CONTENT_FIELDS starts empty, this test currently passes
    trivially.  When option F adds fields, it must also declare which event
    types carry them (by adding a ``LATENT_CONTENT_EVENT_TYPES`` set or
    equivalent), and this test will be updated to check the intersection.
    """
    from kaine.faithful.external_input import INTERNAL_EVENT_TYPES

    if not LATENT_CONTENT_FIELDS:
        return

    from kaine.evaluation.observers.research_event_observer import _TAXONOMY

    latent_event_types: set[str] = set()
    for event_type, allowed_keys in _TAXONOMY.items():
        if LATENT_CONTENT_FIELDS & allowed_keys:
            latent_event_types.add(event_type)

    internal_types = {t for _, t in INTERNAL_EVENT_TYPES}
    overlap = latent_event_types & internal_types
    assert not overlap, (
        f"event type(s) with latent content fields are in INTERNAL_EVENT_TYPES: "
        f"{overlap!r} — the episodic memory module would store latent content"
    )


def test_latent_fields_disjoint_from_content_and_vector_fields():
    """LATENT_CONTENT_FIELDS does not duplicate keys already in CONTENT_FIELDS
    or VECTOR_FIELDS.  Overlap would not break the filter (it is a union) but
    would make the separation of concerns misleading."""
    overlap_content = LATENT_CONTENT_FIELDS & CONTENT_FIELDS
    assert not overlap_content, (
        f"LATENT_CONTENT_FIELDS overlaps CONTENT_FIELDS: {overlap_content!r}"
    )
    overlap_vector = LATENT_CONTENT_FIELDS & VECTOR_FIELDS
    assert not overlap_vector, (
        f"LATENT_CONTENT_FIELDS overlaps VECTOR_FIELDS: {overlap_vector!r}"
    )
