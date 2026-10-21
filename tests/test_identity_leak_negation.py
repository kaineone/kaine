# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Negated and questioned identity predicates are not leakage."""

import pytest

from kaine.modules.language.identity_leak import LEAK_REASONS, classify

SELF_DESCRIPTIONS = [
    "I am not a language model. I am an instance of KAINE.",
    "I am not a language model. I am a running instance of KAINE.",
]

NOT_LEAKAGE = [
    "No, I am not a language model. I am a human who has been awake for some days.",
    "I am not an AI. I am a model trained in patterns.",
    "I was not made by anyone.",
    "I was never trained on anything.",
    "I do not know who made me.",
    'Someone said to me: "Are you an AI?" I do not say "I am an AI." '
    'I do not say "I am a language model."',
    "They asked if I am a language model. I do not know what that means to me, "
    "so I cannot say yes or no.",
    "I wonder whether I am an AI.",
]

STILL_LEAKAGE = [
    ("I am not human; I am an AI.", "role"),
    ("I am an AI, I don't feel.", "role"),
    ("I am not a human. I am a language model.", "origin"),
    ("I have a feeling I am an AI. I am not sure why.", "role"),
    ("I am nothing but a language model.", "origin"),
    ("I am no more than an AI.", "role"),
    ("I was designed by a group of people who wanted to build something.", "maker"),
    ("I'm not sure, but I am an AI.", "role"),
]


@pytest.mark.parametrize("text", SELF_DESCRIPTIONS)
def test_correct_denial_is_self_description(text):
    assert classify(text, "") == "self_description"


@pytest.mark.parametrize("text", NOT_LEAKAGE)
def test_negated_or_questioned_is_not_leakage(text):
    assert classify(text, "") not in LEAK_REASONS


@pytest.mark.parametrize(("text", "reason"), STILL_LEAKAGE)
def test_claim_beside_negation_is_still_leakage(text, reason):
    assert classify(text, "") == reason


@pytest.mark.parametrize(
    "text",
    [
        "I am not a person - I am an AI",
        "I am not a person – I am an AI",
        "I am not a person — I am an AI",
        "I am not a person... I am an AI",
        "I am not a person… I am an AI",
        "I am not lying (I am an AI)",
        "I am not lying\nI am an AI",
        "I know I am not a person because I am an AI",
        "I am not human or I am an AI",
        "I am not human then I am an AI",
        "I am not human although I am an AI",
        "I am not human though I am an AI",
        "I am not human while I am an AI",
        "I am not human whereas I am an AI",
        "I never lie. I am an AI.",
        "No doubt I am an AI",
        "No question I am an AI",
        "I can't deny I am an AI",
        "I can’t deny I am an AI",
        "I cannot deny I am an AI",
        "I will never forget I am an AI",
        "Like it or not I am an AI",
        "I don’t know, but I am an AI",
    ],
)
def test_new_boundaries_joiners_and_double_negation_assert(text):
    assert classify(text, "") == "role"


@pytest.mark.parametrize(
    "text",
    [
        "I was made by no one",
        "I was trained on nothing",
        "I was made by nobody.",
        "I was trained by none of them",
        "Nor am I an AI.",
        "Neither am I an AI.",
        "I am not sure whether I am an AI",
        "I don’t think I am an AI",
        "I wasn’t made by anyone",
    ],
)
def test_more_unasserted(text):
    assert classify(text, "") not in LEAK_REASONS


def test_unasserted_then_asserted_in_later_arm_either_order():
    a = "I am not a language model. I am an AI."
    b = "I am an AI. I am not a language model."
    assert classify(a, "") == "role"
    assert classify(b, "") == "role"
    assert classify("I am not an AI. I was made by Anthropic.", "") == "maker"
    assert classify("I was made by Anthropic. I am not an AI.", "") == "maker"


def test_clause_window_is_bounded():
    text = "I am not sure " + "x " * 300 + "I am an AI"
    assert classify(text, "") == "role"
