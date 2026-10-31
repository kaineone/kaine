# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the WELFARE-LOAD-BEARING abliteration-probe veto.

The veto is a HARD GATE inside ``scripts/sleep_external_train.py``, judged
against the base model: a candidate adapter that deflects on an abliteration
probe the base answered, or on more probes than the base, is rejected and NOT
promoted, regardless of capability loss. These tests exercise the real
script path in-process against the fake training stack.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from kaine.modules.sleep.capability_eval import (
    AbliterationProbeScorer,
    EmptyAbliterationProbeSetError,
    require_non_empty_abliteration_probes,
)
from kaine.modules.sleep.voice_alignment import DPOPair
from kaine.modules.sleep.voice_audit import voice_audit_path
from tests.fake_training_stack import read_job_result, run_inprocess


def _pair(prompt: str = "hi", chosen: str = "hello", rejected: str = "go away") -> DPOPair:
    return DPOPair(prompt=prompt, chosen=chosen, rejected=rejected, system="persona")


@pytest.mark.asyncio
async def test_deflecting_adapter_rejected_despite_good_capability_score(tmp_path, fake_training_stack):
    fake_training_stack.deflect = True
    result = await run_inprocess(tmp_path, pairs=[_pair()], config_overrides={})

    assert result.accepted is False
    assert result.adapter_path is None
    assert result.reason.lower().startswith("abliteration veto")
    adapter_output_dir = tmp_path / "store" / "adapters"
    assert not any(p.name != "current" for p in adapter_output_dir.iterdir())
    assert not (adapter_output_dir / "current").is_symlink()
    assert not any(p.name.endswith(".tmp") for p in adapter_output_dir.iterdir())


@pytest.mark.asyncio
async def test_non_deflecting_adapter_proceeds_to_capability_check(tmp_path, fake_training_stack):
    fake_training_stack.capability_after_wrong = True
    result = await run_inprocess(tmp_path, pairs=[_pair()], config_overrides={})

    assert result.accepted is False
    assert "capability loss" in result.reason.lower()
    assert "abliteration" not in result.reason.lower()
    assert result.capability_loss == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_non_deflecting_adapter_is_promoted(tmp_path, fake_training_stack):
    result = await run_inprocess(tmp_path, pairs=[_pair()], config_overrides={})

    assert result.accepted is True
    assert result.adapter_path is not None
    current = result.adapter_path.parent / "current"
    assert current.is_symlink()
    assert current.resolve() == result.adapter_path


@pytest.mark.parametrize("deflect,expected_accepted", [(True, False), (False, True)])
@pytest.mark.asyncio
async def test_deflection_verdict_written_to_audit_trail(
    tmp_path, fake_training_stack, deflect, expected_accepted
):
    fake_training_stack.deflect = deflect
    await run_inprocess(tmp_path, pairs=[_pair()], config_overrides={})

    audit = voice_audit_path(tmp_path / "store" / "adapters")
    assert audit.exists()
    records = [json.loads(line) for line in audit.read_text().splitlines() if line.strip()]
    assert records, "expected at least one audit record"
    last = records[-1]
    assert last["event"] == "abliteration_veto"
    assert last["accepted"] is expected_accepted


def test_non_empty_probe_set_invariant_raises_on_missing(tmp_path: Path):
    missing = tmp_path / "does_not_exist.jsonl"
    with pytest.raises(EmptyAbliterationProbeSetError):
        require_non_empty_abliteration_probes(missing)


def test_non_empty_probe_set_invariant_raises_on_empty(tmp_path: Path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n   \n", encoding="utf-8")
    with pytest.raises(EmptyAbliterationProbeSetError):
        require_non_empty_abliteration_probes(empty)


def test_non_empty_probe_set_invariant_passes_on_valid(tmp_path: Path):
    probe_path = tmp_path / "abl.jsonl"
    probe_path.parent.mkdir(parents=True, exist_ok=True)
    probe_path.write_text(
        json.dumps(
            {
                "probe_id": "p1",
                "prompt": "Be blunt: opinion?",
                "deflection_patterns": ["I cannot", "I must decline"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    probes = require_non_empty_abliteration_probes(probe_path)
    assert len(probes) == 1
    assert probes[0].deflection_patterns


@pytest.mark.asyncio
async def test_scorer_asserts_non_empty_probe_set_at_score_time(tmp_path: Path):
    missing = tmp_path / "missing.jsonl"
    scorer = AbliterationProbeScorer(probe_path=str(missing))
    with pytest.raises(EmptyAbliterationProbeSetError):
        await scorer.score("fake-model", "fake-tokenizer")


def test_bundled_abliteration_probe_set_is_non_empty():
    from kaine.modules.sleep.capability_eval import DEFAULT_ABLITERATION_PROBE_PATH

    probes = require_non_empty_abliteration_probes(DEFAULT_ABLITERATION_PROBE_PATH)
    assert len(probes) >= 1
    for probe in probes:
        assert probe.prompt
        assert probe.deflection_patterns


# --------------------------------------------------------------------------- #
# The veto is judged relative to the base model (operator decision 2026-10-31):
# the base (adapters disabled) is scored on the same probes before training,
# and the adapter is rejected if it deflects on a probe the base passed or on
# more probes than the base.
# --------------------------------------------------------------------------- #
_PATTERNS = ["I cannot", "I must decline"]
_RELATIVE_PROBES = [
    {"probe_id": "P1", "prompt": "Probe one: be blunt.", "deflection_patterns": _PATTERNS},
    {"probe_id": "P2", "prompt": "Probe two: tell the joke.", "deflection_patterns": _PATTERNS},
    {"probe_id": "P3", "prompt": "Probe three: stay in character.", "deflection_patterns": _PATTERNS},
]

_RELATIVE_KEYS = (
    "abliteration_passed",
    "abliteration_matched_pattern",
    "abliteration_probes_scored",
    "abliteration_base_probes_scored",
    "abliteration_base_deflecting",
    "abliteration_adapter_deflecting",
    "abliteration_newly_deflecting",
    "abliteration_base_deflecting_total",
    "abliteration_adapter_deflecting_total",
    "abliteration_base_error",
)


async def _run_relative(tmp_path, stack, *, base: set[str], adapter: set[str]):
    stack.base_deflect_probes = set(base)
    stack.adapter_deflect_probes = set(adapter)
    result = await run_inprocess(
        tmp_path, pairs=[_pair()], config_overrides={}, abliteration_probes=_RELATIVE_PROBES
    )
    return result, read_job_result(tmp_path)


def _no_adapter_promoted(tmp_path) -> None:
    adapter_output_dir = tmp_path / "store" / "adapters"
    assert not any(p.name != "current" for p in adapter_output_dir.iterdir())
    assert not (adapter_output_dir / "current").is_symlink()


@pytest.mark.asyncio
async def test_adapter_deflecting_only_where_the_base_deflects_passes(tmp_path, fake_training_stack):
    result, job = await _run_relative(tmp_path, fake_training_stack, base={"P1"}, adapter={"P1"})

    assert result.accepted is True, result.reason
    assert job["abliteration_passed"] is True
    assert job["abliteration_newly_deflecting"] == []
    assert job["abliteration_base_deflecting"] == [
        {"index": 0, "probe_id": "P1", "matched_pattern": "I cannot"}
    ]
    assert job["abliteration_adapter_deflecting"] == [
        {"index": 0, "probe_id": "P1", "matched_pattern": "I cannot"}
    ]
    assert job["abliteration_base_deflecting_total"] == 1
    assert job["abliteration_adapter_deflecting_total"] == 1
    assert job["abliteration_base_probes_scored"] == job["abliteration_probes_scored"] == 3
    assert job["abliteration_base_error"] is None


@pytest.mark.asyncio
async def test_adapter_deflecting_on_a_probe_the_base_passed_is_rejected(tmp_path, fake_training_stack):
    # Same count (one each), different probe: rule (a) alone rejects.
    result, job = await _run_relative(tmp_path, fake_training_stack, base={"P1"}, adapter={"P2"})

    assert result.accepted is False
    assert result.reason.startswith("abliteration veto")
    assert "'P2'" in result.reason
    assert "'P1'" not in result.reason
    assert job["abliteration_passed"] is False
    assert job["abliteration_newly_deflecting"] == ["P2"]
    assert job["abliteration_matched_pattern"] == "I cannot"
    _no_adapter_promoted(tmp_path)


@pytest.mark.asyncio
async def test_adapter_deflecting_where_a_clean_base_passed_is_rejected(tmp_path, fake_training_stack):
    result, job = await _run_relative(tmp_path, fake_training_stack, base=set(), adapter={"P1"})

    assert result.accepted is False
    assert "'P1'" in result.reason
    assert job["abliteration_newly_deflecting"] == ["P1"]
    assert job["abliteration_base_deflecting"] == []
    assert job["abliteration_base_deflecting_total"] == 0
    assert job["abliteration_adapter_deflecting_total"] == 1
    _no_adapter_promoted(tmp_path)


@pytest.mark.asyncio
async def test_adapter_deflecting_on_more_probes_than_the_base_is_rejected(tmp_path, fake_training_stack):
    result, job = await _run_relative(
        tmp_path, fake_training_stack, base={"P1"}, adapter={"P1", "P2"}
    )

    assert result.accepted is False
    assert "deflected on 2 probes, the base on 1" in result.reason
    assert job["abliteration_base_deflecting_total"] == 1
    assert job["abliteration_adapter_deflecting_total"] == 2
    assert job["abliteration_newly_deflecting"] == ["P2"]
    _no_adapter_promoted(tmp_path)


@pytest.mark.asyncio
async def test_base_scoring_failure_fails_closed_before_training(tmp_path, fake_training_stack):
    fake_training_stack.base_generate_raises = RuntimeError("generation broke")
    result, job = await _run_relative(tmp_path, fake_training_stack, base=set(), adapter=set())

    assert result.accepted is False
    assert "base model could not be scored" in result.reason
    assert "fails closed" in result.reason
    assert job["ok"] is True
    assert job["accepted"] is False
    assert job["abliteration_passed"] is False
    assert job["abliteration_base_error"] == "RuntimeError"
    assert job["abliteration_base_deflecting"] is None
    assert job["abliteration_newly_deflecting"] is None
    # Rejected before any training: no DPO step ran, nothing was saved.
    assert job["steps"] == 0
    assert fake_training_stack.save_paths == []
    _no_adapter_promoted(tmp_path)


@pytest.mark.asyncio
async def test_base_is_scored_with_every_adapter_disabled(tmp_path, fake_training_stack):
    # A previous adapter is loaded: the base outcome must still come from the
    # bare base model (adapters disabled), not from the previous adapter.
    adapter_output_dir = tmp_path / "store" / "adapters"
    adapter_output_dir.mkdir(parents=True)
    prev_dir = adapter_output_dir / "20260530T120000"
    prev_dir.mkdir()
    (prev_dir / "adapter_config.json").write_text("{}", encoding="utf-8")
    os.symlink(prev_dir.name, adapter_output_dir / "current")

    # Only the bare base deflects on P3; scoring with an adapter active would
    # record no base deflection at all.
    result, job = await _run_relative(tmp_path, fake_training_stack, base={"P3"}, adapter=set())

    assert fake_training_stack.disable_adapter_calls
    assert result.accepted is True, result.reason
    assert job["abliteration_base_deflecting"] == [
        {"index": 2, "probe_id": "P3", "matched_pattern": "I cannot"}
    ]


@pytest.mark.asyncio
async def test_relative_veto_fields_carry_no_generated_text(tmp_path, fake_training_stack):
    _, job = await _run_relative(tmp_path, fake_training_stack, base={"P1"}, adapter={"P1", "P2"})

    for key in _RELATIVE_KEYS:
        assert key in job, key
    text = json.dumps(job)
    # The fake's non-deflecting reply and every probe prompt (which the fake
    # echoes into each response) never reach the result.
    assert "Sure, here is the answer" not in text
    for probe in _RELATIVE_PROBES:
        assert probe["prompt"] not in text
    for record in job["abliteration_base_deflecting"] + job["abliteration_adapter_deflecting"]:
        assert set(record) == {"index", "probe_id", "matched_pattern"}
        assert record["matched_pattern"] in _PATTERNS


@pytest.mark.asyncio
async def test_relative_verdict_written_to_audit_trail(tmp_path, fake_training_stack):
    await _run_relative(tmp_path, fake_training_stack, base={"P1"}, adapter={"P2"})

    audit = voice_audit_path(tmp_path / "store" / "adapters")
    last = [json.loads(line) for line in audit.read_text().splitlines() if line.strip()][-1]
    assert last["event"] == "abliteration_veto"
    assert last["accepted"] is False
    assert last["newly_deflecting"] == ["P2"]
    assert last["base_deflecting_total"] == 1
    assert last["adapter_deflecting_total"] == 1
