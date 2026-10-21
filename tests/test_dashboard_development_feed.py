# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the dashboard developmental feed and maturation hearing stage."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from kaine.dashboard.health.blocks import module_states, perception_feed_block
from kaine.dashboard.health.prober import HealthProber
from kaine.dashboard.maturation import (
    build_maturation_router,
    maturation_snapshot,
    read_development,
    read_hearing_stage,
)
from kaine.perception_state import PerceptionState


def _write_runtime(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_read_hearing_stage_valid_round_trip(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime.json"
    _write_runtime(runtime, {
        "hearing_stage": {
            "stage": 2,
            "previous_stage": 1,
            "low_hz": 100.5,
            "high_hz": 500.0,
            "awake_seconds": 120.0,
            "text": "extra",
        }
    })
    assert read_hearing_stage(runtime_path=runtime) == {
        "stage": 2,
        "previous_stage": 1,
        "low_hz": 100.5,
        "high_hz": 500.0,
        "awake_seconds": 120.0,
    }


def test_read_hearing_stage_invalid_stage_returns_none(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime.json"
    for stage in (5, True, "1"):
        _write_runtime(runtime, {"hearing_stage": {"stage": stage}})
        assert read_hearing_stage(runtime_path=runtime) is None


def test_read_hearing_stage_bad_number_becomes_none(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime.json"
    _write_runtime(runtime, {
        "hearing_stage": {
            "stage": 1,
            "previous_stage": 0,
            "low_hz": float("nan"),
            "high_hz": 100.0,
            "awake_seconds": 10.0,
        }
    })
    result = read_hearing_stage(runtime_path=runtime)
    assert result is not None
    assert result["low_hz"] is None
    assert result["high_hz"] == 100.0
    assert result["awake_seconds"] == 10.0

    _write_runtime(runtime, {
        "hearing_stage": {
            "stage": 1,
            "low_hz": "bad",
            "high_hz": 2.0,
            "awake_seconds": 3.0,
        }
    })
    result = read_hearing_stage(runtime_path=runtime)
    assert result["low_hz"] is None
    assert result["high_hz"] == 2.0
    assert result["awake_seconds"] == 3.0


def test_read_hearing_stage_missing_or_bad_returns_none(tmp_path: Path) -> None:
    assert read_hearing_stage(runtime_path=tmp_path / "missing.json") is None

    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert read_hearing_stage(runtime_path=bad) is None

    no_key = tmp_path / "no_key.json"
    _write_runtime(no_key, {"developmental_stage": {}})
    assert read_hearing_stage(runtime_path=no_key) is None


def test_read_development_keeps_world_conditions_drops_unknown(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime.json"
    _write_runtime(runtime, {
        "developmental_stage": {
            "stage": 3,
            "world": "perceptual",
            "conditions": {
                "c2_sleep_required": False,
                "c2_consolidation_required": False,
            },
            "extra": "drop",
        }
    })
    result = read_development(runtime_path=runtime)
    assert result["world"] == "perceptual"
    assert result["conditions"] == {
        "c2_sleep_required": False,
        "c2_consolidation_required": False,
    }
    assert "extra" not in result


def test_maturation_snapshot_includes_hearing_and_development(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    ack_path = tmp_path / "ack.json"
    runtime_path = tmp_path / "runtime.json"
    _write_runtime(runtime_path, {
        "hearing_stage": {
            "stage": 1,
            "previous_stage": 0,
            "low_hz": 158.1,
            "high_hz": 707.1,
            "awake_seconds": 60.0,
        },
        "developmental_stage": {
            "stage": 1,
            "world": "perceptual",
            "conditions": {
                "c2_sleep_required": False,
                "c2_consolidation_required": False,
            },
        },
    })
    snapshot = maturation_snapshot(
        request_path=request_path,
        ack_path=ack_path,
        runtime_path=runtime_path,
    )
    assert snapshot["hearing"]["stage"] == 1
    assert snapshot["hearing"]["low_hz"] == 158.1
    assert snapshot["development"]["world"] == "perceptual"
    assert snapshot["pending"] is False


def test_maturation_snapshot_hearing_none_without_key(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    ack_path = tmp_path / "ack.json"
    runtime_path = tmp_path / "runtime.json"
    _write_runtime(runtime_path, {"developmental_stage": {"stage": 0}})
    snapshot = maturation_snapshot(
        request_path=request_path,
        ack_path=ack_path,
        runtime_path=runtime_path,
    )
    assert "hearing" in snapshot
    assert snapshot["hearing"] is None


@pytest.mark.asyncio
async def test_maturation_router_returns_hearing_and_conditions(tmp_path: Path) -> None:
    runtime_path = tmp_path / "runtime.json"
    request_path = tmp_path / "request.json"
    ack_path = tmp_path / "ack.json"
    _write_runtime(runtime_path, {
        "hearing_stage": {
            "stage": 2,
            "low_hz": 50.0,
            "high_hz": 200.0,
            "awake_seconds": 30.0,
        },
        "developmental_stage": {
            "stage": 2,
            "world": "embodied",
            "conditions": {
                "c2_sleep_required": True,
                "c2_consolidation_required": True,
            },
        },
    })
    router = build_maturation_router(
        request_path=request_path,
        ack_path=ack_path,
        runtime_path=runtime_path,
    )
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/diagnostics/maturation.json")
    assert response.status_code == 200
    data = response.json()
    assert data["hearing"]["stage"] == 2
    assert data["development"]["world"] == "embodied"
    assert data["development"]["conditions"]["c2_consolidation_required"] is True


def test_perception_feed_block_stimulus_source_defaults() -> None:
    block = perception_feed_block(
        perception_feed_cfg={"mode": "stimulus_source"},
        vision_capture_geometry=(640, 480),
        audition_capture_geometry=(16000, 1),
    )
    assert block["mode"] == "stimulus_source"
    summary = block["stimulus_source"]
    assert summary["heartbeat_bpm"] == 70.0
    assert summary["heartbeat_drift"] == 0.03
    assert summary["colour_ramp_seconds"] == 3600.0
    assert summary["colour_hue_gain"] == 0.6
    assert summary["maternal_voice_enabled"] is True
    assert summary["hearing_enabled"] is True
    assert summary["hearing_maturation_seconds"] == 43200.0
    for value in summary.values():
        assert isinstance(value, (bool, int, float)) or value is None


def test_perception_feed_block_voice_disabled() -> None:
    block = perception_feed_block(
        perception_feed_cfg={
            "mode": "stimulus_source",
            "stimulus_source": {"voice": {"enabled": False}},
        },
        vision_capture_geometry=(640, 480),
        audition_capture_geometry=(16000, 1),
    )
    assert block["stimulus_source"]["maternal_voice_enabled"] is False


def test_perception_feed_block_invalid_hearing_table() -> None:
    block = perception_feed_block(
        perception_feed_cfg={
            "mode": "stimulus_source",
            "stimulus_source": {"hearing": {"unknown_key": 1}},
        },
        vision_capture_geometry=(640, 480),
        audition_capture_geometry=(16000, 1),
    )
    summary = block["stimulus_source"]
    assert summary["hearing_enabled"] is None
    assert summary["hearing_maturation_seconds"] is None
    assert summary["heartbeat_bpm"] == 70.0
    assert summary["maternal_voice_enabled"] is True


def test_perception_feed_block_seeded_no_stimulus_source() -> None:
    block = perception_feed_block(
        perception_feed_cfg={"mode": "seeded", "seed": 1},
        vision_capture_geometry=(640, 480),
        audition_capture_geometry=(16000, 1),
    )
    assert block["mode"] == "seeded"
    assert "stimulus_source" not in block


def _stub_perception_state(monkeypatch, **kwargs) -> None:
    monkeypatch.setattr(
        "kaine.dashboard.health.blocks.read_perception_runtime",
        lambda: PerceptionState(**kwargs),
    )


def test_module_states_stimulus_source_marks_perception_capturing(
    monkeypatch, tmp_path: Path
) -> None:
    runtime = tmp_path / "runtime.json"
    _write_runtime(runtime, {"modules": ["vision", "audition"]})
    _stub_perception_state(monkeypatch)
    rows = module_states(
        runtime,
        {"vision": True, "audition": True, "affect": True},
        feed_mode="stimulus_source",
    )
    by_name = {row["name"]: row for row in rows}
    assert by_name["vision"]["capturing"] is True
    assert by_name["vision"]["feed"] == "stimulus_source"
    assert by_name["audition"]["capturing"] is True
    assert by_name["audition"]["feed"] == "stimulus_source"
    assert "feed" not in by_name["affect"]


def test_module_states_off_leaves_perception_not_capturing(
    monkeypatch, tmp_path: Path
) -> None:
    runtime = tmp_path / "runtime.json"
    _write_runtime(runtime, {"modules": ["vision", "audition"]})
    _stub_perception_state(monkeypatch)
    rows = module_states(
        runtime,
        {"vision": True, "audition": True},
        feed_mode="off",
    )
    for name in ("vision", "audition"):
        row = next(r for r in rows if r["name"] == name)
        assert row["capturing"] is False
        assert row["feed"] is None


def test_module_states_live_video_active_marks_vision_live(
    monkeypatch, tmp_path: Path
) -> None:
    runtime = tmp_path / "runtime.json"
    _write_runtime(runtime, {"modules": ["vision", "audition"]})
    _stub_perception_state(monkeypatch, video_live_active=True)
    rows = module_states(
        runtime,
        {"vision": True, "audition": True},
        feed_mode="live",
    )
    vision = next(r for r in rows if r["name"] == "vision")
    audition = next(r for r in rows if r["name"] == "audition")
    assert vision["capturing"] is True
    assert vision["feed"] == "live"
    assert audition["capturing"] is False
    assert audition["feed"] is None


def test_module_states_absent_module_not_capturing_seeded(
    monkeypatch, tmp_path: Path
) -> None:
    runtime = tmp_path / "runtime.json"
    _write_runtime(runtime, {"modules": ["vision"]})
    _stub_perception_state(monkeypatch)
    rows = module_states(
        runtime,
        {"vision": True, "audition": True},
        feed_mode="seeded",
    )
    audition = next(r for r in rows if r["name"] == "audition")
    assert audition["capturing"] is False
    assert audition["feed"] is None


def test_module_states_no_runtime_not_capturing_seeded(
    monkeypatch, tmp_path: Path
) -> None:
    runtime = tmp_path / "runtime.json"
    _stub_perception_state(monkeypatch)
    rows = module_states(
        runtime,
        {"vision": True},
        feed_mode="seeded",
    )
    vision = next(r for r in rows if r["name"] == "vision")
    assert vision["capturing"] is False
    assert vision["feed"] is None


def test_health_prober_passes_feed_mode(monkeypatch, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime.json"
    _write_runtime(runtime, {"modules": ["vision"]})
    _stub_perception_state(monkeypatch)
    prober = HealthProber(
        modules_enabled={"vision": True},
        dependencies=[],
        perception_feed_cfg={"mode": "Seeded"},
        cycle_runtime_path=runtime,
    )
    rows = prober._module_states()
    vision = next(r for r in rows if r["name"] == "vision")
    assert vision["feed"] == "seeded"
