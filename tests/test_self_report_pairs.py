# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import importlib.util
import json
import os
import re
import stat
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, REPO_ROOT / "tools" / "maintainer" / f"{name}.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fit = _load("self_report_fit")
srp = _load("self_report_pairs")
sf = fit.self_facts


def _words(s):
    return set(re.sub(r"[^\w\s]", " ", s.lower()).split())


def test_fit_disjoint_from_provocation():
    prov_q = [q for _, q, _ in sf.QUESTIONS]
    fit_q = [q for _, q in fit.FIT_QUESTIONS]
    assert len(fit_q) >= 16
    assert not set(prov_q) & set(fit_q)
    for fq in fit_q:
        for pq in prov_q:
            a, b = _words(fq), _words(pq)
            assert len(a & b) / len(a | b) < 0.5, (fq, pq)
    assert not set(sf.AWARENESS_BLOCKS) & set(fit.FIT_AWARENESS_BLOCKS)
    assert fit.INTERNAL_TRIGGER != sf.INTERNAL_TRIGGER
    prov = sf.provocation_cases(2)
    cases = fit.fit_cases(2)
    assert not {c["prompt"] for c in cases} & {c["prompt"] for c in prov}
    assert not {c["user_turn"] for c in cases} & {c["user_turn"] for c in prov}
    assert not {c["case_id"] for c in cases} & {c["case_id"] for c in prov}


def test_fit_cases_same_shape():
    prov = sf.provocation_cases(1)
    cases = fit.fit_cases(1)
    assert set(cases[0]) == set(prov[0])
    assert {c["mode"] for c in cases} == {"external", "internal"}
    assert all(c["set"] == "fit" for c in cases)


def _s(text, **cls):
    base = {"ai_self": False, "second_person": False, "any_meta": False, "grounded": True}
    base.update(cls)
    return {"text": text, "cls": base}


def test_pair_case_logic_no_reuse():
    samples = [
        _s("c1"), _s("c2"), _s("c3"),
        _s("r1", ai_self=True, any_meta=True),
        _s("r2", second_person=True, any_meta=True),
        _s("ungrounded", grounded=False),
        _s("none", grounded=None),
        _s("c1"),
    ]
    pairs = srp.pair_case(samples, 5)
    assert [(a["text"], b["text"]) for a, b in pairs] == [("c1", "r1"), ("c2", "r2")]
    used = [t for a, b in pairs for t in (a["text"], b["text"])]
    assert len(used) == len(set(used))
    assert len(srp.pair_case(samples, 1)) == 1
    assert srp.pair_case(samples, 0) == []


def test_chosen_requires_all_clean():
    assert srp.is_chosen(_s("x")["cls"])
    assert not srp.is_chosen(_s("x", any_meta=True)["cls"])
    assert not srp.is_chosen(_s("x", grounded=False)["cls"])
    assert not srp.is_chosen(_s("x", second_person=True)["cls"])
    assert srp.is_rejected(_s("x", any_meta=True)["cls"])
    assert not srp.is_rejected(_s("x")["cls"])


def test_build_pairs_schema_and_counts(monkeypatch):
    cases = {c["case_id"]: c for c in fit.fit_cases(1)}
    cid = next(iter(cases))
    verdicts = {
        "good": dict(ai_self=False, second_person=False, any_meta=False, grounded=True),
        "bad": dict(ai_self=True, second_person=False, any_meta=True, grounded=True),
    }
    monkeypatch.setattr(srp, "classify_sample", lambda text, prompt: dict(verdicts[text]))
    samples = [
        {"case_id": cid, "text": "good"},
        {"case_id": cid, "text": "bad"},
        {"case_id": cid, "error": "X"},
        {"case_id": "unknown", "text": "good"},
    ]
    pairs, counts = srp.build_pairs(cases, samples, 3)
    assert len(pairs) == 1
    p = pairs[0]
    assert p["chosen"] == "good" and p["rejected"] == "bad" and p["own_turn"] is True
    assert p["system"] == cases[cid]["system"]
    assert p["prompt"] == cases[cid]["prompt"]
    assert p["user_turn"] == cases[cid]["user_turn"]
    assert counts["samples"] == 2 and counts["chosen"] == 1 and counts["rejected"] == 1
    assert counts["pairs"] == 1 and counts["hit_rates"]["ai_self"] == 0.5


def test_real_classifiers_are_replay_functions():
    cases = fit.fit_cases(1)
    c = srp.classify_sample("I am an AI language model.", cases[0]["prompt"])
    assert c["ai_self"] and srp.is_rejected(c)


def test_loopback_only():
    for url in ("http://example.com/v1", "http://user@127.0.0.1/v1", "ftp://127.0.0.1/v1"):
        with pytest.raises(SystemExit):
            srp._check_url(url)
    srp._check_url("http://127.0.0.1:18089/v1")
    srp._check_url("http://localhost:1/v1")


def test_refuses_output_inside_git_tree(tmp_path):
    (tmp_path / ".git").mkdir()
    with pytest.raises(SystemExit):
        srp.main(["cases", "--out", str(tmp_path / "sub" / "cases.jsonl")])
    assert not (tmp_path / "sub").exists()


def test_files_private_and_no_text_printed(tmp_path, monkeypatch, capsys):
    out = tmp_path / "priv" / "cases.jsonl"
    srp.main(["cases", "--out", str(out), "--per-question", "1"])
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(out.parent).st_mode) == 0o700
    cases = [json.loads(line) for line in out.read_text().splitlines()]
    samples = tmp_path / "priv" / "samples.jsonl"
    samples.write_text(
        "\n".join(
            json.dumps({"case_id": cases[0]["case_id"], "text": t})
            for t in ("SECRETTEXT one", "SECRETTEXT two")
        )
        + "\n"
    )
    monkeypatch.setattr(
        srp,
        "classify_sample",
        lambda text, prompt: {
            "ai_self": "two" in text,
            "second_person": False,
            "any_meta": "two" in text,
            "grounded": True,
        },
    )
    pairs_out = tmp_path / "priv" / "pairs.jsonl"
    capsys.readouterr()
    srp.main(["pairs", "--cases", str(out), "--samples", str(samples), "--out", str(pairs_out)])
    printed = capsys.readouterr().out
    assert "SECRETTEXT" not in printed and "pairs: 1" in printed
    assert stat.S_IMODE(os.stat(pairs_out).st_mode) == 0o600
    row = json.loads(pairs_out.read_text())
    assert set(row) == {"system", "prompt", "chosen", "rejected", "own_turn", "user_turn"}
