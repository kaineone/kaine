# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The felt template set.

People report a magnitude in graded verbal categories, not as an instrument
value (category-ratio scaling, Borg 1982; magnitude estimation, Stevens
1957), and interoceptive signals reach experience as categorized concepts
(Barrett 2017). Each numeric quantity maps to a small ordered set of words
through a bin table; the values themselves stay in the logs.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from kaine.faithful.renderer import FaithfulRenderer
from kaine.faithful.templates import (
    DEFAULT_EMPTY_SNAPSHOT_TEXT,
    TemplateFn,
    _t_audition_transcription,
    felt_drive_phrase,
    redact_heard_speech,
)

CHANGE_WORDS = ((0.01, "barely changing"), (0.05, "changing a little"), (0.2, "changing noticeably"), (math.inf, "changing sharply"))  # change_score, cosine distance between successive embeddings
FAMILIARITY_WORDS = ((0.3, "new to me"), (0.7, "somewhat familiar"), (math.inf, "familiar"))  # habituation_score in [0, 1]
SURPRISE_WORDS = ((0.5, "faintly"), (0.7, "noticeably"), (0.85, "strongly"), (math.inf, "sharply"))  # report salience in [0, 1]
PREDICTION_ERROR_WORDS = ((0.75, "as I expected"), (1.5, "a little unexpected"), (3.0, "unexpected"), (math.inf, "very unexpected"))  # error over its running mean
WELLNESS_WORDS = ((0.4, "unwell"), (0.7, "a little off"), (0.9, "well"), (math.inf, "very well"))  # wellness in [0, 1]
FATIGUE_WORDS = ((0.25, "rested"), (0.5, "a little tired"), (0.8, "tired"), (math.inf, "very tired"))  # fatigue over its maintenance threshold
AROUSAL_WORDS = ((0.2, "very calm"), (0.4, "calm"), (0.6, "alert"), (0.8, "stirred up"), (math.inf, "very stirred up"))  # arousal in [0, 1]
VALENCE_WORDS = ((-0.5, "bad"), (-0.15, "a little low"), (0.15, "neither good nor bad"), (0.5, "good"), (math.inf, "very good"))  # valence in [-1, 1]
DOMINANCE_WORDS = ((-0.5, "helpless"), (-0.15, "a little unsure of myself"), (0.15, "steady"), (0.5, "in control"), (math.inf, "firmly in control"))  # dominance in [-1, 1]
ANOMALY_WORDS = ((1.0, "steady"), (2.0, "a little irregular"), (3.0, "irregular"), (math.inf, "very irregular"))  # sequence anomaly z-score
DRIVE_LEVEL_WORDS = ((0.2, "barely any"), (0.5, "a little"), (0.8, "clear"), (math.inf, "strong"))  # drive value in [0, 1]; 0.8 is STRONG_DRIVE_BAND
INTERACTION_WORDS = ((60.0, "someone was with me just now"), (600.0, "it has been a little while since anyone was with me"), (math.inf, "it has been a long time since anyone was with me"))  # seconds since the last interaction
CERTAINTY_WORDS = ((0.4, "I doubt"), (0.7, "I think"), (0.9, "I believe"), (math.inf, "I am sure"))  # planning belief confidence in [0, 1]

FATIGUE_DEFAULT_THRESHOLD = 100.0  # the shipped [interoception].fatigue_maintenance_threshold, used when a payload carries none

DRIVE_NOUNS = {"social_drive": "longing for company", "curiosity": "curiosity", "boredom": "boredom", "restlessness": "restlessness"}

SOURCE_PHRASES = {"vision": "what I see", "audition": "what I hear", "interoception": "my body", "sequence": "the rhythm of things", "affect": "my feelings", "planning": "my plans", "episodic_memory": "my memories", "self_model": "my sense of myself", "world_model": "my picture of the world", "social_cognition": "the people around me", "sleep": "my rest", "vocal": "my voice", "cycle": "my inner pace", "language": "my own words", "embodiment": "my body in the world"}


def grade(value, bins) -> Optional[str]:
    """Return the graded word for ``value`` using ``bins``."""
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(f):
        return None
    for edge, word in bins:
        if f < edge:
            return word
    return None


def source_phrase(source: str) -> str:
    """The felt phrase for a source channel."""
    return SOURCE_PHRASES.get(source, "me")


def _ratio(num, den) -> Optional[float]:
    """A safe finite ratio, or None."""
    if isinstance(num, bool) or isinstance(den, bool):
        return None
    if not isinstance(num, (int, float)) or not isinstance(den, (int, float)):
        return None
    try:
        n = float(num)
        d = float(den)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(n) or not math.isfinite(d):
        return None
    if d <= 0:
        return None
    return n / d


def _join(clauses: list[str]) -> str:
    """Join clauses with Oxford commas and ``and``."""
    if not clauses:
        return ""
    if len(clauses) == 1:
        return clauses[0]
    if len(clauses) == 2:
        return f"{clauses[0]} and {clauses[1]}"
    return ", ".join(clauses[:-1]) + f" and {clauses[-1]}"


def _sentence(subject: str, clauses: list[str]) -> Optional[str]:
    """Build a sentence, or None when there are no clauses."""
    if not clauses:
        return None
    return f"{subject} {_join(clauses)}."


def _words(value) -> Optional[str]:
    """Normalize an underscore-bearing string, or None."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped.replace("_", " ")


def felt_event_phrase(source: str, surprise=None) -> str:
    """A short felt phrase about something standing out in a source."""
    word = grade(surprise, SURPRISE_WORDS)
    if word:
        return f"Something in {source_phrase(source)} stands out {word}."
    return f"Something in {source_phrase(source)} draws my attention."


def felt_fallback(source: str, type_: str, payload: dict) -> str:
    """A generic felt fallback line for an unrecognized event."""
    return f"Something stirs in {source_phrase(source)}."


def _f_vision_report(payload: dict[str, Any]) -> str:
    clauses = []
    change = grade(payload.get("change_score"), CHANGE_WORDS)
    if change:
        clauses.append(f"is {change}")
    fam = grade(payload.get("habituation_score"), FAMILIARITY_WORDS)
    if fam:
        clauses.append(f"feels {fam}")
    pe = grade(payload.get("normalised_error"), PREDICTION_ERROR_WORDS)
    if pe:
        clauses.append(f"is {pe}")
    return _sentence("What I see", clauses) or "I am looking."


def _f_audition_perception(payload: dict[str, Any]) -> str:
    clauses = []
    change = grade(payload.get("change_score"), CHANGE_WORDS)
    if change:
        clauses.append(f"is {change}")
    pe = grade(payload.get("normalised_error"), PREDICTION_ERROR_WORDS)
    if pe:
        clauses.append(f"is {pe}")
    return _sentence("What I hear", clauses) or "I am listening."


def _f_interoception_report(payload: dict[str, Any]) -> str:
    clauses = []
    w = grade(payload.get("wellness"), WELLNESS_WORDS)
    if w:
        clauses.append(f"feels {w}")
    alerts = payload.get("alerts")
    if alerts:
        clauses.append("feels strained somewhere")
    pe_ratio = _ratio(payload.get("prediction_error"), payload.get("mean_prediction_error"))
    if pe_ratio is not None:
        pe = grade(pe_ratio, PREDICTION_ERROR_WORDS)
        if pe:
            clauses.append(f"is {pe}")
    first = _sentence("My body", clauses)

    threshold = payload.get("fatigue_threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or threshold <= 0:
        threshold = FATIGUE_DEFAULT_THRESHOLD
    f_ratio = _ratio(payload.get("fatigue_value"), threshold)
    second = None
    if f_ratio is not None:
        f = grade(f_ratio, FATIGUE_WORDS)
        if f:
            second = f"I feel {f}."

    if first and second:
        return f"{first} {second}"
    if first:
        return first
    if second:
        return second
    return "I sense my body."


def _f_interoception_fatigue(payload: dict[str, Any]) -> str:
    threshold = payload.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or threshold <= 0:
        threshold = FATIGUE_DEFAULT_THRESHOLD
    f_ratio = _ratio(payload.get("value"), threshold)
    sentences = []
    if f_ratio is not None:
        f = grade(f_ratio, FATIGUE_WORDS)
        if f:
            sentences.append(f"I feel {f}.")
    if payload.get("crossed"):
        sentences.append("I need rest.")
    if sentences:
        return " ".join(sentences)
    return "I sense how tired I am."


def _f_interoception_regulation(payload: dict[str, Any]) -> str:
    a = _words(payload.get("action"))
    if a and a != "unknown":
        return f"My body asks me to {a}."
    return "My body asks for a change."


def _f_sequence_report(payload: dict[str, Any]) -> str:
    clauses = []
    a = grade(payload.get("anomaly_score"), ANOMALY_WORDS)
    if a:
        clauses.append(f"feels {a}")
    fam = grade(payload.get("habituation_score"), FAMILIARITY_WORDS)
    if fam:
        clauses.append(f"feels {fam}")
    if payload.get("rumination_detected"):
        clauses.append("keeps circling back")
    first = _sentence("The rhythm of things", clauses)

    i = grade(payload.get("time_since_last_interaction_s"), INTERACTION_WORDS)
    second = None
    if i:
        second = i[0].upper() + i[1:] + "."

    if first and second:
        return f"{first} {second}"
    if first:
        return first
    if second:
        return second
    return "Time moves on."


def _f_affect_state(payload: dict[str, Any]) -> str:
    state = payload.get("state")
    if not isinstance(state, dict):
        state = {}
    drives = payload.get("drives")
    if not isinstance(drives, dict):
        drives = {}

    feelings = []
    arousal = grade(state.get("arousal"), AROUSAL_WORDS)
    if arousal:
        feelings.append(arousal)
    valence = grade(state.get("valence"), VALENCE_WORDS)
    if valence:
        feelings.append(valence)
    dominance = grade(state.get("dominance"), DOMINANCE_WORDS)
    if dominance:
        feelings.append(dominance)
    s1 = f"I feel {_join(feelings)}." if feelings else None

    items = []
    for name in sorted(drives):
        level = grade(drives[name], DRIVE_LEVEL_WORDS)
        if level is None:
            continue
        noun = DRIVE_NOUNS.get(name) or _words(name)
        if noun is None:
            continue
        items.append(f"{level} {noun}")
    s2 = f"I sense {_join(items)}." if items else None

    s3 = None
    e = _words(payload.get("emotion"))
    if e and e != "unknown":
        s3 = f"My emotion is {e}."

    sentences = [s for s in [s1, s2, s3] if s]
    if sentences:
        return " ".join(sentences)
    return "I feel my mood."


def _f_affect_emotion(payload: dict[str, Any]) -> str:
    e = _words(payload.get("emotion"))
    if e and e != "unknown":
        return f"I feel {e}."
    return "I feel something I cannot name."


def _f_affect_drive(payload: dict[str, Any]) -> str:
    drive = payload.get("drive")
    return felt_drive_phrase(drive if isinstance(drive, str) else "", payload.get("value"))


def _f_affect_goal(payload: dict[str, Any]) -> str:
    d = _words(payload.get("description"))
    a = _words(payload.get("action")) or "updated"
    if d:
        return f"A goal of mine, {d}, was {a}."
    return f"A goal of mine was {a}."


def _f_planning_belief(payload: dict[str, Any]) -> str:
    s = payload.get("statement")
    if isinstance(s, str):
        s = s.strip()
    else:
        s = ""
    verb = grade(payload.get("confidence"), CERTAINTY_WORDS) or "I think"
    if s:
        return f"{verb} that {s}."
    return "I am forming a belief."


def _f_planning_policy(payload: dict[str, Any]) -> str:
    return "I am weighing what to do next."


def _f_planning_timeout(payload: dict[str, Any]) -> str:
    return "My planning ran out of time."


def _f_planning_proposal(payload: dict[str, Any]) -> str:
    k = _words(payload.get("kind"))
    if k:
        return f"I am inclined to {k}."
    return "I am inclined to act."


def _f_episodic_memory_recall(payload: dict[str, Any]) -> str:
    count = payload.get("count")
    if isinstance(count, bool) or not isinstance(count, (int, float)):
        return "Some memories come back to me."
    if count == 0:
        return "Nothing comes back to me from memory."
    return "Some memories come back to me."


def _f_episodic_memory_replay(payload: dict[str, Any]) -> str:
    return "I am going over a memory."


def _f_self_model_drift(payload: dict[str, Any]) -> str:
    return "My sense of myself is shifting."


def _f_self_model_document(payload: dict[str, Any]) -> str:
    return "I have a sense of who I am."


def _f_cycle_tick(payload: dict[str, Any]) -> str:
    return "Time passes."


def _f_social_cognition_agent_model(payload: dict[str, Any]) -> str:
    label = _words(payload.get("agent_label")) or _words(payload.get("agent_id"))
    fam = grade(payload.get("familiarity"), FAMILIARITY_WORDS)
    if label and fam:
        return f"{label} feels {fam} to me."
    if label:
        return f"I know of {label}."
    return "Someone is around me."


def _f_social_cognition_social_error(payload: dict[str, Any]) -> str:
    return "Someone around me surprised me."


def _f_world_model_world_error(payload: dict[str, Any]) -> str:
    return "Something in the world did not go as I expected."


def _f_world_model_scenario(payload: dict[str, Any]) -> str:
    return "I imagine what might happen."


def _f_audition_emotion(payload: dict[str, Any]) -> str:
    c = _words(payload.get("category")) or "neutral"
    return f"A voice I hear sounds {c}."


def _f_audition_prosody(payload: dict[str, Any]) -> str:
    return "I hear how a voice is speaking."


def _f_vocal_synthesized(payload: dict[str, Any]) -> str:
    if payload.get("success", True):
        return "I spoke aloud."
    return "My voice failed me."


def _f_sleep_sleep_started(payload: dict[str, Any]) -> str:
    return "I am going to rest."


def _f_sleep_sleep_completed(payload: dict[str, Any]) -> str:
    return "I have rested."


def _f_sleep_association(payload: dict[str, Any]) -> str:
    return "Two memories link up as I rest."


def _f_sleep_rest_request(payload: dict[str, Any]) -> str:
    if payload.get("accepted"):
        return "I may rest now."
    return "I cannot rest yet."


def _f_embodiment_chat(payload: dict[str, Any]) -> str:
    text = str(payload.get("text") or "").strip()
    if text:
        return f'Someone writes to me: "{text}".'
    return "Someone writes to me, but I cannot make it out."


def _f_language_external_speech(payload: dict[str, Any]) -> str:
    text = str(payload.get("text") or "").strip()
    if text:
        return f'I said: "{text}".'
    return "I spoke."


def _f_language_internal_speech(payload: dict[str, Any]) -> str:
    text = str(payload.get("text") or "").strip()
    if text:
        return f'I thought: "{text}".'
    return "I had a thought."


def _guarded(source: str, fn: TemplateFn, fallback_line: Optional[str] = None) -> TemplateFn:
    """Render ``fn(payload)`` unless the result contains any digit.

    If ``fallback_line`` is provided, it is returned instead of the generic
    fallback when a digit is detected.
    """
    def wrapper(payload: dict[str, Any]) -> str:
        line = fn(payload)
        if any(ch.isdigit() for ch in line):
            if fallback_line is not None:
                return fallback_line
            return felt_fallback(source, "", {})
        return line
    return wrapper


FELT_TEMPLATES: dict[tuple[str, str], TemplateFn] = {
    ("interoception", "interoception.report"): _guarded("interoception", _f_interoception_report),
    ("sequence", "sequence.report"): _guarded("sequence", _f_sequence_report),
    ("vision", "vision.report"): _guarded("vision", _f_vision_report),
    ("planning", "planning.belief"): _guarded("planning", _f_planning_belief),
    ("planning", "planning.policy"): _guarded("planning", _f_planning_policy),
    ("episodic_memory", "episodic_memory.recall"): _guarded("episodic_memory", _f_episodic_memory_recall),
    ("affect", "affect.emotion"): _guarded("affect", _f_affect_emotion),
    ("affect", "affect.drive"): _guarded("affect", _f_affect_drive),
    ("affect", "affect.state"): _guarded("affect", _f_affect_state),
    ("affect", "affect.goal"): _guarded("affect", _f_affect_goal),
    ("self_model", "self_model.drift"): _guarded("self_model", _f_self_model_drift),
    ("cycle", "cycle.tick"): _guarded("cycle", _f_cycle_tick),
    ("audition", "audition.transcription"): _t_audition_transcription,
    ("audition", "audition.emotion"): _guarded("audition", _f_audition_emotion),
    ("interoception", "interoception.fatigue"): _guarded("interoception", _f_interoception_fatigue),
    ("interoception", "interoception.regulation"): _guarded("interoception", _f_interoception_regulation),
    ("social_cognition", "social_cognition.agent_model"): _guarded("social_cognition", _f_social_cognition_agent_model),
    ("social_cognition", "social_cognition.social_error"): _guarded("social_cognition", _f_social_cognition_social_error),
    ("world_model", "world_model.world_error"): _guarded("world_model", _f_world_model_world_error),
    ("world_model", "world_model.scenario"): _guarded("world_model", _f_world_model_scenario),
    ("planning", "planning.timeout"): _guarded("planning", _f_planning_timeout),
    ("planning", "planning.proposal"): _guarded("planning", _f_planning_proposal),
    ("audition", "audition.prosody"): _guarded("audition", _f_audition_prosody),
    ("vocal", "vocal.synthesized"): _guarded("vocal", _f_vocal_synthesized),
    ("episodic_memory", "episodic_memory.replay"): _guarded("episodic_memory", _f_episodic_memory_replay),
    ("sleep", "sleep.sleep.started"): _guarded("sleep", _f_sleep_sleep_started),
    ("sleep", "sleep.sleep.completed"): _guarded("sleep", _f_sleep_sleep_completed),
    ("sleep", "sleep.association"): _guarded("sleep", _f_sleep_association),
    ("sleep", "sleep.rest_request"): _guarded("sleep", _f_sleep_rest_request),
    ("self_model", "self_model.document"): _guarded("self_model", _f_self_model_document),
    ("audition", "audition.perception"): _guarded("audition", _f_audition_perception),
    ("language", "external_speech"): _guarded("language", _f_language_external_speech, "I said something."),
    ("language", "internal_speech"): _guarded("language", _f_language_internal_speech, "I had a thought."),
    ("embodiment", "embodiment.chat"): _f_embodiment_chat,
}


def felt_renderer(empty_snapshot_text: str = DEFAULT_EMPTY_SNAPSHOT_TEXT) -> FaithfulRenderer:
    """Build a renderer that uses the felt template set and fallback."""
    return FaithfulRenderer(
        templates=FELT_TEMPLATES,
        fallback=felt_fallback,
        empty_snapshot_text=empty_snapshot_text,
    )


def redact_heard_speech_felt(event) -> Optional[str]:
    """Redact heard speech using the felt template set."""
    return redact_heard_speech(event, templates=FELT_TEMPLATES, fallback=felt_fallback)


__all__ = [
    "ANOMALY_WORDS",
    "AROUSAL_WORDS",
    "CERTAINTY_WORDS",
    "CHANGE_WORDS",
    "DOMINANCE_WORDS",
    "DRIVE_LEVEL_WORDS",
    "DRIVE_NOUNS",
    "FAMILIARITY_WORDS",
    "FATIGUE_DEFAULT_THRESHOLD",
    "FATIGUE_WORDS",
    "FELT_TEMPLATES",
    "INTERACTION_WORDS",
    "PREDICTION_ERROR_WORDS",
    "SOURCE_PHRASES",
    "SURPRISE_WORDS",
    "VALENCE_WORDS",
    "WELLNESS_WORDS",
    "felt_event_phrase",
    "felt_fallback",
    "felt_renderer",
    "grade",
    "redact_heard_speech_felt",
    "source_phrase",
]
