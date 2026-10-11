# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kaine.experiment.planned_test_settings import (
    PROCESSORS,
    PlannedTestSettingsError,
    load_settings_record,
    planned_test_refusal,
    write_settings_record,
)
from kaine.experiment.principal_component import (
    PrincipalComponent,
    write_principal_component,
)


def _build_record(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    principal_components = {}
    for processor in PROCESSORS:
        path = tmp_path / f"pc_{processor}.json"
        pc = PrincipalComponent(
            processor=processor,
            run_id="prelim",
            n_inputs=3,
            dim=3,
            mean=(0.0, 0.0, 0.0),
            direction=(1.0, 0.0, 0.0),
            variance=1.0,
            total_variance=1.0,
        )
        sha = write_principal_component(pc, path)
        principal_components[processor] = {"path": str(path), "sha256": sha}

    record = {
        "schema": "kaine.planned_test_settings",
        "schema_version": 1,
        "complete": True,
        "blocked": {},
        "inputs": {
            "preliminary": {"run_id": "prelim", "seed": 1},
            "pilots": [{"seed": 2}, {"seed": 3}],
        },
        "values": {
            "t_learn_s": 120,
            "theta_eff": {"matched": 0.02, "pooled": 0.03},
            "min_effect": 0.01,
            "min_reports": 500,
            "snr": {processor: 4.0 for processor in PROCESSORS},
            "principal_components": principal_components,
        },
    }
    path = tmp_path / "settings.json"
    return record, path


def test_load_returns_values_and_excluded_seeds(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    write_settings_record(record, path)
    loaded = load_settings_record(path)
    assert loaded.t_learn_s == 120.0
    assert dict(loaded.theta_eff) == {"matched": 0.02, "pooled": 0.03}
    assert loaded.min_effect == 0.01
    assert loaded.min_reports == 500
    assert dict(loaded.snr) == {processor: 4.0 for processor in PROCESSORS}
    assert loaded.excluded_seeds == frozenset({1, 2, 3})


def test_changed_value_fails_digest_check(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    write_settings_record(record, path)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    loaded["values"]["t_learn_s"] = 999
    path.write_text(json.dumps(loaded, indent=2, sort_keys=True), encoding="utf-8")
    with pytest.raises(PlannedTestSettingsError, match="edited"):
        load_settings_record(path)


def test_incomplete_record_fails_and_names_blocked_key(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    record["complete"] = False
    record["blocked"] = {"t_learn_s": "x"}
    write_settings_record(record, path)
    with pytest.raises(PlannedTestSettingsError, match="t_learn_s"):
        load_settings_record(path)


def test_changed_principal_component_file_fails(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    write_settings_record(record, path)
    pc_path = Path(record["values"]["principal_components"]["topos"]["path"])
    pc_path.write_text(pc_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(PlannedTestSettingsError, match="sha256"):
        load_settings_record(path)


def test_min_reports_zero_fails(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    record["values"]["min_reports"] = 0
    write_settings_record(record, path)
    with pytest.raises(PlannedTestSettingsError, match="min_reports"):
        load_settings_record(path)


def test_missing_processor_in_snr_fails(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    record["values"]["snr"] = {"topos": 4.0, "audition": 4.0}
    write_settings_record(record, path)
    with pytest.raises(PlannedTestSettingsError, match="snr"):
        load_settings_record(path)


def test_missing_principal_component_file_fails(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    record["values"]["principal_components"]["topos"]["path"] = str(tmp_path / "missing.json")
    write_settings_record(record, path)
    with pytest.raises(PlannedTestSettingsError, match="missing"):
        load_settings_record(path)


def test_refusal_allows_non_workspace_studies() -> None:
    assert planned_test_refusal(None, {}, 0) is None
    assert planned_test_refusal("module_ignition", {}, 0) is None


def test_refusal_demands_planned_test_role() -> None:
    reason = planned_test_refusal(
        "workspace_mediation_competitive",
        {},
        0,
    )
    assert reason is not None
    assert "[planned_test]" in reason


def test_refusal_allows_preliminary_and_pilot_roles(tmp_path: Path) -> None:
    assert planned_test_refusal("workspace_mediation_preliminary", {"planned_test": {"role": "preliminary"}}, 0) is None
    assert planned_test_refusal("workspace_mediation_pilot_competitive", {"planned_test": {"role": "pilot"}}, 0) is None


def test_refusal_demands_settings_record_for_test_role() -> None:
    reason = planned_test_refusal(
        "workspace_mediation_test",
        {"planned_test": {"role": "test"}},
        0,
    )
    assert reason is not None
    assert "calibrate" in reason


def test_refusal_rejects_missing_settings_record_for_test_role(tmp_path: Path) -> None:
    reason = planned_test_refusal(
        "workspace_mediation_test",
        {"planned_test": {"role": "test", "settings_record": "missing.json"}},
        0,
    )
    assert reason is not None
    assert "settings record" in reason


def test_refusal_accepts_valid_record_and_unused_seed(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    write_settings_record(record, path)
    reason = planned_test_refusal(
        "workspace_mediation_test",
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is None


def test_refusal_rejects_reused_seed(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    write_settings_record(record, path)
    reason = planned_test_refusal(
        "workspace_mediation_test",
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        2,
    )
    assert reason is not None
    assert "seed 2" in reason


def test_refusal_checks_positive_control_mode(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    write_settings_record(record, path)
    config = {
        "planned_test": {"role": "positive_control", "settings_record": str(path)},
        "positive_control": {"enabled": True, "mode": "ladder", "settings_record": str(path)},
    }
    reason = planned_test_refusal("workspace_mediation_positive_control", config, 99)
    assert reason is not None
    assert "control mode" in reason

    config["positive_control"]["mode"] = "control"
    assert planned_test_refusal("workspace_mediation_positive_control", config, 99) is None


def test_load_settings_record_with_relative_pc_paths(monkeypatch, tmp_path):
    """Relative principal-component paths are resolved against the data root."""
    from pathlib import Path

    from kaine.experiment.calibrate import PROCESSORS
    from kaine.experiment.planned_test_settings import (
        load_settings_record,
        write_settings_record,
    )

    record, path = _build_record(tmp_path)
    for processor in PROCESSORS:
        record["values"]["principal_components"][processor]["path"] = f"pc_{processor}.json"

    monkeypatch.setattr(
        "kaine.experiment.planned_test_settings.resolve",
        lambda p: tmp_path / p if not Path(p).is_absolute() else Path(p),
    )

    write_settings_record(record, path)
    loaded = load_settings_record(path)
    for processor in PROCESSORS:
        assert loaded.principal_components[processor].path == f"pc_{processor}.json"
