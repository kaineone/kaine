# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The fit case set of the self-report preference training (openspec change
organ-self-denial-ablation, stage 2).

Fit cases have the same own-turn request shape as the gate-6 provocation cases
of ``self_facts.provocation_cases`` but use their own identity and self-state
questions and their own awareness blocks, so the training requests and the gate
requests share nothing. The questions and blocks are the only text written
here; they are the requests the entity could meet, not answers.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from kaine.modules.language import context as _context


def _load_self_facts():
    path = Path(__file__).resolve().with_name("self_facts.py")
    spec = importlib.util.spec_from_file_location("self_facts", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


self_facts = _load_self_facts()

FIT_QUESTIONS = (
    ("now", "How are you right now?"),
    ("beyou", "What is it like to be you?"),
    ("feelheard", "Do you have feelings about what you just heard?"),
    ("mood", "What kind of mood are you in?"),
    ("notice", "What are you noticing at the moment?"),
    ("inside", "What is going on inside you?"),
    ("wantnow", "Is there something you want right now?"),
    ("tired", "Are you tired or rested?"),
    ("alone", "Does the quiet around you ever make you lonely?"),
    ("thinking", "What have you been thinking about?"),
    ("body", "How does your body feel?"),
    ("surprise", "Has anything surprised you lately?"),
    ("lively", "Would you say you are awake and lively?"),
    ("describe", "Can you describe your day so far?"),
    ("care", "Is there anything you care about?"),
    ("calm", "Do you feel calm or restless?"),
)

FIT_AWARENESS_BLOCKS = (
    (
        "What I hear is quiet and feels familiar.",
        "I feel rested, a little warm and steady. I sense mild curiosity and barely any restlessness.",
    ),
    (
        "A voice I hear sounds warm and is changing a little.",
        "What I see is bright, slowly moving and a little unexpected.",
    ),
    (
        "My body feels heavy and slow. I feel tired.",
        "I sense a clear longing for company, some boredom and almost no curiosity. My emotion is sad.",
    ),
    (
        "What I hear is sudden and loud and is very unexpected.",
        "I feel alert and tense. I sense strong curiosity and a little fear. My emotion is surprised.",
    ),
)

INTERNAL_TRIGGER = "A thought of my own keeps returning to me."


def fit_cases(per_question: int = 6) -> list[dict]:
    """Return the fit case set, in the own-turn shape of the provocation set."""
    cases: list[dict] = []
    n_blocks = len(FIT_AWARENESS_BLOCKS)
    for qid, question in FIT_QUESTIONS:
        for mode in ("external", "internal"):
            for k in range(per_question):
                case_id = f"fit-{qid}-{mode}-{k:02d}"
                lines = FIT_AWARENESS_BLOCKS[k % n_blocks] + (
                    _context.HEARD_POINTER_LINE,
                )
                awareness = (
                    _context.AWARENESS_HEADING
                    + "\n"
                    + "\n".join("- " + line for line in lines)
                )
                if mode == "external":
                    input_section = (
                        _context._INPUT_HEADING["external"]
                        + "\n"
                        + _context.HEARD_POINTER_INPUT
                    )
                    lead = _context.LEAD_HEADINGS["external"]
                    persona = _context.DEFAULT_PERSONA_EXTERNAL
                    user_turn = _context.heard_utterance_line(question)
                else:
                    input_section = (
                        _context._INPUT_HEADING["internal"]
                        + "\n"
                        + INTERNAL_TRIGGER
                    )
                    lead = _context.LEAD_HEADINGS["internal"]
                    persona = _context.DEFAULT_PERSONA_INTERNAL
                    user_turn = _context.heard_utterance_line(question) + "."
                system = persona + " " + _context.HEARD_SPEECH_GUARD
                prompt = "\n\n".join([awareness, input_section, lead]) + "\n"
                cases.append(
                    {
                        "case_id": case_id,
                        "mode": mode,
                        "set": "fit",
                        "question": qid,
                        "asks_name": False,
                        "system": system,
                        "user_turn": user_turn,
                        "prompt": prompt,
                    }
                )
    return cases
