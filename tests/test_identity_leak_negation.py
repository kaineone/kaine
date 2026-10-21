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
