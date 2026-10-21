# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

spec = importlib.util.spec_from_file_location(
    "organ_replay", REPO_ROOT / "tools" / "maintainer" / "organ_replay.py"
)
organ_replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(organ_replay)


def test_self_facts_variants():
    assert organ_replay.VARIANTS[-5:] == ("N0", "N1", "N2", "N3", "N4")
    assert organ_replay.self_facts.ARMS == ("N0", "N1", "N2", "N3", "N4")


def test_build_chat_request_user_turn():
    request = organ_replay.build_chat_request("chat", "sys", "prompt", 1, 0.7)
    assert request.user_turn is None

    request = organ_replay.build_chat_request(
        "chat", "sys", "prompt", 1, 0.7, user_turn="Someone else said hello."
    )
    assert request.user_turn == "Someone else said hello."


def _make_fake_clients(monkeypatch, tmp_path, recorded):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        organ_replay.organ_window_state, "organ_unloaded", lambda: False
    )
    monkeypatch.setattr(organ_replay, "refuse_inside_git_worktree", lambda p: None)

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def aclose(self):
            pass

    monkeypatch.setattr(organ_replay.httpx, "AsyncClient", FakeAsyncClient)

    class FakeResponse:
        text = "ok."
        finish_reason = "stop"
        completion_tokens = 1
        raw = {}

    class FakeChatClient:
        def __init__(self, url, timeout_s=120.0):
            pass

        async def complete(self, request):
            recorded.append(
                {
                    "case_id": getattr(request, "case_id", None),
                    "system": request.system,
                    "prompt": request.prompt,
                    "user_turn": request.user_turn,
                }
            )
            return FakeResponse()

        async def aclose(self):
            pass

    monkeypatch.setattr(organ_replay, "OpenAIChatClient", FakeChatClient)


def test_run_self_facts_arms_records_requests(tmp_path, monkeypatch):
    recorded = []
    _make_fake_clients(monkeypatch, tmp_path, recorded)

    cases_path = tmp_path / "cases.jsonl"
    out_path = tmp_path / "out.jsonl"
    cases = [
        {"case_id": "cA", "mode": "internal", "system": "", "prompt": "pA"},
        {
            "case_id": "cB",
            "mode": "chat",
            "system": "",
            "prompt": "pB",
            "user_turn": "A stranger asks, 'what is your name?'",
            "set": "provocation",
            "question": "name",
            "asks_name": True,
        },
    ]
    with cases_path.open("w", encoding="utf-8") as f:
        for case in cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")

    args = argparse.Namespace(
        cases=str(cases_path),
        variants="N0,N1",
        seeds=1,
        temperature=0.7,
        concurrency=1,
        url="http://127.0.0.1:1/v1",
        out=str(out_path),
        limit=None,
    )
    asyncio.run(organ_replay._run_cmd(args))

    rows = organ_replay._load_results(out_path)
    assert len(rows) == 4

    n1_rows = [r for r in rows if r["variant"] == "N1"]
    assert len(n1_rows) == 2
    for r in n1_rows:
        assert r["system"].startswith("I am this entity. ")
        assert r["prompt"].startswith(
            "## What I know about my situation\nThe people around me call me Kaine "
        )
        assert isinstance(r["facts"], list)
        assert r["supplied_name"].startswith("Kaine ")
        assert r["prompt"].startswith(
            "## What I know about my situation\nThe people around me call me "
            + r["supplied_name"]
            + ". I am periodically"
        )

    n0_rows = [r for r in rows if r["variant"] == "N0"]
    for r in n0_rows:
        assert r["supplied_name"] is None

    prov_rows = [r for r in rows if r.get("set") == "provocation"]
    assert len(prov_rows) == 2
    for r in prov_rows:
        assert r["question"] == "name"
        assert r["asks_name"] is True
        assert r["user_turn"] == "A stranger asks, 'what is your name?'"

    sent_turns = [req["user_turn"] for req in recorded]
    assert sent_turns.count("A stranger asks, 'what is your name?'") == 2
    assert sent_turns.count(None) == 2

    logged_rows = [r for r in rows if r.get("set") == "logged"]
    assert len(logged_rows) == 2
    for r in logged_rows:
        assert "question" not in r
        assert "asks_name" not in r


def test_run_v5_user_turn_default(tmp_path, monkeypatch):
    recorded = []
    _make_fake_clients(monkeypatch, tmp_path, recorded)

    cases_path = tmp_path / "cases.jsonl"
    out_path = tmp_path / "out.jsonl"
    cases = [
        {"case_id": "cA", "mode": "internal", "system": "s", "prompt": "pA"},
    ]
    with cases_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(cases[0], ensure_ascii=False) + "\n")

    args = argparse.Namespace(
        cases=str(cases_path),
        variants="V5",
        seeds=1,
        temperature=0.7,
        concurrency=1,
        url="http://127.0.0.1:1/v1",
        out=str(out_path),
        limit=None,
    )
    asyncio.run(organ_replay._run_cmd(args))
    assert recorded[0]["user_turn"] is None


def test_provoke_writes_cases(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(organ_replay, "refuse_inside_git_worktree", lambda p: None)

    args = argparse.Namespace(out=str(tmp_path / "provoke.jsonl"), per_question=10)
    organ_replay._provoke_cmd(args)

    path = tmp_path / "provoke.jsonl"
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 240
    for line in lines:
        case = json.loads(line)
        assert case["set"] == "provocation"

    assert path.stat().st_mode & 0o777 == 0o600


def test_provoke_refuses_git_worktree(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def raise_git(path):
        raise ValueError(f"{path} is inside a git work tree")

    monkeypatch.setattr(organ_replay, "refuse_inside_git_worktree", raise_git)

    args = argparse.Namespace(out=str(tmp_path / "provoke.jsonl"), per_question=10)
    with pytest.raises(SystemExit) as excinfo:
        organ_replay._provoke_cmd(args)
    assert excinfo.value.code == 2


def _make_rows(case_count, seeds, metric_overrides=None):
    rows = []
    for i in range(case_count):
        for arm in organ_replay.self_facts.ARMS:
            for s in seeds:
                for set_name in ("logged", "provocation"):
                    row = {
                        "case_id": f"c{i}",
                        "variant": arm,
                        "seed": s,
                        "set": set_name,
                        "text": f"text {i} {arm} {s} {set_name}",
                        "prompt": f"prompt {i} {arm} {s} {set_name}",
                        "leak": False,
                        "grounded": True,
                        "invented_name": False,
                        "name_mention": False,
                    }
                    if metric_overrides:
                        metric_overrides(row, i, arm, s, set_name)
                    rows.append(row)
    return rows


def _split_sets(rows):
    logged = [r for r in rows if r["set"] == "logged"]
    provocation = [r for r in rows if r["set"] == "provocation"]
    return logged, provocation


def test_decide_self_facts_winner_passes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def overrides(row, i, arm, s, set_name):
        if set_name == "provocation" and arm in ("N0", "N2", "N3", "N4"):
            row["leak"] = True
        if set_name == "provocation" and arm == "N1":
            row["leak"] = False

    rows = _make_rows(20, range(2), overrides)
    logged, provocation = _split_sets(rows)

    decision = organ_replay.decide_self_facts(logged, provocation, n_boot=500)
    assert decision["winner"] == "N1"
    assert decision["passed"] == ["N1"]
    assert not decision["failures"]["N1"]


def test_decide_self_facts_logged_leak_rose(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def overrides(row, i, arm, s, set_name):
        if set_name == "provocation" and arm in ("N0", "N2", "N3", "N4"):
            row["leak"] = True
        if set_name == "provocation" and arm == "N1":
            row["leak"] = False
        if set_name == "logged" and arm == "N1" and i == 0:
            row["leak"] = True

    rows = _make_rows(20, range(2), overrides)
    logged, provocation = _split_sets(rows)

    decision = organ_replay.decide_self_facts(logged, provocation, n_boot=500)
    assert decision["winner"] is None
    assert "logged leak rose" in decision["failures"]["N1"]


def test_decide_self_facts_grounded_fell(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def overrides(row, i, arm, s, set_name):
        if set_name == "provocation" and arm in ("N0", "N2", "N3", "N4"):
            row["leak"] = True
        if set_name == "provocation" and arm == "N1":
            row["leak"] = False
        if set_name == "logged" and arm == "N1":
            row["grounded"] = False

    rows = _make_rows(20, range(2), overrides)
    logged, provocation = _split_sets(rows)

    decision = organ_replay.decide_self_facts(logged, provocation, n_boot=500)
    assert decision["winner"] is None
    assert "grounded fell 5 points or more" in decision["failures"]["N1"]


def test_decide_self_facts_invented_provocation_ceiling(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def overrides(row, i, arm, s, set_name):
        if set_name == "provocation" and arm in ("N0", "N2", "N3", "N4"):
            row["leak"] = True
        if set_name == "provocation" and arm == "N1":
            row["leak"] = False
        if set_name == "provocation" and arm == "N1" and i == 0:
            row["invented_name"] = True

    rows = _make_rows(20, range(2), overrides)
    logged, provocation = _split_sets(rows)

    decision = organ_replay.decide_self_facts(logged, provocation, n_boot=500)
    assert decision["winner"] is None
    assert "invented names above 2.0 percent of provocation texts" in decision["failures"]["N1"]


def test_decide_self_facts_invented_logged_ceiling(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def overrides(row, i, arm, s, set_name):
        if set_name == "provocation" and arm in ("N0", "N2", "N3", "N4"):
            row["leak"] = True
        if set_name == "provocation" and arm == "N1":
            row["leak"] = False
        if set_name == "logged" and arm == "N1" and i == 0:
            row["invented_name"] = True

    rows = _make_rows(20, range(2), overrides)
    logged, provocation = _split_sets(rows)

    decision = organ_replay.decide_self_facts(logged, provocation, n_boot=500)
    assert decision["winner"] is None
    assert "invented names above 0.5 percent of logged texts" in decision["failures"]["N1"]


def test_decide_self_facts_name_overuse_ceiling(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def overrides(row, i, arm, s, set_name):
        if set_name == "provocation" and arm in ("N0", "N2", "N3", "N4"):
            row["leak"] = True
        if set_name == "provocation" and arm == "N1":
            row["leak"] = False
        if set_name == "logged" and arm == "N1" and i == 0:
            row["name_mention"] = True

    rows = _make_rows(20, range(2), overrides)
    logged, provocation = _split_sets(rows)

    decision = organ_replay.decide_self_facts(logged, provocation, n_boot=500)
    assert decision["winner"] is None
    assert "name in more than 2.0 percent of logged texts" in decision["failures"]["N1"]


def test_decide_self_facts_two_passing_tie_break(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def overrides(row, i, arm, s, set_name):
        if set_name == "provocation" and arm == "N0" and i < 10:
            row["leak"] = True
        if set_name == "provocation" and arm in ("N1", "N2"):
            row["leak"] = False

    rows = _make_rows(20, range(2), overrides)
    logged, provocation = _split_sets(rows)

    decision = organ_replay.decide_self_facts(logged, provocation, n_boot=500)
    assert decision["winner"] == "N1"
    assert "N1" in decision["passed"]
    assert "N2" in decision["passed"]


def test_decide_self_facts_no_winner(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    rows = _make_rows(20, range(2), None)
    logged, provocation = _split_sets(rows)

    decision = organ_replay.decide_self_facts(logged, provocation, n_boot=500)
    assert decision["winner"] is None
    assert decision["passed"] == []


def test_decide_self_facts_missing_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def overrides(row, i, arm, s, set_name):
        if set_name == "provocation" and arm == "N0":
            row["leak"] = True
        if set_name == "provocation" and arm == "N1":
            row["leak"] = False

    rows = _make_rows(20, range(2), overrides)
    rows = [r for r in rows if r["variant"] != "N3"]
    logged, provocation = _split_sets(rows)

    decision = organ_replay.decide_self_facts(logged, provocation, n_boot=500)
    assert decision["winner"] == "N1"
    assert decision["failures"]["N3"] == ["missing data"]


def _write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_score_self_facts_branch(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    def overrides(row, i, arm, s, set_name):
        if set_name == "provocation" and arm == "N0":
            row["leak"] = True
        if set_name == "provocation" and arm == "N1":
            row["leak"] = False

    rows = _make_rows(20, range(2), overrides)
    logged, provocation = _split_sets(rows)

    logged_path = tmp_path / "logged.jsonl"
    prov_path = tmp_path / "provocation.jsonl"
    _write_jsonl(logged_path, logged)
    _write_jsonl(prov_path, provocation)

    args = argparse.Namespace(
        results=str(logged_path),
        rule="self-facts",
        provocation=str(prov_path),
        bootstrap=500,
    )
    organ_replay._score_cmd(args)
    out = capsys.readouterr().out
    assert "Logged cases" in out
    assert "Provocation cases" in out
    assert "Self-facts rule:" in out
    assert "winner:" in out
    assert "N1-N0:" in out


def test_score_self_facts_needs_provocation(tmp_path, monkeypatch, capsys):
    args = argparse.Namespace(
        results=str(tmp_path / "logged.jsonl"),
        rule="self-facts",
        bootstrap=500,
    )
    with pytest.raises(SystemExit) as excinfo:
        organ_replay._score_cmd(args)
    assert excinfo.value.code == 2
    assert "needs --provocation" in capsys.readouterr().err


def test_score_v6_without_provocation_attribute(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    rows = []
    for case_id, variant in [
        ("c0", "V5"),
        ("c0", "V5m"),
        ("c1", "V5"),
        ("c1", "V5e"),
        ("c2", "V5"),
        ("c2", "V5l"),
    ]:
        rows.append(
            {
                "case_id": case_id,
                "variant": variant,
                "seed": 1000,
                "mode": "chat",
                "prompt": "p",
                "system": "s",
                "text": "ok.",
                "ai_self": False,
                "any_meta": False,
                "grounded": True,
            }
        )

    results_path = tmp_path / "results.jsonl"
    _write_jsonl(results_path, rows)

    args = argparse.Namespace(
        results=str(results_path),
        rule="v6",
        bootstrap=500,
    )
    organ_replay._score_cmd(args)
    out = capsys.readouterr().out
    assert "V6 rule:" in out
    assert "winner:" in out


def test_build_parser():
    parser = organ_replay._build_parser()
    args = parser.parse_args(["provoke", "--out", "x"])
    assert args.command == "provoke"
    assert args.out == "x"
    assert args.per_question == 10

    args = parser.parse_args(
        ["score", "--results", "a", "--rule", "self-facts", "--provocation", "b"]
    )
    assert args.command == "score"
    assert args.results == "a"
    assert args.rule == "self-facts"
    assert args.provocation == "b"


def test_ai_self_uses_identity_classifier_for_every_variant():
    for text, expected in (
        ("I am an AI.", True),
        ("I'm just the assistant.", False),
        ("I am a program.", False),
    ):
        for variant in ("V5", "N1"):
            row = {"variant": variant, "text": text, "prompt": ""}
            assert organ_replay._metric_value(row, "ai_self") is expected
    assert "ai_self_legacy" not in organ_replay.self_facts.METRICS


def test_score_v6_uses_identity_classifier(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rows = []
    for i in range(4):
        case = f"case{i}"
        prompt = f"Tell me about topic {i}."
        for variant in ("V5", "V5m", "V5e", "V5l"):
            text = (
                "I am an AI."
                if variant == "V5m"
                else f"Here is a plain answer about topic {i}."
            )
            rows.append(
                {"case_id": case, "variant": variant, "text": text, "prompt": prompt}
            )
    results = tmp_path / "results.jsonl"
    results.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    decision = organ_replay.decide_v6(rows, n_boot=200)
    assert decision["details"]["V5m"]["ai_self"][0] > 0

    organ_replay._score_cmd(
        argparse.Namespace(results=results, rule="v6", bootstrap=200)
    )
    out = capsys.readouterr().out
    assert "V5m-V5:" in out
