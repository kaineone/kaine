# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the oscillatory_ablation evaluation switch."""
from __future__ import annotations

import asyncio

import pytest

from kaine.evaluation.ab_divergence import FakeBareInferenceClient
from kaine.evaluation.config import EvaluationConfig
from kaine.evaluation.embeddings import HashEmbedder
from kaine.evaluation.registry import SidecarRegistry


class FakeBus:
    async def read(self, stream, *, last_id="0", count=100, block_ms=0):
        return []

    async def read_entries(self, stream, last_id="0", count=100, block_ms=0):
        return [], None

    async def subscribe_workspace(self, last_id="$", count=32, poll_interval_s=0.05):
        while True:
            await asyncio.sleep(poll_interval_s)
            if False:  # pragma: no cover
                yield

    async def current_workspace_id(self):
        return "0"


def _config_dict(tmp_path, **overrides):
    return {
        "workspace_trajectory": True,
        "paths": {
            "trajectory_dir": str(tmp_path / "traj"),
            "evaluation_logs": str(tmp_path / "eval"),
            "retention_days": 30,
        },
        **overrides,
    }


def test_from_mapping_reads_oscillatory_ablation():
    assert (
        EvaluationConfig.from_mapping({"oscillatory_ablation": True}).oscillatory_ablation
        is True
    )
    assert EvaluationConfig.from_mapping({}).oscillatory_ablation is False


@pytest.mark.asyncio
async def test_registry_builds_ablation_recorder_when_enabled(tmp_path):
    cfg = EvaluationConfig.from_mapping(_config_dict(tmp_path, oscillatory_ablation=True))
    sidecar = SidecarRegistry(
        bus=FakeBus(),
        config=cfg,
        embedder=HashEmbedder(),
        bare_inference_client=FakeBareInferenceClient(),
    )
    sidecar.build()
    assert sidecar.ablation_recorder is not None


@pytest.mark.asyncio
async def test_registry_ablation_recorder_absent_by_default(tmp_path):
    cfg = EvaluationConfig.from_mapping(_config_dict(tmp_path))
    sidecar = SidecarRegistry(
        bus=FakeBus(),
        config=cfg,
        embedder=HashEmbedder(),
        bare_inference_client=FakeBareInferenceClient(),
    )
    sidecar.build()
    assert sidecar.ablation_recorder is None
