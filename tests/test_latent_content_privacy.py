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


# ---------------------------------------------------------------------------
# The latent rule (change latent-content-privacy, PR G2-1): one tag, one strip.
# Ported from build/operator-speech (6f4ce3c86, aac6047e5).
# ---------------------------------------------------------------------------

from datetime import datetime, timezone  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from kaine.bus.schema import Event  # noqa: E402
from kaine.privacy_filter import (  # noqa: E402
    LATENT_DERIVED_KEY,
    LATENT_FIELDS,
    LATENT_RULE_VERSION,
    holds_latent_field,
    strip_latent,
    strip_vectors,
    without_latent_derived,
)

# Recognisable latent numbers: none of them is a round value any other field uses.
CODE = [0.123457, -0.654321, 0.271828, 0.314159, -0.161803, 0.577215, 0.693147, -0.207879]
ASCENDING = [0.918273, -0.465564, 0.112358]
LATENT = [0.836541, -0.729183, 0.401234, 0.555123]


def _ev(source: str, type_: str, payload: dict, salience: float = 0.5) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=salience,
        timestamp=datetime(2026, 10, 31, tzinfo=timezone.utc),
        causal_parent=None,
    )



def test_tag_is_a_vector_and_latent_field():
    assert LATENT_DERIVED_KEY == "latent_derived"
    assert "latent_derived" in VECTOR_FIELDS
    assert "latent_derived" in LATENT_FIELDS
    assert LATENT_FIELDS == VECTOR_FIELDS
    assert LATENT_RULE_VERSION == 1


def test_strip_latent_spec_example():
    record = {
        "workspace_feedback": {"gain": 1.1, "latent_derived": {"code": [0.2, 0.4]}},
        "latent": [0.1, 0.3],
    }
    assert strip_latent(record) == {"workspace_feedback": {"gain": 1.1}}


def test_strip_latent_nested_lists_tuples_arrays():
    record = {
        "members": [
            {"source": "vision", "latent": np.asarray(LATENT), "change": 0.2},
            ({"latent_derived": {"code": CODE}, "kept": 1},),
        ],
        "array_of_maps": np.asarray([{"foveal": [0.5, 0.6], "x": 2}], dtype=object),
        "deep": {"a": {"b": {"latent_derived": {"err": np.asarray(ASCENDING)}}}},
        "peripheral": [0.9] * 3,
        "temporal_context": [0.1, 0.2],
        "feature_vector": (0.3, 0.4),
    }
    out = strip_latent(record)
    assert out == {
        "members": [
            {"source": "vision", "change": 0.2},
            ({"kept": 1},),
        ],
        "array_of_maps": [{"x": 2}],
        "deep": {"a": {"b": {}}},
    }
    # Tuples stay tuples; the input is untouched.
    assert isinstance(out["members"][1], tuple)
    assert "latent" in record["members"][0]
    assert not holds_latent_field(out)
    assert holds_latent_field(record)
    assert holds_latent_field({"x": [({"y": {"latent_derived": {}}},)]})
    assert holds_latent_field({"x": np.asarray([{"latent": [1.0]}], dtype=object)})
    assert not holds_latent_field({"x": np.zeros(4), "y": [1, 2], "z": "latent"})


def test_strip_latent_keeps_long_reviewed_lists():
    record = {
        "saliences": [0.01 * i for i in range(40)],
        "step_magnitudes": list(range(64)),
        "scores": [0.1, 0.2, 0.3, 0.4, 0.5],
        "table": [[1.0, 2.0]] * 30,
        "text": "content keys are not this strip's business",
    }
    assert strip_latent(record) == record


def test_strip_latent_converts_an_unreviewed_array_to_exact_numbers():
    values = np.asarray([0.1234567891234, -2.5, 3.0e-9, 7.0, 1.0 / 3.0, 2.0, 5.5, 8.25])
    out = strip_latent({"scores": values})
    assert isinstance(out["scores"], list)
    assert out["scores"] == values.tolist()
    assert all(type(v) is float for v in out["scores"])


def test_without_latent_derived_is_copy_on_write():
    payload = {"change_score": 0.1, "latent": [0.2, 0.3], "nested": [{"a": (1, 2)}]}
    assert without_latent_derived(payload) is payload
    tagged = {"change_score": 0.1, "latent": [0.2], "nested": [{"latent_derived": {"c": CODE}, "a": 1}]}
    out = without_latent_derived(tagged)
    assert out == {"change_score": 0.1, "latent": [0.2], "nested": [{"a": 1}]}
    assert out["latent"] is tagged["latent"]
    assert "latent_derived" in tagged["nested"][0]


# ---------------------------------------------------------------------------
# The diagnostics filter and the episodic store's strip_vectors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dev_mode", [False, True])
def test_diagnostics_filter_removes_latent_derived_in_dev_mode(dev_mode):
    event = _ev(
        "cycle",
        "workspace.broadcast",
        {"metadata": {"workspace_feedback": {"gain": 1.0, "latent_derived": {"code": CODE}}}},
    )
    filtered = PrivacyFilter(dev_content_override=dev_mode).filter(event)
    assert filtered.payload == {"metadata": {"workspace_feedback": {"gain": 1.0}}}
    assert strip_vectors({"latent_derived": {"code": CODE[:2]}, "k": 1}) == {"k": 1}




def test_without_latent_derived_walks_object_arrays():
    np = pytest.importorskip("numpy")
    from kaine.privacy_filter import without_latent_derived

    arr = np.empty(1, dtype=object)
    arr[0] = {"latent_derived": {"code": [0.1, 0.2]}, "n": 1}
    out = without_latent_derived({"x": arr})
    assert out == {"x": [{"n": 1}]}
    numeric = np.asarray([0.1, 0.2])
    payload = {"x": numeric}
    assert without_latent_derived(payload) is payload
