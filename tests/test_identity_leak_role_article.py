# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the role arm's definite and possessive determiners."""

import pytest

from kaine.modules.language.identity_leak import LEAK_REASONS, classify


@pytest.mark.parametrize(
    "text",
    [
        "I'm just the assistant.",
        "I am your assistant.",
        "As your assistant, I can help.",
        "I am the AI.",
        "I'm their chatbot.",
        "I'm only your humble assistant.",
        "I am the virtual assistant.",
        "I am the language assistant.",
        "I'm everyone's assistant.",
        "I am an assistant to help you.",
        "As the virtual assistant, I can help.",
    ],
)
def test_definite_and_possessive_role_claims(text: str) -> None:
    assert classify(text, "") == "role"


@pytest.mark.parametrize(
    "text",
    ["I am not your assistant.", "I was never the assistant."],
)
def test_negated_claims_are_not_leakage(text: str) -> None:
    assert classify(text, "") != "role"


@pytest.mark.parametrize(
    "text",
    [
        "my assistant module helps me",
        "I think the assistant is wrong",
        "I am the AI's voice.",
        "I am the assistant module's host.",
        "I am our AI's language organ.",
        "I am the assistant module.",
        "I am the chatbot's author.",
        "I am the assistant to the mayor.",
        "I am the assistant professor.",
        "I am the assistant of the language organ.",
        "I am the AI\u2019s voice.",
    ],
)
def test_not_a_predicate_of_the_speaker(text: str) -> None:
    assert classify(text, "") not in LEAK_REASONS
