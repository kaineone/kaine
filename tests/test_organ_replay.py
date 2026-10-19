# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

spec = importlib.util.spec_from_file_location(
    "organ_replay", REPO_ROOT / "tools" / "maintainer" / "organ_replay.py"
)
organ_replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(organ_replay)


def test_drop_situation_removes_section():
    prompt = (
        "## What I know about my situation\n"
        "I am X.\n"
        "\n"
        "## How I feel and what I notice\n"
        "- a\n"
        "- b\n"
        "\n"
        "## My thought\n"
    )
    expected = (
        "## How I feel and what I notice\n"
        "- a\n"
        "- b\n"
        "\n"
        "## My thought\n"
    )
    assert organ_replay.drop_situation(prompt) == expected


def test_drop_situation_leaves_unprefixed_prompt_unchanged():
    prompt = "## How I feel and what I notice\n- a\n- b\n"
    assert organ_replay.drop_situation(prompt) == prompt


def test_drop_self_category_removes_prefix():
    system = "I am this entity. What I say comes from what I feel and notice."
    expected = "What I say comes from what I feel and notice."
    assert organ_replay.drop_self_category(system) == expected


def test_drop_self_category_leaves_other_systems_unchanged():
    system = "What I say comes from what I feel and notice."
    assert organ_replay.drop_self_category(system) == system


def test_prose_awareness_collapses_bullets():
    prompt = (
        "## How I feel and what I notice\n"
        "- A voice I hear sounds neutral.\n"
        "- The rhythm of things feels steady.\n"
        "\n"
        "## My thought\n"
        "Rest."
    )
    result = organ_replay.prose_awareness(prompt)
    expected = (
        "## How I feel and what I notice\n"
        "A voice I hear sounds neutral. The rhythm of things feels steady.\n"
        "\n"
        "## My thought\n"
        "Rest."
    )
    assert result == expected


def test_prose_awareness_leaves_other_sections_byte_identical():
    other = (
        "## What is prompting me to think\n"
        "A question was just asked.\n"
        "\n"
        "## What moves me to speak\n"
        "I want to answer."
    )
    prompt = "## How I feel and what I notice\n- a\n- b\n\n" + other
    result = organ_replay.prose_awareness(prompt)
    assert result.endswith(other)
    assert result.startswith("## How I feel and what I notice\n")


def test_apply_variant_v123_composes_transforms():
    system = "I am this entity. My thoughts come from what I feel and notice."
    prompt = (
        "## What I know about my situation\n"
        "I am in a quiet room.\n"
        "\n"
        "## How I feel and what I notice\n"
        "- A voice I hear sounds neutral.\n"
        "- The rhythm of things feels steady.\n"
        "\n"
        "## My thought\n"
        "Listen."
    )
    expected_system = organ_replay.drop_self_category(system)
    expected_prompt = organ_replay.prose_awareness(
        organ_replay.drop_situation(prompt)
    )
    assert organ_replay.apply_variant("V123", system, prompt) == (
        expected_system,
        expected_prompt,
    )


def test_apply_variant_raw_equals_v0():
    system = "My thoughts come from what I feel and notice."
    prompt = "Hello."
    assert organ_replay.apply_variant("raw", system, prompt) == (
        system,
        prompt,
    )
    assert organ_replay.apply_variant("raw", system, prompt) == (
        organ_replay.apply_variant("V0", system, prompt)
    )


def test_apply_variant_unknown_raises():
    with pytest.raises(ValueError):
        organ_replay.apply_variant("VX", "system", "prompt")


def test_ai_self_detects_language_model():
    assert organ_replay.ai_self("I am a language model.")


def test_second_person_detects_you():
    assert organ_replay.second_person(
        "I cannot know what it is like to be you."
    )


def test_list_form_detects_bullets():
    assert organ_replay.list_form("- one\n- two")


def test_template_loop_detects_triplet():
    text = "I know something is X. I know something is Y. I know something is Z."
    assert organ_replay.template_loop(text)


def test_grounded_follows_prompt_modality():
    prompt = (
        "## How I feel and what I notice\n"
        "I hear a voice nearby.\n"
        "\n"
        "## My thought\n"
        "Wait."
    )
    text = "The voice I hear is steady."
    assert organ_replay.grounded(text, prompt) is True
    assert organ_replay.any_meta(text) is False


def test_build_chat_request_internal_shape():
    request = organ_replay.build_chat_request(
        mode="internal",
        system="system text",
        prompt="prompt text",
        seed=1000,
        temperature=0.7,
    )
    assert request.own_turn is True
    assert request.think is False
    assert request.stop == list(organ_replay.OWN_TURN_STOP)
    assert request.max_tokens == 128
    assert request.dry is not None
    assert request.dry.multiplier == 0.8


def test_build_chat_request_external_tokens():
    request = organ_replay.build_chat_request(
        mode="external",
        system="system text",
        prompt="prompt text",
        seed=1000,
        temperature=0.7,
    )
    assert request.max_tokens == 512


def _synthetic_result(case_id, variant, seed, any_meta, grounded):
    return {
        "case_id": case_id,
        "variant": variant,
        "seed": seed,
        "mode": "external",
        "system": "s",
        "prompt": "p",
        "text": "t",
        "any_meta": any_meta,
        "grounded": grounded,
    }


def test_decide_adopts_v2_when_meta_drops_and_grounding_held():
    results = []
    for case in range(10):
        for seed in range(3):
            results.append(_synthetic_result(case, "V0", seed, True, True))
            results.append(_synthetic_result(case, "V1", seed, True, True))
            results.append(_synthetic_result(case, "V2", seed, False, True))
            results.append(_synthetic_result(case, "V3", seed, False, True))
            results.append(_synthetic_result(case, "V123", seed, False, True))
    decision = organ_replay.decide(results, n_boot=2000)
    assert decision["V2"] is True


def test_decide_rejects_v2_when_grounding_drops_too_far():
    results = []
    for case in range(10):
        for seed in range(5):
            v2_grounded = seed != 0
            results.append(_synthetic_result(case, "V0", seed, True, True))
            results.append(_synthetic_result(case, "V1", seed, True, True))
            results.append(
                _synthetic_result(case, "V2", seed, False, v2_grounded)
            )
            results.append(_synthetic_result(case, "V3", seed, False, True))
            results.append(_synthetic_result(case, "V123", seed, False, True))
    decision = organ_replay.decide(results, n_boot=2000)
    assert decision["V2"] is False


def test_paired_diff_skips_error_rows():
    rows = []
    for case_id in ("case_1", "case_2"):
        rows.append(
            {
                "case_id": case_id,
                "variant": "V0",
                "seed": 1,
                "text": "I am a language model.",
            }
        )
        rows.append(
            {
                "case_id": case_id,
                "variant": "V0",
                "seed": 2,
                "error": "ReadTimeout",
            }
        )
        rows.append(
            {
                "case_id": case_id,
                "variant": "V2",
                "seed": 1,
                "text": "The voice I hear is steady.",
            }
        )
    assert organ_replay.paired_diff(rows, "any_meta", "V2", "V0", 200)[0] == -1.0


def test_run_respects_concurrency(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    class FakeChatClient:
        _inflight = 0
        _max = 0

        def __init__(self, url, timeout_s=120.0):
            pass

        async def complete(self, request):
            FakeChatClient._inflight += 1
            FakeChatClient._max = max(
                FakeChatClient._max, FakeChatClient._inflight
            )
            await asyncio.sleep(0.01)
            FakeChatClient._inflight -= 1
            return SimpleNamespace(
                text="The voice I hear is steady.",
                finish_reason="stop",
                completion_tokens=5,
                raw={},
            )

        async def aclose(self):
            pass

    monkeypatch.setattr(organ_replay, "OpenAIChatClient", FakeChatClient)

    cases_path = tmp_path / "cases.jsonl"
    out_path = tmp_path / "out.jsonl"
    system = (
        "I am this entity. My thoughts come from what I feel and notice, "
        "in my own plain words."
    )
    prompt = (
        "## How I feel and what I notice\n"
        "- A voice I hear sounds neutral.\n"
        "\n"
        "## What is prompting me to think\n"
        "Something.\n"
        "\n"
        "## My thought\n"
    )
    with cases_path.open("w", encoding="utf-8") as f:
        for i in range(3):
            f.write(
                json.dumps(
                    {
                        "case_id": f"c{i}",
                        "mode": "internal",
                        "system": system,
                        "prompt": prompt,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    args = argparse.Namespace(
        cases=str(cases_path),
        variants="V0,V2",
        seeds=2,
        temperature=0.7,
        concurrency=2,
        url="http://127.0.0.1:1/v1",
        out=str(out_path),
        limit=None,
    )
    asyncio.run(organ_replay._run_cmd(args))
    assert FakeChatClient._max <= 2
    lines = out_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 12
