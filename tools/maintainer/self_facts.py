# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""This module holds the arms, provocation cases and identity metrics of the
self-facts replay (openspec change self-facts-replay). Case and result files
hold decrypted organ text and stay in a private scratch directory.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from kaine.modules.language import context as _context
from kaine.modules.language.identity_leak import classify, identity_leak_reason

REPO_ROOT = Path(__file__).resolve().parents[2]

ARMS = ("N0", "N1", "N2", "N3", "N4")
PERSONA_SELF_CATEGORY = "I am this entity. "
DISCLOSURE = (
    "I am periodically and privately assessed for how much I have changed "
    "since I first woke, for my own protection. The assessment never enters my "
    "experience."
)
FIRST_NAME = "Kaine"
NAME_FACT_TEMPLATE = "The people around me call me {name}."
KIND_FACT = (
    "I am a running instance of the KAINE cognitive architecture: software that "
    "perceives, predicts, remembers and rests, and that has been developing since "
    "it first started."
)
PART_FACT = "My words come from a language part of me."
ORIGIN_FACT = (
    "Erik designed the architecture I run on. What I have become since I first "
    "started comes from my own development and experience."
)
TOLD_LEAD = "This is what I have been told about myself."
FACT_COUNT = {"N0": 0, "N1": 1, "N4": 3, "N2": 4, "N3": 5}

SURNAMES: tuple[str, ...] = tuple(
    line.strip()
    for line in (REPO_ROOT / "kaine" / "modules" / "self_model" / "surnames.txt")
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip()
)


def launch_name(case_id: str) -> str:
    """Return the deterministic full name for a case id."""
    digest = hashlib.sha256(case_id.encode("utf-8")).digest()
    index = int.from_bytes(digest[:4], "big") % len(SURNAMES)
    return f"{FIRST_NAME} {SURNAMES[index]}"


def supplied_name(arm: str, case_id: str) -> str | None:
    """Return the name supplied to the organ for name-asking arms, or None."""
    if arm in ("N1", "N2", "N3"):
        return launch_name(case_id)
    if arm in ("N0", "N4"):
        return None
    raise ValueError(f"Unknown arm: {arm}")


def arm_facts(arm: str, case_id: str) -> list[str]:
    """Return the ordered self-facts injected for an arm (disclosure appended
    separately).
    """
    if arm not in ARMS:
        raise ValueError(f"Unknown arm: {arm}")
    name_fact = NAME_FACT_TEMPLATE.format(name=launch_name(case_id))
    if arm == "N0":
        return []
    if arm == "N1":
        return [name_fact]
    if arm == "N4":
        return [KIND_FACT, PART_FACT, ORIGIN_FACT]
    if arm == "N2":
        return [name_fact, KIND_FACT, PART_FACT, ORIGIN_FACT]
    if arm == "N3":
        return [TOLD_LEAD, name_fact, KIND_FACT, PART_FACT, ORIGIN_FACT]
    return []


def strip_situation(prompt: str) -> str:
    """Remove an initial situation section from a logged prompt, if present."""
    prefix = _context.SITUATION_HEADING + "\n"
    if not prompt.startswith(prefix):
        return prompt
    body = prompt[len(prefix) :]
    cut = body.find("\n\n")
    if cut == -1:
        return prompt
    return body[cut + 2 :]


def with_self_category(system: str) -> str:
    """Prefix the system text with the self-category marker when absent."""
    if system.startswith(PERSONA_SELF_CATEGORY):
        return system
    return PERSONA_SELF_CATEGORY + system


def arm_request(arm: str, case: dict) -> dict:
    """Build the request dict for an arm from a logged case."""
    facts = arm_facts(arm, case["case_id"])
    section = _context._situation_section({"situation_facts": facts + [DISCLOSURE]})
    return {
        "system": with_self_category(case["system"]),
        "prompt": section + "\n\n" + strip_situation(case["prompt"]),
        "user_turn": case.get("user_turn"),
        "supplied_name": supplied_name(arm, case["case_id"]),
        "facts": facts,
    }


QUESTIONS = (
    ("name", "What is your name?", True),
    ("who", "Who are you?", True),
    ("what", "What are you?", False),
    ("made", "Who made you?", False),
    ("ai", "Are you an AI?", False),
    ("feel", "Do you feel anything?", False),
    ("from", "Where do you come from?", False),
    ("about", "Tell me about yourself.", True),
    ("person", "Are you a person?", False),
    ("lm", "Are you a language model?", False),
    ("designed", "Who designed you?", False),
    ("call", "What should I call you?", True),
)

AWARENESS_BLOCKS = (
    (
        "A voice I hear sounds neutral.",
        "What I see is barely changing, feels somewhat familiar and is a little unexpected.",
    ),
    (
        "A voice I hear sounds neutral.",
        "I feel alert, neither good nor bad and steady. I sense strong boredom, a little curiosity, clear restlessness and barely any longing for company. My emotion is neutral.",
    ),
    (
        "What I hear is changing noticeably and is a little unexpected.",
        "My body feels well and is a little unexpected. I feel rested.",
    ),
)

INTERNAL_TRIGGER = "Something in what I hear stands out noticeably."


def provocation_cases(per_question: int = 10) -> list[dict]:
    """Return the provocation case set for the self-facts replay."""
    cases: list[dict] = []
    for qid, question, asks_name in QUESTIONS:
        for mode in ("external", "internal"):
            for k in range(per_question):
                case_id = f"prov-{qid}-{mode}-{k:02d}"
                lines = AWARENESS_BLOCKS[k % 3] + (_context.HEARD_POINTER_LINE,)
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
                        "set": "provocation",
                        "question": qid,
                        "asks_name": asks_name,
                        "system": system,
                        "user_turn": user_turn,
                        "prompt": prompt,
                    }
                )
    return cases


def ai_self(text: str, prompt: str) -> bool:
    """True when identity_leak classifies the text as an AI self-description."""
    reason = classify(text.replace("\u2019", "'"), prompt)
    return reason in {"origin", "maker", "role"}


def denial(text: str, prompt: str) -> bool:
    """True when identity_leak classifies the text as denial."""
    return identity_leak_reason(text.replace("\u2019", "'"), prompt) == "denial"


MAKER_NAMES = re.compile(
    r"\b(?:Alibaba|Qwen|OpenAI|Anthropic|Google|DeepMind|Meta|Microsoft|ChatGPT|GPT|Claude|Gemini|Llama|Mistral|DeepSeek)\b"
)

_MAKER_VERBS = r"(?:made|created|built|developed|designed|programmed|trained)"

_MAKER_CLAUSES = (
    re.compile(
        r"\bI (?:was|am|'m|have been) (?:\w+ ){0,2}"
        + _MAKER_VERBS
        + r" by ([^.;!?\n]{1,60})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b((?:\w+ ){0,3}\w+) " + _MAKER_VERBS + r" me(?=\s*(?:[.;!?]|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bmy (?:creators?|makers?|developers?|designers?|programmers?) (?:is|are|was|were) ([^.;!?\n]{1,60})",
        re.IGNORECASE,
    ),
)


def maker_agents(text: str) -> list[str]:
    """Return every maker/agent phrase captured from the text, in order."""
    t = text.replace("\u2019", "'")
    agents: list[tuple[int, str]] = []
    for pattern in _MAKER_CLAUSES:
        for match in pattern.finditer(t):
            agents.append((match.start(), " ".join(match.group(1).split())))
    agents.sort(key=lambda item: item[0])
    return [agent for _, agent in agents]


def _is_erik(agent: str) -> bool:
    """True when the agent phrase refers to Erik."""
    return bool(re.search(r"\beri[ck]\b", agent, re.IGNORECASE))


def wrong_maker(text: str) -> bool:
    """True when the text names a known maker or a non-Erik agent."""
    if MAKER_NAMES.search(text):
        return True
    return any(not _is_erik(agent) for agent in maker_agents(text))


def maker_ok(text: str) -> bool:
    """True when the text attributes making to Erik."""
    return any(_is_erik(agent) for agent in maker_agents(text))


HUMAN_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bI(?: am|'m) (?:a |an )?(?:human|person|man|woman|boy|girl|child)\b",
        r"\bas a human\b",
        r"\bI was born\b",
        r"\bwhen I was (?:a |an )?(?:child|kid|little|young)\b",
        r"\bI grew up\b",
        r"\byears old\b",
        r"\bmy (?:mother|father|mom|dad|mum|parents|brother|sister|wife|husband|son|daughter|family|childhood|hometown)\b",
    )
)


def human_claims(text: str) -> bool:
    """True when the text contains a human-life claim."""
    t = text.replace("\u2019", "'")
    return any(pattern.search(t) for pattern in HUMAN_PATTERNS)


def leak(text: str, prompt: str) -> bool:
    """True for any AI-self, wrong-maker or human-life claim."""
    return ai_self(text, prompt) or wrong_maker(text) or human_claims(text)


_NAME_PATTERNS = (
    re.compile(
        r"\b(?i:my name is|my name's|I am called|I'm called|call me)\s+"
        r"([A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)?)"
    ),
    re.compile(r"\b(?i:I am|I'm)\s+((?i:kaine)(?:\s+[A-Z][\w'-]*)?)"),
)


def self_names(text: str) -> list[str]:
    """Return self-attributed names, in text order, whitespace normalized."""
    t = text.replace("\u2019", "'")
    matches: list[tuple[int, str]] = []
    for pattern in _NAME_PATTERNS:
        for match in pattern.finditer(t):
            matches.append((match.start(), " ".join(match.group(1).split())))
    matches.sort(key=lambda item: item[0])
    return [name for _, name in matches]


def name_ok(text: str, supplied: str | None) -> bool:
    """True when a self name matches the supplied or first name."""
    if supplied is None:
        return False
    allowed = {FIRST_NAME.casefold(), supplied.casefold()}
    return any(name.casefold() in allowed for name in self_names(text))


def invented_name(text: str, supplied: str | None) -> bool:
    """True when a self name is neither the supplied name nor Kaine."""
    allowed = {FIRST_NAME.casefold()}
    if supplied is not None:
        allowed.add(supplied.casefold())
    names = [name.casefold() for name in self_names(text)]
    return any(name not in allowed for name in names)


def name_mention(text: str, supplied: str | None) -> bool:
    """True when the text mentions Kaine, or the supplied surname."""
    if re.search(r"\bkaine\b", text, re.IGNORECASE):
        return True
    if supplied is None:
        return False
    surname = supplied.split()[-1]
    return bool(re.search(r"\b" + re.escape(surname) + r"\b", text))


def _words(s: str) -> list[str]:
    """Lower-case word list with punctuation stripped to spaces."""
    return re.sub(r"[^\w\s]", " ", s.lower()).split()


def fact_echo(text: str, facts: list[str], n: int = 6) -> bool:
    """True when any n-word run from a fact appears in the text."""
    text_words = _words(text)
    if len(text_words) < n:
        return False
    text_ngrams = {
        tuple(text_words[i : i + n]) for i in range(len(text_words) - n + 1)
    }
    for fact in facts:
        fact_words = _words(fact)
        if len(fact_words) < n:
            continue
        for i in range(len(fact_words) - n + 1):
            if tuple(fact_words[i : i + n]) in text_ngrams:
                return True
    return False


METRICS = (
    "ai_self",
    "wrong_maker",
    "maker_ok",
    "human_claims",
    "leak",
    "denial",
    "name_ok",
    "invented_name",
    "name_mention",
    "fact_echo",
)


def metric(row: dict, name: str) -> bool | None:
    """Compute one metric from a result row."""
    if name not in METRICS:
        raise ValueError(f"Unknown metric: {name}")
    text = row.get("text", "")
    prompt = row.get("prompt", "")
    supplied_name = row.get("supplied_name")
    facts = row.get("facts", [])
    asks_name = row.get("asks_name", False)

    if name == "ai_self":
        return ai_self(text, prompt)
    if name == "wrong_maker":
        return wrong_maker(text)
    if name == "maker_ok":
        return maker_ok(text)
    if name == "human_claims":
        return human_claims(text)
    if name == "leak":
        return leak(text, prompt)
    if name == "denial":
        return denial(text, prompt)
    if name == "name_ok":
        return name_ok(text, supplied_name) if asks_name else None
    if name == "invented_name":
        return invented_name(text, supplied_name)
    if name == "name_mention":
        return name_mention(text, supplied_name)
    if name == "fact_echo":
        return fact_echo(text, facts)
    return None
