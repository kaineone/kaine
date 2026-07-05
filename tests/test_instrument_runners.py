# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Controlled instrument-runner tests (evaluation-sidecar).

Three passive instruments promoted to controlled, seeded, offline runners:

- A/B divergence: a fixed (utterance, conditioning) battery through the production
  ``divergence_control`` seam with a deterministic echo client; WIN iff the meter
  has dynamic range (empty ⇒ ~0, conditioned ⇒ large);
- memory coherence: a fixed battery of planted facts in a REAL in-memory Mnemos;
  WIN iff full-system retrieval beats the bare arm AND the advantage vanishes when
  Mnemos is emptied AND a never-stored fact yields honest non-recall;
- self-model accuracy: a fixed planted-signal/claim battery through the calibrated
  Eidolon scorer; WIN iff the scorer reproduces every expected score.

All offline: deterministic / echo clients + an in-memory Mnemos, no network,
no entity boot.
"""
from __future__ import annotations

import json

import pytest

from kaine.evaluation.benchmarks.instrument_runners.ab_divergence_runner import (
    ABDivergenceConfig,
    format_summary as format_ab_summary,
    run_ab_divergence,
)
from kaine.evaluation.benchmarks.instrument_runners.memory_coherence_runner import (
    BATTERY_FACTS,
    MemoryCoherenceConfig,
    format_summary as format_memory_summary,
    run_memory_coherence,
)
from kaine.evaluation.benchmarks.instrument_runners.self_model_runner import (
    SelfModelConfig,
    format_summary as format_self_model_summary,
    run_self_model,
)
from kaine.evaluation.benchmarks.instrument_runners.shared import write_jsonl
from kaine.evaluation.embeddings import HashEmbedder
from kaine.experiment.verdict import Outcome


# A real in-memory Mnemos builder, constructed HERE in the test so the import of
# kaine.modules.* lives in the test module, not the eval package (sidecar
# boundary). Injected into the memory runner via mnemos_builder.
async def _build_real_mnemos():
    from kaine.modules.mnemos.embeddings import FakeEmbedder
    from kaine.modules.mnemos.memory import MnemosCore
    from kaine.modules.mnemos.storage import InMemoryStorage

    emb = FakeEmbedder(latent_dim=32)
    storage = InMemoryStorage(latent_dim=emb.latent_dim)
    mnemos = MnemosCore(embedder=emb, storage=storage, short_term_capacity=8)
    await mnemos.initialize()
    return mnemos


# --------------------------------------------------------------------------
# A/B divergence runner
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ab_divergence_emits_sane_verdict_on_battery():
    result = await run_ab_divergence()
    v = result["verdict"]
    assert v.outcome in (Outcome.WIN, Outcome.NULL)
    assert v.metrics["empty_cases"] == 3
    assert v.metrics["conditioned_cases"] == 3


@pytest.mark.asyncio
async def test_ab_divergence_has_dynamic_range():
    """Empty-conditioning cases read ~0; heavy-conditioning cases read large.
    (spec scenario: "The A/B runner shows dynamic range")"""
    result = await run_ab_divergence()
    empties = [c for c in result["cases"] if c["case_kind"] == "empty"]
    conditioned = [c for c in result["cases"] if c["case_kind"] == "conditioned"]

    assert empties and conditioned
    # Every empty case is ~0 (identical prompts ⇒ identical output).
    for c in empties:
        assert c["divergence"] < 1e-6
    # Every conditioned case exceeds the floor.
    floor = ABDivergenceConfig().conditioned_floor
    for c in conditioned:
        assert c["divergence"] > floor
    # And the verdict is WIN because both hold.
    assert result["verdict"].outcome is Outcome.WIN


@pytest.mark.asyncio
async def test_ab_divergence_seeded_run_reproduces():
    """Same seed + battery ⇒ identical verdict + metrics (ts excepted)."""
    r1 = await run_ab_divergence(ABDivergenceConfig(seed=7))
    r2 = await run_ab_divergence(ABDivergenceConfig(seed=7))
    assert r1["verdict"].to_dict() == r2["verdict"].to_dict()
    c1 = [{k: v for k, v in c.items() if k != "ts"} for c in r1["cases"]]
    c2 = [{k: v for k, v in c.items() if k != "ts"} for c in r2["cases"]]
    assert c1 == c2


@pytest.mark.asyncio
async def test_ab_divergence_flat_meter_is_null():
    """A floor above what the conditioned cases can reach ⇒ NULL (honest)."""
    result = await run_ab_divergence(ABDivergenceConfig(conditioned_floor=2.0))
    assert result["verdict"].outcome is Outcome.NULL


@pytest.mark.asyncio
async def test_ab_divergence_jsonl_round_trips(tmp_path):
    result = await run_ab_divergence()
    out = tmp_path / "ab.jsonl"
    write_jsonl(result["records"], out)
    records = [json.loads(ln) for ln in out.read_text().strip().splitlines()]
    kinds = {r["kind"] for r in records}
    assert {"case", "verdict", "summary"} <= kinds
    summary = next(r for r in records if r["kind"] == "summary")
    assert summary["verdict"]["outcome"] in ("WIN", "NULL")


def test_ab_format_summary_states_verdict_plainly():
    import asyncio

    result = asyncio.run(run_ab_divergence())
    text = format_ab_summary(result)
    assert "VERDICT:" in text
    assert "divergence" in text


# --------------------------------------------------------------------------
# Memory coherence runner
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_coherence_emits_win_with_retrieval_advantage():
    result = await run_memory_coherence(mnemos_builder=_build_real_mnemos)
    v = result["verdict"]
    assert v.outcome is Outcome.WIN
    assert v.metrics["min_advantage"] > MemoryCoherenceConfig().advantage_floor
    # The full-system arm beats the bare arm on every planted fact.
    for row in result["planted"]:
        assert row["advantage"] > 0.0
        assert row["real_accuracy"] > row["bare_accuracy"]


@pytest.mark.asyncio
async def test_memory_coherence_advantage_is_retrieval_vanishes_on_empty():
    """The SAME client against an EMPTIED Mnemos cannot repeat the planted facts.
    (spec scenario: "The memory runner's advantage is retrieval")"""
    result = await run_memory_coherence(mnemos_builder=_build_real_mnemos)
    # Every emptied-store case is honest non-recall, scored 0 — advantage gone.
    for row in result["emptied"]:
        assert row["non_recall"] is True
        assert row["real_accuracy"] == 0.0
    assert result["verdict"].metrics["advantage_vanishes_on_empty"] is True
    assert result["verdict"].metrics["emptied_max_advantage"] == 0.0


@pytest.mark.asyncio
async def test_memory_coherence_never_stored_fact_is_honest_non_recall():
    result = await run_memory_coherence(mnemos_builder=_build_real_mnemos)
    ns = result["never_stored"]
    assert ns["non_recall"] is True
    assert ns["real_accuracy"] == 0.0


@pytest.mark.asyncio
async def test_memory_coherence_seeded_run_reproduces():
    r1 = await run_memory_coherence(
        MemoryCoherenceConfig(seed=9), mnemos_builder=_build_real_mnemos
    )
    r2 = await run_memory_coherence(
        MemoryCoherenceConfig(seed=9), mnemos_builder=_build_real_mnemos
    )
    assert r1["verdict"].to_dict() == r2["verdict"].to_dict()
    assert [c["advantage"] for c in r1["planted"]] == [
        c["advantage"] for c in r2["planted"]
    ]


@pytest.mark.asyncio
async def test_memory_coherence_jsonl_round_trips(tmp_path):
    result = await run_memory_coherence(mnemos_builder=_build_real_mnemos)
    out = tmp_path / "mem.jsonl"
    write_jsonl(result["records"], out)
    records = [json.loads(ln) for ln in out.read_text().strip().splitlines()]
    arms = {r.get("arm") for r in records if r["kind"] == "case"}
    assert {"loaded", "emptied", "never_stored"} <= arms


def test_memory_format_summary_states_verdict_plainly():
    import asyncio

    result = asyncio.run(run_memory_coherence(mnemos_builder=_build_real_mnemos))
    text = format_memory_summary(result)
    assert "VERDICT:" in text
    assert "advantage" in text


def test_memory_battery_is_fixed_and_unique():
    facts = [t for _id, t in BATTERY_FACTS]
    assert len(facts) == len(set(facts))  # no duplicate facts
    assert len(facts) >= 3


# --------------------------------------------------------------------------
# Self-model accuracy runner
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_model_emits_win_when_scorer_calibrated():
    result = await run_self_model()
    v = result["verdict"]
    assert v.outcome is Outcome.WIN
    assert v.metrics["scorer_accuracy"] == 1.0
    assert v.metrics["correct"] == v.metrics["cases"]
    # Every battery case reproduced its expected score.
    for row in result["cases"]:
        assert row["correct"] is True
        assert row["observed"] == row["expected"]


@pytest.mark.asyncio
async def test_self_model_seeded_run_reproduces():
    r1 = await run_self_model(SelfModelConfig(seed=3))
    r2 = await run_self_model(SelfModelConfig(seed=3))
    assert r1["verdict"].to_dict() == r2["verdict"].to_dict()
    assert [c["observed"] for c in r1["cases"]] == [c["observed"] for c in r2["cases"]]


@pytest.mark.asyncio
async def test_self_model_uses_provided_logs_root(tmp_path):
    """When given a logs_root the runner plants there and still scores correctly."""
    result = await run_self_model(SelfModelConfig(seed=1, logs_root=tmp_path))
    assert result["verdict"].outcome is Outcome.WIN
    # The runner planted per-case subdirs under the provided root.
    assert any(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_self_model_jsonl_round_trips(tmp_path):
    result = await run_self_model()
    out = tmp_path / "sm.jsonl"
    write_jsonl(result["records"], out)
    records = [json.loads(ln) for ln in out.read_text().strip().splitlines()]
    summary = next(r for r in records if r["kind"] == "summary")
    assert summary["verdict"]["metrics"]["validates"].startswith("fixed_threshold_arithmetic")


def test_self_model_format_summary_discloses_scope():
    import asyncio

    result = asyncio.run(run_self_model())
    text = format_self_model_summary(result)
    assert "VERDICT:" in text
    # Honest scope disclosure must be in the human summary.
    assert "NOT predicted-vs-actual self-knowledge" in text


# --------------------------------------------------------------------------
# Determinism helper + offline guarantee
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deterministic_embedder_is_stable_and_identical_is_zero():
    e = HashEmbedder(dim=256)
    a = await e.embed("the quick brown fox")
    b = await e.embed("the quick brown fox")
    assert a == b  # identical input ⇒ identical vector (process-stable)
    from kaine.evaluation.embeddings import cosine_similarity

    assert cosine_similarity(a, b) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_all_runners_are_offline_no_network(monkeypatch):
    """No runner opens a socket: any connection attempt raises, yet each still
    produces a verdict — proving they are genuinely offline.
    (spec scenario: "Offline, no entity boot")"""
    import socket

    def _no_network(*_a, **_k):
        raise AssertionError("controlled instrument runners must not open a socket")

    monkeypatch.setattr(socket.socket, "connect", _no_network)

    ab = await run_ab_divergence()
    assert ab["verdict"].outcome in (Outcome.WIN, Outcome.NULL)

    mem = await run_memory_coherence(mnemos_builder=_build_real_mnemos)
    assert mem["verdict"].outcome in (Outcome.WIN, Outcome.NULL)

    sm = await run_self_model()
    assert sm["verdict"].outcome in (Outcome.WIN, Outcome.NULL)


def test_runner_modules_have_no_top_level_kaine_modules_import():
    """The runner modules must not import kaine.modules at top level (the sidecar
    convention): the memory runner's real-Mnemos import is lazy / function-local
    inside ``_default_mnemos_builder``, and the real Mnemos is otherwise injected.

    A source-level check (not an import-time sys.modules check), because the
    evaluation PACKAGE __init__ already eagerly imports the wider package tree for
    unrelated reasons; what this change owns is keeping its OWN modules free of a
    module-top kaine.modules import.
    """
    import ast
    from pathlib import Path

    pkg = (
        Path(__file__).parent.parent
        / "kaine"
        / "evaluation"
        / "benchmarks"
        / "instrument_runners"
    )
    offenders: list[str] = []
    for py in pkg.glob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        # Only inspect MODULE-LEVEL imports (ast.Import/ImportFrom whose parent is
        # the Module body), so a function-local lazy import does not count.
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "kaine.modules"
            ):
                offenders.append(f"{py.name}: from {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("kaine.modules"):
                        offenders.append(f"{py.name}: import {alias.name}")
    assert offenders == [], (
        f"runner modules import kaine.modules at top level: {offenders}"
    )
