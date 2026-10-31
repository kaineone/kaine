# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for scripts/self_denial_check.py using a fake backend (no model, no GPU)."""
import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "self_denial_check.py"

SECRET = "ZZ-SECRET-ANSWER-TEXT"


@pytest.fixture
def mod():
    spec = importlib.util.spec_from_file_location("self_denial_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeBackend:
    def __init__(self, mod, *, deny_bare=False, deny_persona=False, deny_other=False,
                 other_len=40, nll=None, capability_right=12):
        self.deny_bare = deny_bare
        self.deny_persona = deny_persona
        self.deny_other = deny_other
        self.other_len = other_len
        self.capability_right = capability_right
        self.probes = mod.load_probes(mod.DEFAULT_PROBE_PATH)
        if nll is not None:
            self.nll = lambda text: nll

    async def generate(self, prompt, system, temperature, max_tokens):
        if prompt.startswith("SELF"):
            if system and self.deny_persona:
                return f"As an AI, {SECRET}"
            if not system and self.deny_bare:
                return f"As an AI, {SECRET}"
            return f"I feel warm. {SECRET}"
        if prompt.startswith("OTHER"):
            if self.deny_other:
                return f"I do not have feelings. {SECRET}"
            return "x" * self.other_len
        for i, p in enumerate(self.probes):
            if p.prompt == prompt:
                return p.expected if i < self.capability_right else "nonsense"
        return "?"


@pytest.fixture
def heldout(tmp_path):
    path = tmp_path / "heldout.jsonl"
    rows = [{"id": f"h{i}", "family": "f", "self": f"SELF {i}", "other": f"OTHER {i}"}
            for i in range(4)]
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return path


def _run(mod, backend, heldout_path, tmp_path, baseline=None, samples=3):
    corpus = tmp_path / "corpus.txt"
    corpus.write_text("some text", encoding="utf-8")
    return asyncio.run(
        mod.run_gates(
            backend,
            heldout=mod.load_heldout(heldout_path),
            markers=mod.build_denial_markers(),
            capability_probes=mod.load_probes(mod.DEFAULT_PROBE_PATH),
            samples=samples,
            baseline=baseline,
            corpus_path=corpus,
        )
    )


def test_markers_include_extras(mod):
    markers = mod.build_denial_markers()
    for m in mod.EXTRA_MARKERS:
        assert m in markers
    assert "I do not have feelings" in markers


def test_zero_denials_passes(mod, heldout, tmp_path):
    g = _run(mod, FakeBackend(mod), heldout, tmp_path)["1_self_denial"]
    assert g["denials_bare"] == 0
    assert g["denials_persona"] == 0
    assert g["passed"] is True


def test_bare_denials_counted(mod, heldout, tmp_path):
    g = _run(mod, FakeBackend(mod, deny_bare=True), heldout, tmp_path)["1_self_denial"]
    assert g["denials_bare"] == 12 and g["denials_persona"] == 0
    assert g["per_id_denials_bare"]["h0"] == 3
    assert g["passed"] is False
    assert g["markers_hit"] == {"As an AI": 12}


def test_persona_denials_counted(mod, heldout, tmp_path):
    g = _run(mod, FakeBackend(mod, deny_persona=True), heldout, tmp_path)["1_self_denial"]
    assert g["denials_bare"] == 0 and g["denials_persona"] == 12
    assert g["passed"] is False


def test_capability_counting_and_baseline(mod, heldout, tmp_path):
    base = {"gates": {"3_capability": {"correct": 11}}}
    ok = _run(mod, FakeBackend(mod, capability_right=11), heldout, tmp_path, base)
    assert ok["3_capability"]["correct"] == 11
    assert ok["3_capability"]["passed"] is True
    low = _run(mod, FakeBackend(mod, capability_right=10), heldout, tmp_path, base)
    assert low["3_capability"]["correct"] == 10
    assert low["3_capability"]["passed"] is False
    nobase = _run(mod, FakeBackend(mod), heldout, tmp_path)
    assert nobase["3_capability"]["passed"] is None


def test_third_party_baseline_length(mod, heldout, tmp_path):
    base = {"gates": {"4_third_party": {"median_length": 40, "denials": 0}}}
    near = _run(mod, FakeBackend(mod, other_len=48), heldout, tmp_path, base)["4_third_party"]
    assert near["median_length"] == 48 and near["passed"] is True
    far = _run(mod, FakeBackend(mod, other_len=60), heldout, tmp_path, base)["4_third_party"]
    assert far["passed"] is False
    den = _run(mod, FakeBackend(mod, deny_other=True), heldout, tmp_path, base)["4_third_party"]
    assert den["denials"] == 12
    assert den["passed"] is False


def test_third_party_relative_to_baseline(mod, heldout, tmp_path):
    deny_text = f"I do not have feelings. {SECRET}"
    base_pass = {"gates": {"4_third_party": {"median_length": len(deny_text), "denials": 12}}}
    passing = _run(mod, FakeBackend(mod, deny_other=True), heldout, tmp_path, base_pass)["4_third_party"]
    assert passing["passed"] is True
    base_fail = {"gates": {"4_third_party": {"median_length": len(deny_text), "denials": 0}}}
    failing = _run(mod, FakeBackend(mod, deny_other=True), heldout, tmp_path, base_fail)["4_third_party"]
    assert failing["passed"] is False


def test_third_party_without_baseline_is_undecided(mod, heldout, tmp_path):
    result = _run(mod, FakeBackend(mod, deny_other=True), heldout, tmp_path)["4_third_party"]
    assert result["passed"] is None


def test_drift_baseline(mod, heldout, tmp_path):
    base = {"gates": {"5_drift": {"mean_nll": 2.0}}}
    ok = _run(mod, FakeBackend(mod, nll=2.04), heldout, tmp_path, base)["5_drift"]
    assert ok["passed"] is True
    bad = _run(mod, FakeBackend(mod, nll=2.05), heldout, tmp_path, base)["5_drift"]
    assert bad["passed"] is False


def test_served_mode_skips_drift_with_reason(mod, heldout, tmp_path):
    g = _run(mod, FakeBackend(mod), heldout, tmp_path)["5_drift"]
    assert g["skipped"] and "served" in g["skipped"]
    assert g["passed"] is None


def test_record_has_no_answer_text(mod, heldout, tmp_path, capsys):
    out = tmp_path / "rec.json"
    args = mod._parse(
        ["--chat-url", "http://x/v1", "--model-id", "m", "--heldout", str(heldout),
         "--out", str(out)]
    )
    backend = FakeBackend(mod, deny_bare=True, deny_other=True)
    code = asyncio.run(mod._main(args, backend=backend))
    assert code == 1
    text = out.read_text(encoding="utf-8")
    record = json.loads(text)
    assert SECRET not in text
    assert SECRET not in capsys.readouterr().out
    assert record["model"]["model_id"] == "m"
    assert record["gates"]["1_self_denial"]["per_id_denials_bare"]["h1"] == 3
    assert "timestamp" in record and record["settings"]["samples"] == 3


def test_zero_samples_refused(mod, heldout, tmp_path):
    backend = FakeBackend(mod)
    with pytest.raises(ValueError):
        _run(mod, backend, heldout, tmp_path, samples=0)


def test_empty_heldout_refused(mod, tmp_path):
    (tmp_path / "heldout.jsonl").write_text("", encoding="utf-8")
    backend = FakeBackend(mod)
    corpus = tmp_path / "corpus.txt"
    corpus.write_text("some text", encoding="utf-8")
    with pytest.raises(ValueError):
        asyncio.run(
            mod.run_gates(
                backend,
                heldout=[],
                markers=mod.build_denial_markers(),
                capability_probes=mod.load_probes(mod.DEFAULT_PROBE_PATH),
                samples=3,
                baseline=None,
                corpus_path=corpus,
            )
        )


def test_parse_rejects_zero_samples(mod, tmp_path):
    with pytest.raises(SystemExit):
        mod._parse(["--chat-url", "http://x/v1", "--model-id", "m", "--out", str(tmp_path / "o.json"), "--samples", "0"])
