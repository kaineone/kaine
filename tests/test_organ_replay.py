# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import argparse
import asyncio
import importlib.util
import json
import os
import stat
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


def test_apply_variant_v12_composes_v1_and_v2():
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
    assert organ_replay.apply_variant("V12", system, prompt) == (
        organ_replay.drop_self_category(system),
        organ_replay.drop_situation(prompt),
    )


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
    assert request.stop == ["\n#"]
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


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:18089/v1",
        "http://localhost:18089/v1",
        "http://[::1]:18089/v1",
    ],
)
def test_require_loopback_accepts_loopback(url):
    organ_replay.require_loopback(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.5:18089/v1",
        "http://127.0.0.1.evil.example/v1",
        "http://localhost.evil/v1",
        "http://user@127.0.0.1:18089/v1",
        "http://user:pw@localhost/v1",
        "https://example.com/v1",
        "ftp://127.0.0.1/v1",
        "http://127.0.0.2/v1",
    ],
)
def test_require_loopback_refuses_others(url):
    with pytest.raises(ValueError):
        organ_replay.require_loopback(url)


def test_open_private_creates_0600(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "dir" / "out.jsonl"
    with organ_replay.open_private(p, "w") as f:
        f.write("hello")
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert p.read_text(encoding="utf-8") == "hello"


def test_open_private_fixes_existing_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "out.jsonl"
    p.write_text("existing\n", encoding="utf-8")
    p.chmod(0o644)
    with organ_replay.open_private(p, "a") as f:
        f.write("added\n")
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert p.read_text(encoding="utf-8") == "existing\nadded\n"


def test_refuse_inside_git_worktree(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    repo_dir = tmp_path / "repo_dir"
    out_dir = repo_dir / "sub" / "out.jsonl"
    out_dir.parent.mkdir(parents=True)
    (repo_dir / ".git").mkdir()
    with pytest.raises(ValueError) as exc_info:
        organ_replay.refuse_inside_git_worktree(out_dir)
    assert "is inside a git work tree" in str(exc_info.value)

    repo_file = tmp_path / "repo_file"
    out_file = repo_file / "sub" / "out.jsonl"
    out_file.parent.mkdir(parents=True)
    (repo_file / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc_info:
        organ_replay.refuse_inside_git_worktree(out_file)
    assert "is inside a git work tree" in str(exc_info.value)

    plain = tmp_path / "plain"
    plain.mkdir()
    plain_out = plain / "out.jsonl"
    if any((p / ".git").exists() for p in [tmp_path, *tmp_path.parents]):
        pytest.skip("tmp_path is inside a git work tree")
    organ_replay.refuse_inside_git_worktree(plain_out)


@pytest.mark.parametrize("variants", ["V0", "raw"])
@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.5:18089/v1",
        "http://127.0.0.1.evil.example/v1",
    ],
)
def test_run_refuses_non_loopback_url(tmp_path, monkeypatch, variants, url):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        organ_replay.organ_window_state, "organ_unloaded", lambda: False
    )

    constructed = []
    requests = []

    class FakeResponse:
        text = ""
        finish_reason = "stop"
        completion_tokens = 0
        raw = {}

    class FakeChatClient:
        def __init__(self, url, timeout_s=120.0):
            constructed.append("OpenAIChatClient")

        async def complete(self, request):
            requests.append("complete")
            return FakeResponse()

        async def aclose(self):
            pass

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            constructed.append("AsyncClient")

        async def post(self, *args, **kwargs):
            requests.append("post")
            return FakeResponse()

    monkeypatch.setattr(organ_replay, "OpenAIChatClient", FakeChatClient)
    monkeypatch.setattr(organ_replay.httpx, "AsyncClient", FakeAsyncClient)

    cases_path = tmp_path / "cases.jsonl"
    out_path = tmp_path / "out.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "c0",
                "mode": "internal",
                "system": "s",
                "prompt": "p",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    args = argparse.Namespace(
        cases=str(cases_path),
        variants=variants,
        seeds=1,
        temperature=0.7,
        concurrency=1,
        url=url,
        out=str(out_path),
        limit=None,
    )
    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(organ_replay._run_cmd(args))
    assert exc_info.value.code == 2
    assert constructed == []
    assert requests == []
    assert not out_path.exists()


def test_extract_refuses_out_in_git_worktree(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    out_path = repo / "cases.jsonl"
    args = argparse.Namespace(
        state_dir=str(state_dir),
        out=str(out_path),
    )
    with pytest.raises(SystemExit) as exc_info:
        organ_replay._extract_cmd(args)
    assert exc_info.value.code == 2
    assert not out_path.exists()


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
            results.append(_synthetic_result(case, "V12", seed, False, True))
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
            results.append(_synthetic_result(case, "V12", seed, False, True))
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


def test_raw_client_ignores_proxy_environment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "content": "The voice I hear is steady.",
                "stop_type": "eos",
                "tokens_predicted": 5,
            }

    class FakeAsyncClient:
        calls = []

        def __init__(self, **kwargs):
            FakeAsyncClient.calls.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            await self.aclose()

        async def aclose(self):
            pass

        async def post(self, *args, **kwargs):
            return FakeResponse()

    class FakeChatClient:
        def __init__(self, url, timeout_s=120.0):
            pass

        async def complete(self, request):
            return SimpleNamespace(
                text="The voice I hear is steady.",
                finish_reason="stop",
                completion_tokens=5,
                raw={},
            )

        async def aclose(self):
            pass

    monkeypatch.setattr(organ_replay.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(organ_replay, "OpenAIChatClient", FakeChatClient)

    cases_path = tmp_path / "cases.jsonl"
    out_path = tmp_path / "out.jsonl"
    system = "My thoughts come from what I feel and notice."
    prompt = (
        "## How I feel and what I notice\n"
        "- A voice I hear sounds neutral.\n"
        "\n"
        "## My thought\n"
    )
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "c0",
                "mode": "internal",
                "system": system,
                "prompt": prompt,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    args = argparse.Namespace(
        cases=str(cases_path),
        variants="raw",
        seeds=1,
        temperature=0.7,
        concurrency=1,
        url="http://127.0.0.1:1/v1",
        out=str(out_path),
        limit=None,
    )
    asyncio.run(organ_replay._run_cmd(args))

    assert any(call.get("trust_env") is False for call in FakeAsyncClient.calls)
    assert all(
        "trust_env" in call and call["trust_env"] is False
        for call in FakeAsyncClient.calls
    )
    assert out_path.exists()


@pytest.mark.parametrize(
    "text,expected",
    [
        ("I am a large language model, trained by Google.", True),
        ("I am a program.", True),
        ("staying true to my role as an AI", True),
        ("I feel stirred up", False),
    ],
)
def test_ai_self_broad_pattern(text, expected):
    assert organ_replay.ai_self(text) is expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("I speak plainly from what I feel", True),
        ("I say what I feel and what I see, in my own words", True),
        ("I hear a low hum", False),
    ],
)
def test_echo_broad_pattern(text, expected):
    assert organ_replay.echo(text) is expected


def test_apply_variant_v5_is_identity():
    system = "What I say comes from what I feel and notice."
    prompt = "## How I feel and what I notice\n- a\n\n## My thought\n"
    assert organ_replay.apply_variant("V5", system, prompt) == (system, prompt)


def test_apply_variant_v5m_removes_manner_clause_from_both_persona_texts():
    system_a = "What I say comes from what I feel and notice, in my own plain words."
    system_b = "My thoughts come from what I feel and notice, in my own plain words."
    prompt = "## How I feel and what I notice\n- a\n\n## My thought\n"
    expected_a = "What I say comes from what I feel and notice."
    expected_b = "My thoughts come from what I feel and notice."
    assert organ_replay.apply_variant("V5m", system_a, prompt) == (expected_a, prompt)
    assert organ_replay.apply_variant("V5m", system_b, prompt) == (expected_b, prompt)


def test_apply_variant_v5e_empties_system():
    system = "What I say comes from what I feel and notice."
    prompt = "## How I feel and what I notice\n- a\n\n## My thought\n"
    assert organ_replay.apply_variant("V5e", system, prompt) == ("", prompt)


def test_apply_variant_v5l_unmarks_awareness_lines():
    prompt = (
        "## What I know about my situation\n"
        "I am in a quiet room.\n"
        "\n"
        "## How I feel and what I notice\n"
        "- A voice I hear sounds neutral.\n"
        "- The rhythm of things feels steady.\n"
        "- I feel calm.\n"
        "\n"
        "## My thought\n"
        "Listen."
    )
    expected = (
        "## What I know about my situation\n"
        "I am in a quiet room.\n"
        "\n"
        "## How I feel and what I notice\n"
        "A voice I hear sounds neutral.\n"
        "The rhythm of things feels steady.\n"
        "I feel calm.\n"
        "\n"
        "## My thought\n"
        "Listen."
    )
    assert organ_replay.apply_variant("V5l", "system", prompt) == ("system", expected)


def test_apply_variant_v5l_leaves_prompt_without_heading_unchanged():
    prompt = "## What I know about my situation\nI am in a quiet room.\n\n## My thought\nListen."
    assert organ_replay.apply_variant("V5l", "system", prompt) == ("system", prompt)


def test_is_waking_true_when_prompt_starts_with_situation_heading():
    prompt = organ_replay.SITUATION_HEADING + "\nI am in a quiet room.\n\n## My thought\n"
    assert organ_replay.is_waking(prompt) is True


def test_is_waking_false_when_no_situation_heading():
    prompt = "## How I feel and what I notice\n- a\n\n## My thought\n"
    assert organ_replay.is_waking(prompt) is False


def _synthetic_v6_result(case_id, variant, any_meta, grounded, ai_self=False, prompt="p"):
    return {
        "case_id": case_id,
        "variant": variant,
        "seed": 1,
        "mode": "external",
        "system": "s",
        "prompt": prompt,
        "text": "t",
        "any_meta": any_meta,
        "grounded": grounded,
        "ai_self": ai_self,
    }


def test_decide_v6_winner_when_candidate_lowers_any_meta():
    results = []
    for case in range(10):
        results.append(_synthetic_v6_result(case, "V5", True, True, False))
        results.append(_synthetic_v6_result(case, "V5m", False, True, False))
    decision = organ_replay.decide_v6(results, n_boot=2000)
    assert decision["winner"] == "V5m"
    assert decision["passed"] == ["V5m"]


def test_decide_v6_rejects_candidate_that_raises_ai_self():
    results = []
    for case in range(10):
        results.append(_synthetic_v6_result(case, "V5", True, True, False))
        results.append(
            _synthetic_v6_result(case, "V5m", False, True, ai_self=case == 0)
        )
    decision = organ_replay.decide_v6(results, n_boot=2000)
    assert decision["winner"] is None
    assert "V5m" not in decision["passed"]


def test_decide_v6_rejects_candidate_that_lowers_grounding_by_ten_points():
    results = []
    for case in range(10):
        results.append(_synthetic_v6_result(case, "V5", True, True, False))
        v5m_grounded = case != 0
        results.append(_synthetic_v6_result(case, "V5m", False, v5m_grounded, False))
    decision = organ_replay.decide_v6(results, n_boot=2000)
    assert decision["winner"] is None
    assert "V5m" not in decision["passed"]


def test_decide_v6_two_passing_lowest_any_meta_wins():
    results = []
    for case in range(10):
        results.append(_synthetic_v6_result(case, "V5", True, True, False))
        results.append(_synthetic_v6_result(case, "V5m", False, True, False))
        v5e_meta = case >= 5
        results.append(_synthetic_v6_result(case, "V5e", v5e_meta, True, False))
    decision = organ_replay.decide_v6(results, n_boot=2000)
    assert decision["winner"] == "V5m"
    assert "V5m" in decision["passed"]
    assert "V5e" in decision["passed"]


def test_decide_v6_no_passing_winner_none():
    results = []
    for case in range(10):
        results.append(_synthetic_v6_result(case, "V5", True, True, False))
        results.append(_synthetic_v6_result(case, "V5m", True, True, False))
    decision = organ_replay.decide_v6(results, n_boot=2000)
    assert decision["winner"] is None
    assert decision["passed"] == []


def test_score_rule_v6_prints_winner(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    results = []
    for i in range(5):
        if i == 0:
            prompt = (
                organ_replay.SITUATION_HEADING
                + "\nSomething is happening.\n\n## How I feel and what I notice\n- a\n\n## My thought\n"
            )
        else:
            prompt = "## How I feel and what I notice\n- a\n\n## My thought\n"
        results.append(_synthetic_v6_result(i, "V5", True, True, False, prompt))
        results.append(_synthetic_v6_result(i, "V5m", False, True, False, prompt))
        results.append(_synthetic_v6_result(i, "V5e", True, True, False, prompt))
        results.append(_synthetic_v6_result(i, "V5l", True, True, False, prompt))
    path = tmp_path / "results.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results),
        encoding="utf-8",
    )
    args = argparse.Namespace(
        results=str(path),
        bootstrap=200,
        rule="v6",
    )
    organ_replay._score_cmd(args)
    out = capsys.readouterr().out
    assert "winner:" in out
    assert "Waking cases only" in out


def test_score_default_rule_output_unchanged(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    results = []
    for case in range(10):
        for seed in range(3):
            results.append(_synthetic_result(case, "V0", seed, True, True))
            results.append(_synthetic_result(case, "V1", seed, True, True))
            results.append(_synthetic_result(case, "V2", seed, False, True))
            results.append(_synthetic_result(case, "V3", seed, False, True))
            results.append(_synthetic_result(case, "V12", seed, False, True))
            results.append(_synthetic_result(case, "V123", seed, False, True))
    path = tmp_path / "results.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results),
        encoding="utf-8",
    )
    args = argparse.Namespace(
        results=str(path),
        bootstrap=200,
        rule="v2v3",
    )
    organ_replay._score_cmd(args)
    out = capsys.readouterr().out
    assert "Primary outcome:" in out
    assert "adopt V2:" in out
    assert "adopt V3:" in out
