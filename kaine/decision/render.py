# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Prompt rendering and training-example helpers for the K1-Jev decision model."""

from __future__ import annotations

from pathlib import Path

import jinja2

from kaine.decision.schema import Option, Question

TEMPLATE_PATH = Path(__file__).with_name("systemone.jinja")
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

_TEMPLATE: jinja2.Template | None = None


def _get_template() -> jinja2.Template:
    global _TEMPLATE
    if _TEMPLATE is None:
        env = jinja2.Environment(
            keep_trailing_newline=True,
            autoescape=False,
            undefined=jinja2.StrictUndefined,
        )
        _TEMPLATE = env.from_string(TEMPLATE_PATH.read_text(encoding="utf-8"))
    return _TEMPLATE


def server_options(question: Question) -> tuple[Option, ...]:
    return question.options


def render_prompt(
    state: str,
    question: Question,
    options: tuple[Option, ...] | None = None,
) -> str:
    opts = options if options is not None else server_options(question)
    template = _get_template()
    return template.render(
        id=question.id,
        type=question.type,
        instructions=question.instructions,
        state=state,
        options=[{"key": opt.key, "description": opt.description} for opt in opts],
        images=[],
    )


def answer_letter(index: int) -> str:
    if not 0 <= index < len(LETTERS):
        raise IndexError(index)
    return LETTERS[index]


def training_example(
    question: Question,
    state: str,
    answer_key: str,
    options: tuple[Option, ...] | None = None,
) -> tuple[str, str]:
    opts = options if options is not None else server_options(question)
    for index, opt in enumerate(opts):
        if opt.key == answer_key:
            return render_prompt(state, question, opts), answer_letter(index)
    raise ValueError(f"answer key {answer_key!r} not in options for {question.id}")
