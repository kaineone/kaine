# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from kaine.experiment import calibration_rules as rules
from kaine.experiment.planned_test_settings import (
    PROCESSORS,
    RECORD_ROLES,
    STUDY_ROLES,
    TONE_STUDIES,
    PlannedTestSettingsError,
    load_settings_record,
    planned_test_gate,
    planned_test_refusal,
    records_digest,
    verify_run_data,
    write_settings_record,
)
from kaine.experiment.principal_component import (
    PrincipalComponent,
    file_sha256,
    write_principal_component,
)
from kaine.experiment.run_records import load_records_for_runs


def _build_record(
    tmp_path: Path,
    n_pilots: int | None = None,
    not_exercised: int = 0,
) -> tuple[dict[str, Any], Path]:
    if n_pilots is None:
        n_pilots = rules.N_CAL + not_exercised
    n_counted = n_pilots - not_exercised

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

    pilots = []
    seed = 2
    for i in range(n_pilots):
        runs: dict[str, Any] = {}
        for arm in ("competitive", "matched", "pooled", "tone"):
            runs[arm] = {
                "run_id": f"run_{i}_{arm}",
                "manifest_sha256": "a" * 64,
                "records_sha256": "b" * 64,
            }
        entry: dict[str, Any] = {
            "seed": seed,
            "counted": i < n_counted,
            "runs": runs,
        }
        if not entry["counted"]:
            entry["not_exercised_reason"] = "excluded by design"
        pilots.append(entry)
        seed += 1

    record = {
        "schema": "kaine.planned_test_settings",
        "schema_version": 1,
        "complete": True,
        "blocked": {},
        "inputs": {
            "preliminary": {
                "run_id": "prelim",
                "seed": 1,
                "manifest_sha256": "0" * 64,
                "records_sha256": "1" * 64,
            },
            "pilots": pilots,
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
            "n_attempted": n_pilots,
            "n_not_exercised": not_exercised,
            "n_counted": rules.N_CAL,
            "n_exact": rules.N_EXACT,
            "snr": {processor: 4.0 for processor in PROCESSORS},
            "min_effect_tone": 0.05,
            "tone_bins": [0.5, 0.8, 1.1, 1.6],
            "principal_components": principal_components,
        },
    }
    path = tmp_path / "settings.json"
    return record, path


def _write_manifest_and_record(tmp_path: Path, run_id: str, events_file: Path) -> Path:
    manifest_dir = tmp_path / "runs" / run_id
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "manifest.json"
    manifest_path.write_text(json.dumps({"run_id": run_id}), encoding="utf-8")
    with events_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"run_id": run_id}) + "\n")
    return manifest_path


def _make_record_with_run_data(
    tmp_path: Path,
    n_pilots: int | None = None,
    not_exercised: int = 0,
) -> tuple[Any, Path]:
    record, path = _build_record(tmp_path, n_pilots=n_pilots, not_exercised=not_exercised)
    events_dir = tmp_path / "research_events"
    events_dir.mkdir(parents=True, exist_ok=True)
    events_file = events_dir / "research_events-2026-10-11.jsonl"
    events_file.write_text("", encoding="utf-8")

    prelim = record["inputs"]["preliminary"]
    manifest_path = _write_manifest_and_record(tmp_path, prelim["run_id"], events_file)
    prelim["manifest_sha256"] = file_sha256(manifest_path)
    prelim["records_sha256"] = records_digest(
        load_records_for_runs([prelim["run_id"]], root=tmp_path)[prelim["run_id"]]
    )

    for pilot in record["inputs"]["pilots"]:
        for arm in ("competitive", "matched", "pooled", "tone"):
            ref = pilot["runs"][arm]
            manifest_path = _write_manifest_and_record(tmp_path, ref["run_id"], events_file)
            ref["manifest_sha256"] = file_sha256(manifest_path)
            ref["records_sha256"] = records_digest(
                load_records_for_runs([ref["run_id"]], root=tmp_path)[ref["run_id"]]
            )

    write_settings_record(record, path)
    settings = load_settings_record(path)
    return settings, path


def test_load_returns_values_and_excluded_seeds(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    write_settings_record(record, path)
    loaded = load_settings_record(path)
    assert loaded.t_learn_s == 120.0
    assert dict(loaded.theta_eff) == {"matched": 0.02, "pooled": 0.03}
    assert loaded.min_effect == 0.01
    assert loaded.min_reports == 500
    assert dict(loaded.snr) == {processor: 4.0 for processor in PROCESSORS}
    assert loaded.excluded_seeds == frozenset(range(1, rules.N_CAL + 2))


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
    reason, digest, run_data = planned_test_gate(
        "workspace_mediation_competitive",
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "mser_ignore_end" in reason
    assert digest is None
    assert run_data is None


def test_wrong_mser_min_batches_is_refused(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    record["constants"]["mser_min_batches"] = 9
    write_settings_record(record, path)
    reason, digest, run_data = planned_test_gate(
        "workspace_mediation_competitive",
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "mser_min_batches" in reason
    assert digest is None
    assert run_data is None


def test_refusal_checks_n_cal(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    record["constants"]["n_cal"] = 4
    write_settings_record(record, path)
    reason, digest, run_data = planned_test_gate(
        "workspace_mediation_competitive",
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "n_cal" in reason
    assert run_data is None


def test_refusal_checks_c_eff(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    record["constants"]["c_eff"] = 0.4
    write_settings_record(record, path)
    reason, digest, run_data = planned_test_gate(
        "workspace_mediation_competitive",
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "c_eff" in reason
    assert run_data is None


def test_refusal_checks_mser_batch(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    record["constants"]["mser_batch"] = 4
    write_settings_record(record, path)
    reason, digest, run_data = planned_test_gate(
        "workspace_mediation_competitive",
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "mser_batch" in reason
    assert run_data is None


def test_refusal_checks_snr_ladder(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    record["constants"]["snr_ladder"] = [1.0, 2.0]
    write_settings_record(record, path)
    reason, digest, run_data = planned_test_gate(
        "workspace_mediation_competitive",
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "snr_ladder" in reason
    assert run_data is None


def test_refusal_checks_n_counted(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    record["values"]["n_counted"] = 29
    write_settings_record(record, path)
    reason, digest, run_data = planned_test_gate(
        "workspace_mediation_competitive",
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "n_counted" in reason
    assert run_data is None


def test_refusal_checks_n_exact(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    record["values"]["n_exact"] = 101
    write_settings_record(record, path)
    reason, digest, run_data = planned_test_gate(
        "workspace_mediation_competitive",
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "n_exact" in reason
    assert run_data is None


def test_empty_pilots_list_is_refused(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path, n_pilots=0)
    record["inputs"]["pilots"] = []
    record["values"]["n_attempted"] = 0
    write_settings_record(record, path)
    reason, digest, run_data = planned_test_gate(
        None,
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "pilots" in reason
    assert digest is None
    assert run_data is None


def test_duplicate_pilot_seed_is_refused(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path, n_pilots=2)
    record["inputs"]["pilots"][1]["seed"] = record["inputs"]["pilots"][0]["seed"]
    write_settings_record(record, path)
    reason, digest, run_data = planned_test_gate(
        None,
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "seed" in reason
    assert digest is None
    assert run_data is None


def test_pilot_seed_matching_preliminary_is_refused(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path, n_pilots=1)
    record["inputs"]["pilots"][0]["seed"] = record["inputs"]["preliminary"]["seed"]
    write_settings_record(record, path)
    reason, digest, run_data = planned_test_gate(
        None,
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "seed" in reason
    assert digest is None
    assert run_data is None


def test_too_few_counted_pilots_is_refused(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path, n_pilots=29)
    write_settings_record(record, path)
    reason, digest, run_data = planned_test_gate(
        None,
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "counted" in reason
    assert digest is None
    assert run_data is None


def test_not_exercised_pilot_without_reason_is_refused(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path, not_exercised=1)
    for pilot in record["inputs"]["pilots"]:
        if not pilot["counted"]:
            pilot.pop("not_exercised_reason", None)
    write_settings_record(record, path)
    reason, digest, run_data = planned_test_gate(
        None,
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "not_exercised_reason" in reason
    assert digest is None
    assert run_data is None


def test_n_attempted_mismatch_is_refused(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    record["values"]["n_attempted"] = 999
    write_settings_record(record, path)
    reason, digest, run_data = planned_test_gate(
        None,
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "n_attempted" in reason
    assert digest is None
    assert run_data is None


def test_n_not_exercised_mismatch_is_refused(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path, not_exercised=1)
    record["values"]["n_not_exercised"] = 0
    write_settings_record(record, path)
    reason, digest, run_data = planned_test_gate(
        None,
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "n_not_exercised" in reason
    assert digest is None
    assert run_data is None


def test_repeated_run_id_is_refused(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path, n_pilots=2)
    record["inputs"]["pilots"][0]["runs"]["competitive"]["run_id"] = "prelim"
    write_settings_record(record, path)
    reason, digest, run_data = planned_test_gate(
        None,
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is not None
    assert "run_id" in reason
    assert digest is None
    assert run_data is None


def test_verify_run_data_absent_when_no_run_data(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    write_settings_record(record, path)
    settings = load_settings_record(path)
    assert verify_run_data(settings, root=tmp_path) == "absent"


def test_gate_returns_absent_run_data_when_no_run_data(
    monkeypatch: Any, tmp_path: Path
) -> None:
    record, path = _build_record(tmp_path)
    write_settings_record(record, path)

    from kaine.experiment import planned_test_settings as pts

    original = pts.verify_run_data

    def _verify(settings: Any) -> str:
        return original(settings, root=tmp_path)

    monkeypatch.setattr(pts, "verify_run_data", _verify)
    reason, digest, run_data = planned_test_gate(
        None,
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is None
    assert digest is not None
    assert run_data == "absent"


def test_verify_run_data_verified_when_run_data_matches(tmp_path: Path) -> None:
    settings, path = _make_record_with_run_data(tmp_path)
    assert verify_run_data(settings, root=tmp_path) == "verified"


def test_verify_run_data_raises_when_records_differ(tmp_path: Path) -> None:
    settings, path = _make_record_with_run_data(tmp_path)
    run_id = settings.runs[0].run_id
    events_file = tmp_path / "research_events" / "research_events-2026-10-11.jsonl"
    lines = events_file.read_text(encoding="utf-8").splitlines()
    new_lines = []
    for line in lines:
        obj = json.loads(line)
        if obj.get("run_id") == run_id:
            obj["extra"] = "tampered"
        new_lines.append(json.dumps(obj))
    events_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    with pytest.raises(PlannedTestSettingsError, match=run_id):
        verify_run_data(settings, root=tmp_path)


def test_verify_run_data_partial_when_some_runs_missing(tmp_path: Path) -> None:
    settings, path = _make_record_with_run_data(tmp_path)
    absent_id = settings.runs[-1].run_id
    manifest_path = tmp_path / "runs" / absent_id / "manifest.json"
    manifest_path.unlink()
    events_file = tmp_path / "research_events" / "research_events-2026-10-11.jsonl"
    present_ids = [r.run_id for r in settings.runs if r.run_id != absent_id]
    events_file.write_text(
        "".join(json.dumps({"run_id": rid}) + "\n" for rid in present_ids),
        encoding="utf-8",
    )
    assert verify_run_data(settings, root=tmp_path) == "partial"


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


def test_positive_control_mismatched_settings_record_is_refused_for_test(
    tmp_path: Path,
) -> None:
    record, path = _build_record(tmp_path)
    write_settings_record(record, path)
    other_path = tmp_path / "other_settings.json"
    other_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    config = {
        "planned_test": {"role": "test", "settings_record": str(path)},
        "positive_control": {
            "enabled": True,
            "mode": "control",
            "settings_record": str(other_path),
        },
    }
    reason, digest, run_data = planned_test_gate(
        "workspace_mediation_competitive", config, 99
    )
    assert reason is not None
    assert "[positive_control].settings_record must equal [planned_test].settings_record" in reason
    assert digest is None
    assert run_data is None


def test_positive_control_settings_record_without_planned_test_refused_for_pilot() -> None:
    config = {
        "planned_test": {"role": "pilot"},
        "positive_control": {
            "enabled": True,
            "mode": "ladder",
            "settings_record": "some_settings.json",
        },
    }
    reason, digest, run_data = planned_test_gate(
        "workspace_mediation_pilot_competitive", config, 99
    )
    assert reason is not None
    assert "[positive_control].settings_record must equal [planned_test].settings_record" in reason
    assert digest is None
    assert run_data is None


def test_gate_test_role_without_study_or_record_is_refused() -> None:
    reason, digest, run_data = planned_test_gate(None, {"planned_test": {"role": "test"}}, 0)
    assert reason is not None
    assert digest is None
    assert run_data is None


def test_gate_test_role_with_renamed_study_without_record_is_refused() -> None:
    reason, digest, run_data = planned_test_gate(
        "my_renamed_study",
        {"planned_test": {"role": "test"}},
        0,
    )
    assert reason is not None
    assert digest is None
    assert run_data is None


def test_gate_test_role_with_record_and_no_study_passes(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    write_settings_record(record, path)
    reason, digest, run_data = planned_test_gate(
        None,
        {"planned_test": {"role": "test", "settings_record": str(path)}},
        99,
    )
    assert reason is None
    loaded = load_settings_record(path)
    assert digest == loaded.record_sha256
    assert isinstance(run_data, str)


def test_gate_rejects_workspace_study_with_wrong_role() -> None:
    reason, digest, run_data = planned_test_gate(
        "workspace_mediation_competitive",
        {"planned_test": {"role": "pilot"}},
        0,
    )
    assert reason is not None
    assert "role = 'test'" in reason
    assert run_data is None

    reason, digest, run_data = planned_test_gate(
        "workspace_mediation_pilot_matched",
        {"planned_test": {"role": "test"}},
        0,
    )
    assert reason is not None
    assert "role = 'pilot'" in reason
    assert run_data is None

    reason, digest, run_data = planned_test_gate(
        "workspace_mediation_preliminary",
        {"planned_test": {"role": "pilot"}},
        0,
    )
    assert reason is not None
    assert "role = 'preliminary'" in reason
    assert run_data is None


def test_gate_rejects_unknown_workspace_study() -> None:
    reason, digest, run_data = planned_test_gate(
        "workspace_mediation_other",
        {"planned_test": {"role": "test"}},
        0,
    )
    assert reason is not None
    assert "unknown workspace-mediation study" in reason
    assert run_data is None


@pytest.mark.parametrize("study, expected_role", list(STUDY_ROLES.items()))
def test_gate_accepts_correct_study_role_pairs(tmp_path: Path, study: str, expected_role: str) -> None:
    config: dict[str, Any] = {"planned_test": {"role": expected_role}}
    if study in TONE_STUDIES:
        config["audition"] = {"tone_rule": "error_ratio"}
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

    reason, digest, run_data = planned_test_gate(study, config, 99)
    assert reason is None
    if expected_role in RECORD_ROLES:
        assert path is not None
        loaded = load_settings_record(path)
        assert digest == loaded.record_sha256
        assert run_data == "absent"
    else:
        assert digest is None
        assert run_data is None


def test_gate_test_role_refuses_non_control_positive_control_modes(tmp_path: Path) -> None:
    record, path = _build_record(tmp_path)
    write_settings_record(record, path)
    base_config = {"planned_test": {"role": "test", "settings_record": str(path)}}

    for mode in ("ladder", "estimate_pc"):
        config = {
            **base_config,
            "positive_control": {
                "enabled": True,
                "mode": mode,
                "settings_record": str(path),
            },
        }
        reason, digest, run_data = planned_test_gate(
            "workspace_mediation_competitive", config, 99
        )
        assert reason is not None
        assert mode in reason
        assert run_data is None

    config = {**base_config, "positive_control": {"enabled": False}}
    assert planned_test_gate("workspace_mediation_competitive", config, 99)[0] is None

    config = {
        **base_config,
        "positive_control": {
            "enabled": True,
            "mode": "control",
            "settings_record": str(path),
        },
    }
    assert planned_test_gate("workspace_mediation_competitive", config, 99)[0] is None


def test_gate_returns_none_when_no_study_or_planned_test() -> None:
    assert planned_test_gate(None, {}, 0) == (None, None, None)


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


def _write_mutated(tmp_path: Path, mutate: Callable[[dict[str, Any]], None]) -> Path:
    record, path = _build_record(tmp_path)
    mutate(record)
    write_settings_record(record, path)
    return path


def test_record_without_tone_variant_is_refused(tmp_path: Path) -> None:
    def strip_tone(record: dict[str, Any]) -> None:
        for pilot in record["inputs"]["pilots"]:
            del pilot["runs"]["tone"]

    path = _write_mutated(tmp_path, strip_tone)
    with pytest.raises(PlannedTestSettingsError, match="tone-variant"):
        load_settings_record(path)


def test_min_effect_tone_zero_is_refused(tmp_path: Path) -> None:
    def zero_tone(record: dict[str, Any]) -> None:
        record["values"]["min_effect_tone"] = 0

    path = _write_mutated(tmp_path, zero_tone)
    with pytest.raises(PlannedTestSettingsError, match="min_effect_tone"):
        load_settings_record(path)


@pytest.mark.parametrize(
    "tone_bins",
    [
        [0.5, 0.8, 1.1],  # wrong length
        [0.5, 0.8, 1.1, 0.6],  # decreasing pair
        [0.5, 0.8, 1.1, "1.6"],  # non-number entry
    ],
)
def test_tone_bins_invalid_is_refused(tmp_path: Path, tone_bins: list[Any]) -> None:
    def set_bins(record: dict[str, Any]) -> None:
        record["values"]["tone_bins"] = tone_bins

    path = _write_mutated(tmp_path, set_bins)
    with pytest.raises(PlannedTestSettingsError, match="tone_bins"):
        load_settings_record(path)


def test_loaded_record_exposes_tone_fields(tmp_path: Path) -> None:
    settings, _ = _make_record_with_run_data(tmp_path)
    assert settings.min_effect_tone == pytest.approx(0.05)
    assert settings.tone_bins == (0.5, 0.8, 1.1, 1.6)
