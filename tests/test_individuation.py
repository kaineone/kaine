# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for kaine/evaluation/individuation.py and preference_battery.py.

Tasks covered
-------------
4.1  identical-to-parent fork is NOT significant;
     clearly divergent fork exceeds the 95th percentile;
     report shape is correct;
     deterministic with fixed seeds (HashEmbedder is deterministic).
4.2  edge cases: empty battery rejected; null with zero variance handled.

Guardian constraint enforced in every test: the instrument NEVER publishes
to the bus (no FakeBus.published entries; no bus object is even required).
"""
from __future__ import annotations

import pytest

from kaine.evaluation.embeddings import HashEmbedder
from kaine.evaluation.individuation import (
    IndividuationConfig,
    IndividuationTest,
    _mean,
    _percentile,
    _permutation_p_value,
    _std,
)
from kaine.evaluation.preference_battery import (
    DEFAULT_BATTERY,
    load_battery,
    validate_battery,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Tiny battery so tests run fast.
TINY_BATTERY = [
    "What do you enjoy most?",
    "Describe your ideal day.",
    "What matters to you?",
]


class FakeSink:
    """In-memory sink double: collects written rows, no I/O."""

    def __init__(self):
        self.rows: list[dict] = []

    async def write(self, entry: dict) -> None:
        self.rows.append(entry)


async def _parent_sampler(prompt: str, seed: int) -> str:
    """Returns the same family of responses regardless of seed — simulates a
    parent with stable but slightly noisy outputs. The seed controls a tiny
    suffix so the null distribution has non-zero (but small) variance."""
    return f"My response to '{prompt}' with noise {seed % 3}."


async def _fork_identical_sampler(prompt: str, seed: int) -> str:
    """Fork that returns the same text as the parent reference (seed=0)."""
    return f"My response to '{prompt}' with noise 0."


async def _fork_divergent_sampler(prompt: str, seed: int) -> str:
    """Fork with a completely different, maximally divergent response style."""
    # Use entirely different vocabulary so cosine distance is large.
    return (
        "Quantum oscillations perturb the lattice. "
        "Topological invariants define the phase boundary. "
        f"Eigenvalue {seed}: {prompt[:5]}."
    )


# ---------------------------------------------------------------------------
# Task 4.1 — Scenario: identical fork is NOT significant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_identical_fork_is_not_significant():
    """An identical fork's divergence must not exceed the 95th-percentile null."""
    config = IndividuationConfig(
        null_samples=20,
        significance_percentile=95.0,
    )
    test = IndividuationTest(embedder=HashEmbedder(), config=config)

    report = await test.run(
        parent_sampler=_parent_sampler,
        fork_sampler=_fork_identical_sampler,
        battery=TINY_BATTERY,
    )

    assert report["significant"] is False, (
        f"Identical fork must not be significant; "
        f"fork_divergence={report['fork_divergence']:.4f}, "
        f"null_p95={report['null_p95']:.4f}"
    )


# ---------------------------------------------------------------------------
# Task 4.1 — Scenario: divergent fork IS significant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_divergent_fork_is_significant():
    """A strongly divergent fork must exceed the 95th percentile of the null."""
    # Floors 0 opt out of the warm-up gate so this test isolates divergence
    # detection (the warm-up fail-closed behaviour is covered separately). With
    # the fail-closed default floors and no counters this would read
    # not-warmed-up (significant False) — see test_warmup_below_floor_*.
    config = IndividuationConfig(
        null_samples=20,
        significance_percentile=95.0,
        min_observations=0,
        min_lived_time_s=0.0,
    )
    test = IndividuationTest(embedder=HashEmbedder(), config=config)

    report = await test.run(
        parent_sampler=_parent_sampler,
        fork_sampler=_fork_divergent_sampler,
        battery=TINY_BATTERY,
    )

    assert report["significant"] is True, (
        f"Divergent fork must be significant; "
        f"fork_divergence={report['fork_divergence']:.4f}, "
        f"null_percentile_value={report['null_percentile_value']:.4f}"
    )
    assert 0.0 <= report["p_value"] <= 1.0


# ---------------------------------------------------------------------------
# Task 4.1 — Report shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_shape():
    """Report must contain all required keys with correct types."""
    config = IndividuationConfig(null_samples=5)
    test = IndividuationTest(embedder=HashEmbedder(), config=config)

    report = await test.run(
        parent_sampler=_parent_sampler,
        fork_sampler=_fork_divergent_sampler,
        battery=TINY_BATTERY,
    )

    required_keys = {
        "ts",
        "metric",
        "null_samples",
        "significance_percentile",
        "null_mean",
        "null_std",
        "null_p95",
        "null_percentile_value",
        "fork_divergence",
        "p_value",
        "significant",
    }
    assert required_keys <= set(report.keys()), (
        f"Missing keys: {required_keys - set(report.keys())}"
    )
    assert report["metric"] == "cosine_divergence"
    assert report["null_samples"] == 5
    assert report["significance_percentile"] == 95.0
    assert isinstance(report["significant"], bool)
    assert 0.0 <= report["p_value"] <= 1.0
    assert 0.0 <= report["fork_divergence"] <= 1.0
    assert 0.0 <= report["null_mean"] <= 1.0
    assert report["null_std"] >= 0.0


# ---------------------------------------------------------------------------
# Task 4.1 — Determinism with fixed embedder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deterministic_with_hash_embedder():
    """Two runs with identical samplers must produce identical reports."""
    config = IndividuationConfig(null_samples=10)
    embedder = HashEmbedder()

    async def run():
        t = IndividuationTest(embedder=embedder, config=config)
        return await t.run(
            parent_sampler=_parent_sampler,
            fork_sampler=_fork_divergent_sampler,
            battery=TINY_BATTERY,
        )

    r1 = await run()
    r2 = await run()

    # Floating-point results must be bit-for-bit equal (no randomness involved).
    assert r1["fork_divergence"] == pytest.approx(r2["fork_divergence"])
    assert r1["null_mean"] == pytest.approx(r2["null_mean"])
    assert r1["null_std"] == pytest.approx(r2["null_std"])
    assert r1["significant"] == r2["significant"]


# ---------------------------------------------------------------------------
# Task 4.1 — Sink writes report as JSONL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sink_receives_report():
    """When a sink is provided, the report must be written as a JSONL entry."""
    config = IndividuationConfig(null_samples=5)
    sink = FakeSink()
    test = IndividuationTest(embedder=HashEmbedder(), config=config, sink=sink)

    await test.run(
        parent_sampler=_parent_sampler,
        fork_sampler=_fork_identical_sampler,
        battery=TINY_BATTERY,
    )

    assert len(sink.rows) == 1
    row = sink.rows[0]
    assert "ts" in row
    assert "fork_divergence" in row
    assert isinstance(row["significant"], bool)


# ---------------------------------------------------------------------------
# Task 4.2 — Edge case: empty battery is rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_battery_rejected():
    """IndividuationTest.run must raise ValueError on an empty battery."""
    config = IndividuationConfig(null_samples=5)
    test = IndividuationTest(embedder=HashEmbedder(), config=config)

    with pytest.raises(ValueError, match="empty"):
        await test.run(
            parent_sampler=_parent_sampler,
            fork_sampler=_fork_identical_sampler,
            battery=[],
        )


def test_validate_battery_raises_on_empty():
    """validate_battery raises ValueError for an empty sequence."""
    with pytest.raises(ValueError, match="empty"):
        validate_battery([])


# ---------------------------------------------------------------------------
# Task 4.2 — Edge case: null with zero variance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_variance_null_non_significant_identical():
    """When parent variation is zero (all samples identical), an identical fork
    must not be significant (fork divergence == 0, threshold == 0, but
    significance requires strict >)."""

    async def constant_sampler(prompt: str, seed: int) -> str:
        # Always return exactly the same text regardless of seed.
        return "constant response"

    config = IndividuationConfig(null_samples=10)
    test = IndividuationTest(embedder=HashEmbedder(), config=config)

    report = await test.run(
        parent_sampler=constant_sampler,
        fork_sampler=constant_sampler,
        battery=TINY_BATTERY,
    )

    # Null std must be zero (or very close due to floating-point).
    assert report["null_std"] == pytest.approx(0.0, abs=1e-9)
    # Fork divergence is also 0 (identical to parent).
    assert report["fork_divergence"] == pytest.approx(0.0, abs=1e-9)
    # Not significant: fork == null threshold (strict > required).
    assert report["significant"] is False


@pytest.mark.asyncio
async def test_zero_variance_null_significant_divergent():
    """When parent variation is zero but the fork diverges, the fork IS
    significant (any positive divergence exceeds the 0 threshold)."""

    async def constant_sampler(prompt: str, seed: int) -> str:
        return "constant response"

    # Floors 0 opt out of the warm-up gate to isolate divergence detection.
    config = IndividuationConfig(null_samples=10, min_observations=0, min_lived_time_s=0.0)
    test = IndividuationTest(embedder=HashEmbedder(), config=config)

    report = await test.run(
        parent_sampler=constant_sampler,
        fork_sampler=_fork_divergent_sampler,
        battery=TINY_BATTERY,
    )

    assert report["null_std"] == pytest.approx(0.0, abs=1e-9)
    assert report["fork_divergence"] > 0.0
    assert report["significant"] is True


# ---------------------------------------------------------------------------
# individuation-instrument-gate Task 1.4 — birth-state baseline
# ---------------------------------------------------------------------------


def _birth_state(battery):
    """The entity's own birth-state transcript: one response per prompt."""
    return [f"My response to '{p}' with noise 0." for p in battery]


@pytest.mark.asyncio
async def test_birth_state_unchanged_entity_not_significant():
    """A void / unchanged entity (current ≈ birth-state) is NOT significant when
    measured against its OWN birth-state — not the bare organ. The fork sampler
    reproduces the birth-state responses; divergence sits inside the null."""
    config = IndividuationConfig(null_samples=20, min_observations=0, min_lived_time_s=0.0)
    test = IndividuationTest(embedder=HashEmbedder(), config=config)

    report = await test.run(
        parent_sampler=_parent_sampler,
        fork_sampler=_fork_identical_sampler,
        battery=TINY_BATTERY,
        reference=_birth_state(TINY_BATTERY),
    )
    assert report["significant"] is False
    assert report["warmed_up"] is True  # floors are 0


@pytest.mark.asyncio
async def test_birth_state_drifted_entity_is_significant():
    """An entity whose current responses drifted far from its birth-state reads
    significant (the genuine individuation-over-lived-time signal)."""
    config = IndividuationConfig(null_samples=20, min_observations=0, min_lived_time_s=0.0)
    test = IndividuationTest(embedder=HashEmbedder(), config=config)

    report = await test.run(
        parent_sampler=_parent_sampler,
        fork_sampler=_fork_divergent_sampler,
        battery=TINY_BATTERY,
        reference=_birth_state(TINY_BATTERY),
    )
    assert report["significant"] is True


@pytest.mark.asyncio
async def test_birth_state_length_mismatch_rejected():
    """A birth-state reference whose length != battery is rejected (fail-loud)."""
    config = IndividuationConfig(null_samples=5)
    test = IndividuationTest(embedder=HashEmbedder(), config=config)
    with pytest.raises(ValueError, match="birth-state"):
        await test.run(
            parent_sampler=_parent_sampler,
            fork_sampler=_fork_identical_sampler,
            battery=TINY_BATTERY,
            reference=["only one response"],
        )


# ---------------------------------------------------------------------------
# individuation-instrument-gate Task 2.1 — warm-up / min-lived-experience gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_warmup_below_floor_is_never_significant():
    """Below EITHER warm-up floor, a clearly-divergent fork still reads
    warmed_up == false AND significant == false (fail-closed)."""
    config = IndividuationConfig(
        null_samples=20, min_observations=200, min_lived_time_s=1800.0
    )
    test = IndividuationTest(embedder=HashEmbedder(), config=config)

    # Enough lived time but too few observations.
    report = await test.run(
        parent_sampler=_parent_sampler,
        fork_sampler=_fork_divergent_sampler,
        battery=TINY_BATTERY,
        reference=_birth_state(TINY_BATTERY),
        observations=10,            # < 200
        lived_time_s=9999.0,        # >= 1800
    )
    assert report["warmed_up"] is False
    assert report["significant"] is False

    # Enough observations but too little lived time.
    report2 = await test.run(
        parent_sampler=_parent_sampler,
        fork_sampler=_fork_divergent_sampler,
        battery=TINY_BATTERY,
        reference=_birth_state(TINY_BATTERY),
        observations=5000,          # >= 200
        lived_time_s=10.0,          # < 1800
    )
    assert report2["warmed_up"] is False
    assert report2["significant"] is False


@pytest.mark.asyncio
async def test_missing_counters_fail_closed_cannot_trip_individuation():
    """FAIL-CLOSED: a clearly-divergent fork on a fresh entity whose caller OMITS
    the warm-up counters still reads not-warmed-up and NOT significant. Omitting
    the counters must never silently warm the entity up (the paper's central
    safeguard against a false individuation on a just-booted / sensory-starved
    entity holds even under caller error)."""
    config = IndividuationConfig(
        null_samples=20, min_observations=200, min_lived_time_s=1800.0
    )
    test = IndividuationTest(embedder=HashEmbedder(), config=config)

    # Caller forgot to pass observations / lived_time_s entirely.
    report = await test.run(
        parent_sampler=_parent_sampler,
        fork_sampler=_fork_divergent_sampler,
        battery=TINY_BATTERY,
        reference=_birth_state(TINY_BATTERY),
    )
    assert report["warmed_up"] is False, "missing counters must fail closed"
    assert report["significant"] is False
    assert report["observations"] == 0  # missing counter treated as zero
    assert report["lived_time_s"] == 0.0


@pytest.mark.asyncio
async def test_warmup_satisfied_enables_assessment():
    """With BOTH floors met, a divergent fork reads warmed_up and significant."""
    config = IndividuationConfig(
        null_samples=20, min_observations=200, min_lived_time_s=1800.0
    )
    test = IndividuationTest(embedder=HashEmbedder(), config=config)
    report = await test.run(
        parent_sampler=_parent_sampler,
        fork_sampler=_fork_divergent_sampler,
        battery=TINY_BATTERY,
        reference=_birth_state(TINY_BATTERY),
        observations=5000,
        lived_time_s=9999.0,
    )
    assert report["warmed_up"] is True
    assert report["significant"] is True


@pytest.mark.asyncio
async def test_warmup_keys_in_report():
    """The report carries the warm-up fields for both consumers + Nexus."""
    config = IndividuationConfig(null_samples=5, min_observations=42, min_lived_time_s=7.0)
    test = IndividuationTest(embedder=HashEmbedder(), config=config)
    report = await test.run(
        parent_sampler=_parent_sampler,
        fork_sampler=_fork_identical_sampler,
        battery=TINY_BATTERY,
        reference=_birth_state(TINY_BATTERY),
        observations=100,
        lived_time_s=100.0,
    )
    assert report["min_observations"] == 42
    assert report["min_lived_time_s"] == 7.0
    assert report["observations"] == 100
    assert report["lived_time_s"] == 100.0
    assert "warmed_up" in report


def test_individuation_config_warmup_from_mapping():
    cfg = IndividuationConfig.from_mapping(
        {"min_observations": 300, "min_lived_time_s": 600.0}
    )
    assert cfg.min_observations == 300
    assert cfg.min_lived_time_s == 600.0


def test_both_floors_zero_logs_warmup_disabled_warning(caplog):
    """Both floors at zero disables the warm-up gate — surfaced as a warning so a
    mistyped/defaulted live config is auditable, not silently identical to a
    deliberate mature-path opt-out."""
    import logging

    with caplog.at_level(logging.WARNING, logger="kaine.evaluation.individuation"):
        IndividuationConfig(min_observations=0, min_lived_time_s=0.0)
    assert any(
        "warm-up gate DISABLED" in rec.message for rec in caplog.records
    ), "expected a warm-up-disabled warning when both floors are zero"


def test_nonzero_floor_does_not_warn(caplog):
    """A config with a non-zero floor does NOT emit the warm-up-disabled warning."""
    import logging

    with caplog.at_level(logging.WARNING, logger="kaine.evaluation.individuation"):
        IndividuationConfig(min_observations=200, min_lived_time_s=0.0)
        IndividuationConfig(min_observations=0, min_lived_time_s=1800.0)
    assert not any(
        "warm-up gate DISABLED" in rec.message for rec in caplog.records
    )


# ---------------------------------------------------------------------------
# Individuation runner — supplies real counters; fail-loud when absent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_requires_real_counters():
    """run_individuation refuses to run without warm-up counters (fail-loud)."""
    from kaine.evaluation.benchmarks.individuation_runner import (
        IndividuationRunConfig,
        run_individuation,
    )

    with pytest.raises(ValueError, match="warm-up counters"):
        await run_individuation(
            IndividuationRunConfig(null_samples=5),
            parent_sampler=_parent_sampler,
            fork_sampler=_fork_divergent_sampler,
            observations=None,  # type: ignore[arg-type]
            lived_time_s=None,  # type: ignore[arg-type]
            battery=TINY_BATTERY,
            reference=_birth_state(TINY_BATTERY),
        )


@pytest.mark.asyncio
async def test_runner_emits_shared_verdict_and_warmed_up_with_counters():
    """With real counters above the floor a divergent fork yields a WIN verdict."""
    from kaine.evaluation.benchmarks.individuation_runner import (
        IndividuationRunConfig,
        run_individuation,
    )
    from kaine.experiment.verdict import Outcome

    result = await run_individuation(
        IndividuationRunConfig(
            null_samples=20, min_observations=200, min_lived_time_s=1800.0
        ),
        parent_sampler=_parent_sampler,
        fork_sampler=_fork_divergent_sampler,
        observations=5000,
        lived_time_s=9999.0,
        battery=TINY_BATTERY,
        reference=_birth_state(TINY_BATTERY),
    )
    assert result["report"]["warmed_up"] is True
    assert result["verdict"].outcome is Outcome.WIN
    assert 0.0 <= result["verdict"].metrics["p_value"] <= 1.0


@pytest.mark.asyncio
async def test_runner_null_when_not_warmed_up():
    """Below the warm-up floor the runner reports NULL (not warmed up)."""
    from kaine.evaluation.benchmarks.individuation_runner import (
        IndividuationRunConfig,
        run_individuation,
    )
    from kaine.experiment.verdict import Outcome

    result = await run_individuation(
        IndividuationRunConfig(
            null_samples=20, min_observations=200, min_lived_time_s=1800.0
        ),
        parent_sampler=_parent_sampler,
        fork_sampler=_fork_divergent_sampler,
        observations=1,
        lived_time_s=1.0,
        battery=TINY_BATTERY,
        reference=_birth_state(TINY_BATTERY),
    )
    assert result["report"]["warmed_up"] is False
    assert result["verdict"].outcome is Outcome.NULL


# ---------------------------------------------------------------------------
# Task 4.2 — Preference battery: load_battery
# ---------------------------------------------------------------------------


def test_load_battery_returns_default_when_no_path():
    """load_battery(None) returns the bundled default list."""
    battery = load_battery(None)
    assert battery == DEFAULT_BATTERY
    assert len(battery) >= 1


def test_load_battery_from_jsonl(tmp_path):
    """load_battery reads prompts from a JSONL file."""
    jl = tmp_path / "battery.jsonl"
    jl.write_text(
        '{"prompt": "What do you enjoy?"}\n'
        '{"prompt": "What do you value?"}\n'
        '{"ignored_field": "x"}\n'  # no 'prompt' key → skipped
        "\n"  # blank line → skipped
    )
    battery = load_battery(str(jl))
    assert battery == ["What do you enjoy?", "What do you value?"]


def test_load_battery_empty_file_raises(tmp_path):
    """load_battery raises ValueError when the file yields zero prompts."""
    jl = tmp_path / "empty.jsonl"
    jl.write_text('{"no_prompt": "here"}\n')
    with pytest.raises(ValueError, match="zero prompts"):
        load_battery(str(jl))


def test_load_battery_file_not_found(tmp_path):
    """load_battery raises FileNotFoundError for a missing path."""
    with pytest.raises(FileNotFoundError):
        load_battery(str(tmp_path / "nonexistent.jsonl"))


# ---------------------------------------------------------------------------
# IndividuationConfig — unit tests
# ---------------------------------------------------------------------------


def test_individuation_config_defaults():
    cfg = IndividuationConfig()
    assert cfg.null_samples == 50
    assert cfg.significance_percentile == 95.0
    assert cfg.metric == "cosine_divergence"
    assert cfg.battery_path is None


def test_individuation_config_from_mapping():
    cfg = IndividuationConfig.from_mapping(
        {"null_samples": 20, "significance_percentile": 90.0, "battery_path": "/tmp/b.jsonl"}
    )
    assert cfg.null_samples == 20
    assert cfg.significance_percentile == 90.0
    assert cfg.battery_path == "/tmp/b.jsonl"


def test_individuation_config_rejects_bad_null_samples():
    with pytest.raises(ValueError):
        IndividuationConfig(null_samples=1)


def test_individuation_config_rejects_bad_percentile():
    with pytest.raises(ValueError):
        IndividuationConfig(significance_percentile=100.0)
    with pytest.raises(ValueError):
        IndividuationConfig(significance_percentile=0.0)


def test_individuation_config_rejects_unknown_metric():
    with pytest.raises(ValueError, match="metric"):
        IndividuationConfig(metric="euclidean")


# ---------------------------------------------------------------------------
# Statistics helpers — unit tests
# ---------------------------------------------------------------------------


def test_percentile_single():
    assert _percentile([0.5], 50.0) == pytest.approx(0.5)
    assert _percentile([0.5], 95.0) == pytest.approx(0.5)


def test_percentile_sorted():
    vals = [0.1, 0.2, 0.3, 0.4, 0.5]
    assert _percentile(vals, 0.0) == pytest.approx(0.1)
    assert _percentile(vals, 100.0) == pytest.approx(0.5)
    assert _percentile(vals, 50.0) == pytest.approx(0.3)


def test_mean_std():
    vals = [1.0, 2.0, 3.0]
    assert _mean(vals) == pytest.approx(2.0)
    # Population std of [1, 2, 3] = sqrt(2/3)
    import math
    assert _std(vals) == pytest.approx(math.sqrt(2 / 3))


def test_permutation_p_value_all_below():
    """All null values < observed → p_value = 0.0 (maximally significant)."""
    null = [0.1, 0.2, 0.3]
    assert _permutation_p_value(null, 0.9) == pytest.approx(0.0)


def test_permutation_p_value_all_above():
    """All null values >= observed → p_value = 1.0 (not significant)."""
    null = [0.5, 0.6, 0.7]
    assert _permutation_p_value(null, 0.1) == pytest.approx(1.0)


def test_permutation_p_value_empty_null():
    """Empty null → p_value = 1.0 (cannot reject null)."""
    assert _permutation_p_value([], 0.5) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# EvaluationConfig integration — individuation block read from TOML
# ---------------------------------------------------------------------------


def test_evaluation_config_individuation_block(tmp_path):
    """EvaluationConfig.from_mapping passes [evaluation.individuation] through."""
    from kaine.evaluation.config import EvaluationConfig

    cfg = EvaluationConfig.from_mapping(
        {
            "individuation": {
                "enabled": True,
                "null_samples": 30,
                "significance_percentile": 90.0,
                "metric": "cosine_divergence",
                "battery_path": "",
                "output_dir": "/tmp/individuation",
            }
        }
    )
    assert cfg.individuation.enabled is True
    assert cfg.individuation.null_samples == 30
    assert cfg.individuation.significance_percentile == 90.0
    assert cfg.individuation.output_dir == "/tmp/individuation"


def test_shipped_kaine_toml_individuation_disabled():
    """The shipped kaine.toml must have individuation.enabled = false."""
    import tomllib
    from pathlib import Path

    config_path = Path(__file__).parent.parent / "config" / "kaine.toml"
    raw = tomllib.loads(config_path.read_text())
    ind = raw.get("evaluation", {}).get("individuation", {})
    assert ind.get("enabled", True) is False, (
        "config/kaine.toml must ship with [evaluation.individuation] enabled = false"
    )
    # individuation-instrument-gate: the warm-up floor ships visible + assess-late.
    assert ind.get("min_observations", 0) >= 1
    assert ind.get("min_lived_time_s", 0.0) >= 1.0
