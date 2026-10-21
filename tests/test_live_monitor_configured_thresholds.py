# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for OpenSpec change live-monitor-configured-thresholds.

The live preservation monitor must pass the configured voice-distinctiveness
threshold to assess_divergence, so it agrees with the decommission CLI.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from kaine.cycle import control_state
from kaine.cycle.incident_log import IncidentLog
from kaine.cycle.preservation_monitor import (
    DivergenceMonitor,
    DivergenceMonitorConfig,
)
from kaine.experiment.run_context import RunContext, set_run_context
from kaine.lifecycle.divergence import distinctiveness_threshold_from_config
from kaine.modules.registry import ModuleRegistry
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor


@pytest.fixture(autouse=True)
def _plaintext_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


@pytest.fixture(autouse=True)
def _run_context():
    set_run_context(
        RunContext(
            run_id="prtworun01234567",
            seed=7,
            started_at=datetime.now(timezone.utc).isoformat(),
            git_sha=None,
        )
    )
    yield
    set_run_context(None)


@pytest.fixture(autouse=True)
def _control_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(control_state, "CONTROL_PATH", tmp_path / "control.json")
    yield


class _StubFM:
    """ForkManager double recording preserve_live calls without touching disk."""

    def __init__(self):
        self.calls: list[dict] = []

    async def preserve_live(
        self,
        registry,
        *,
        reason,
        label,
        out_root,
        entity_name,
        require_encryption=False,
    ):
        self.calls.append(
            {
                "reason": reason,
                "label": label,
                "out_root": out_root,
                "entity_name": entity_name,
                "require_encryption": require_encryption,
            }
        )
        from kaine.lifecycle.preservation import PreservationResult

        return PreservationResult(
            ok=True,
            preservation_id=f"pid{len(self.calls)}",
            snapshot_id=f"snap{len(self.calls)}",
            reason=reason,
            label=label,
            run_id="thresholdrun0001",
            world_model_captured=False,
        )


class _FakeBus:
    async def publish(self, stream, payload):
        pass


@pytest.fixture
def _capture_assess_divergence(monkeypatch):
    """Wrap the monitor's assess_divergence to record kwargs and real result."""
    from kaine.cycle import preservation_monitor as pm

    real_assess = pm.assess_divergence
    captured: dict = {}

    def wrapper(*args, **kwargs):
        captured["kwargs"] = kwargs
        result = real_assess(*args, **kwargs)
        captured["result"] = result
        return result

    monkeypatch.setattr(pm, "assess_divergence", wrapper)
    return captured


@pytest.fixture
def _spoken_state(tmp_path):
    """Write a spoken intent and a readable distinctiveness measurement."""
    state_root = tmp_path / "state"
    language = state_root / "language"
    language.mkdir(parents=True, exist_ok=True)
    with open(language / "intent_expression.jsonl", "w") as f:
        f.write(json.dumps({"generated_text": "hello world"}) + "\n")
    with open(language / "voice_measures_latest.json", "w") as f:
        json.dump({"distinctiveness": 0.3}, f)
    return state_root


def test_distinctiveness_threshold_from_config_wiring():
    assert distinctiveness_threshold_from_config(
        {"sleep": {"voice_alignment": {"distinctiveness_threshold": 0.2}}}
    ) == 0.2
    assert distinctiveness_threshold_from_config(None) == 0.0
    assert distinctiveness_threshold_from_config({}) == 0.0


@pytest.mark.asyncio
async def test_live_monitor_honours_configured_distinctiveness_threshold(
    tmp_path, _spoken_state, _capture_assess_divergence
):
    state_root = _spoken_state

    config = DivergenceMonitorConfig(
        enabled=True,
        poll_interval_s=60.0,
        state_root=str(state_root),
        boot_settle_s=0.0,
        min_interval_s=0.0,
    )

    # Lowered distinctiveness threshold: 0.2 < observed 0.3 -> diverged.
    monitor_low = DivergenceMonitor(
        registry=ModuleRegistry(),
        fork_manager=_StubFM(),
        config=config,
        bus=_FakeBus(),
        incident_log=IncidentLog(
            enabled=True,
            path=tmp_path / "incidents_low",
            name="divergence",
        ),
        require_encryption=False,
        distinctiveness_threshold=0.2,
    )
    await monitor_low._poll_once(asyncio.Event())
    assert _capture_assess_divergence["kwargs"]["distinctiveness_threshold"] == 0.2
    assert _capture_assess_divergence["result"].diverged is True

    # Raised distinctiveness threshold: 0.5 > observed 0.3 -> not diverged.
    _capture_assess_divergence.clear()
    monitor_high = DivergenceMonitor(
        registry=ModuleRegistry(),
        fork_manager=_StubFM(),
        config=config,
        bus=_FakeBus(),
        incident_log=IncidentLog(
            enabled=True,
            path=tmp_path / "incidents_high",
            name="divergence",
        ),
        require_encryption=False,
        distinctiveness_threshold=0.5,
    )
    await monitor_high._poll_once(asyncio.Event())
    assert _capture_assess_divergence["kwargs"]["distinctiveness_threshold"] == 0.5
    assert _capture_assess_divergence["result"].diverged is False
