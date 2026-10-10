# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for OpenSpec change live-monitor-configured-thresholds.

The live preservation monitor must pass the configured consolidation-divergence
thresholds to assess_divergence, so it agrees with the decommission CLI.
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
from kaine.lifecycle.divergence import (
    DEFAULT_CONSOLIDATION_MAGNITUDE_THRESHOLD,
    DEFAULT_CONSOLIDATION_RATE_THRESHOLD,
    consolidation_thresholds_from_config,
)
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
def _consolidation_record(tmp_path):
    """Write the cheap consolidation-divergence record used by the monitor."""
    hypnos_dir = tmp_path / "state" / "hypnos"
    hypnos_dir.mkdir(parents=True)
    with open(hypnos_dir / "consolidation_divergence.json", "w") as f:
        json.dump({"divergence_rate": 0.3, "divergence_magnitude": 0.1}, f)
    return tmp_path / "state"


def test_consolidation_thresholds_from_config_wiring():
    assert consolidation_thresholds_from_config(
        {"hypnos": {"voice_alignment": {"consolidation_divergence_rate_threshold": 0.2}}}
    ) == (0.2, DEFAULT_CONSOLIDATION_MAGNITUDE_THRESHOLD)


@pytest.mark.asyncio
async def test_live_monitor_honours_configured_consolidation_thresholds(
    tmp_path, _consolidation_record, _capture_assess_divergence
):
    state_root = _consolidation_record

    config = DivergenceMonitorConfig(
        enabled=True,
        poll_interval_s=60.0,
        state_root=str(state_root),
        boot_settle_s=0.0,
        min_interval_s=0.0,
    )

    # Lowered rate threshold: 0.2 < observed rate 0.3 → diverged.
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
        consolidation_rate_threshold=0.2,
        consolidation_magnitude_threshold=DEFAULT_CONSOLIDATION_MAGNITUDE_THRESHOLD,
    )
    await monitor_low._poll_once(asyncio.Event())
    assert _capture_assess_divergence["kwargs"]["consolidation_rate_threshold"] == 0.2
    assert (
        _capture_assess_divergence["kwargs"]["consolidation_magnitude_threshold"]
        == DEFAULT_CONSOLIDATION_MAGNITUDE_THRESHOLD
    )
    assert _capture_assess_divergence["result"].diverged is True

    # Default thresholds: rate 0.5 > observed rate 0.3 → not diverged by this signal.
    _capture_assess_divergence.clear()
    monitor_default = DivergenceMonitor(
        registry=ModuleRegistry(),
        fork_manager=_StubFM(),
        config=config,
        bus=_FakeBus(),
        incident_log=IncidentLog(
            enabled=True,
            path=tmp_path / "incidents_default",
            name="divergence",
        ),
        require_encryption=False,
    )
    await monitor_default._poll_once(asyncio.Event())
    assert (
        _capture_assess_divergence["kwargs"]["consolidation_rate_threshold"]
        == DEFAULT_CONSOLIDATION_RATE_THRESHOLD
    )
    assert (
        _capture_assess_divergence["kwargs"]["consolidation_magnitude_threshold"]
        == DEFAULT_CONSOLIDATION_MAGNITUDE_THRESHOLD
    )
    assert _capture_assess_divergence["result"].diverged is False
