# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Regression tests for the divergence review fixes (adapter dir, corrupt
reports, and failed-preservation retry timing).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kaine.cycle.incident_log import IncidentLog
from kaine.cycle.preservation_monitor import DivergenceMonitor, DivergenceMonitorConfig
from kaine.experiment.run_context import RunContext, set_run_context
from kaine.lifecycle.divergence import adapter_dir_for, assess_divergence
from kaine.lifecycle.individuation_store import conditioning_digest
from kaine.modules.registry import ModuleRegistry
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor
from kaine.storage import resolve
from tests.test_decommission_divergence import (
    _write_ledger,
    _write_reference,
    _write_report,
    _write_self_model,
)
from tests.test_preservation_monitors import _StubFM


@pytest.fixture(autouse=True)
def _plaintext_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


@pytest.fixture(autouse=True)
def _run_context():
    set_run_context(
        RunContext(
            run_id="reviewrun01234567",
            seed=7,
            started_at=datetime.now(timezone.utc).isoformat(),
            git_sha=None,
        )
    )
    yield
    set_run_context(None)


def test_adapter_dir_for_defaults_and_custom():
    root = Path("/tmp/test-state-root")

    assert adapter_dir_for(None, root) == root / "hypnos" / "adapters"
    assert (
        adapter_dir_for(
            {"hypnos": {"voice_alignment": {"adapter_output_dir": "state/hypnos/adapters"}}},
            root,
        )
        == root / "hypnos" / "adapters"
    )

    custom = adapter_dir_for(
        {"hypnos": {"voice_alignment": {"adapter_output_dir": "custom/gen1"}}},
        root,
    )
    assert custom == resolve(Path("custom/gen1"))


def test_custom_adapter_dir_makes_measurement_stale(tmp_path):
    state_root = tmp_path / "state"
    ref = _write_reference(state_root)
    _write_self_model(state_root)

    empty_digest = conditioning_digest(adapter_sha=None, values=[], norms=[])
    _write_ledger(
        state_root,
        ref,
        individuated=False,
        looks_completed=1,
        last_look_conditions_digest=empty_digest,
    )

    now = datetime.now(timezone.utc)
    _write_report(
        state_root,
        outcome="scored",
        significant=False,
        p_value=0.9,
        effect_size_h=0.1,
        alpha_k=0.05,
        reference_id=ref.reference_id,
        reference_kind=ref.reference_kind,
        reference_captured_at=ref.captured_at,
        look_index=0,
        ts=(now - timedelta(days=1)).isoformat(),
    )

    custom = tmp_path / "custom"
    gen1 = custom / "gen1"
    (gen1 / "adapter.gguf").parent.mkdir(parents=True, exist_ok=True)
    (gen1 / "adapter.gguf").write_text("fake", encoding="utf-8")
    (custom / "current").symlink_to(gen1, target_is_directory=True)

    a = assess_divergence(state_root=state_root, adapter_output_dir=custom)
    assert a.signals["individuation_state"] == "stale"
    assert a.signals["hypnos_adapters_present"] is True
    assert a.diverged is True

    # Hazard documentation: without the custom dir, the old path reads the
    # measurement as current because it scans the wrong adapter directory.
    a_default = assess_divergence(state_root=state_root)
    assert a_default.signals["individuation_state"] == "not_individuated"
    assert a_default.signals["hypnos_adapters_present"] is False


def test_corrupt_report_line_counts_as_unreadable(tmp_path):
    state_root = tmp_path / "state"
    ref = _write_reference(state_root)
    _write_self_model(state_root)

    empty_digest = conditioning_digest(adapter_sha=None, values=[], norms=[])
    _write_ledger(
        state_root,
        ref,
        individuated=False,
        looks_completed=1,
        last_look_conditions_digest=empty_digest,
    )

    now = datetime.now(timezone.utc)
    _write_report(
        state_root,
        outcome="scored",
        significant=False,
        p_value=0.9,
        effect_size_h=0.1,
        alpha_k=0.05,
        reference_id=ref.reference_id,
        reference_kind=ref.reference_kind,
        reference_captured_at=ref.captured_at,
        look_index=0,
        ts=(now - timedelta(days=1)).isoformat(),
    )

    report_files = list((state_root / "individuation" / "reports").rglob("*.jsonl"))
    assert report_files
    with report_files[0].open("a", encoding="utf-8") as fh:
        fh.write("this is not a valid encrypted jsonl line\n")

    a = assess_divergence(state_root=state_root)
    assert a.diverged is True
    assert a.signals["individuation_state"] == "unreadable"


@pytest.mark.asyncio
async def test_monitor_poll_passes_adapter_output_dir(tmp_path, monkeypatch):

    recorded: dict = {}

    def fake_assess(*, state_root, **kwargs):
        recorded["kwargs"] = kwargs
        from kaine.lifecycle.divergence import DivergenceAssessment

        return DivergenceAssessment(diverged=False, signals={}, summary="")

    monkeypatch.setattr(
        "kaine.cycle.preservation_monitor.assess_divergence", fake_assess
    )

    monitor = DivergenceMonitor(
        registry=ModuleRegistry(),
        fork_manager=_StubFM(),
        config=DivergenceMonitorConfig(
            enabled=True,
            min_interval_s=0.0,
            boot_settle_s=0.0,
            state_root=str(tmp_path / "state"),
        ),
        bus=None,
        incident_log=IncidentLog(enabled=False, path="unused"),
        adapter_output_dir=Path("/x"),
    )

    await monitor._poll_once(asyncio.Event())
    assert recorded["kwargs"]["adapter_output_dir"] == Path("/x")
