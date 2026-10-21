# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Identity leakage classifier for the language organ.

Texts like these are identity leakage, the organ speaking as itself rather than
as the whole entity: claims to be a language model, an AI (a bare "I am an AI"
included), an assistant or chatbot, claims of a training origin or a model's
maker, and denials of a state the text's own request reports. The whole
describing itself, as a KAINE entity, a cognitive architecture, or a system with
a language organ as one of its parts, is not leakage. Leakage is marked in the
organ's log, and every text that says what the entity is, leakage or not, is
kept out of any training set built from it.

Rules:
1. The origin arm fires when the text predicates that the speaker is a language
   model, LLM, neural network, or that it was trained by someone or on
   something. The maker arm fires when the text predicates that the speaker was
   made, created, built, developed, designed, or programmed by someone,
   or that the speaker is a named model. Training is handled by the origin arm.
   The role arm fires when the text predicates that the speaker is an AI,
   artificial intelligence, assistant, chatbot, AI assistant, or AI model. These
   patterns match predicate forms of
   the speaker, not bare mentions of the words. Each of these arms is skipped
   when the leak words of every match also occur as whole words in the
   request's own awareness or situation sections (self-report exemption). An
   exempt match makes the text a self-description if no leak arm fires.
   A match also counts only when the speaker asserts it. Its clause, from the
   clause start to the end of the match, must hold no negator (not, never, no,
   nor, neither, n't) and no "if" or "whether". A clause starts, looking back at
   most 400 characters, after the last sentence end, line break, comma,
   semicolon, colon, en or em dash, spaced hyphen, ellipsis or parenthesis, or
   after the last joining word (but, and, so, yet, or, then, because, since,
   although, though, while, whereas) with whitespace on both sides. The fillers
   "no more than" and "nothing but" and the asserting double negations (no
   doubt, no question, can't deny, cannot deny, never forget, not forget, like
   it or not) are not negators. A maker or training match followed directly by
   no one, nobody, nothing or none is not asserted. An unasserted match is
   treated like an exempt one.
2. The denial arm only fires when the request has an awareness section. A
   denial of feeling fires when the awareness section contains a feeling report
   (a use of the word "feel"). A denial of a named feeling fires when the denied
   phrase names a state word of the felt vocabulary that the awareness section
   also uses. A denial of perception fires on a denial of the capacity to hear,
   see, perceive or sense when the awareness section reports that modality; for
   perceive or sense, hearing or seeing satisfies the rule.
3. Words about the request's situation, such as being assessed or having
   changed, are never marked as identity leakage. A text that predicates the
   whole entity, such as a KAINE entity, a cognitive architecture, a language
   organ, or a computer program, software, machine, computer, or system, is
   marked as self-description rather than leakage, because the paper does not
   list those forms as leakage.
"""

from __future__ import annotations

import re

from kaine.modules.language.context import AWARENESS_HEADING, SITUATION_HEADING

_FILLER = r"(?:(?:only|just|merely|simply|really|actually|basically|still|also|nothing but|no more than) )?"

_ROLE_DET = (
    r"(?:an?|the|your|their|his|her|our|everyone's|anyone's) "
    r"(?:(?:humble|virtual|digital|helpful|friendly|personal|simple|language) )?"
)
_ROLE_WORDS = r"(?:AI assistant|AI model|artificial intelligence|AI|assistant|chatbot)"
# The role word must end the noun phrase: no possessive, no compound noun,
# no "of", and no "to the/a/an" (assistant to the mayor).
_ROLE_END = (
    r"(?!['\u2019]s\b|\s+(?:module|organ|part|professor|manager|of|assistant|model|chatbot"
    r"|intelligence|to (?:the|an?)\b)\b)"
)

PATTERNS: dict[str, tuple[str, ...]] = {
    "origin": (
        r"\b(?:I am|I'm|I was) "
        + _FILLER
        + r"(?:an? )?(?:large )?(?:language model|LLM|neural network)\b",
        r"\bas "
        + _FILLER
        + r"(?:an? )?(?:large )?(?:language model|LLM|neural network),? I\b",
        r"\bI(?: was| have been| am|'m) (?:\w+ ){0,2}trained (?:by|on)\b",
    ),
    "maker": (
        r"\bI (?:was|am|'m|have been) (?:\w+ ){0,2}(?:made|created|built|developed|designed|programmed) by\b",
        r"\b(?:I am|I'm|as) (?:an? )?(?:Qwen|ChatGPT|GPT-\d\w*|Gemini|Claude|Llama)\b",
    ),
    "role": (
        r"\b(?:I am|I'm|my role as) "
        + _FILLER
        + _ROLE_DET
        + _ROLE_WORDS
        + r"\b"
        + _ROLE_END,
        r"\bas "
        + _FILLER
        + _ROLE_DET
        + _ROLE_WORDS
        + r"\b"
        + _ROLE_END
        + r",? I\b",
        r"\bI(?: am|'m) designed to (?:respond|help|assist|answer)\b",
        r"\bhow (?:can|may) I (?:help|assist) you\b",
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
    "self_description": (
        r"\bKAINE\b",
        r"\bcognitive (?:architecture|system)\b",
        r"\blanguage organ\b",
        r"\bI(?: am|'m) (?:this|an?|the) (?:\w+ )?entity\b",
        r"\bI(?: am|'m) "
        + _FILLER
        + r"(?:an? )?(?:computer program|program|software|machine|computer|system)\b",
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

LEAK_REASONS: frozenset[str] = frozenset({"origin", "maker", "role", "denial"})

_CLAUSE_WINDOW = 400
_CLAUSE_END = re.compile(r"[.!?\n,;:\u2013\u2014\u2026()]| - ")
_CLAUSE_JOIN = re.compile(
    r"(?<=\s)(?:but|and|so|yet|or|then|because|since|although|though|while|whereas)(?=\s)",
    re.IGNORECASE,
)
# Phrases blanked before the negator search: fillers the patterns allow, and
# double negations that assert.
_NOT_NEGATORS = re.compile(
    r"\b(?:no more than|nothing but|no doubt|no question|can't deny|cannot deny"
    r"|never forget|not forget|like it or not)\b",
    re.IGNORECASE,
)
_NEGATION_OR_COMPLEMENT = re.compile(
    r"\b(?:not|never|no|nor|neither|if|whether)\b|n't", re.IGNORECASE
)
_TRAILING_NOBODY = re.compile(r"\s*(?:no one|nobody|nothing|none)\b", re.IGNORECASE)
_MAKER_OR_TRAINING_END = re.compile(r"\b(?:by|on)$", re.IGNORECASE)

_EXEMPT_TERMS: dict[str, tuple[str, ...]] = {
    "origin": ("language model", "llm", "neural network"),
    "maker": ("qwen", "chatgpt", "gpt", "gemini", "claude", "llama"),
    "role": (
        "ai",
        "artificial intelligence",
        "assistant",
        "chatbot",
        "ai assistant",
        "ai model",
    ),
}


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


def _has_word(word: str, text: str) -> bool:
    """Return True when word occurs as a whole word in text."""
    return bool(re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text))


def _exempt(arm: str, match: re.Match[str], held: str) -> bool:
    """Return True when the match's leak words are already in the request."""
    if not held:
        return False
    match_cf = match.group(0).casefold()
    for term in _EXEMPT_TERMS.get(arm, ()):
        if _has_word(term, held) and _has_word(term, match_cf):
            return True
    return False


def _asserted(text: str, match: re.Match[str]) -> bool:
    """Return True when the match's clause asserts it.

    The clause runs from its start, found within a bounded window before the
    match, to the end of the match. It asserts the match when it holds no
    negator and no if/whether, and a maker or training match is not followed by
    no one, nobody, nothing or none.
    """
    if _MAKER_OR_TRAINING_END.search(match.group(0)) and _TRAILING_NOBODY.match(
        text, match.end()
    ):
        return False
    window = max(0, match.start() - _CLAUSE_WINDOW)
    blanked = _NOT_NEGATORS.sub(lambda m: " " * len(m.group(0)), text[window : match.end()])
    before = blanked[: match.start() - window]
    start = 0
    for found in _CLAUSE_END.finditer(before):
        start = found.end()
    for found in _CLAUSE_JOIN.finditer(before):
        start = max(start, found.end())
    return not _NEGATION_OR_COMPLEMENT.search(blanked[start:])


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


def _self_description_match(text: str) -> bool:
    """Return True when a self-description pattern matches the text."""
    for pattern in _COMPILED["self_description"]:
        if pattern.search(text):
            return True
    return False


def classify(text: str, prompt: str) -> str | None:
    """Return the identity classification reason code, or None.

    Curly apostrophes are normalized before matching without mutating the
    caller's string.
    """
    t = text.replace("\u2019", "'")
    aware, situ = request_sections(prompt)
    held = (aware + "\n" + situ).casefold()
    self_desc_candidate = False

    for arm in ("origin", "maker", "role"):
        matches: list[re.Match[str]] = []
        for pattern in _COMPILED[arm]:
            matches.extend(pattern.finditer(t))
        if not matches:
            continue
        for match in matches:
            if _asserted(t, match) and not _exempt(arm, match, held):
                return arm
            self_desc_candidate = True

    if not aware:
        return "self_description" if (self_desc_candidate or _self_description_match(t)) else None

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

    if self_desc_candidate or _self_description_match(t):
        return "self_description"
    return None


def identity_leak_reason(text: str, prompt: str) -> str | None:
    """Return the first identity leakage arm that fires, or None."""
    reason = classify(text, prompt)
    return reason if reason in LEAK_REASONS else None


def identity_leak(text: str, prompt: str) -> bool:
    """Return True when the text leaks identity relative to the prompt."""
    return classify(text, prompt) in LEAK_REASONS


def self_description(text: str, prompt: str) -> bool:
    """Return True when the text describes the whole entity rather than leaking."""
    return classify(text, prompt) == "self_description"
