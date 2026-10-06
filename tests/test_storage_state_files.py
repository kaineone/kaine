# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

import kaine.lifecycle.stage as stage_module
from kaine.cycle.control_state import CONTROL_PATH, CycleControl, read_control, write_control
from kaine.cycle.escalation_state import (
    ESCALATION_PATH,
    EscalationRecord,
    read_escalation,
    write_escalation,
)
from kaine.cycle.preserve_watch import REQUEST_PATH as PRESERVE_REQUEST_PATH
from kaine.cycle.preserve_watch import new_request, read_request, write_request
from kaine.lifecycle.birth_ack import (
    BIRTH_ACK_PATH,
    BIRTH_REQUEST_PATH,
    BirthAck,
    read_ack,
    write_ack,
)
from kaine.lifecycle.birth_ack import new_request as new_birth_request
from kaine.lifecycle.birth_ack import (
    read_request as read_birth_request,
)
from kaine.lifecycle.birth_ack import (
    write_request as write_birth_request,
)
from kaine.modules.hypnos.voice_alignment import (
    CONSOLIDATION_DIVERGENCE_STATE,
    ConsolidationDivergence,
    read_consolidation_divergence,
    write_consolidation_divergence,
)
from kaine.organ_window_state import ORGAN_WINDOW_STATE, read_window_state, write_window_state
from kaine.perception_state import DESIRED_PATH as PERCEPTION_DESIRED_PATH
from kaine.perception_state import RUNTIME_PATH as PERCEPTION_RUNTIME_PATH
from kaine.perception_state import (
    PerceptionState,
    read_desired,
    read_runtime,
    write_desired_audio,
    write_runtime,
)
from kaine.storage import set_data_root


@pytest.fixture(autouse=True)
def _isolate_storage_root(tmp_path, monkeypatch):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    yield
    set_data_root(None)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_state_files_round_trip_under_data_root(tmp_path, monkeypatch):
    root = tmp_path / "root"
    set_data_root(root)
    cwd = tmp_path / "cwd"

    # cycle control
    control = CycleControl(frozen=True, frozen_at=_now_iso(), reason="data-root test")
    write_control(control)
    assert (root / CONTROL_PATH).is_file()
    assert not (cwd / CONTROL_PATH).exists()
    loaded_control = read_control()
    assert loaded_control.frozen is True
    assert loaded_control.reason == "data-root test"

    # escalation
    escalation = EscalationRecord(escalated=True, module="topos", attempts=5, message="data-root test")
    write_escalation(escalation)
    assert (root / ESCALATION_PATH).is_file()
    assert not (cwd / ESCALATION_PATH).exists()
    assert read_escalation() == escalation

    # preserve watch request
    preserve_req = new_request("test", False)
    write_request(preserve_req)
    assert (root / PRESERVE_REQUEST_PATH).is_file()
    assert read_request() == preserve_req

    # lifecycle stage: restore the relative default the conftest fixture
    # replaces, so its resolution under the data root is what is tested.
    monkeypatch.setattr(stage_module, "STAGE_PATH", stage_module.DEFAULT_STAGE_PATH)
    stage = stage_module.StageState(stage=stage_module.EMBODIED)
    stage_module.write_stage(stage)
    assert (root / stage_module.STAGE_PATH).is_file()
    assert not (cwd / stage_module.STAGE_PATH).exists()
    assert stage_module.read_stage() == stage

    # birth request / ack
    birth_req = new_birth_request(_now_iso())
    write_birth_request(birth_req)
    assert (root / BIRTH_REQUEST_PATH).is_file()
    assert not (cwd / BIRTH_REQUEST_PATH).exists()
    assert read_birth_request() == birth_req

    birth_ack = BirthAck(
        request_id=birth_req.request_id,
        acknowledged_at=_now_iso(),
    )
    write_ack(birth_ack)
    assert (root / BIRTH_ACK_PATH).is_file()
    assert read_ack() == birth_ack

    # organ window state
    write_window_state("ready")
    assert (root / ORGAN_WINDOW_STATE).is_file()
    assert not (cwd / ORGAN_WINDOW_STATE).exists()
    window = read_window_state()
    assert isinstance(window, dict)
    assert window["phase"] == "ready"

    # hypnos consolidation divergence
    metric = ConsolidationDivergence(records_scanned=4, usable_pairs=1, divergence_rate=0.25)
    write_consolidation_divergence(metric, sleep_index=3)
    assert (root / CONSOLIDATION_DIVERGENCE_STATE).is_file()
    assert not (cwd / CONSOLIDATION_DIVERGENCE_STATE).exists()
    divergence = read_consolidation_divergence()
    assert isinstance(divergence, dict)
    assert divergence["sleep_index"] == 3

    # perception runtime
    runtime = PerceptionState(audio_live_active=True, audio_last_started_at=_now_iso())
    write_runtime(runtime)
    assert (root / PERCEPTION_RUNTIME_PATH).is_file()
    assert not (cwd / PERCEPTION_RUNTIME_PATH).exists()
    assert read_runtime() == runtime

    # perception desired (audio toggle)
    written_desired = write_desired_audio(True)
    assert (root / PERCEPTION_DESIRED_PATH).is_file()
    assert not (cwd / PERCEPTION_DESIRED_PATH).exists()
    assert read_desired() == written_desired


@pytest.mark.no_data_root
def test_no_data_root_writes_under_cwd(tmp_path):
    # The autouse fixture has already chdir'd to tmp_path/cwd and reset root.
    control = CycleControl()
    write_control(control)
    expected = tmp_path / "cwd" / "state" / "cycle" / "control.json"
    assert expected.is_file()


def test_absolute_path_ignores_data_root(tmp_path):
    root = tmp_path / "root"
    set_data_root(root)
    custom = tmp_path / "custom" / "control.json"

    control = CycleControl()
    write_control(control, path=custom)
    assert custom.is_file()
    assert not (root / CONTROL_PATH).exists()
    assert read_control(path=custom) == control


def test_health_prober_paths_derived_from_defaults(tmp_path: Path) -> None:
    """Built HealthProber path fields are derived from its own dataclass defaults."""
    import dataclasses

    from kaine.nexus.health.config import load_health_prober
    from kaine.nexus.health.prober import HealthProber

    set_data_root(tmp_path / "root")
    toml = tmp_path / "kaine.toml"
    toml.write_text("[modules]\n")
    prober = load_health_prober(kaine_toml=toml)

    for field in dataclasses.fields(HealthProber):
        if field.name in {"evaluation_logs_path", "preservation_incident_path"}:
            continue
        if isinstance(field.default, Path):
            expected = tmp_path / "root" / field.default
            assert getattr(prober, field.name) == expected, field.name
