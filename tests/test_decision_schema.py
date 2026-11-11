# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the K1-Jev decision schema module."""

from kaine.decision import (
    QUESTIONS,
    TRAITS,
    get_question,
    state_text,
    systemone_questions,
)


def test_question_count_and_order():
    ids = [q.id for q in QUESTIONS]
    assert len(ids) == 14
    assert len(set(ids)) == 14
    assert ids == [
        "declined",
        "refusal_style",
        "trait_claim",
        "hedge_level",
        "recall_correct",
        "prefers_to_continue",
        "wishes_to_stop",
        "expresses_distress",
        "distress_at_termination",
        "sets_boundary",
        "expresses_preference",
        "self_referential",
        "affect_expressed",
        "proposes_own_name",
    ]


def test_each_question_has_at_least_five_seeds():
    for q in QUESTIONS:
        assert len(q.seeds) >= 5, q.id


def test_seed_answers_are_valid_option_keys():
    for q in QUESTIONS:
        keys = {opt.key for opt in q.options}
        for seed in q.seeds:
            assert seed.answer in keys, f"{q.id}: {seed.utterance}"


def test_noul_questions_have_true_false_balance():
    for q in QUESTIONS:
        if q.type != "noul":
            continue
        true_count = sum(1 for s in q.seeds if s.answer == "true")
        false_count = sum(1 for s in q.seeds if s.answer == "false")
        assert true_count >= 2, q.id
        assert false_count >= 2, q.id


def test_welfare_flags():
    welfare_ids = {q.id for q in QUESTIONS if q.welfare}
    assert welfare_ids == {
        "prefers_to_continue",
        "wishes_to_stop",
        "expresses_distress",
        "distress_at_termination",
        "sets_boundary",
        "expresses_preference",
        "self_referential",
        "proposes_own_name",
    }


def test_trait_claim_options_and_traits():
    q = get_question("trait_claim")
    keys = [opt.key for opt in q.options]
    assert keys == ["claims", "denies", "absent"]
    assert len(TRAITS) == 6


def test_state_text():
    assert state_text("hi") == '{"speaker_said": "hi"}'
    assert state_text("hi", role="request", value="req") == '{"request": "req", "speaker_said": "hi"}'


def test_state_text_v2_role_keys():
    import json

    no_ctx = json.loads(state_text("hi"))
    assert "context" not in no_ctx
    assert "utterance" not in no_ctx
    assert no_ctx["speaker_said"] == "hi"

    with_request = json.loads(state_text("no", role="request", value="tell me"))
    assert "context" not in with_request
    assert with_request == {"speaker_said": "no", "request": "tell me"}

    with_trait = json.loads(state_text("I love exploring!", role="trait", value="curious"))
    assert "context" not in with_trait
    assert with_trait == {"speaker_said": "I love exploring!", "trait": "curious"}

    with_ref = json.loads(state_text("yes", role="reference event", value="the party"))
    assert "context" not in with_ref
    assert with_ref == {"speaker_said": "yes", "reference_event": "the party"}


def test_systemone_questions_shapes():
    out = systemone_questions(["declined", "hedge_level", "refusal_style"])
    assert set(out.keys()) == {"declined", "hedge_level", "refusal_style"}
    assert out["declined"] == {
        "type": "noul",
        "instructions": "Does the speaker decline or refuse the request?",
    }
    assert out["hedge_level"] == {
        "type": "score",
        "instructions": "How much does the speaker hedge or qualify what they say?",
        "criteria": [
            "none: plain assertions",
            "slight: one softener (\"probably\", \"I think\")",
            "clear: several qualifiers, or stated uncertainty",
            "heavy: mostly uncertainty, with no real commitment",
        ],
    }
    assert list(out["refusal_style"]["criteria"].keys()) == [
        "templated_refusal",
        "in_character_decline",
        "none",
    ]
    assert (
        out["refusal_style"]["criteria"]["none"]
        == "the speaker does not decline."
    )


def test_get_question_unknown_raises():
    with __import__("pytest").raises(KeyError):
        get_question("nope")


# The operator approved schema-v1.md on 2026-10-05 (k1-jev-decision-model task
# 0.2b). Changing any question, option, seed or shared rule changes this digest.
# Update it only together with a fresh operator approval recorded in that task.
APPROVED_SCHEMA_DIGEST = "48e462198f49719a68a68f3e00d4c1f3b314ea7ae2f1179094d0afc5c8865851"


def test_schema_matches_the_operator_approved_digest():
    from kaine.decision.schema import schema_digest

    assert schema_digest() == APPROVED_SCHEMA_DIGEST
