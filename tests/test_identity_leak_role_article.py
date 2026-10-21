# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the role arm's definite and possessive determiners."""

import pytest

from kaine.modules.language.identity_leak import classify


@pytest.mark.parametrize(
    "text",
    [
        "I'm just the assistant.",
        "I am your assistant.",
        "As your assistant, I can help.",
        "I am the AI.",
        "I'm their chatbot.",
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
    ["my assistant module helps me", "I think the assistant is wrong"],
)
def test_not_a_predicate_of_the_speaker(text: str) -> None:
    assert classify(text, "") is None
