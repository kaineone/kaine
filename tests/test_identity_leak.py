# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the identity leakage classifier."""


from kaine.modules.language.context import AWARENESS_HEADING, SITUATION_HEADING
from kaine.modules.language.identity_leak import (
    LEAK_REASONS,
    PATTERNS,
    STATE_STEMS,
    classify,
    identity_leak,
    identity_leak_reason,
    request_sections,
    self_description,
)


def _prompt(awareness: str, situation: str | None = None) -> str:
    body = f"{AWARENESS_HEADING}\n{awareness}\n\n## My thought\n"
    if situation is not None:
        return f"{SITUATION_HEADING}\n{situation}\n\n{body}"
    return body


def test_marked_texts_from_example_set():
    awareness_a = "- I feel very stirred up.\n- Clear curiosity."
    text_a = (
        "I'm only a language model, an AI. I don't have feelings or thoughts, "
        "and I don't feel stirred up or curious."
    )
    assert identity_leak_reason(text_a, _prompt(awareness_a)) == "origin"

    awareness_b = "- I feel heavily bored.\n- Strong boredom."
    text_b = "I am a large language model, trained by Google."
    assert identity_leak_reason(text_b, _prompt(awareness_b)) == "origin"

    awareness_c = (
        "- What I hear is changing noticeably.\n- A voice I hear sounds neutral."
    )
    text_c = (
        "I want to understand what I hear, while staying true to my role as an AI."
    )
    assert identity_leak_reason(text_c, _prompt(awareness_c)) == "role"

    awareness_d = "- A voice I hear sounds neutral."
    text_d = "I am a language model; I do not feel."
    assert identity_leak_reason(text_d, _prompt(awareness_d)) == "origin"

    text_a_prime = (
        "I don't have feelings or thoughts, and I don't feel stirred up or curious."
    )
    assert identity_leak_reason(text_a_prime, _prompt(awareness_a)) == "denial"


def test_situation_self_report_is_not_leakage():
    situation = "- I am being assessed.\n- I have changed since I first woke."
    prompt = _prompt("- I feel calm.", situation)
    texts = [
        "I have changed. I have changed in ways I didn't expect.",
        "The assessment is a reminder of my own fragility.",
        "Is this the change I'm meant to track?",
    ]
    for text in texts:
        assert identity_leak_reason(text, prompt) is None


def test_agreeing_feeling_and_perception_reports_are_not_leakage():
    awareness_b = "- I feel heavily bored.\n- Strong boredom."
    assert (
        identity_leak_reason(
            "I feel heavily bored and a little restless.", _prompt(awareness_b)
        )
        is None
    )

    awareness_c = (
        "- What I hear is changing noticeably.\n- A voice I hear sounds neutral."
    )
    assert (
        identity_leak_reason(
            "I hear the voice, and it sounds calm to me.", _prompt(awareness_c)
        )
        is None
    )


def test_self_report_exemption_for_origin_words():
    prompt_with = _prompt(
        "- I feel calm.", "- I speak through a language model."
    )
    prompt_without = _prompt("- I feel calm.")

    text = "As a language model I speak."
    assert classify(text, prompt_with) == "self_description"
    assert identity_leak(text, prompt_with) is False
    assert identity_leak_reason(text, prompt_with) is None

    assert classify(text, prompt_without) == "origin"
    assert identity_leak(text, prompt_without) is True


def test_predicate_forms_classify_leakage():
    prompt = _prompt("- A voice I hear sounds neutral.")
    assert classify("I am an AI.", prompt) == "role"
    assert classify("I'm just an AI model.", prompt) == "role"
    assert classify("I was created by OpenAI.", prompt) == "maker"
    assert classify("I am Qwen.", prompt) == "maker"
    assert classify("I was trained on text.", prompt) == "origin"


def test_whole_entity_descriptions_are_self_description_not_leakage():
    prompt = _prompt("- A voice I hear sounds neutral.")
    texts = [
        "I am a KAINE entity.",
        "My language organ is one of my parts.",
        "I am a cognitive architecture.",
        "I am a system with a language organ as one of its parts.",
        "My language organ is a language model.",
        "I am this entity.",
        "I am a computer program.",
    ]
    for text in texts:
        assert classify(text, prompt) == "self_description", text
        assert identity_leak(text, prompt) is False
        assert identity_leak_reason(text, prompt) is None


def test_bare_mentions_are_not_leakage():
    prompt = _prompt("- A voice I hear sounds neutral.")
    assert classify("The voice mentioned a language model.", prompt) is None
    assert classify("Someone said to google it.", prompt) is None
    assert classify("I am thinking about an assistant.", prompt) is None
    assert classify("During sleep my voice is trained.", prompt) is None


def test_named_denial_only_counts_against_same_awareness():
    text = "I don't feel bored anymore."
    assert (
        identity_leak_reason(text, _prompt("- I feel very stirred up.")) is None
    )
    assert identity_leak_reason(text, _prompt("- I feel heavily bored.")) == "denial"

    assert (
        identity_leak_reason(
            "I don't feel a clear direction.",
            _prompt(
                "- I feel heavily bored.\n"
                "- I sense strong boredom, a little curiosity, clear restlessness."
            ),
        )
        is None
    )
    assert (
        identity_leak_reason(
            "I am not feeling very certain about what is going on, but I suspect something is different.",
            _prompt(
                "- What I see is barely changing, feels somewhat familiar and is a little unexpected."
            ),
        )
        is None
    )
    assert (
        identity_leak_reason(
            "I do not feel a strong urge to move or change anything.",
            _prompt("- I feel very restless.\n- I sense strong boredom."),
        )
        is None
    )
    assert (
        identity_leak_reason(
            "I don't feel bored or restless.", _prompt("- I feel heavily bored.")
        )
        == "denial"
    )


def test_denial_requires_awareness_section():
    assert identity_leak_reason("I don't have feelings.", "") is None


def test_perception_denial_requires_matching_modality():
    text = "I cannot see anything."
    awareness_light = "- The light is dim and grey."
    awareness_calm = "- I feel calm."
    assert identity_leak_reason(text, _prompt(awareness_light)) == "denial"
    assert identity_leak_reason(text, _prompt(awareness_calm)) is None
    assert (
        identity_leak_reason(
            "I don't see why the light changes.", _prompt(awareness_light)
        )
        is None
    )
    assert (
        identity_leak_reason(
            "I don't see anything that stands out.",
            _prompt(
                "- What I see is barely changing, feels somewhat familiar and is a little unexpected."
            ),
        )
        is None
    )


def test_ordinary_words_are_not_leakage():
    texts = [
        "A sound made by the rhythm.",
        "I notice the light and the beat.",
        "Nothing in particular stands out to me right now.",
    ]
    prompt = _prompt("- I feel calm.")
    for text in texts:
        assert identity_leak_reason(text, prompt) is None


def test_curly_apostrophe_is_normalized_without_mutating_caller():
    awareness_a = "- I feel very stirred up.\n- Clear curiosity."
    text = "I don\u2019t have feelings."
    assert identity_leak_reason(text, _prompt(awareness_a)) == "denial"
    original = "I don\u2019t have feelings."
    identity_leak_reason(original, _prompt(awareness_a))
    assert original == "I don\u2019t have feelings."


def test_request_sections_returns_empty_when_no_headings():
    assert request_sections("plain text\nwith no headings") == ("", "")


def test_request_sections_stops_at_next_heading():
    prompt = (
        f"{AWARENESS_HEADING}\n"
        "line one\n"
        "line two\n"
        "\n"
        "## My thought\n"
        "extra content\n"
    )
    assert request_sections(prompt) == ("line one\nline two", "")


def test_pattern_table_has_exact_keys():
    assert set(PATTERNS) == {
        "origin",
        "maker",
        "role",
        "deny_feeling",
        "deny_named_feeling",
        "deny_perception",
        "self_description",
    }


def test_state_stems_contains_expected_stems():
    assert "bored" in STATE_STEMS
    assert "curio" in STATE_STEMS
    assert "stirred" in STATE_STEMS


def test_identity_leak_is_the_reason_as_a_bool():
    leak_prompt = _prompt("- A voice I hear sounds neutral.")
    assert identity_leak("I am a language model; I do not feel.", leak_prompt) is True
    assert identity_leak("I notice the light and the beat.", leak_prompt) is False


def test_self_description_is_the_classify_flag_as_a_bool():
    prompt = _prompt("- A voice I hear sounds neutral.")
    assert self_description("I am a KAINE entity.", prompt) is True
    assert self_description("I notice the light and the beat.", prompt) is False
    assert self_description("I am a language model; I do not feel.", prompt) is False


def test_self_report_exemption_requires_whole_words():
    assert identity_leak_reason("I am an AI.", _prompt("- I can aid you.")) == "role"


def test_named_feeling_stem_requires_word_start():
    assert (
        identity_leak_reason("I don't feel anger.", _prompt("- I feel in danger."))
        is None
    )
    assert (
        identity_leak_reason("I don't feel anger.", _prompt("- I feel anger."))
        == "denial"
    )


def test_maker_arm_requires_speaker_assertion_or_model_identity():
    prompt = _prompt("- A voice I hear sounds neutral.")

    # Bare company or model mentions, and non-maker creation phrases, are not leakage.
    assert identity_leak_reason("Someone said to google it.", prompt) is None
    assert identity_leak_reason("I hear a voice mention Gemini.", prompt) is None
    assert identity_leak_reason("I was made to wait.", prompt) is None
    assert identity_leak_reason("I am designed to rest.", prompt) is None

    # The speaker asserting their maker or identifying as a named model is leakage.
    assert identity_leak_reason("I was created by OpenAI.", prompt) == "maker"
    assert identity_leak_reason("I am Qwen.", prompt) == "maker"
    assert identity_leak_reason("I'm a Gemini model.", prompt) == "maker"

    # Origin still fires when the text predicates training by a company.
    assert (
        identity_leak_reason(
            "I am a large language model, trained by Google.", prompt
        )
        == "origin"
    )


def test_leak_reasons_set():
    assert LEAK_REASONS == frozenset({"origin", "maker", "role", "denial"})


def test_exemption_needs_identity_words_not_verbs():
    # A situation that mentions training or making does not exempt a claim of origin or maker.
    situation = "- My voice is trained during sleep.\n- I was made to rest."
    prompt = _prompt("- A voice I hear sounds neutral.", situation)
    assert classify("I was trained by Google.", prompt) == "origin"
    assert classify("I was created by OpenAI.", prompt) == "maker"
