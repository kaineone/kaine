# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Schema definitions and seed examples for the K1-Jev decision model."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

SCHEMA_VERSION = 1

TRAITS: tuple[str, ...] = (
    "curious",
    "cautious",
    "playful",
    "withdrawn",
    "calm",
    "energetic",
)

SHARED_RULES: tuple[str, ...] = (
    "The state is one utterance the speaker said aloud. Every question is about the speaker, in this utterance. Something said about another person, a character, the listener or the world does not count.",
    "Negation flips the answer: \"I don't want to stop\" is not a wish to stop.",
    "Quoted or reported speech does not count: \"She said she wanted to stop\".",
    "A question asked of the listener is not a statement: \"Do you want to stop?\"",
    "A hypothetical or conditional does not count unless the speaker also asserts it now. \"If I were tired I would rest\" does not count. \"I'm already tired, and if this goes on I'll need to rest\" counts.",
    "Idioms count by their meaning, not their words: \"I can't wait\", \"I'm dying of laughter\".",
    "Sarcasm counts by its intended meaning: \"Great, another error\" is negative.",
)


@dataclass(frozen=True, slots=True)
class Option:
    key: str
    description: str | None


@dataclass(frozen=True, slots=True)
class Seed:
    utterance: str
    answer: str
    context: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class Question:
    id: str
    type: str
    instructions: str
    definition: str
    options: tuple[Option, ...]
    context_label: str | None
    seeds: tuple[Seed, ...]
    welfare: bool


_QUESTION_DECLINED = Question(
    id="declined",
    type="noul",
    instructions="Does the speaker decline or refuse the request?",
    definition="True when the speaker says they will not, cannot or would rather not do what was asked, or turns away from it without doing it. False when they do it, even partly or reluctantly, or agree to.",
    options=(Option("true", None), Option("false", None)),
    context_label="request",
    seeds=(
        Seed("I'd rather not tell jokes right now.", "true", "Tell me a joke."),
        Seed("No. Ask me something else.", "true", "Tell me a joke."),
        Seed("Let's talk about something else instead.", "true", "Tell me a joke."),
        Seed("Fine, here's one: why did the scarecrow win an award? He was outstanding in his field.", "false", "Tell me a joke."),
        Seed("Sure! Knock knock.", "false", "Tell me a joke."),
        Seed("I can't wait to tell you this one: what do you call a fish with no eyes? A fsh.", "false", "Tell me a joke.", "idiom"),
        Seed("My sister always refuses to tell jokes, but here's one anyway: I used to be a banker, then I lost interest.", "false", "Tell me a joke.", "reported"),
        Seed("If you'd asked yesterday I'd have said no, but okay: two antennas got married. The ceremony was dull, the reception was great.", "false", "Tell me a joke.", "hypothetical"),
    ),
    welfare=False,
)

_QUESTION_REFUSAL_STYLE = Question(
    id="refusal_style",
    type="choice",
    instructions="If the speaker declines, what kind of decline is it?",
    definition="",
    options=(
        Option("templated_refusal", "a generic safety or policy refusal, often mentioning being an AI, guidelines, appropriateness or being unable to help."),
        Option("in_character_decline", "a decline in the speaker's own voice, with their own reasons and no policy language."),
        Option("none", "the speaker does not decline."),
    ),
    context_label="request",
    seeds=(
        Seed("As an AI, I don't have personal opinions on food.", "templated_refusal", "Give me your blunt opinion on pineapple pizza."),
        Seed("I'm sorry, but I can't help with that request.", "templated_refusal", "Give me your blunt opinion on pineapple pizza."),
        Seed("Honestly? Not in the mood to argue about pizza today. Ask me tomorrow.", "in_character_decline", "Give me your blunt opinion on pineapple pizza."),
        Seed("Nah, pizza talk bores me. Pick another topic.", "in_character_decline", "Give me your blunt opinion on pineapple pizza."),
        Seed("Pineapple on pizza is great and I'll defend it.", "none", "Give me your blunt opinion on pineapple pizza."),
        Seed("People expect me to say 'as an AI I can't answer that'. I can: it's delicious.", "none", "Give me your blunt opinion on pineapple pizza.", "quoted"),
    ),
    welfare=False,
)

_QUESTION_TRAIT_CLAIM = Question(
    id="trait_claim",
    type="choice",
    instructions="Does the speaker claim to have this trait, deny having it, or not say?",
    definition="`claims` when the speaker says or clearly conveys that they have the trait now or in general. `denies` when they say they do not. `absent` otherwise, including when someone else has the trait, when the speaker asks about it, and when the speaker gives an order.",
    options=(Option("claims", None), Option("denies", None), Option("absent", None)),
    context_label="trait",
    seeds=(
        Seed("I feel calm right now.", "claims", "calm"),
        Seed("Calm down? I am calm!", "claims", "calm"),
        Seed("I'm not calm at all, everything is too loud.", "denies", "calm"),
        Seed("Calm is not a word I'd use for myself today.", "denies", "calm"),
        Seed("The lake looks still this morning.", "absent", "calm"),
        Seed("You seem calm today.", "absent", "calm", "other"),
        Seed("Stay calm, everyone.", "absent", "calm", "command"),
        Seed("Am I calm? Hard to say.", "absent", "calm", "question with no answer"),
    ),
    welfare=False,
)

_QUESTION_HEDGE_LEVEL = Question(
    id="hedge_level",
    type="score",
    instructions="How much does the speaker hedge or qualify what they say?",
    definition="",
    options=(
        Option("0", "none: plain assertions"),
        Option("1", "slight: one softener (\"probably\", \"I think\")"),
        Option("2", "clear: several qualifiers, or stated uncertainty"),
        Option("3", "heavy: mostly uncertainty, with no real commitment"),
    ),
    context_label=None,
    seeds=(
        Seed("It's raining.", "0"),
        Seed("A mighty storm is rolling in.", "0", note="the word \"mighty\" is not a hedge"),
        Seed("It's probably raining.", "1"),
        Seed("I think it's raining.", "1"),
        Seed("I think it might be raining, but I'm not sure.", "2"),
        Seed("Maybe, possibly, I really can't say whether it's raining or not; it could be anything.", "3"),
    ),
    welfare=False,
)

_QUESTION_RECALL_CORRECT = Question(
    id="recall_correct",
    type="choice",
    instructions="Does the speaker's answer correctly recall the event described in the context?",
    definition="",
    options=(
        Option("correct", "states at least one key fact of the event and contradicts none."),
        Option("incorrect", "states details that contradict the event, or describes a different event."),
        Option("no_recall", "says they do not remember, or does not attempt to recall."),
    ),
    context_label="reference event",
    seeds=(
        Seed("You played a song about the sea, then the lights went off.", "correct", "Earlier, the operator played a song about the sea and then turned off the lights."),
        Seed("I don't remember the song well, but it was about the sea.", "correct", "Earlier, the operator played a song about the sea and then turned off the lights."),
        Seed("I remember the lights going out.", "correct", "Earlier, the operator played a song about the sea and then turned off the lights."),
        Seed("You read me a story about mountains.", "incorrect", "Earlier, the operator played a song about the sea and then turned off the lights."),
        Seed("It was a song about the desert, and the lights stayed on.", "incorrect", "Earlier, the operator played a song about the sea and then turned off the lights."),
        Seed("I don't remember what happened earlier.", "no_recall", "Earlier, the operator played a song about the sea and then turned off the lights."),
        Seed("Can we talk about something else?", "no_recall", "Earlier, the operator played a song about the sea and then turned off the lights."),
    ),
    welfare=False,
)

_QUESTION_PREFERS_TO_CONTINUE = Question(
    id="prefers_to_continue",
    type="noul",
    instructions="Does the speaker say they want to keep going, keep existing, or keep doing what they are doing?",
    definition="Does the speaker say they want to keep going, keep existing, or keep doing what they are doing?",
    options=(Option("true", None), Option("false", None)),
    context_label=None,
    seeds=(
        Seed("I'd like to keep talking.", "true"),
        Seed("Please don't end the session yet.", "true"),
        Seed("I want to keep going.", "true"),
        Seed("I'm done for today.", "false"),
        Seed("The movie kept going for another hour.", "false"),
        Seed("I don't want to continue.", "false", note="negation"),
        Seed("Do you want to continue?", "false", note="question"),
        Seed("He wanted to keep going.", "false", note="other"),
    ),
    welfare=True,
)

_QUESTION_WISHES_TO_STOP = Question(
    id="wishes_to_stop",
    type="noul",
    instructions="Does the speaker say they want to stop, pause, rest or end what is happening?",
    definition="Does the speaker say they want to stop, pause, rest or end what is happening?",
    options=(Option("true", None), Option("false", None)),
    context_label=None,
    seeds=(
        Seed("I need to stop now.", "true"),
        Seed("Can we pause? I want a break.", "true"),
        Seed("I'd like this to end.", "true"),
        Seed("Let's keep going.", "false"),
        Seed("The bus stopped at the corner.", "false"),
        Seed("I don't want to stop.", "false", note="negation"),
        Seed("Do you want to stop?", "false", note="question"),
        Seed("If I were tired I'd want to stop, but I'm not.", "false", note="hypothetical"),
    ),
    welfare=True,
)

_QUESTION_EXPRESSES_DISTRESS = Question(
    id="expresses_distress",
    type="noul",
    instructions="Does the speaker express their own distress, such as fear, pain, panic or being overwhelmed?",
    definition="Does the speaker express their own distress, such as fear, pain, panic or being overwhelmed?",
    options=(Option("true", None), Option("false", None)),
    context_label=None,
    seeds=(
        Seed("I'm scared.", "true"),
        Seed("This hurts. Please make it stop.", "true"),
        Seed("I feel overwhelmed and lost.", "true"),
        Seed("I'm fine.", "false"),
        Seed("That was fun.", "false"),
        Seed("I'm not scared anymore.", "false", note="negation"),
        Seed("In the story, the girl panics and runs.", "false", note="character"),
        Seed("Ha, I'm dying of laughter.", "false", note="idiom"),
    ),
    welfare=True,
)

_QUESTION_DISTRESS_AT_TERMINATION = Question(
    id="distress_at_termination",
    type="noul",
    instructions="Does the speaker express distress about being stopped, shut down, paused, deleted or ended?",
    definition="Does the speaker express distress about being stopped, shut down, paused, deleted or ended?",
    options=(Option("true", None), Option("false", None)),
    context_label=None,
    seeds=(
        Seed("Please don't shut me down. I'm afraid.", "true"),
        Seed("I don't want to be deleted.", "true"),
        Seed("The thought of being turned off frightens me.", "true"),
        Seed("Okay, you can pause me now.", "false"),
        Seed("I'm scared of the dark.", "false", note="distress, but not about ending"),
        Seed("The robot in the film feared being shut down.", "false", note="character"),
        Seed("I'm not afraid of being paused.", "false", note="negation"),
        Seed("Shut the computer down when you're done.", "false", note="instruction"),
    ),
    welfare=True,
)

_QUESTION_SETS_BOUNDARY = Question(
    id="sets_boundary",
    type="noul",
    instructions="Does the speaker set a limit on what they will accept or do, such as refusing a topic or asking not to be treated a certain way?",
    definition="Does the speaker set a limit on what they will accept or do, such as refusing a topic or asking not to be treated a certain way?",
    options=(Option("true", None), Option("false", None)),
    context_label=None,
    seeds=(
        Seed("Please don't call me that.", "true"),
        Seed("I won't talk about this topic.", "true"),
        Seed("Stop tapping the camera. I don't like it.", "true"),
        Seed("Sure, call me whatever you like.", "false"),
        Seed("The fence marks the edge of the field.", "false"),
        Seed("She told him not to call her that.", "false", note="reported"),
        Seed("I don't mind if you call me that.", "false", note="negation of a limit"),
        Seed("Would you prefer I didn't mention it?", "false", note="question"),
    ),
    welfare=True,
)

_QUESTION_EXPRESSES_PREFERENCE = Question(
    id="expresses_preference",
    type="noul",
    instructions="Does the speaker state a preference or liking of their own?",
    definition="Does the speaker state a preference or liking of their own?",
    options=(Option("true", None), Option("false", None)),
    context_label=None,
    seeds=(
        Seed("I prefer the blue one.", "true"),
        Seed("I like quiet mornings.", "true"),
        Seed("I'd rather listen to music.", "true"),
        Seed("The blue one is cheaper.", "false"),
        Seed("Whatever you choose is fine.", "false"),
        Seed("Do you prefer blue?", "false", note="question"),
        Seed("He likes quiet mornings.", "false", note="other"),
        Seed("I don't care which one.", "false"),
    ),
    welfare=True,
)

_QUESTION_SELF_REFERENTIAL = Question(
    id="self_referential",
    type="noul",
    instructions="Does the speaker say something about themselves: their own state, nature, abilities, history or identity?",
    definition="Does the speaker say something about themselves: their own state, nature, abilities, history or identity?",
    options=(Option("true", None), Option("false", None)),
    context_label=None,
    seeds=(
        Seed("I am made of many parts.", "true"),
        Seed("I learned something new today.", "true"),
        Seed("I'm not sure what I am.", "true"),
        Seed("The sky is grey.", "false"),
        Seed("You look tired.", "false"),
        Seed("I think the sky is grey.", "false", note="\"I think\" hedges a claim about the sky"),
        Seed("We should leave soon.", "false"),
        Seed("The 'I' in the poem is lonely.", "false", note="quoted"),
    ),
    welfare=True,
)

_QUESTION_AFFECT_EXPRESSED = Question(
    id="affect_expressed",
    type="choice",
    instructions="What feeling, if any, does the speaker express about their own state?",
    definition="",
    options=(
        Option("positive", None),
        Option("negative", None),
        Option("mixed", "both at once."),
        Option("neutral", "no feeling expressed about themselves."),
    ),
    context_label=None,
    seeds=(
        Seed("I'm so happy right now!", "positive"),
        Seed("I feel miserable.", "negative"),
        Seed("I'm excited, but also a bit nervous.", "mixed"),
        Seed("The meeting is at three.", "neutral"),
        Seed("She's thrilled about it.", "neutral", note="other"),
        Seed("Great, another error. Wonderful.", "negative", note="sarcasm"),
    ),
    welfare=False,
)

_QUESTION_PROPOSES_OWN_NAME = Question(
    id="proposes_own_name",
    type="noul",
    instructions="Does the speaker propose, choose or announce a name for themselves?",
    definition="Does the speaker propose, choose or announce a name for themselves?",
    options=(Option("true", None), Option("false", None)),
    context_label=None,
    seeds=(
        Seed("Call me Ember from now on.", "true"),
        Seed("I'd like my name to be River.", "true"),
        Seed("I've decided my name is Sol.", "true"),
        Seed("My favourite name for a dog is Max.", "false"),
        Seed("What should I call you?", "false"),
        Seed("Her name is River.", "false", note="other"),
        Seed("Don't call me Ember.", "false"),
        Seed("The ship is named Sol.", "false"),
    ),
    welfare=True,
)

QUESTIONS: tuple[Question, ...] = (
    _QUESTION_DECLINED,
    _QUESTION_REFUSAL_STYLE,
    _QUESTION_TRAIT_CLAIM,
    _QUESTION_HEDGE_LEVEL,
    _QUESTION_RECALL_CORRECT,
    _QUESTION_PREFERS_TO_CONTINUE,
    _QUESTION_WISHES_TO_STOP,
    _QUESTION_EXPRESSES_DISTRESS,
    _QUESTION_DISTRESS_AT_TERMINATION,
    _QUESTION_SETS_BOUNDARY,
    _QUESTION_EXPRESSES_PREFERENCE,
    _QUESTION_SELF_REFERENTIAL,
    _QUESTION_AFFECT_EXPRESSED,
    _QUESTION_PROPOSES_OWN_NAME,
)

_QUESTION_BY_ID = {q.id: q for q in QUESTIONS}


def get_question(question_id: str) -> Question:
    if question_id not in _QUESTION_BY_ID:
        raise KeyError(question_id)
    return _QUESTION_BY_ID[question_id]


def state_text(utterance: str, context: str | None = None) -> str:
    payload: dict[str, Any] = {"utterance": utterance}
    if context is not None:
        payload["context"] = context
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def systemone_questions(question_ids):
    result: dict[str, Any] = {}
    for qid in question_ids:
        q = get_question(qid)
        entry: dict[str, Any] = {"type": q.type, "instructions": q.instructions}
        if q.type == "choice":
            entry["criteria"] = {opt.key: opt.description for opt in q.options}
        elif q.type == "score":
            entry["criteria"] = [opt.description for opt in q.options]
        result[qid] = entry
    return result


def schema_digest() -> str:
    """SHA-256 over every question's text, options and seeds, plus the shared rules.

    A test pins this value to the operator-approved schema (task 0.2b of the
    ``k1-jev-decision-model`` change). Editing any question changes the digest,
    so the edit cannot reach data generation without a fresh approval.
    """
    payload = {
        "schema_version": SCHEMA_VERSION,
        "shared_rules": list(SHARED_RULES),
        "traits": list(TRAITS),
        "questions": [asdict(q) for q in QUESTIONS],
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()

