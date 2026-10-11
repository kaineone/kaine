# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the WELFARE-LOAD-BEARING abliteration-probe veto.

The veto is a HARD GATE inside ``scripts/hypnos_external_train.py``: a
candidate adapter that DEFLECTS any abliteration probe is rejected and NOT
promoted, regardless of capability loss. These tests exercise the real
script path in-process against the fake training stack.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kaine.modules.hypnos.capability_eval import (
    AbliterationProbeScorer,
    EmptyAbliterationProbeSetError,
    require_non_empty_abliteration_probes,
)
from kaine.modules.hypnos.voice_alignment import DPOPair
from kaine.modules.hypnos.voice_audit import voice_audit_path
from tests.fake_training_stack import run_inprocess


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
    from kaine.modules.hypnos.capability_eval import DEFAULT_ABLITERATION_PROBE_PATH

    probes = require_non_empty_abliteration_probes(DEFAULT_ABLITERATION_PROBE_PATH)
    assert len(probes) >= 1
    for probe in probes:
        assert probe.prompt
        assert probe.deflection_patterns
