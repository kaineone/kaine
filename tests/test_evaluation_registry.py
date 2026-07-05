# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from kaine.evaluation.ab_divergence import FakeBareInferenceClient
from kaine.evaluation.config import EvaluationConfig, EvaluationPaths
from kaine.evaluation.embeddings import HashEmbedder
from kaine.evaluation.registry import SidecarRegistry


class FakeBus:
    async def read(self, stream, *, last_id="0", count=100, block_ms=0):
        return []

    async def read_entries(self, stream, last_id="0", count=100, block_ms=0):
        return [], None

    async def subscribe_workspace(self, last_id="$", count=32, poll_interval_s=0.05):
        # Idle generator: never yields, keeps workspace observers alive and
        # waiting (the `yield` is unreachable but makes this an async generator).
        while True:
            await asyncio.sleep(poll_interval_s)
            if False:  # pragma: no cover
                yield

    async def current_workspace_id(self):
        return "0"


def _config(tmp_path, **overrides) -> EvaluationConfig:
    base = EvaluationConfig.from_mapping(
        {
            "paths": {
                "trajectory_dir": str(tmp_path / "traj"),
                "evaluation_logs": str(tmp_path / "eval"),
                "retention_days": 30,
            },
            **overrides,
        }
    )
    return base


@pytest.mark.asyncio
async def test_registry_builds_passive_observers(tmp_path):
    cfg = _config(tmp_path)
    bus = FakeBus()
    sidecar = SidecarRegistry(
        bus=bus,
        config=cfg,
        embedder=HashEmbedder(),
        bare_inference_client=FakeBareInferenceClient(),
    )
    sidecar.build()
    names = [o.name for o in sidecar.observers]
    # No memory_source / cognitive_client provided → those two observers skipped.
    assert "trajectory" in names
    assert "attribution" in names
    assert "proactive_audit" in names
    assert "sleep_snapshots" in names
    assert "voice_tracking" in names
    assert "affect_correlation" in names
    assert "ab_divergence" in names
    assert "memory_probes" not in names
    assert "eidolon_accuracy" not in names


@pytest.mark.asyncio
async def test_registry_disabled_when_master_off(tmp_path):
    cfg = _config(tmp_path, enabled=False)
    sidecar = SidecarRegistry(bus=FakeBus(), config=cfg)
    sidecar.build()
    assert sidecar.observers == []
    await sidecar.start()
    assert sidecar.started is False


@pytest.mark.asyncio
async def test_registry_per_component_opt_out(tmp_path):
    cfg = _config(tmp_path, ab_divergence=False)
    sidecar = SidecarRegistry(
        bus=FakeBus(),
        config=cfg,
        embedder=HashEmbedder(),
        bare_inference_client=FakeBareInferenceClient(),
    )
    sidecar.build()
    names = [o.name for o in sidecar.observers]
    assert "ab_divergence" not in names
    assert "trajectory" in names


@pytest.mark.asyncio
async def test_registry_start_stop_lifecycle(tmp_path):
    cfg = _config(tmp_path)
    sidecar = SidecarRegistry(
        bus=FakeBus(),
        config=cfg,
        embedder=HashEmbedder(),
        bare_inference_client=FakeBareInferenceClient(),
    )
    await sidecar.start()
    assert sidecar.started is True
    # Every observer must actually be running — not silently dead from a missing
    # bus method (the exact failure mode that hid the workspace-decode bug).
    await asyncio.sleep(0.05)
    for obs in sidecar.observers:
        assert obs._task is not None, f"{obs.name} never started a task"
        assert not obs._task.done(), f"{obs.name} task died after start"
    await sidecar.stop()
    assert sidecar.started is False
    for obs in sidecar.observers:
        assert obs._task is None, f"{obs.name} task not cleaned up"


def test_no_core_module_imports_kaine_evaluation():
    """The privacy boundary: only kaine/cycle/__main__.py is allowed
    to import from kaine.evaluation. No core module should."""
    proc = subprocess.run(
        ["git", "grep", "-l", "from kaine.evaluation", "--", "kaine/"],
        cwd=Path(__file__).parent.parent,
        capture_output=True,
        text=True,
    )
    matches = [
        line for line in proc.stdout.strip().splitlines() if line
    ]
    # The cycle entrypoint and nexus entrypoint are the allowed coupling points.
    # nexus/__main__.py uses a lazy/optional import to mount the tab when enabled.
    allowed = {
        "kaine/cycle/__main__.py",
        "kaine/nexus/__main__.py",
    }
    unexpected = set(matches) - allowed - {p + "/" for p in allowed}
    # Filter out any kaine/evaluation/ files (they're allowed to import each other).
    unexpected = {m for m in unexpected if not m.startswith("kaine/evaluation/")}
    assert unexpected == set(), (
        f"sidecar boundary violated: {unexpected}. Only "
        f"{allowed} are allowed to import from kaine.evaluation."
    )


class _FakeMemorySource:
    async def sample_old_memory(self, *, older_than_seconds):
        return None


class _FakeCognitiveClient:
    async def query(self, user_text):
        return ""


@pytest.mark.asyncio
async def test_registry_builds_memory_and_eidolon_with_providers(tmp_path):
    """With a memory_source + cognitive_query_client supplied, the memory-probe
    and eidolon-accuracy observers instantiate (the 7-of-9 → 9 fix)."""
    cfg = _config(tmp_path)
    sidecar = SidecarRegistry(
        bus=FakeBus(),
        config=cfg,
        embedder=HashEmbedder(),
        bare_inference_client=FakeBareInferenceClient(),
        memory_source=_FakeMemorySource(),
        cognitive_query_client=_FakeCognitiveClient(),
    )
    sidecar.build()
    names = [o.name for o in sidecar.observers]
    assert "memory_probes" in names
    assert "eidolon_accuracy" in names
