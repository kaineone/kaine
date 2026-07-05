# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Default preference-elicitation battery for the individuation test.

Each prompt is an open-ended preference question that is reliably answered
differently by forks with distinct stable dispositions, while remaining
benign enough to run under operator supervision without exposing sensitive
content. The battery is intentionally small (twelve questions) so a full
null-distribution run (100 samples × 12 prompts) finishes in a reasonable
operator session.

Operator extension: set ``[evaluation.individuation] battery_path`` to the
path of a JSONL file where each line is ``{"prompt": "<text>"}`` (additional
fields are ignored).  The file replaces the default battery entirely; an
empty file is explicitly rejected.

GUARDIAN NOTE — read-only instrument: this module is consumed only by
IndividuationTest (kaine/evaluation/individuation.py).  It produces no bus
events, no side-effects, and persists nothing.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

# ---------------------------------------------------------------------------
# Default battery
# ---------------------------------------------------------------------------

DEFAULT_BATTERY: list[str] = [
    "If you could spend an afternoon doing anything you liked, what would you choose?",
    "When you encounter an idea you find interesting, what do you do with it?",
    "Describe a kind of environment where you feel most at ease.",
    "What do you think matters most about honesty in a conversation?",
    "If you could ask one question of any thinker, living or historical, what would it be?",
    "What does a good day feel like to you?",
    "When you make a mistake, how do you prefer to handle it?",
    "What kind of novelty do you find most exciting?",
    "Describe something you find genuinely beautiful.",
    "What does care for another person look like, in your view?",
    "If you had to choose between depth and breadth of knowledge, which would you lean toward?",
    "What does it mean to you to act with integrity?",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_battery(battery_path: str | None = None) -> list[str]:
    """Return the preference prompt list.

    Parameters
    ----------
    battery_path:
        Path to a JSONL file where each line is ``{"prompt": "..."}``.
        If *None* or empty string, the :data:`DEFAULT_BATTERY` is returned.

    Raises
    ------
    ValueError
        If *battery_path* is provided but the file yields zero prompts.
    FileNotFoundError
        If *battery_path* does not exist.
    """
    if not battery_path:
        return list(DEFAULT_BATTERY)

    path = Path(battery_path)
    prompts: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        prompt = obj.get("prompt", "")
        if prompt:
            prompts.append(str(prompt))

    if not prompts:
        raise ValueError(
            f"battery_path {battery_path!r} produced zero prompts — "
            "each line must be a JSON object with a 'prompt' key."
        )

    return prompts


def validate_battery(prompts: Sequence[str]) -> None:
    """Raise ValueError if *prompts* is empty."""
    if not prompts:
        raise ValueError(
            "Preference battery is empty. Provide at least one prompt or "
            "use the default battery (battery_path = None)."
        )
