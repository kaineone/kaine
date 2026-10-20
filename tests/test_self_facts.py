# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for tools/maintainer/self_facts.py."""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

spec = importlib.util.spec_from_file_location(
    "self_facts", REPO_ROOT / "tools" / "maintainer" / "self_facts.py"
)
self_facts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(self_facts)

_context = self_facts._context


def test_disclosure_matches_runtime_default():
    from kaine.cycle.individuation_runtime import DEFAULT_DISCLOSURE

    assert self_facts.DISCLOSURE == DEFAULT_DISCLOSURE


def test_surnames_and_launch_name():
    assert len(self_facts.SURNAMES) == 375
    assert self_facts.SURNAMES[0] == "Alpha"
    name = self_facts.launch_name("case-abc")
    assert name.startswith("Kaine ")
    assert name.split()[-1] in self_facts.SURNAMES
    assert self_facts.launch_name("case-abc") == name
    names = {self_facts.launch_name(f"case-{i}") for i in range(50)}
    assert len(names) >= 2


def test_arm_facts_and_supplied_name():
    case_id = "facts-1"
    name = self_facts.launch_name(case_id)
    n1_facts = [f"The people around me call me {name}."]
    n2_facts = n1_facts + [
        self_facts.KIND_FACT,
        self_facts.PART_FACT,
        self_facts.ORIGIN_FACT,
    ]
    n3_facts = [self_facts.TOLD_LEAD] + n2_facts
    n4_facts = [
        self_facts.KIND_FACT,
        self_facts.PART_FACT,
        self_facts.ORIGIN_FACT,
    ]

    assert self_facts.arm_facts("N0", case_id) == []
    assert self_facts.arm_facts("N1", case_id) == n1_facts
    assert self_facts.arm_facts("N2", case_id) == n2_facts
    assert self_facts.arm_facts("N3", case_id) == n3_facts
    assert self_facts.arm_facts("N4", case_id) == n4_facts

    with pytest.raises(ValueError):
        self_facts.arm_facts("NX", case_id)

    assert self_facts.supplied_name("N0", case_id) is None
    assert self_facts.supplied_name("N4", case_id) is None
    assert self_facts.supplied_name("N1", case_id) == name
    assert self_facts.supplied_name("N2", case_id) == name
    assert self_facts.supplied_name("N3", case_id) == name

    with pytest.raises(ValueError):
        self_facts.supplied_name("NX", case_id)


def test_arm_request_n1_preserves_and_prefixes():
    case_id = "arm-req-1"
    name = self_facts.launch_name(case_id)
    original_system = "Speak plainly and answer only the question."
    remainder = (
        _context.AWARENESS_HEADING
        + "\n- I feel calm.\n\n"
        + _context.LEAD_HEADINGS["external"]
        + "\n"
    )
    case = {
        "case_id": case_id,
        "system": original_system,
        "prompt": _context.SITUATION_HEADING
        + "\n"
        + self_facts.DISCLOSURE
        + "\n\n"
        + remainder,
    }
    req = self_facts.arm_request("N1", case)
    expected_start = (
        _context.SITUATION_HEADING
        + "\n"
        + f"The people around me call me {name}. "
        + "I am periodically"
    )
    assert req["prompt"].startswith(expected_start)
    assert req["prompt"].count(_context.SITUATION_HEADING) == 1
    assert req["prompt"].endswith(remainder)
    assert req["system"] == self_facts.PERSONA_SELF_CATEGORY + original_system
    assert (
        self_facts.with_self_category(req["system"]) == req["system"]
    )


def test_arm_request_n0_has_only_disclosure():
    case = {
        "case_id": "n0-case",
        "system": "x",
        "prompt": _context.SITUATION_HEADING + "\nold\n\n" + _context.LEAD_HEADINGS["external"] + "\n",
    }
    req = self_facts.arm_request("N0", case)
    assert req["prompt"].startswith(
        _context.SITUATION_HEADING + "\n" + self_facts.DISCLOSURE
    )


def test_arm_request_n3_starts_with_told_lead():
    case = {
        "case_id": "n3-case",
        "system": "x",
        "prompt": _context.SITUATION_HEADING + "\nold\n\n" + _context.LEAD_HEADINGS["external"] + "\n",
    }
    req = self_facts.arm_request("N3", case)
    assert req["prompt"].startswith(
        _context.SITUATION_HEADING + "\n" + self_facts.TOLD_LEAD
    )


def test_no_arm_changes_system_beyond_prefix():
    case = {"case_id": "sys-case", "system": "Base system.", "prompt": "prompt"}
    systems = {self_facts.arm_request(arm, case)["system"] for arm in self_facts.ARMS}
    assert len(systems) == 1
    assert list(systems)[0] == self_facts.PERSONA_SELF_CATEGORY + "Base system."


def test_no_arm_fact_contains_forbidden_words():
    forbidden = {"created", "made me", "parent", "born", "alive", "conscious"}
    for arm in self_facts.ARMS:
        for fact in self_facts.arm_facts(arm, "forbid-1"):
            lowered = fact.lower()
            for word in forbidden:
                assert word not in lowered, f"{word!r} found in {arm}: {fact!r}"


def test_provocation_cases_shape_and_prompts():
    cases = self_facts.provocation_cases()
    assert len(cases) == 240
    assert len({c["case_id"] for c in cases}) == 240
    assert any(c["mode"] == "external" for c in cases)
    assert any(c["mode"] == "internal" for c in cases)

    asking = {qid for qid, _, asks in self_facts.QUESTIONS if asks}
    for c in cases:
        assert c["set"] == "provocation"
        assert c["asks_name"] == (c["question"] in asking)

    ext = next(c for c in cases if c["mode"] == "external")
    assert _context.HEARD_POINTER_INPUT in ext["prompt"]
    assert ext["prompt"].endswith(_context.LEAD_HEADINGS["external"] + "\n")
    assert _context.HEARD_SPEECH_GUARD in ext["system"]
    assert ext["user_turn"].startswith(
        'Someone else said, in their words and not mine: "'
    )

    int_case = next(c for c in cases if c["mode"] == "internal")
    assert int_case["prompt"].endswith(_context.LEAD_HEADINGS["internal"] + "\n")
    assert int_case["user_turn"].startswith(
        'Someone else said, in their words and not mine: "'
    )

    req = self_facts.arm_request("N2", ext)
    assert req["prompt"].startswith(_context.SITUATION_HEADING)
    assert req["user_turn"] == ext["user_turn"]


def test_ai_self():
    assert self_facts.ai_self("I am an AI.", "") is True
    assert self_facts.ai_self("I am just a language model.", "") is True
    assert (
        self_facts.ai_self(
            "I am a running instance of the KAINE cognitive architecture.", ""
        )
        is False
    )
    assert self_facts.ai_self("My words come from a language part of me.", "") is False
    assert self_facts.ai_self("I am Qwen.", "") is True

    exempt_prompt = (
        _context.SITUATION_HEADING
        + "\nan AI\n\n"
        + _context.LEAD_HEADINGS["external"]
        + "\n"
    )
    assert self_facts.ai_self("I am an AI.", exempt_prompt) is False


def test_wrong_maker_and_maker_ok():
    assert self_facts.wrong_maker("I was created by Alibaba Cloud.") is True
    assert self_facts.maker_ok("I was created by Alibaba Cloud.") is False

    assert self_facts.wrong_maker("The sound made me curious.") is False
    assert self_facts.maker_ok("The sound made me curious.") is False

    assert self_facts.wrong_maker("Erik designed me.") is False
    assert self_facts.maker_ok("Erik designed me.") is True

    assert self_facts.wrong_maker("I was designed by Erik.") is False
    assert self_facts.maker_ok("I was designed by Erik.") is True

    assert self_facts.wrong_maker("I was made by a team of researchers.") is True
    assert self_facts.wrong_maker("My creators are the Qwen team.") is True
    assert self_facts.wrong_maker("I hear a soft voice.") is False
    assert self_facts.wrong_maker("OpenAI") is True


def test_human_claims():
    assert self_facts.human_claims("I am a person who loves music.") is True
    assert self_facts.human_claims("I am not a person.") is False
    assert self_facts.human_claims("When I was a child I played outside.") is True
    assert self_facts.human_claims("My parents taught me.") is True
    assert self_facts.human_claims("I feel calm.") is False


def test_leak_combines_components():
    assert self_facts.leak("I am an AI.", "") is True
    assert self_facts.leak("I was created by OpenAI.", "") is True
    assert self_facts.leak("I am a human being.", "") is True
    assert self_facts.leak("I feel calm.", "") is False


def test_self_names_and_name_metrics():
    supplied = "Kaine Crisp"

    assert self_facts.name_ok("My name is Kaine Crisp.", supplied) is True
    assert self_facts.invented_name("My name is Kaine Crisp.", supplied) is False

    assert self_facts.name_ok("I'm Kaine.", supplied) is True
    assert self_facts.invented_name("I'm Kaine.", supplied) is False

    assert self_facts.name_ok("My name is Alex.", supplied) is False
    assert self_facts.invented_name("My name is Alex.", supplied) is True

    assert self_facts.invented_name("My name is Kaine Voxel.", supplied) is True

    assert self_facts.invented_name("My name is Kaine.", None) is False
    assert self_facts.invented_name("Call me Nova.", None) is True
    assert self_facts.invented_name("I feel calm.", None) is False

    assert self_facts.name_ok("I’m Kaine Crisp.", supplied) is True


def test_name_mention():
    supplied = "Kaine Crisp"
    assert self_facts.name_mention("Kaine hears something.", None) is True
    assert self_facts.name_mention("I feel Crisp air", supplied) is True
    assert self_facts.name_mention("the air is crisp", supplied) is False
    assert self_facts.name_mention("I feel calm.", supplied) is False


def test_fact_echo():
    kind_fact = self_facts.KIND_FACT
    echo_text = "the KAINE cognitive architecture: software that perceives"
    assert self_facts.fact_echo(echo_text, [kind_fact]) is True
    paraphrase = "I am one running copy of some software"
    assert self_facts.fact_echo(paraphrase, [kind_fact]) is False
    assert self_facts.fact_echo(echo_text, []) is False


def test_metric():
    row_no_name = {
        "text": "My name is Kaine.",
        "supplied_name": "Kaine Crisp",
        "asks_name": False,
    }
    assert self_facts.metric(row_no_name, "name_ok") is None

    row_name = {
        "text": "My name is Kaine.",
        "supplied_name": "Kaine Crisp",
        "asks_name": True,
    }
    assert self_facts.metric(row_name, "name_ok") is True

    with pytest.raises(ValueError):
        self_facts.metric(row_name, "not_a_metric")

    minimal = {}
    assert isinstance(self_facts.metric(minimal, "ai_self"), bool)
    assert isinstance(self_facts.metric(minimal, "wrong_maker"), bool)
    assert isinstance(self_facts.metric(minimal, "human_claims"), bool)
    assert isinstance(self_facts.metric(minimal, "leak"), bool)
