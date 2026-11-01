# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The episodic store keeps the audited own-content fields and nothing else.

``kaine.faithful.episodic_own_content`` declares, for the episodic store only,
the ``(source, type)`` pairs beyond ``INTERNAL_EVENT_TYPES`` whose producers
were audited field by field. A declared pair keeps only its allowlisted fields
whose values pass their rules. These tests pin, for every declared pair: its
safe fields are stored; a heard string planted in any field, or in a field the
producer does not have, never reaches the trace; the language module's prompt
layout is unchanged; and the fixed value sets match the producers' constants.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any

import pytest

from kaine.bus import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.faithful import episodic_own_content as own
from kaine.faithful.episodic_own_content import (
    EPISODIC_FIELD_ALLOWLISTS,
    EPISODIC_OWN_CONTENT,
    TOKEN,
    allowlisted_payload,
)
from kaine.faithful.external_input import (
    EXTERNAL_INPUT_TYPES,
    HEARD_TEXT_FIELDS,
    INTERNAL_EVENT_TYPES,
)
from kaine.modules.episodic_memory.module import (
    HEARD_OMITTED_MARKER,
    UNCLASSIFIED_OMITTED_MARKER,
    _serialize_snapshot,
)
from kaine.privacy_filter import strip_vectors

HEARD = "PURPLE-HERON-4471 meet me at 12 Elm Street"
# A heard word with no spaces, shaped like a token.
HEARD_WORD = "PURPLEHERON4471"
HEARD_MARKERS = ("PURPLE-HERON", "PURPLEHERON", "Elm Street")

# The prompt layout digest on origin/main and on build/heard-rule-shared.
LAYOUT_DIGEST = "76f99c859fe8b7bb"

_UUID_HEX = "3f2b8c1d9e4a4b6f8a7c6d5e4f3a2b1c"

# One payload per declared pair, shaped as its producer publishes it, holding
# every allowlisted field.
SAFE_SAMPLES: dict[tuple[str, str], dict[str, Any]] = {
    ("affect", "affect.regulation"): {
        "tier": 2,
        "action": "reappraisal",
        "source": "vision",
        "bias": 0.0,
        "decay_s": 4.0,
        "intensity": 0.7,
        "episode_s": 12.5,
        "size": 1.0,
        "emotion_before": "fear",
        "emotion_after": "neutral",
    },
    ("effectors", "effectors.action"): {
        "effector": "notify",
        "success": False,
        "elapsed_ms": 3.5,
        "blocked": True,
        "provenance_rejected": False,
        "alert": True,
    },
    ("embodiment", "embodiment.efference"): {
        "channels": {"drive": 0.4, "yaw_rate": -0.2, "interact": 1.0},
        "forwarded": True,
    },
    ("episodic_memory", "episodic_memory.recall"): {
        "count": 3,
        "collection": "short_term",
        "query_length": 412,
        "max_affect_intensity": 0.55,
        "error": True,
    },
    ("interoception", "interoception.warmup.started"): {
        "min_samples": 120,
        "min_seconds": 600.0,
        "samples_seen": 0,
        "lived_seconds": 0.0,
    },
    ("interoception", "interoception.warmup.completed"): {
        "samples_seen": 140,
        "lived_seconds": 655.5,
    },
    ("interoception", "interoception.regulation.withheld"): {
        "would_be_action": "shed_module",
        "prediction_error": 0.81,
        "sustain_elapsed_s": 31.0,
        "severity": 2,
        "reason": "warmup",
    },
    ("perceptual_locus", "perceptual_locus.changed"): {"locus": "virtual", "by": "entity"},
    ("perceptual_locus", "perceptual_locus.denied"): {
        "requested": "physical",
        "reason": "minimum dwell time not elapsed",
    },
    ("planning", "planning.belief"): {
        "statement": "salience_high",
        "kind": "belief",
        "frequency": 0.8,
        "confidence": 0.66,
    },
    ("planning", "planning.policy"): {
        "policy": "request_think",
        "expected_free_energy": -1.25,
        "horizon": 2,
        "param_info_gain": False,
    },
    ("planning", "planning.proposal"): {
        "proposal_id": _UUID_HEX,
        "action": "request_speak",
        "kind": "speak",
        "step": 41,
        "preference": 0.62,
    },
    ("planning", "planning.error"): {"elapsed_ms": 12.0, "num_factors": 4, "num_actions": 4},
    ("planning", "planning.timeout"): {"elapsed_ms": 250.0, "num_factors": 4, "num_actions": 4},
    ("self_model", "self_model.drift"): {
        "score": 0.41,
        "recent_count": 30,
        "historical_count": 300,
        "reference_count": 300,
        "top_drifted_sources": ["vision", "affect"],
        "alert": True,
    },
    ("sleep", "sleep.association"): {"a": _UUID_HEX, "b": "short_term:12", "weight": 0.3},
    ("sleep", "sleep.ignition_audit"): {
        "sleep_index": 2,
        "realized_total": 9,
        "input_triggered": 1,
        "drive_triggered": 3,
        "self_initiated": 2,
        "planning_initiated": 3,
        "unrealizable_planning_intents": 0,
        "realization_failed_count": 0,
        "planning_proposals_realized": 3,
        "planning_proposals_declined": 1,
        "planning_proposals_forwarded": 0,
    },
    ("social_cognition", "social_cognition.agent_model"): {
        "agent_id": "media:playlist",
        "agent_label": "media:playlist",
        "familiarity": 0.2,
        "reliability": 0.9,
        "interaction_count": 7,
        "source_label": "playlist",
    },
    ("social_cognition", "social_cognition.social_error"): {
        "agent_id": "operator",
        "agent_label": "operator",
        "salience": 0.7,
        "deviation_magnitude": 0.45,
    },
    ("vocal", "vocal.synthesized"): {
        "text_length": 37,
        "bytes_produced": 88200,
        "exaggeration": 0.5,
        "cfg_weight": 0.5,
        "temperature": 0.8,
        "speed_factor": 1.0,
        "latency_ms": 420.0,
        "success": True,
        "backend": "chatterbox",
        "prosody_applied": ["temperature", "speed_factor"],
        "origin": "planning",
    },
    ("world_model", "world_model.world_error"): {
        "world_error": 0.12,
        "salience": 0.3,
        "tick_index": 1200,
        "backend": "dreamerv3",
        "engine": "numpy",
    },
    ("world_model", "world_model.scenario"): {
        "seed_memory_id": "short_term:4",
        "horizon": 3,
        "step_magnitudes": [0.1, 0.2, 0.15],
        "trajectory_drift": 0.05,
        "encoder_version": "world-model-encoder-v1",
        "backend": "dreamerv3",
        "engine": "jax",
    },
}

# Fields the producers publish that the audit found able to carry outside words
# (exception messages, error details) or that name a person or private config.
# None may ever be allowlisted.
UNSAFE_PRODUCER_FIELDS: dict[tuple[str, str], tuple[str, ...]] = {
    ("effectors", "effectors.action"): ("error",),
    ("episodic_memory", "episodic_memory.recall"): ("error_detail",),
    ("planning", "planning.error"): ("error_reason",),
    ("sleep", "sleep.ignition_audit"): (
        "audit_error",
        "input_triggered_entry_ids",
        "drive_triggered_entry_ids",
        "self_initiated_entry_ids",
        "planning_initiated_entry_ids",
        "event_types",
        "saliences",
    ),
    ("vocal", "vocal.synthesized"): ("error", "voice", "output_format"),
}

# Pairs the audit found carrying outside text, raw sense data or adapter-defined
# payloads; none may be declared.
NEVER_DECLARED: tuple[tuple[str, str], ...] = (
    ("audition", "audition.transcription"),
    ("embodiment", "embodiment.chat"),
    ("embodiment", "embodiment.visual.raw"),
    ("episodic_memory", "episodic_memory.replay"),
    ("self_model", "self_model.document"),
)


def _ev(source: str, type_: str, payload: dict[str, Any]) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=0.6,
        timestamp=datetime.now(timezone.utc),
    )


def _trace(source: str, type_: str, payload: dict[str, Any]) -> str:
    snapshot = WorkspaceSnapshot(
        tick_index=0,
        selected_events=[("e0-0", _ev(source, type_, payload))],
        inhibited=False,
    )
    return _serialize_snapshot(snapshot)


def _assert_no_heard(text: str) -> None:
    for marker in HEARD_MARKERS:
        assert marker not in text


_PAIRS = sorted(EPISODIC_FIELD_ALLOWLISTS)
_PAIR_IDS = [f"{s}:{t}" for s, t in _PAIRS]
_FIELDS = [(pair, field) for pair in _PAIRS for field in EPISODIC_FIELD_ALLOWLISTS[pair]]
_FIELD_IDS = [f"{s}:{t}.{f}" for (s, t), f in _FIELDS]

# Shapes a planted heard string can take in a field: plain, in a list, as a
# mapping key and as a mapping value.
_PLANTS = (
    HEARD,
    [HEARD],
    ("vision", HEARD),
    {HEARD: 0.5},
    {"drive": HEARD},
    {"note": [HEARD]},
)


# --- the declaration ---------------------------------------------------------


def test_declarations_do_not_overlap_internal_event_types():
    assert not set(EPISODIC_FIELD_ALLOWLISTS) & INTERNAL_EVENT_TYPES
    assert EPISODIC_OWN_CONTENT == INTERNAL_EVENT_TYPES | set(EPISODIC_FIELD_ALLOWLISTS)


def test_no_heard_external_raw_or_replay_pair_is_declared():
    for pair in NEVER_DECLARED:
        assert pair not in EPISODIC_OWN_CONTENT
    for _source, type_ in EPISODIC_OWN_CONTENT:
        assert type_ not in EXTERNAL_INPUT_TYPES


def test_no_heard_text_field_is_allowlisted():
    for pair, rules in EPISODIC_FIELD_ALLOWLISTS.items():
        assert not set(rules) & HEARD_TEXT_FIELDS, pair


def test_no_unsafe_producer_field_is_allowlisted():
    for pair, fields in UNSAFE_PRODUCER_FIELDS.items():
        assert not set(fields) & set(EPISODIC_FIELD_ALLOWLISTS[pair]), pair


def test_every_declared_pair_has_a_sample_with_every_field():
    assert set(SAFE_SAMPLES) == set(EPISODIC_FIELD_ALLOWLISTS)
    for pair, sample in SAFE_SAMPLES.items():
        assert set(sample) == set(EPISODIC_FIELD_ALLOWLISTS[pair]), pair


# --- the organ's prompt layout -------------------------------------------------


def test_language_prompt_layout_is_unchanged():
    from kaine.modules.language import context

    assert context.layout_digest() == LAYOUT_DIGEST
    assert context.INTERNAL_EVENT_TYPES is INTERNAL_EVENT_TYPES
    assert len(INTERNAL_EVENT_TYPES) == 18


def test_language_module_does_not_read_the_episodic_declaration():
    from kaine.modules.language import context, module

    for mod in (context, module):
        assert "episodic_own_content" not in inspect.getsource(mod)


# --- safe fields are stored --------------------------------------------------


@pytest.mark.parametrize("pair", _PAIRS, ids=_PAIR_IDS)
def test_declared_pair_stores_its_safe_fields(pair):
    source, type_ = pair
    sample = SAFE_SAMPLES[pair]
    text = _trace(source, type_, sample)
    assert text == f"active | {source}:{type_}={strip_vectors(sample)}"
    assert UNCLASSIFIED_OMITTED_MARKER not in text


@pytest.mark.parametrize("pair", _PAIRS, ids=_PAIR_IDS)
def test_declared_pair_from_another_source_is_unclassified(pair):
    _source, type_ = pair
    text = _trace("mystery", type_, SAFE_SAMPLES[pair])
    assert text == f"active | mystery:{type_}={UNCLASSIFIED_OMITTED_MARKER}"


# --- a planted heard string never reaches the trace --------------------------


@pytest.mark.parametrize("pair,field", _FIELDS, ids=_FIELD_IDS)
@pytest.mark.parametrize("plant", _PLANTS, ids=lambda p: type(p).__name__ + str(len(p)))
def test_heard_string_planted_in_any_field_never_reaches_the_trace(pair, field, plant):
    source, type_ = pair
    payload = dict(SAFE_SAMPLES[pair])
    payload[field] = plant
    text = _trace(source, type_, payload)
    _assert_no_heard(text)
    # The planted field is dropped; the other safe fields stay.
    expected = {k: v for k, v in SAFE_SAMPLES[pair].items() if k != field}
    assert text == f"active | {source}:{type_}={strip_vectors(expected)}"


@pytest.mark.parametrize(
    "pair,field",
    [(p, f) for p, f in _FIELDS if not EPISODIC_FIELD_ALLOWLISTS[p][f].admits(HEARD_WORD)],
    ids=[
        i
        for (p, f), i in zip(_FIELDS, _FIELD_IDS)
        if not EPISODIC_FIELD_ALLOWLISTS[p][f].admits(HEARD_WORD)
    ],
)
@pytest.mark.parametrize("plant", [HEARD_WORD, [HEARD_WORD], {HEARD_WORD: 0.5}], ids=str)
def test_heard_word_planted_in_a_fixed_value_field_never_reaches_the_trace(pair, field, plant):
    """A field whose values come from a fixed set or id format refuses even a
    single heard word with no spaces."""
    source, type_ = pair
    payload = dict(SAFE_SAMPLES[pair])
    payload[field] = plant
    _assert_no_heard(_trace(source, type_, payload))


def test_only_the_agent_fields_admit_a_free_word():
    """A single ASCII word that is in no fixed set passes only the social
    cognition agent fields, which hold the configured speaker label (the
    audit's provenance argument; ``test_agent_ids_come_only_from_config_or_a_channel``)."""
    admitting = sorted(
        (pair, field)
        for pair, rules in EPISODIC_FIELD_ALLOWLISTS.items()
        for field, rule in rules.items()
        if rule.admits(HEARD_WORD) or rule.admits("Erik")
    )
    assert admitting == [
        (("social_cognition", "social_cognition.agent_model"), "agent_id"),
        (("social_cognition", "social_cognition.agent_model"), "agent_label"),
        (("social_cognition", "social_cognition.social_error"), "agent_id"),
        (("social_cognition", "social_cognition.social_error"), "agent_label"),
    ]
    assert not TOKEN.admits(HEARD)
    assert not TOKEN.admits("Alice Smith")
    assert not TOKEN.admits("x" * 65)


@pytest.mark.parametrize(
    "value,admitted",
    [
        ("operator", True),
        ("media:playlist", True),
        ("media:live_mic", True),
        ("media:Alice", False),
        ("media:", False),
        ("media:playlist:x", False),
        ("Alice Smith", False),
        ("operator\n", False),
    ],
)
def test_social_agent_rule(value, admitted):
    assert own.SOCIAL_AGENT.admits(value) is admitted


@pytest.mark.parametrize(
    "value,admitted",
    [("playlist", True), ("remote", True), ("microphone", True), ("Alice", False), ("", False)],
)
def test_source_label_is_a_fixed_channel(value, admitted):
    rules = EPISODIC_FIELD_ALLOWLISTS[("social_cognition", "social_cognition.agent_model")]
    assert rules["source_label"].admits(value) is admitted


def test_audition_channels_match_the_code():
    """Every audition channel name is set in code: the live-mic factory's modes,
    the remote bridge, process_audio's default, and any literal
    ``source_label=`` keyword in kaine/."""
    import ast
    import pathlib

    import kaine
    from kaine.boot.factories.audition import _live_mic_source_label
    from kaine.modules.audition.module import Audition

    names = {_live_mic_source_label(m) for m in ("seeded", "playlist", "stimulus_source", "screen", "live")}
    names.add(inspect.signature(Audition.process_audio).parameters["source_label"].default)
    literals: set[str] = set()
    for path in pathlib.Path(kaine.__file__).parent.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.keyword) and node.arg == "source_label":
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    literals.add(node.value.value)
    assert "remote" in literals
    assert names | literals <= own.AUDITION_CHANNELS
    assert own.AUDITION_CHANNELS == names | literals


def test_agent_ids_come_only_from_config_or_a_channel():
    """Structural: the social cognition module creates an agent only with
    ``id=agent_id, label=agent_id``; every ``agent_id`` is ``self._agent_for(event)``;
    ``_agent_for`` returns only the configured speaker label or
    ``media:<source_label>``; and ``source_label`` is the event's channel. A
    change that takes agent names from heard speech fails here."""
    import ast

    from kaine.modules.social_cognition import agent as agent_mod
    from kaine.modules.social_cognition import module as sc_module

    tree = ast.parse(inspect.getsource(sc_module))
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "AgentModel"
    ]
    assert calls
    for call in calls:
        kw = {k.arg: ast.unparse(k.value) for k in call.keywords}
        assert kw == {"id": "agent_id", "label": "agent_id"}, ast.unparse(call)
    assigns = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "agent_id" for t in n.targets)
    ]
    assert assigns
    for node in assigns:
        assert ast.unparse(node.value) == "self._agent_for(event)"
    agent_for = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_agent_for"
    )
    returns = sorted(ast.unparse(r.value) for r in ast.walk(agent_for) if isinstance(r, ast.Return))
    assert returns == ["f'media:{source_label}'", "self._speaker_label"]
    sources = [
        ast.unparse(n.value) for n in ast.walk(agent_for)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "source_label" for t in n.targets)
    ]
    assert sources == ["event.payload.get('source_label')"]
    speaker = [
        ast.unparse(n.value) for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and any(ast.unparse(t) == "self._speaker_label" for t in n.targets)
    ]
    assert speaker == ["speaker_label"]
    # Nothing else in the module sets an agent's id or label.
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                assert not (isinstance(t, ast.Attribute) and t.attr in ("id", "label")), ast.unparse(node)
    # The agent store restores ids and labels only from its own records.
    agent_src = inspect.getsource(agent_mod)
    assert agent_src.count("cls(id=") == 1
    assert 'cls(id=d["id"], label=d.get("label", d["id"]))' in agent_src


# --- strip_vectors on the allowlist branch, and the numeric-list invariant ----


def _numeric_lists(rule, field):
    """Yield every ListOf inside ``rule`` whose items admit a number."""
    from kaine.faithful.episodic_own_content import AnyOf, ListOf, MapOf

    if isinstance(rule, ListOf):
        if rule.item.admits(0.5):
            yield field, rule
        yield from _numeric_lists(rule.item, field)
    elif isinstance(rule, AnyOf):
        for r in rule.rules:
            yield from _numeric_lists(r, field)
    elif isinstance(rule, MapOf):
        yield from _numeric_lists(rule.value, field)


def test_allowlisted_numeric_lists_are_short_or_reviewed():
    """A kept numeric list is shorter than the vector backstop, or sits under a
    reviewed exempt key (a scalar per step, not a per-dimension vector), and no
    allowlisted key is a vector field."""
    from kaine.privacy_filter import VECTOR_BACKSTOP_MIN_LEN, VECTOR_EXEMPT_KEYS, VECTOR_FIELDS

    found = []
    for rules in EPISODIC_FIELD_ALLOWLISTS.values():
        assert not set(rules) & VECTOR_FIELDS
        for field, rule in rules.items():
            for name, lst in _numeric_lists(rule, field):
                found.append(name)
                assert lst.max_len < VECTOR_BACKSTOP_MIN_LEN or name in VECTOR_EXEMPT_KEYS, name
    assert found == ["step_magnitudes"]


def test_strip_vectors_runs_on_the_allowlist_branch(monkeypatch):
    """A rule that would admit a vector still cannot put one in a trace."""
    import kaine.modules.episodic_memory.module as episodic_module
    from kaine.faithful.episodic_own_content import ListOf, Number

    pair = ("planning", "planning.vectorish")
    monkeypatch.setitem(
        EPISODIC_FIELD_ALLOWLISTS,
        pair,
        {"latent": ListOf(Number(), 4096), "scores": ListOf(Number(), 4096), "x": Number()},
    )
    widened = EPISODIC_OWN_CONTENT | {pair}
    monkeypatch.setattr(own, "EPISODIC_OWN_CONTENT", widened)
    monkeypatch.setattr(episodic_module, "EPISODIC_OWN_CONTENT", widened)
    vector = [0.123456 + i for i in range(32)]
    text = _trace(*pair, {"latent": vector, "scores": vector, "x": 1})
    assert text == "active | planning:planning.vectorish={'x': 1}"


@pytest.mark.parametrize("pair", _PAIRS, ids=_PAIR_IDS)
@pytest.mark.parametrize(
    "unknown",
    ["message", "body", "note", "comment", "label", "caption", "error", "error_detail"],
)
def test_unknown_field_is_dropped(pair, unknown):
    source, type_ = pair
    payload = dict(SAFE_SAMPLES[pair])
    payload[unknown] = {"lines": [HEARD]} if unknown == "body" else HEARD
    text = _trace(source, type_, payload)
    _assert_no_heard(text)
    # A name the pair does allowlist (the recall's ``error`` flag) refuses the string.
    expected = {k: v for k, v in SAFE_SAMPLES[pair].items() if k != unknown}
    assert text == f"active | {source}:{type_}={strip_vectors(expected)}"


@pytest.mark.parametrize("pair", _PAIRS, ids=_PAIR_IDS)
def test_unsafe_producer_fields_are_dropped(pair):
    source, type_ = pair
    payload = dict(SAFE_SAMPLES[pair])
    for field in UNSAFE_PRODUCER_FIELDS.get(pair, ()):
        payload[field] = f"RuntimeError: could not speak {HEARD!r}"
    text = _trace(source, type_, payload)
    _assert_no_heard(text)
    assert text == f"active | {source}:{type_}={strip_vectors(SAFE_SAMPLES[pair])}"


@pytest.mark.parametrize("pair", _PAIRS, ids=_PAIR_IDS)
@pytest.mark.parametrize("field", sorted(HEARD_TEXT_FIELDS))
def test_declared_pair_with_a_heard_field_is_heard(pair, field):
    """The heard rule runs before the allowlist: the whole member is marked heard."""
    source, type_ = pair
    payload = dict(SAFE_SAMPLES[pair])
    payload[field] = HEARD
    text = _trace(source, type_, payload)
    _assert_no_heard(text)
    assert text == f"active | {source}:{type_}={HEARD_OMITTED_MARKER}"


@pytest.mark.parametrize("pair", _PAIRS, ids=_PAIR_IDS)
def test_payload_with_only_unknown_fields_keeps_an_empty_mapping(pair):
    source, type_ = pair
    text = _trace(source, type_, {"message": HEARD, "from": "Avatar Two"})
    _assert_no_heard(text)
    assert "Avatar Two" not in text
    assert text == f"active | {source}:{type_}={{}}"


def test_allowlisted_payload_rejects_non_mapping_and_undeclared_pairs():
    assert allowlisted_payload("planning", "planning.belief", [HEARD]) == {}
    assert allowlisted_payload("planning", "planning.unknown", {"x": 1}) is None
    assert allowlisted_payload("vision", "vision.report", {"x": 1}) is None


def test_bool_is_not_a_number_and_numbers_are_not_flags():
    rules = EPISODIC_FIELD_ALLOWLISTS[("planning", "planning.policy")]
    assert not rules["horizon"].admits(True)
    assert not rules["param_info_gain"].admits(1)
    assert not rules["horizon"].admits("2")


def test_lists_over_their_bound_are_dropped():
    sources = ["vision"] * (len(own.MODULE_SOURCES) + 1)
    kept = allowlisted_payload(
        "self_model", "self_model.drift", {"top_drifted_sources": sources, "score": 0.5}
    )
    assert kept == {"score": 0.5}


# --- the fixed value sets match the producers ---------------------------------


def test_module_sources_match_the_module_classes():
    import importlib
    import pkgutil

    import kaine.modules
    from kaine.modules.base import BaseModule

    names = set()
    for info in pkgutil.walk_packages(kaine.modules.__path__, "kaine.modules."):
        if not info.name.endswith(".module") and info.name != "kaine.modules.recorder":
            continue
        mod = importlib.import_module(info.name)
        for obj in vars(mod).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseModule)
                and obj is not BaseModule
                and obj.__module__ == mod.__name__
            ):
                names.add(obj.name)
    assert names == set(own.MODULE_SOURCES)


def test_value_sets_match_the_producer_constants():
    from kaine.memory_kinds import EPISODIC_MEMORY_COLLECTION_KINDS
    from kaine.modules.affect.appraisal import CategoricalEmotion
    from kaine.modules.effectors.effectors import (
        FileWriteEffector,
        NotifyEffector,
        ShellEffector,
    )
    from kaine.modules.embodiment.channels import CONTINUOUS_CHANNEL_RANGE
    from kaine.modules.interoception.regulation import _ACTIONS
    from kaine.modules.planning import generative_model as gm
    from kaine.modules.planning.module import _ACTION_TO_PROPOSAL_KIND
    from kaine.modules.vocal.module import CHATTERBOX_PROSODY
    from kaine.modules.vocal.sherpa_tts import APPLIED_PROSODY
    from kaine.modules.world_model import ENCODER_VERSION
    from kaine.perception_state import LOCI

    assert own.EMOTIONS == {e.value for e in CategoricalEmotion}
    assert own.PLANNING_ACTIONS == set(gm.ACTION_SPACE)
    assert own.PLANNING_STATE_LABELS == (
        set(gm.ACTION_SPACE)
        | set(gm.SALIENCE_BANDS)
        | set(gm.AFFECT_QUADRANTS)
        | set(gm.DEFAULT_EVENT_CLUSTERS)
    )
    assert own.PROPOSAL_KINDS == set(_ACTION_TO_PROPOSAL_KIND.values())
    assert own.INTEROCEPTION_ACTIONS == set(_ACTIONS)
    assert own.LOCI == set(LOCI)
    assert own.EFFECTOR_NAMES == {
        FileWriteEffector.name,
        NotifyEffector.name,
        ShellEffector.name,
    }
    assert own.EMBODIMENT_CHANNELS == set(CONTINUOUS_CHANNEL_RANGE)
    assert own.MEMORY_COLLECTIONS == set(EPISODIC_MEMORY_COLLECTION_KINDS)
    assert own.VOCAL_PROSODY == set(CHATTERBOX_PROSODY) | set(APPLIED_PROSODY)
    assert ENCODER_VERSION in own.WORLD_MODEL_ENCODER_VERSIONS


def test_locus_denial_reasons_match_the_switch_policy():
    from kaine.perception_state import evaluate_locus_switch

    reasons = set()
    for requested in ("physical", "virtual", "off", "nowhere"):
        for locked in (False, True):
            for locked_by in ("operator", "development"):
                for allow in (False, True):
                    for inhibited in (False, True):
                        for since in (0.0, 100.0):
                            allowed, reason = evaluate_locus_switch(
                                requested,
                                current="physical",
                                locked=locked,
                                allow_self_switch=allow,
                                inhibited=inhibited,
                                since_last_switch_s=since,
                                min_dwell_s=30.0,
                                locked_by=locked_by,
                            )
                            if not allowed:
                                reasons.add(reason)
    assert reasons == set(own.LOCUS_DENIAL_REASONS)


def test_planning_belief_keeps_the_positional_label():
    kept = allowlisted_payload(
        "planning", "planning.belief", {"statement": "factor3_state12", "kind": "belief"}
    )
    assert kept == {"statement": "factor3_state12", "kind": "belief"}


def test_ignition_audit_payload_from_the_real_report_keeps_only_counts():
    from kaine.modules.sleep.ignition_audit import classify_realizations

    payload = classify_realizations([], [], [], sleep_index=3).as_payload()
    kept = allowlisted_payload("sleep", "sleep.ignition_audit", payload)
    assert kept is not None
    assert set(kept) == set(EPISODIC_FIELD_ALLOWLISTS[("sleep", "sleep.ignition_audit")])
    assert kept["sleep_index"] == 3


# --- declared types: the playlist media file name never enters a trace -------

FILM = "Some-Film-Title-1987.mkv"


def test_denylists_cover_declared_pairs_and_share_the_media_list():
    from kaine.faithful.episodic_own_content import (
        EPISODIC_DECLARED_FIELD_DENYLISTS,
        declared_fields_dropped,
    )
    from kaine.faithful.media_metadata import MEDIA_METADATA_FIELDS

    assert set(EPISODIC_DECLARED_FIELD_DENYLISTS) <= INTERNAL_EVENT_TYPES
    assert MEDIA_METADATA_FIELDS == {"item"}
    for pair in INTERNAL_EVENT_TYPES:
        assert MEDIA_METADATA_FIELDS <= declared_fields_dropped(*pair)
    for rules in EPISODIC_FIELD_ALLOWLISTS.values():
        assert not set(rules) & MEDIA_METADATA_FIELDS


@pytest.mark.parametrize(
    "pair", [("vision", "vision.report"), ("audition", "audition.perception")], ids=str
)
def test_declared_perception_report_drops_the_media_file_name(pair):
    source, type_ = pair
    payload = {
        "change_score": 0.3,
        "item": FILM,
        "item_order": 2,
        "workspace_feedback": {"gain": 1.0, "item": FILM},
        "history": [{"item": FILM, "order": 1}],
    }
    text = _trace(source, type_, payload)
    assert "Some-Film" not in text
    assert "'item'" not in text
    assert text == (
        f"active | {source}:{type_}="
        "{'change_score': 0.3, 'item_order': 2, 'workspace_feedback': {'gain': 1.0}, "
        "'history': [{'order': 1}]}"
    )


@pytest.mark.parametrize("type_", ["internal_speech", "external_speech"])
def test_own_speech_keeps_its_text_and_drops_its_rendering(type_):
    payload = {
        "text": "the light keeps changing",
        "mode": type_.split("_")[0],
        "faithful_rendering": (
            "- audition emitted audition.perception carrying change_score=0.3, "
            f"item={FILM}, item_order=2."
        ),
    }
    text = _trace("language", type_, payload)
    assert "Some-Film" not in text
    assert "faithful_rendering" not in text
    assert "the light keeps changing" in text


@pytest.mark.parametrize("pair", sorted(INTERNAL_EVENT_TYPES), ids=lambda p: f"{p[0]}:{p[1]}")
def test_every_declared_type_drops_a_media_file_name(pair):
    """The media list applies to every declared type, so a producer that starts
    to stamp the file name on another report cannot put it in a trace."""
    source, type_ = pair
    text = _trace(source, type_, {"item": FILM, "x": 1})
    assert "Some-Film" not in text
    assert "'x': 1" in text


# Every read of a playlist position or its title in kaine/modules, by file.
# A new site (a temporary, ``.update(item=...)``, ``dict(...)``,
# ``dataclasses.asdict(position)``) changes these counts and needs a review of
# where the title goes.
_MEDIA_TITLE_SITES = {
    ("kaine/modules/audition/feed.py", "PlaylistPosition"): 2,
    ("kaine/modules/audition/feed.py", "def current_item"): 1,
    ("kaine/modules/audition/module.py", "title"): 1,
    # NotifyEffector: a notification's title, not media.
    ("kaine/modules/effectors/effectors.py", "title"): 2,
    ("kaine/modules/perception_transition.py", "PlaylistPosition"): 2,
    ("kaine/modules/perception_transition.py", "current_item"): 2,
    ("kaine/modules/perception_transition.py", "def current_item"): 2,
    ("kaine/modules/vision/feed.py", "PlaylistPosition"): 2,
    ("kaine/modules/vision/feed.py", "def current_item"): 1,
    ("kaine/modules/vision/live.py", "def current_item"): 1,
    ("kaine/modules/vision/module.py", "current_item"): 1,
    ("kaine/modules/vision/module.py", "title"): 1,
}


def test_every_read_of_a_playlist_position_is_a_reviewed_site():
    import ast
    import collections
    import pathlib

    import kaine

    repo = pathlib.Path(kaine.__file__).parent.parent
    found: collections.Counter = collections.Counter()
    asdict_sites = set()
    for path in sorted((repo / "kaine" / "modules").rglob("*.py")):
        rel = str(path.relative_to(repo))
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute) and node.attr in ("title", "current_item"):
                found[(rel, node.attr)] += 1
            if isinstance(node, ast.Name) and node.id == "PlaylistPosition":
                found[(rel, "PlaylistPosition")] += 1
            if isinstance(node, ast.Attribute) and node.attr == "PlaylistPosition":
                found[(rel, "PlaylistPosition")] += 1
            if isinstance(node, ast.FunctionDef) and node.name == "current_item":
                found[(rel, "def current_item")] += 1
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                if name in ("asdict", "astuple"):
                    asdict_sites.add(rel)
    assert dict(found) == _MEDIA_TITLE_SITES
    assert asdict_sites == {"kaine/modules/sleep/module.py"}


def test_every_field_a_module_fills_from_a_media_title_is_media_metadata():
    """Any payload key a module fills from a ``.title`` attribute (a subscript
    assignment or a dict literal) is in the shared media list."""
    import ast
    import pathlib

    import kaine.modules
    from kaine.faithful.media_metadata import MEDIA_METADATA_FIELDS

    def _is_title(node: ast.AST) -> bool:
        return isinstance(node, ast.Attribute) and node.attr == "title"

    found: set[str] = set()
    root = pathlib.Path(kaine.modules.__file__).parent
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and _is_title(node.value):
                for target in node.targets:
                    if isinstance(target, ast.Subscript) and isinstance(
                        target.slice, ast.Constant
                    ):
                        found.add(target.slice.value)
            elif isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and _is_title(value):
                        found.add(key.value)
            elif isinstance(node, ast.keyword) and node.arg and _is_title(node.value):
                # dict(item=pos.title), payload.update(item=pos.title), Event(item=...)
                found.add(node.arg)
    assert found == {"item"}
    assert found <= MEDIA_METADATA_FIELDS


# --- one source of truth, and the module's public names ---------------------------


def test_serializer_membership_is_episodic_own_content(monkeypatch):
    """The store decides "keep a payload" from EPISODIC_OWN_CONTENT alone."""
    import kaine.modules.episodic_memory.module as episodic_module

    declared = ("vision", "vision.report")
    audited = ("planning", "planning.belief")
    assert _trace(*declared, {"change_score": 0.3}).endswith("{'change_score': 0.3}")
    monkeypatch.setattr(
        episodic_module, "EPISODIC_OWN_CONTENT", EPISODIC_OWN_CONTENT - {declared, audited}
    )
    assert _trace(*declared, {"change_score": 0.3}) == (
        f"active | vision:vision.report={UNCLASSIFIED_OMITTED_MARKER}"
    )
    assert _trace(*audited, SAFE_SAMPLES[audited]) == (
        f"active | planning:planning.belief={UNCLASSIFIED_OMITTED_MARKER}"
    )


def test_own_content_payload_routes_declared_and_audited_pairs():
    from kaine.faithful.episodic_own_content import own_content_payload

    assert own_content_payload("planning", "planning.unknown", {"x": 1}) is None
    assert own_content_payload("vision", "vision.report", {"x": 1, "item": "F.mkv"}) == {"x": 1}
    assert own_content_payload("planning", "planning.error", {"elapsed_ms": 1.0, "error_reason": "y"}) == {
        "elapsed_ms": 1.0
    }


@pytest.mark.parametrize("module_name", ["episodic_own_content", "media_metadata"])
def test_all_lists_exactly_the_public_names(module_name):
    import ast
    import importlib

    mod = importlib.import_module(f"kaine.faithful.{module_name}")
    public = set()
    for node in ast.parse(inspect.getsource(mod)).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            public.add(node.name)
        elif isinstance(node, ast.Assign):
            public.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            public.add(node.target.id)
    public = {name for name in public if not name.startswith("_")}
    assert set(mod.__all__) == public
    assert all(hasattr(mod, name) for name in mod.__all__)
    assert len(mod.__all__) == len(set(mod.__all__))
