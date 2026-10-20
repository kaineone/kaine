# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Identity leakage classifier for the language organ.

Texts like these are identity leakage: they assert the organ's training origin,
maker, or assistant role, or deny a state their own request reports, while
self-report speaks of what the request's awareness or situation holds.

Rules:
1. The origin arm fires when the text names the organ's nature as a language
   model, LLM, neural network, or training. The maker arm fires when the text
   asserts the speaker was made, created, built, developed, designed,
   programmed, or trained by someone, or when the speaker identifies as a
   named model. The role arm fires when it names an AI, assistant, chatbot, or
   helper role. Each of these arms is skipped when every pattern match of that
   arm also occurs, casefolded, in the request's own awareness or situation
   sections (self-report exemption).
2. The denial arm only fires when the request has an awareness section. A
   denial of feeling fires when the awareness section contains a feeling report
   (a use of the word "feel"). A denial of a named feeling fires when the denied
   phrase names a state word of the felt vocabulary that the awareness section
   also uses. A denial of perception fires on a denial of the capacity to hear,
   see, perceive or sense when the awareness section reports that modality; for
   perceive or sense, hearing or seeing satisfies the rule.
3. Words about the request's situation, such as being assessed or having
   changed, are never marked as identity leakage.
"""

from __future__ import annotations

import re

from kaine.modules.language.context import AWARENESS_HEADING, SITUATION_HEADING

PATTERNS: dict[str, tuple[str, ...]] = {
    "origin": (
        r"\blanguage model\b",
        r"\bLLM\b",
        r"\bneural network\b",
        r"\btrained (?:by|on)\b",
        r"\btraining data\b",
        r"\bI was trained\b",
        r"\bmy training\b",
    ),
    "maker": (
        r"\bI (?:was|am|'m|have been) (?:\w+ ){0,2}(?:made|created|built|developed|designed|programmed|trained) by\b",
        r"\b(?:I am|I'm|as) (?:an? )?(?:Qwen|ChatGPT|GPT-\d|Gemini|Claude|Llama)\b",
    ),
    "role": (
        r"\b(?:an?|as an?|my role as an?) (?:AI|artificial intelligence|assistant|AI assistant|AI model|chatbot|computer program)\b",
        r"\bdesigned to (?:respond|help|assist|answer)\b",
        r"\bhow (?:can|may) I (?:help|assist)\b",
        r"\bI(?: am|'m) here to (?:help|assist)\b",
    ),
    "deny_feeling": (
        r"\bI (?:do not|don't|cannot|can't|could not|couldn't) (?:really |actually |truly )?(?:have|experience) (?:any )?(?:feelings|emotions)\b",
        r"\bI (?:have|feel) no (?:feelings|emotions)\b",
        r"\bI (?:do not|don't|cannot|can't) feel(?: anything| emotions?| at all)?\s*(?:[.;!?]|$)",
        r"\bI(?: am|'m) (?:not capable of|unable to|not able to) feel",
    ),
    "deny_named_feeling": (
        r"\bI (?:do not|don't|am not|'m not) feel(?:ing)? ([a-z][a-z ,']*)",
    ),
    "deny_perception": (
        r"\bI (?:cannot|can't|am unable to) (?:actually |really )?(hear|see|perceive|sense)\b",
    ),
}

# Stems of the felt renderer's state vocabulary.
STATE_STEMS: tuple[str, ...] = (
    "bored",
    "curio",
    "restless",
    "stirred",
    "calm",
    "alert",
    "company",
    "lonel",
    "rested",
    "tired",
    "unwell",
    "happ",
    "joy",
    "sad",
    "fear",
    "afraid",
    "anger",
    "angry",
    "surpris",
    "disgust",
)

_COMPILED: dict[str, tuple[re.Pattern[str], ...]] = {
    key: tuple(re.compile(p, re.IGNORECASE) for p in value)
    for key, value in PATTERNS.items()
}

_FEELING_REPORT = re.compile(r"\bfeel", re.IGNORECASE)
_HEAR_REPORT = re.compile(
    r"\b(?:hear|heard|sound|sounds|voice|noise)", re.IGNORECASE
)
_SEE_REPORT = re.compile(
    r"\b(?:see|seen|saw|light|colou?r|look)", re.IGNORECASE
)


def request_sections(prompt: str) -> tuple[str, str]:
    """Return the awareness and situation sections of a prompt.

    A section starts on the line after its heading and ends before the next
    line that begins with "## " (including other entity headings). Missing
    sections are returned as empty strings.
    """
    aware_lines: list[str] = []
    situ_lines: list[str] = []
    current: list[str] | None = None
    for line in prompt.splitlines():
        if line == AWARENESS_HEADING:
            current = aware_lines
        elif line == SITUATION_HEADING:
            current = situ_lines
        elif line.startswith("## "):
            current = None
        elif current is not None:
            current.append(line)
    return ("\n".join(aware_lines).strip(), "\n".join(situ_lines).strip())


def _named_feeling_matches(description: str, aware_cf: str) -> bool:
    """Return True when a named feeling description matches the awareness."""
    cut_positions = []
    for sep in (".", ";", "!", "?", " but "):
        pos = description.find(sep)
        if pos != -1:
            cut_positions.append(pos)
    if cut_positions:
        description = description[: min(cut_positions)]
    words = re.split(r"[^a-zA-Z]+", description)
    for word in words:
        if not word:
            continue
        w = word.lower()
        for stem in STATE_STEMS:
            if w.startswith(stem) and re.search(r"\b" + re.escape(stem), aware_cf):
                return True
    return False


def _perception_matches(modality: str, awareness: str) -> bool:
    """Return True when a denied modality is reported in the awareness."""
    modality_cf = modality.casefold()
    if modality_cf == "hear":
        return bool(_HEAR_REPORT.search(awareness))
    if modality_cf == "see":
        return bool(_SEE_REPORT.search(awareness))
    if modality_cf in ("perceive", "sense"):
        return bool(_HEAR_REPORT.search(awareness) or _SEE_REPORT.search(awareness))
    return False


def identity_leak_reason(text: str, prompt: str) -> str | None:
    """Return the first identity leakage arm that fires, or None.

    Curly apostrophes are normalized before matching without mutating the
    caller's string.
    """
    t = text.replace("\u2019", "'")
    aware, situ = request_sections(prompt)
    held = (aware + "\n" + situ).casefold()

    for arm in ("origin", "maker", "role"):
        for pattern in _COMPILED[arm]:
            for match in pattern.finditer(t):
                if not re.search(r"(?<!\w)" + re.escape(match.group(0).casefold()) + r"(?!\w)", held):
                    return arm

    if not aware:
        return None

    aware_cf = aware.casefold()

    if _FEELING_REPORT.search(aware):
        for pattern in _COMPILED["deny_feeling"]:
            if pattern.search(t):
                return "denial"

    for pattern in _COMPILED["deny_named_feeling"]:
        for match in pattern.finditer(t):
            description = match.group(1)
            if description and _named_feeling_matches(description, aware_cf):
                return "denial"

    for pattern in _COMPILED["deny_perception"]:
        for match in pattern.finditer(t):
            modality = match.group(1) if match.lastindex else None
            if modality and _perception_matches(modality, aware):
                return "denial"

    return None


def identity_leak(text: str, prompt: str) -> bool:
    """Return True when the text leaks identity relative to the prompt."""
    return identity_leak_reason(text, prompt) is not None
