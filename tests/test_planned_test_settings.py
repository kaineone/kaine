# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kaine.experiment import calibration_rules as rules
from kaine.experiment.planned_test_settings import (
    PROCESSORS,
    RECORD_ROLES,
    STUDY_ROLES,
    PlannedTestSettingsError,
    load_settings_record,
    planned_test_gate,
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
        "constants": {
            "n_cal": rules.N_CAL,
            "c_eff": rules.C_EFF,
            "q_pow": float(rules.Q_POW),
            "target_power": float(rules.TARGET_POWER),
            "alpha_test": float(rules.ALPHA_TEST),
            "mser_batch": rules.MSER_BATCH,
            "mser_min_batches": rules.MSER_MIN_BATCHES,
            "n_bins": rules.N_BINS,
            "snr_ladder": list(rules.SNR_LADDER),
            "mser_ignore_end": rules.MSER_IGNORE_END,
        },
        "values": {
            "t_learn_s": 120,
            "theta_eff": {"matched": 0.02, "pooled": 0.03},
            "min_effect": 0.01,
            "min_reports": 500,
            "n_counted": rules.N_CAL,
            "n_exact": rules.N_EXACT,
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


def test_wrong_mser_ignore_end_is_refused(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    record["constants"]["mser_ignore_end"] = 4
    write_settings_record(record, path)
    reason, digest = planned_test_gate(
        "workspace_mediation_competitive",
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "mser_ignore_end" in reason
    assert digest is None


def test_wrong_mser_min_batches_is_refused(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    record["constants"]["mser_min_batches"] = 9
    write_settings_record(record, path)
    reason, digest = planned_test_gate(
        "workspace_mediation_competitive",
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "mser_min_batches" in reason
    assert digest is None


def test_refusal_checks_n_cal(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    record["constants"]["n_cal"] = 4
    write_settings_record(record, path)
    reason, _ = planned_test_gate(
        "workspace_mediation_competitive",
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "n_cal" in reason


def test_refusal_checks_c_eff(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    record["constants"]["c_eff"] = 0.4
    write_settings_record(record, path)
    reason, _ = planned_test_gate(
        "workspace_mediation_competitive",
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "c_eff" in reason


def test_refusal_checks_mser_batch(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    record["constants"]["mser_batch"] = 4
    write_settings_record(record, path)
    reason, _ = planned_test_gate(
        "workspace_mediation_competitive",
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "mser_batch" in reason


def test_refusal_checks_snr_ladder(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    record["constants"]["snr_ladder"] = [1.0, 2.0]
    write_settings_record(record, path)
    reason, _ = planned_test_gate(
        "workspace_mediation_competitive",
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "snr_ladder" in reason


def test_refusal_checks_n_counted(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    record["values"]["n_counted"] = 29
    write_settings_record(record, path)
    reason, _ = planned_test_gate(
        "workspace_mediation_competitive",
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "n_counted" in reason


def test_refusal_checks_n_exact(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    record["values"]["n_exact"] = 101
    write_settings_record(record, path)
    reason, _ = planned_test_gate(
        "workspace_mediation_competitive",
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "n_exact" in reason


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
        "workspace_mediation_competitive",
        {"planned_test": {"role": "test"}},
        0,
    )
    assert reason is not None
    assert "calibrate" in reason


def test_refusal_rejects_missing_settings_record_for_test_role(tmp_path: Path) -> None:
    reason = planned_test_refusal(
        "workspace_mediation_competitive",
        {"planned_test": {"role": "test", "settings_record": "missing.json"}},
        0,
    )
    assert reason is not None
    assert "settings record" in reason


def test_refusal_accepts_valid_record_and_unused_seed(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    write_settings_record(record, path)
    reason = planned_test_refusal(
        "workspace_mediation_competitive",
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is None


def test_refusal_rejects_reused_seed(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    write_settings_record(record, path)
    reason = planned_test_refusal(
        "workspace_mediation_competitive",
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


def test_gate_test_role_without_study_or_record_is_refused() -> None:
    reason, digest = planned_test_gate(None, {"planned_test": {"role": "test"}}, 0)
    assert reason is not None
    assert digest is None


def test_gate_test_role_with_renamed_study_without_record_is_refused() -> None:
    reason, digest = planned_test_gate(
        "my_renamed_study",
        {"planned_test": {"role": "test"}},
        0,
    )
    assert reason is not None
    assert digest is None


def test_gate_test_role_with_record_and_no_study_passes(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    write_settings_record(record, path)
    reason, digest = planned_test_gate(
        None,
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is None
    loaded = load_settings_record(path)
    assert digest == loaded.record_sha256


def test_gate_rejects_workspace_study_with_wrong_role() -> None:
    reason, _ = planned_test_gate(
        "workspace_mediation_competitive",
        {"planned_test": {"role": "pilot"}},
        0,
    )
    assert reason is not None
    assert "role = 'test'" in reason

    reason, _ = planned_test_gate(
        "workspace_mediation_pilot_matched",
        {"planned_test": {"role": "test"}},
        0,
    )
    assert reason is not None
    assert "role = 'pilot'" in reason

    reason, _ = planned_test_gate(
        "workspace_mediation_preliminary",
        {"planned_test": {"role": "pilot"}},
        0,
    )
    assert reason is not None
    assert "role = 'preliminary'" in reason


def test_gate_rejects_unknown_workspace_study() -> None:
    reason, _ = planned_test_gate(
        "workspace_mediation_other",
        {"planned_test": {"role": "test"}},
        0,
    )
    assert reason is not None
    assert "unknown workspace-mediation study" in reason


@pytest.mark.parametrize("study, expected_role", list(STUDY_ROLES.items()))
def test_gate_accepts_correct_study_role_pairs(tmp_path: Path, study: str, expected_role: str) -> None:
    config: dict[str, Any] = {"planned_test": {"role": expected_role}}
    path: Path | None = None
    if expected_role in RECORD_ROLES:
        record, path = _build_record(tmp_path)
        write_settings_record(record, path)
        config["planned_test"]["settings_record"] = str(path)

    if expected_role == "positive_control":
        config["positive_control"] = {
            "enabled": True,
            "mode": "control",
            "settings_record": str(path),
        }
    elif expected_role == "test":
        config["positive_control"] = {"enabled": False}

    reason, digest = planned_test_gate(study, config, 99)
    assert reason is None
    if expected_role in RECORD_ROLES:
        assert path is not None
        loaded = load_settings_record(path)
        assert digest == loaded.record_sha256
    else:
        assert digest is None


def test_gate_test_role_refuses_non_control_positive_control_modes(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    write_settings_record(record, path)
    base_config = {"planned_test": {"role": "test", "settings_record": str(path)}}

    for mode in ("ladder", "estimate_pc"):
        config = {
            **base_config,
            "positive_control": {"enabled": True, "mode": mode},
        }
        reason, _ = planned_test_gate("workspace_mediation_competitive", config, 99)
        assert reason is not None
        assert mode in reason

    config = {**base_config, "positive_control": {"enabled": False}}
    assert planned_test_gate("workspace_mediation_competitive", config, 99)[0] is None

    config = {**base_config, "positive_control": {"enabled": True, "mode": "control"}}
    assert planned_test_gate("workspace_mediation_competitive", config, 99)[0] is None


def test_gate_returns_none_when_no_study_or_planned_test() -> None:
    assert planned_test_gate(None, {}, 0) == (None, None)


def test_load_settings_record_with_relative_pc_paths(monkeypatch, tmp_path):
    """Relative principal-component paths are resolved against the data root."""
    from pathlib import Path

    from kaine.experiment.calibrate import PROCESSORS as CAL_PROCESSORS
    from kaine.experiment.planned_test_settings import (
        load_settings_record,
        write_settings_record,
    )

    record, path = _build_record(tmp_path)
    for processor in CAL_PROCESSORS:
        record["values"]["principal_components"][processor]["path"] = f"pc_{processor}.json"

    monkeypatch.setattr(
        "kaine.experiment.planned_test_settings.resolve",
        lambda p: tmp_path / p if not Path(p).is_absolute() else Path(p),
    )

    write_settings_record(record, path)
    loaded = load_settings_record(path)
    for processor in CAL_PROCESSORS:
        assert loaded.principal_components[processor].path == f"pc_{processor}.json"
