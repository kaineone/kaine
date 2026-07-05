# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Sidecar subsystem: registry boots, observers write JSONL, boundary holds."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from kaine.evaluation.ab_divergence import FakeBareInferenceClient
from kaine.evaluation.config import EvaluationConfig
from kaine.evaluation.embeddings import HashEmbedder
from kaine.evaluation.registry import SidecarRegistry

from tests.systems._harness import SubsystemHarness


@pytest.mark.asyncio
async def test_registry_boots_passive_observers(tmp_path):
    async with SubsystemHarness() as h:
        cfg = EvaluationConfig.from_mapping(
            {
                "paths": {
                    "trajectory_dir": str(tmp_path / "traj"),
                    "evaluation_logs": str(tmp_path / "eval"),
                    "retention_days": 30,
                },
                "memory_probes": False,  # needs cognitive_client; skip
                "eidolon_accuracy": False,
            }
        )
        sidecar = SidecarRegistry(
            bus=h.bus,
            config=cfg,
            embedder=HashEmbedder(),
            bare_inference_client=FakeBareInferenceClient(),
        )
        await sidecar.start()
        assert sidecar.started is True
        await sidecar.stop()
        assert sidecar.started is False


@pytest.mark.asyncio
async def test_disabled_sidecar_skips_construction(tmp_path):
    async with SubsystemHarness() as h:
        cfg = EvaluationConfig.from_mapping({"enabled": False})
        sidecar = SidecarRegistry(bus=h.bus, config=cfg)
        await sidecar.start()
        assert sidecar.started is False
        assert sidecar.observers == []


def test_boundary_no_core_module_imports_evaluation():
    """Read-only check that no kaine module outside the allowed
    coupling points imports from kaine.evaluation.

    Belt-and-suspenders. The PRIMARY enforcement is now the structural
    import-linter contract "Core must not import the evaluation sidecar"
    (pyproject.toml [tool.importlinter]), run by pre-commit, a dedicated CI
    job, and tests/test_import_boundary_contracts.py — it catches
    ``import kaine.evaluation as ...`` and indirect imports too. This grep is
    kept so the guarantee survives even if the linter config is removed.
    See docs/architecture-boundaries.md.
    """
    proc = subprocess.run(
        ["git", "grep", "-l", "from kaine.evaluation", "--", "kaine/"],
        cwd=Path(__file__).parent.parent.parent,
        capture_output=True,
        text=True,
    )
    matches = [
        line for line in proc.stdout.strip().splitlines() if line
    ]
    allowed = {"kaine/cycle/__main__.py", "kaine/nexus/__main__.py"}
    unexpected = {
        m for m in matches
        if m not in allowed and not m.startswith("kaine/evaluation/")
    }
    assert unexpected == set(), f"sidecar boundary violated: {unexpected}"
