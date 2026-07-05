# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from kaine.evaluation.attribution import AttributionRecorder
from kaine.evaluation.config import EvaluationConfig, EvaluationPaths
from kaine.evaluation.nexus_tab import build_evaluation_router, _scrub


def _config(tmp_path, enabled=True) -> EvaluationConfig:
    return EvaluationConfig.from_mapping(
        {
            "enabled": enabled,
            "paths": {
                "trajectory_dir": str(tmp_path / "traj"),
                "evaluation_logs": str(tmp_path / "eval"),
                "retention_days": 30,
            },
        }
    )


def _app(config):
    app = FastAPI()
    app.include_router(build_evaluation_router(config, attribution=None))
    return app


@pytest.mark.asyncio
async def test_evaluation_route_returns_200_when_enabled(tmp_path):
    app = _app(_config(tmp_path))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/diagnostics/evaluation/")
    assert r.status_code == 200
    assert "evaluation" in r.text.lower()


@pytest.mark.asyncio
async def test_evaluation_route_404_when_disabled(tmp_path):
    app = _app(_config(tmp_path, enabled=False))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/diagnostics/evaluation/")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_summary_json_contains_sections(tmp_path):
    cfg = _config(tmp_path)
    # Pre-populate ab_divergence log so the summary is non-empty.
    ab_dir = Path(cfg.paths.evaluation_logs) / "ab_divergence"
    ab_dir.mkdir(parents=True, exist_ok=True)
    (ab_dir / "ab_divergence-2026-05-20.jsonl").write_text(
        json.dumps({"divergence": 0.4, "cosine_similarity": 0.6, "ts": "2026-05-20T01:00:00Z"}) + "\n"
    )
    app = _app(cfg)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/diagnostics/evaluation/summary.json")
    data = r.json()
    assert "ab_divergence" in data
    assert data["ab_divergence"]["n"] >= 1
    assert "attribution_total" in data
    assert "affect_correlation" in data


def test_scrub_drops_content_fields():
    out = _scrub(
        {
            "ts": "2026-05-20T01:00",
            "text": "secret",
            "user_text": "also secret",
            "divergence": 0.3,
            "nested": {"body": "leak", "metric": 9},
        }
    )
    assert "text" not in out
    assert "user_text" not in out
    assert "body" not in out["nested"]
    assert out["divergence"] == 0.3
    assert out["nested"]["metric"] == 9


@pytest.mark.asyncio
async def test_attribution_passthrough_to_summary(tmp_path):
    bus_stub = type("B", (), {"read": lambda self, *a, **kw: [], "current_workspace_id": lambda self: "0"})()

    class _AttrStub:
        @property
        def running_total(self):
            return {"soma": 7, "thymos": 3}

        @property
        def current_hour_counts(self):
            return {"soma": 1}

    app = FastAPI()
    app.include_router(
        build_evaluation_router(_config(tmp_path), attribution=_AttrStub())
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/diagnostics/evaluation/summary.json")
    data = r.json()
    assert data["attribution_total"]["soma"] == 7
    assert data["attribution_hour"]["soma"] == 1
