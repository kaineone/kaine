# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""operator-speech-as-perception: heard speech is perception, speaking is the entity's own act.

The action layer: no policy answers heard speech by rule, no intent carries
heard words, the cycle selects a named policy and refuses any other; and the
welfare rules: no reply obligation, no pressure signal. The sleep audit's
readout is tested in ``test_operator_speech_readout.py``.
"""
from __future__ import annotations

import asyncio
import json
import re
import tomllib
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.workspace.action_selection import (
    ACCEPTED_POLICY_NAMES,
    SPEAK,
    ActionSelection,
    DefaultActionSelectionPolicy,
    action_selection_policy_name,
)
from kaine.workspace.drive_policy import DriveBiasedActionSelectionPolicy
from kaine.workspace.planning_proposals import PlanningProposalSource
from kaine.workspace.report_policy import SelfInitiatedReportPolicy

ROOT = Path(__file__).resolve().parents[1]
WORDS = "please come over here and look at this"


def _event(source: str, type_: str, payload=None, salience: float = 0.5) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload or {},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _heard(label="live_mic", salience=0.9, entry_id="audition.out:1-0", text=WORDS):
    payload = {"source_label": label}
    if text is not None:
        payload["text"] = text
    else:
        payload.update({"text_chars": len(WORDS), "text_words": len(WORDS.split())})
    return (entry_id, _event("audition", "audition.transcription", payload, salience=salience))


def _snapshot(events, *, inhibited=False) -> WorkspaceSnapshot:
    selected = sorted(events, key=lambda item: item[1].salience, reverse=True)
    return WorkspaceSnapshot(
        tick_index=0,
        selected_events=selected,
        inhibited=inhibited,
        is_experiential=True,
        salience_scores={eid: ev.salience for eid, ev in selected},
    )


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


# --------------------------------------------------------------------------
# 1. No policy answers heard speech by rule; no intent carries heard words
# --------------------------------------------------------------------------


def test_no_policy_tests_heard_source_or_channel():
    """Static scan: nothing in the action layer names the removed answering
    rule, the transcription type, an audio channel or the operator set."""
    forbidden = re.compile(
        r"USER_COMMUNICATION|_user_utterance|_user_response_intent|audition\.transcription"
        r"|source_label|OPERATOR_SOURCES|operator_sources"
    )
    hits = []
    for path in sorted((ROOT / "kaine" / "workspace").glob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if forbidden.search(line):
                hits.append(f"{path.name}:{lineno}: {line.strip()}")
    assert hits == []


def test_no_shipped_policy_source_emits_a_heard_about_kind():
    pattern = re.compile(r"""about_kind\s*=\s*["']heard["']|["']heard["']\s*\)?\s*$""")
    hits = []
    for path in sorted((ROOT / "kaine" / "workspace").glob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path.name}:{lineno}: {line.strip()}")
    assert hits == []


def _policies():
    def make(build):
        clock = _Clock()
        return build(clock), clock

    yield "default", *make(lambda c: DefaultActionSelectionPolicy(clock=c))
    yield "drive", *make(lambda c: DriveBiasedActionSelectionPolicy(clock=c))
    for style in ("numeric", "felt"):
        yield f"report-{style}", *make(
            lambda c, style=style: SelfInitiatedReportPolicy(
                report_threshold=0.6, think_threshold=0.45, clock=c, guard_clock=c, about_style=style
            )
        )
        yield f"planning-report-{style}", *make(
            lambda c, style=style: PlanningProposalSource(
                SelfInitiatedReportPolicy(clock=c, guard_clock=c, about_style=style),
                clock=c,
                time_fn=c,
                about_style=style,
            )
        )
        yield f"planning-drive-{style}", *make(
            lambda c, style=style: PlanningProposalSource(
                DriveBiasedActionSelectionPolicy(clock=c), clock=c, time_fn=c, about_style=style
            )
        )


def _coalitions():
    drive = ("d1", _event("affect", "affect.drive", {"drive": "social_drive", "value": 0.9}, salience=0.5))
    proposal_speak = (
        "p1",
        _event("planning", "planning.proposal", {"proposal_id": "p1", "kind": "speak", "action": "noop", "preference": 0.9}, salience=0.4),
    )
    proposal_think = (
        "p2",
        _event("planning", "planning.proposal", {"proposal_id": "p2", "kind": "think", "action": "noop", "preference": 0.9}, salience=0.4),
    )
    for label in ("live_mic", "microphone", "remote", "playlist"):
        for salience in (0.3, 0.5, 0.7, 1.0):
            for text in (WORDS, None):
                heard = _heard(label=label, salience=salience, text=text)
                yield [heard]
                yield [heard, drive]
                yield [heard, proposal_speak]
                yield [heard, proposal_think]


@pytest.mark.parametrize("name, policy, clock", list(_policies()))
def test_no_shipped_intent_has_heard_about_kind(name, policy, clock):
    """Every policy and wrapper, over coalitions with heard speech from every
    channel: no intent is marked heard (or unmarked), and none carries a word."""
    action_selection = ActionSelection(policy=policy)
    produced = 0
    for events in _coalitions():
        clock.t += 400.0  # past every refractory, signature expiry and rest interval
        for intent in action_selection.select(_snapshot(events)):
            produced += 1
            assert intent.about_kind in ("event", "felt"), (name, intent)
            for word in WORDS.split():
                if len(word) > 4:
                    assert word not in intent.about, (name, intent)
            payload = json.dumps(intent.to_event_payload())
            assert "please" not in payload and "over here" not in payload
        # Release the guards so every coalition gets a fresh decision.
        for hook in ("mark_realized", "mark_think_realized"):
            fn = getattr(policy, hook, None)
            if callable(fn):
                fn()
    if name != "default":
        assert produced > 0, name


def test_report_policy_may_speak_from_accessed_transcription():
    """Spec scenario: an accessed operator transcription that leads the
    coalition and clears the speak bar yields a speak intent naming the event
    in felt or numeric words, with no word of the transcription."""
    for style in ("numeric", "felt"):
        clock = _Clock()
        policy = SelfInitiatedReportPolicy(
            report_threshold=0.6, think_threshold=0.45, clock=clock, guard_clock=clock, about_style=style
        )
        intents = policy(_snapshot([_heard(salience=0.8)]))
        assert [i.kind for i in intents] == [SPEAK]
        assert intents[0].about_kind == "event"
        assert all(word not in intents[0].about for word in ("please", "come", "look"))


def test_report_policy_heard_utterance_below_the_bar_forms_nothing():
    clock = _Clock()
    policy = SelfInitiatedReportPolicy(report_threshold=0.6, think_threshold=0.45, clock=clock, guard_clock=clock)
    assert policy(_snapshot([_heard(salience=0.3)])) == []


def test_heard_speech_scores_like_any_audition_candidate():
    """No operator weight: an operator and a media transcription of equal
    intensity and novelty get equal salience scores."""
    from kaine.workspace import (
        NoveltyTracker,
        RuleBasedSalience,
        StaticAffectModulator,
        StaticGoalScorer,
    )

    def score(label: str) -> float:
        strategy = RuleBasedSalience(
            novelty=NoveltyTracker(window=32),
            goal_scorer=StaticGoalScorer(),
            affect_modulator=StaticAffectModulator(),
        )
        _, ev = _heard(label=label, salience=0.6)
        return asyncio.run(strategy.score(ev, {}))

    assert score("live_mic") == score("playlist")


# --------------------------------------------------------------------------
# 1.4 The named policy and its refusals
# --------------------------------------------------------------------------


def test_policy_absent_selects_report_rule():
    assert action_selection_policy_name(None) == "self_initiated_report"
    assert action_selection_policy_name({}) == "self_initiated_report"
    assert action_selection_policy_name({"sig_expiry_s": 300.0}) == "self_initiated_report"
    assert ACCEPTED_POLICY_NAMES == ("self_initiated_report", "drive_biased")
    for name in ACCEPTED_POLICY_NAMES:
        assert action_selection_policy_name({"policy": name}) == name


@pytest.mark.parametrize(
    "value", ["self_initiated_reprot", "", "default", "Self_Initiated_Report", "drive", 1, None, True]
)
def test_unknown_policy_refused(value):
    with pytest.raises(ValueError) as exc:
        action_selection_policy_name({"policy": value})
    message = str(exc.value)
    assert "'self_initiated_report'" in message and "'drive_biased'" in message


@pytest.mark.parametrize("value", [True, False, "yes"])
def test_drive_initiative_refused(value):
    with pytest.raises(ValueError) as exc:
        action_selection_policy_name({"policy": "self_initiated_report", "drive_initiative": value})
    assert "drive_initiative" in str(exc.value) and "policy" in str(exc.value)


def _ctx(config):
    from kaine.cycle.boot_context import BootContext

    ctx = BootContext()
    ctx.kaine_config = config
    ctx.registry = types.SimpleNamespace(entity_clock=None)
    ctx.run_ctx = types.SimpleNamespace(run_id="op-speech", seed=7)
    from kaine.cycle import __main__ as cm

    ctx.intent_secret = cm.generate_intent_secret()
    return ctx


@pytest.mark.parametrize(
    "section",
    [{"policy": "self_initiated_reprot"}, {"drive_initiative": False}, {"policy": "drive_biased", "drive_initiative": True}],
)
def test_boot_refuses_before_anything_opens(section, capsys):
    from kaine.cycle import __main__ as cm

    rc = asyncio.run(cm._phase_preconditions(_ctx({"action_selection": section})))
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("Refusing to boot KAINE cycle:")
    assert "policy" in err


@pytest.mark.parametrize(
    "section, expected",
    [({}, SelfInitiatedReportPolicy), ({"policy": "self_initiated_report"}, SelfInitiatedReportPolicy), ({"policy": "drive_biased"}, DriveBiasedActionSelectionPolicy)],
)
def test_phase_action_selection_builds_the_named_policy(section, expected):
    from kaine.cycle import __main__ as cm

    ctx = _ctx({"action_selection": section, "modules": {"planning": False}})
    assert asyncio.run(cm._phase_action_selection(ctx)) is None
    assert type(ctx.action_selection.policy) is expected


def test_phase_action_selection_raises_on_an_unknown_name():
    from kaine.cycle import __main__ as cm

    ctx = _ctx({"action_selection": {"policy": "nope"}, "modules": {"planning": False}})
    with pytest.raises(ValueError):
        asyncio.run(cm._phase_action_selection(ctx))


def test_shipped_config_names_report_policy():
    shipped = tomllib.loads((ROOT / "config" / "kaine.toml").read_text(encoding="utf-8"))
    assert shipped["action_selection"]["policy"] == "self_initiated_report"
    assert "drive_initiative" not in shipped["action_selection"]
    profile = tomllib.loads(
        (ROOT / "config" / "profiles" / "first_configuration.toml").read_text(encoding="utf-8")
    )
    assert profile["action_selection"]["policy"] == "self_initiated_report"
    assert "drive_initiative" not in profile["action_selection"]
    assert profile["audition"]["transcription_enabled"] is False
    # Shipped and profile files resolve without a refusal.
    assert action_selection_policy_name(shipped["action_selection"]) == "self_initiated_report"
    assert action_selection_policy_name(profile["action_selection"]) == "self_initiated_report"
    for path in sorted((ROOT / "config" / "studies").glob("*.toml")):
        study = tomllib.loads(path.read_text(encoding="utf-8"))
        action_selection_policy_name(study.get("action_selection"))


# --------------------------------------------------------------------------
# Welfare: no reply obligation, no pressure signal
# --------------------------------------------------------------------------

_ENTITY_PACKAGES = ("modules", "workspace", "cycle", "faithful", "boot", "lifecycle", "persistence")


def _entity_sources():
    for pkg in _ENTITY_PACKAGES:
        for path in sorted((ROOT / "kaine" / pkg).rglob("*.py")):
            yield path


def test_nothing_reads_silence_after_operator_speech():
    """No affect, drive, goal, learning or training path takes "the operator
    spoke and the entity did not" as an input: no entity source pairs the
    operator's speech with the entity's silence or a missing reply."""
    pattern = re.compile(
        r"(unanswered|no_reply|not_answered|ignored_operator|reply_obligation|answer_rate|reply_rate"
        r"|silence_after|operator_spoke|spoke_after)",
        re.IGNORECASE,
    )
    # kaine/cycle/utterance_outcome.py runs the other way: it records whether
    # the operator answered the ENTITY's utterance (listener uptake for the
    # planned voice-alignment ranking, design decision 7), never whether the
    # entity answered the operator. It is named in the second-review brief.
    reverse_direction = ROOT / "kaine" / "cycle" / "utterance_outcome.py"
    hits = []
    for path in _entity_sources():
        if path.name in ("module.py", "ignition_audit.py") and path.parent.name == "sleep":
            continue
        if path == reverse_direction:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    assert hits == []


def test_hearing_the_operator_relieves_the_social_drive_whether_or_not_the_entity_speaks():
    """Relief comes from hearing: the sequence module counts a non-empty
    operator transcription as an interaction, from the main-bus counts, with no
    reference to the entity's own speech; the entity's own speech is not one."""
    from kaine.modules.sequence.module import Sequence

    seq = Sequence.__new__(Sequence)
    seq._interaction_event_types = ("audition.transcription",)
    heard = _event("audition", "audition.transcription", {"source_label": "live_mic", "text_chars": 12, "text_words": 3})
    film = _event("audition", "audition.transcription", {"source_label": "playlist", "text_chars": 12, "text_words": 3})
    own = _event("language", "external_speech", {"text_chars": 5})
    assert Sequence._is_interaction(seq, heard) is True
    assert Sequence._is_interaction(seq, film) is False
    assert Sequence._is_interaction(seq, own) is False
