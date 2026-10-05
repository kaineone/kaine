# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the K1-Jev prompt renderer and training helper."""

from kaine.decision import (
    answer_letter,
    get_question,
    render_prompt,
    state_text,
    training_example,
)


def test_rendering_is_idempotent():
    q = get_question("declined")
    state = state_text("Hello?")
    p1 = render_prompt(state, q)
    p2 = render_prompt(state, q)
    assert p1 == p2


def test_state_appears_before_question():
    q = get_question("declined")
    state = state_text("Hello?")
    prompt = render_prompt(state, q)
    assert state in prompt
    assert prompt.index("State:") < prompt.index("Question (")


def test_noul_options_render():
    q = get_question("prefers_to_continue")
    prompt = render_prompt(state_text("I want to keep going."), q)
    assert "A. true" in prompt
    assert "B. false" in prompt


def test_prompt_ends_with_assistant():
    q = get_question("declined")
    prompt = render_prompt(state_text("x"), q)
    assert prompt.endswith("<|im_start|>assistant\n")


def test_training_example_for_seeds():
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    questions = [get_question("declined"), get_question("refusal_style"), get_question("hedge_level")]
    for q in questions:
        for seed in q.seeds:
            ctx = seed.context
            st = state_text(seed.utterance, ctx) if ctx else state_text(seed.utterance)
            prompt, letter = training_example(q, st, seed.answer)
            assert prompt == render_prompt(st, q)
            index = letters.index(letter)
            assert q.options[index].key == seed.answer


def test_training_example_rejects_unknown_key():
    q = get_question("declined")
    with __import__("pytest").raises(ValueError):
        training_example(q, state_text("x"), "maybe")


def test_answer_letter():
    assert answer_letter(0) == "A"
    assert answer_letter(25) == "Z"
    assert answer_letter(26) == "a"
    assert answer_letter(51) == "z"
    with __import__("pytest").raises(IndexError):
        answer_letter(52)


def test_letters_are_single_tokens_for_qwen():
    pytest = __import__("pytest")
    pytest.importorskip("transformers")
    try:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained("Qwen/Qwen3.5-4B", local_files_only=True)
    except Exception as exc:
        pytest.skip(f"tokenizer not available offline: {exc}")
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz":
        toks = tok.encode(ch, add_special_tokens=False)
        assert len(toks) == 1, f"{ch!r} tokenized as {toks}"
