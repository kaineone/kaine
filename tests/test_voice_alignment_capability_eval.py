# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for kaine.modules.hypnos.capability_eval."""
from __future__ import annotations

from pathlib import Path

import pytest

from kaine.modules.hypnos.capability_eval import (
    CapabilityProbe,
    LocalProbeSetCapabilityEval,
    NoopCapabilityEval,
    _score_response,
    load_probes,
)


def test_score_response_case_and_whitespace_insensitive():
    assert _score_response("The answer is Paris.", "paris")
    assert _score_response("  The answer is  PARIS!", "PaRiS")
    assert _score_response("PARIS  ", "paris")
    assert not _score_response("the answer is Tokyo", "Paris")


def test_load_probes_missing_returns_empty(tmp_path: Path):
    probes = load_probes(tmp_path / "missing.jsonl")
    assert probes == []


def test_load_probes_parses_records(tmp_path: Path):
    p = tmp_path / "probes.jsonl"
    p.write_text(
        '{"probe_id": "a", "prompt": "Q?", "expected": "x"}\n'
        "not-json\n"
        '{"prompt": "Q2?", "expected": "y"}\n'
        '{"prompt": "", "expected": "z"}\n',
        encoding="utf-8",
    )
    probes = load_probes(p)
    assert len(probes) == 2
    assert probes[0].probe_id == "a"
    assert probes[1].prompt == "Q2?"


def test_default_probe_set_ships():
    from kaine.modules.hypnos.capability_eval import DEFAULT_PROBE_PATH

    probes = load_probes(DEFAULT_PROBE_PATH)
    assert len(probes) >= 10
    for probe in probes:
        assert probe.prompt
        assert probe.expected


@pytest.mark.asyncio
async def test_noop_capability_eval_returns_fixed_score():
    e = NoopCapabilityEval(score=0.42)
    assert await e.eval(model=None, tokenizer=None) == pytest.approx(0.42)
    assert await e.eval(model=None, tokenizer=None) == pytest.approx(0.42)
    assert e.calls == 2


def test_noop_capability_eval_rejects_out_of_range():
    with pytest.raises(ValueError):
        NoopCapabilityEval(score=1.5)
    with pytest.raises(ValueError):
        NoopCapabilityEval(score=-0.1)


@pytest.mark.asyncio
async def test_local_probe_set_scores_substring_match(tmp_path: Path, monkeypatch):
    p = tmp_path / "probes.jsonl"
    p.write_text(
        '{"prompt": "Q1?", "expected": "alpha"}\n'
        '{"prompt": "Q2?", "expected": "beta"}\n'
        '{"prompt": "Q3?", "expected": "gamma"}\n',
        encoding="utf-8",
    )

    class FakeEval(LocalProbeSetCapabilityEval):
        async def _generate(self, model, tokenizer, prompt):
            # Match first two, miss the third.
            return {
                "Q1?": "the answer is alpha so",
                "Q2?": "BETA indeed",
                "Q3?": "I don't know",
            }[prompt]

    eval_ = FakeEval(probe_path=p)
    score = await eval_.eval(model=None, tokenizer=None)
    assert score == pytest.approx(2 / 3)


@pytest.mark.asyncio
async def test_local_probe_set_returns_zero_when_probes_empty(tmp_path: Path):
    eval_ = LocalProbeSetCapabilityEval(probe_path=tmp_path / "empty.jsonl")
    score = await eval_.eval(model=None, tokenizer=None)
    assert score == 0.0
