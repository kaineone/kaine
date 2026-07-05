# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

from kaine.bus.schema import Event
from kaine.nexus.privacy import CONTENT_FIELDS, PrivacyFilter


def _event(payload):
    return Event(
        source="lingua",
        type="external_speech",
        payload=payload,
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


def test_no_unfiltered_surface_strips_content():
    # There is no unfiltered surface anymore: any surface content-strips.
    pf = PrivacyFilter()
    evt = _event({"text": "hi", "salience_hint": 0.9})
    out = pf.filter(evt, surface="conversation")
    assert "text" not in out.payload
    assert out.payload == {"salience_hint": 0.9}


def test_diagnostics_strips_text():
    pf = PrivacyFilter()
    evt = _event({"text": "secret", "salience_hint": 0.8})
    out = pf.filter(evt, surface="diagnostics")
    assert "text" not in out.payload
    assert out.payload == {"salience_hint": 0.8}


def test_diagnostics_strips_all_content_fields():
    pf = PrivacyFilter()
    payload = {field: f"value-{field}" for field in CONTENT_FIELDS}
    payload["metric"] = 42
    out = pf.filter(_event(payload), surface="diagnostics")
    assert out.payload == {"metric": 42}


def test_diagnostics_strips_nested_content():
    pf = PrivacyFilter()
    evt = _event({"metadata": {"text": "leak", "level": "info"}, "metric": 1})
    out = pf.filter(evt, surface="diagnostics")
    assert out.payload == {"metadata": {"level": "info"}, "metric": 1}


def test_diagnostics_strips_nested_in_lists():
    pf = PrivacyFilter()
    evt = _event({"items": [{"text": "leak", "x": 1}, {"text": "also", "y": 2}]})
    out = pf.filter(evt, surface="diagnostics")
    assert out.payload == {"items": [{"x": 1}, {"y": 2}]}


def test_dev_override_lets_content_through():
    pf = PrivacyFilter(dev_content_override=True)
    evt = _event({"text": "still visible"})
    out = pf.filter(evt, surface="diagnostics")
    assert out.payload == {"text": "still visible"}


def test_extra_content_fields_also_stripped():
    pf = PrivacyFilter(extra_content_fields=frozenset({"custom"}))
    evt = _event({"custom": "leak", "metric": 1})
    out = pf.filter(evt, surface="diagnostics")
    assert out.payload == {"metric": 1}


def test_any_surface_strips_content():
    # No surface is unfiltered: an unrecognised surface name still content-strips
    # rather than leaking (and rather than raising).
    out = PrivacyFilter().filter(_event({"text": "hi", "metric": 1}), surface="other")
    assert "text" not in out.payload
    assert out.payload == {"metric": 1}


def test_filter_defaults_to_diagnostics_strip():
    # The surface kwarg defaults to the content-stripping diagnostics policy.
    out = PrivacyFilter().filter(_event({"text": "hi", "metric": 1}))
    assert "text" not in out.payload
    assert out.payload == {"metric": 1}


def test_filter_does_not_mutate_input():
    pf = PrivacyFilter()
    original_payload = {"text": "hi", "metric": 1}
    evt = _event(original_payload)
    pf.filter(evt, surface="diagnostics")
    assert original_payload == {"text": "hi", "metric": 1}


def test_description_and_statement_are_content_fields():
    """Thymos goal `description` and Nous belief `statement` are free-text
    entity-interior content — the audit found them leaking through the old
    denylist. Both must now be scrubbed from the diagnostics surface."""
    from kaine.nexus.privacy import CONTENT_FIELDS

    assert "description" in CONTENT_FIELDS
    assert "statement" in CONTENT_FIELDS


def test_novel_thymos_goal_description_is_scrubbed_at_top_level_and_nested():
    """A thymos.goal-shaped event's `description` is stripped whether it sits at
    the payload top level, nested in a dict, or embedded in a list (the recursion
    that also protects workspace.broadcast's embedded payloads)."""
    pf = PrivacyFilter()
    evt = _event(
        {
            "description": "buy milk and reflect on mortality",
            "goal_id": "g-1",
            "metadata": {"description": "nested secret", "coherence": {"a|b": 0.4}},
            "selected": [{"statement": "I believe X", "kind": "belief"}],
        }
    )
    out = pf.filter(evt, surface="diagnostics")
    assert "description" not in out.payload
    assert out.payload["goal_id"] == "g-1"
    # Nested content is scrubbed but the dynamic operational coherence dict stays.
    assert "description" not in out.payload["metadata"]
    assert out.payload["metadata"]["coherence"] == {"a|b": 0.4}
    # Content embedded in a list entry (workspace-broadcast shape) is scrubbed.
    assert out.payload["selected"] == [{"kind": "belief"}]


# ---------------------------------------------------------------------------
# CI guard (harden-security-boundaries task 3, "minimum"): the diagnostics
# surface keeps the recursive content denylist (see the decision comment in
# kaine/privacy_filter.py). This guard scans every module `publish()` payload
# and FAILS when a new content-capable payload key is introduced without being
# either scrubbed (added to CONTENT_FIELDS) or explicitly reviewed as a safe
# operational field below — closing the "novel content key silently leaks" gap.
# ---------------------------------------------------------------------------

# Content-suggesting substrings in a payload key NAME. A key whose name contains
# one of these is treated as content-capable and must be classified.
_CONTENT_SUSPECT_TOKENS = (
    "text", "body", "content", "speech", "utter", "statement", "descript",
    "transcrip", "message", "render", "caption", "prompt", "narrat", "reason",
    "rational", "summary", "label", "note", "comment", "title", "name", "word",
    "phrase", "sentence", "quote", "excerpt", "detail",
)

# Reviewed content-suspect payload keys that are genuinely OPERATIONAL (numbers,
# ids, enums, short source/region labels, exception strings) and are safe on the
# diagnostics surface — several are consumer-read by the dashboard. Adding a key
# here is a deliberate, reviewed decision that it carries no entity-interior
# content. (agent_label: research taxonomy keeps it as a familiarity metric.)
_REVIEWED_OPERATIONAL_KEYS = frozenset(
    {
        "agent_label",     # empatheia: modeled-agent familiarity label (metric)
        "error_detail",    # mnemos: exception detail string
        "error_reason",    # nous: exception reason string
        "reason",          # hypnos/phantasia/perception/preservation: short reason enum (consumer-read)
        "source_label",    # audition: perception source name (e.g. "microphone")
        "temporal_context",  # chronos: numeric hidden-state vector (list[float])
    }
)


def _published_payload_keys() -> dict[str, str]:
    """AST-scan every ``<module>.publish(type, {..})`` / ``payload={..}`` inline
    dict literal under kaine/modules and kaine/cycle; return key -> first site.

    SOUNDNESS LIMIT (do not over-trust this guard as exhaustive): it only sees
    payloads written as an inline dict LITERAL at the publish() call site. A
    payload built via a local variable, ``dict(...)``, comprehension, or
    ``**spread`` is invisible to the scanner, so a content key smuggled in that
    way would NOT trip this test. This is only an early-warning guard for the
    common case — runtime ``PrivacyFilter._scrub`` still strips CONTENT_FIELDS
    from every event at every depth regardless of how the payload was built, so
    a miss here weakens the warning, not the actual privacy boundary."""
    import ast
    from pathlib import Path

    roots = [
        Path(__file__).resolve().parents[1] / "kaine" / "modules",
        Path(__file__).resolve().parents[1] / "kaine" / "cycle",
    ]

    def dict_keys(node: ast.AST) -> list[str]:
        out: list[str] = []
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    out.append(k.value)
        return out

    found: dict[str, str] = {}
    for root in roots:
        for f in root.rglob("*.py"):
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("publish", "publish_workspace")
                ):
                    payload = node.args[1] if len(node.args) >= 2 else None
                    for kw in node.keywords:
                        if kw.arg == "payload":
                            payload = kw.value
                    if payload is not None:
                        for key in dict_keys(payload):
                            found.setdefault(key, f"{f}:{node.lineno}")
    return found


def test_no_uncovered_content_key_in_module_publishers():
    """No module publishes a content-capable payload key that is neither scrubbed
    (CONTENT_FIELDS) nor reviewed-operational. A new content-shaped key trips this
    until a human classifies it — the minimum privacy-regression guard."""
    from kaine.nexus.privacy import CONTENT_FIELDS

    published = _published_payload_keys()
    assert published, "publisher scan found nothing — the scan itself is broken"

    uncovered: dict[str, str] = {}
    for key, site in published.items():
        low = key.lower()
        if not any(tok in low for tok in _CONTENT_SUSPECT_TOKENS):
            continue
        if key in CONTENT_FIELDS or key in _REVIEWED_OPERATIONAL_KEYS:
            continue
        uncovered[key] = site

    assert not uncovered, (
        "content-capable payload key(s) reach diagnostics uncovered — add each to "
        "CONTENT_FIELDS (kaine/privacy_filter.py) if it is entity content, or to "
        "_REVIEWED_OPERATIONAL_KEYS if reviewed safe: "
        + ", ".join(f"{k} ({v})" for k, v in sorted(uncovered.items()))
    )


def test_user_input_and_faithful_rendering_are_content_fields():
    """Lingua's external-speech events carry user_input (the user's utterance)
    and faithful_rendering (the conscious-workspace block) for the eval
    observers; both are content and must be scrubbed from diagnostics."""
    from kaine.nexus.privacy import CONTENT_FIELDS
    assert "user_input" in CONTENT_FIELDS
    assert "faithful_rendering" in CONTENT_FIELDS


# ---------------------------------------------------------------------------
# Batch 3 — the new diagnostics surfaces must never leak entity-interior
# content. The preservation panel reads a durable incident log and crossing
# bus events; both are filtered to an EXACT non-content allowlist.
# ---------------------------------------------------------------------------


def test_preservation_block_drops_all_content_fields(tmp_path):
    """No CONTENT_FIELD survives the preservation incident-log allowlist, even
    if a future incident record were to carry one."""
    import json

    from kaine.nexus.health import HealthProber
    from kaine.nexus.privacy import CONTENT_FIELDS

    pres_dir = tmp_path / "preservation"
    pres_dir.mkdir()
    record = {
        "monitor": "divergence",
        "transition": "preserved",
        "incident_id": "inc-9",
        "reason": "individuation",
        "preservation_id": "PRES-9",
        "snapshot_id": "snap-9",
    }
    # Seed EVERY known content field into the record.
    for f in CONTENT_FIELDS:
        record[f] = f"leak-{f}"
    (pres_dir / "preservation_divergence-2026-06-15.jsonl").write_text(
        json.dumps(record) + "\n"
    )

    prober = HealthProber(
        modules_enabled={},
        dependencies=[],
        preservation_incident_path=pres_dir,
    )
    block = prober._preservation_block()
    assert block["events"], "expected the seeded record to be read"
    surfaced = block["events"][0]
    for f in CONTENT_FIELDS:
        assert f not in surfaced, f"content field {f!r} leaked into preservation surface"
    # The allowlisted operational fields ARE surfaced.
    assert surfaced["preservation_id"] == "PRES-9"
    assert surfaced["snapshot_id"] == "snap-9"


def test_preservation_allowlist_has_no_content_field():
    """The static allowlist itself must not name any content field."""
    from kaine.nexus.health import HealthProber
    from kaine.nexus.privacy import CONTENT_FIELDS

    allowed = set(HealthProber._PRESERVATION_ALLOWED_FIELDS)
    assert allowed.isdisjoint(CONTENT_FIELDS)


def test_preservation_js_reads_only_allowlisted_payload_fields():
    """The nexus.js preservation handler reads only allowlisted payload keys —
    it must not read any CONTENT_FIELD off the bus event payload."""
    from pathlib import Path

    from kaine.nexus.privacy import CONTENT_FIELDS

    js = (
        Path(__file__).parent.parent
        / "kaine"
        / "nexus"
        / "static"
        / "nexus.js"
    ).read_text()
    # The fromPayload() builder is the only place a preservation payload is read.
    start = js.index("function fromPayload(msg)")
    end = js.index("function init(", start)
    block = js[start:end]
    for f in CONTENT_FIELDS:
        assert f"p.{f}" not in block, f"preservation handler reads content field {f!r}"
