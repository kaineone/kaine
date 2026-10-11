# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from kaine.experiment import calibration_rules
from kaine.experiment.calibrate import (
    ARMS,
    CONTROLS,
    PROCESSORS,
    calibrate,
    headline,
    information_gain,
    main,
    not_exercised_reason,
)
from kaine.experiment.calibration_rules import (
    SNR_LADDER,
    CalibrationError,
    interpolate_snr,
    sign_test_critical_count,
    sign_test_power,
    stable_run_count,
)
from kaine.experiment.planned_test_settings import write_settings_record
from kaine.experiment.principal_component import (
    PrincipalComponentEstimator,
    principal_component_path,
    write_principal_component,
)
from kaine.experiment.run_records import load_records_for_runs

E_LADDER = [0.0, 0.001, 0.004, 0.01, 0.02, 0.03, 0.04]
N_REPORTS = 200


def _write_manifest(path: Path, run_id: str, seed: int, study: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id,
        "seed": seed,
        "study": study,
        "perception_feed": {"mode": "playlist", "sha256": "abc"},
    }
    path.write_text(json.dumps(manifest), encoding="utf-8")


def _record_path(root: Path, run_id: str) -> Path:
    path = root / "research_events" / f"research_events-{run_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _append_record(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _build_evaluation_tree(
    tmp_path: Path,
    *,
    n_pilots: int = 5,
    n_reports: int = 200,
    scale: float = 1.0,
    competitive_time_step: float = 1.0,
    wrong_entity_time_run: str | None = None,
    wrong_pc_sha_run_processor: tuple[str, str] | None = None,
    wrong_study_run_arm: tuple[str, str] | None = None,
    not_exercised_pilots: set[int] | None = None,
) -> tuple[dict[str, Any], Path]:
    root = tmp_path
    # The existing body was written against the module constant; bind it to the parameter.
    N_REPORTS = n_reports
    prelim_id = "prelim"
    _write_manifest(
        root / "runs" / prelim_id / "manifest.json",
        prelim_id,
        seed=100,
        study="workspace_mediation_preliminary",
    )

    # One preliminary broadcast, no arm required.
    prelim_path = _record_path(root, prelim_id)
    _append_record(prelim_path, {"run_id": prelim_id, "event_type": "workspace.broadcast"})

    pc_hashes = {}
    for proc_index, processor in enumerate(PROCESSORS):
        pc_path = principal_component_path(root / "positive_control", prelim_id, processor)
        pc_path.parent.mkdir(parents=True, exist_ok=True)
        est = PrincipalComponentEstimator()
        rng = np.random.default_rng([proc_index])
        for _ in range(5):
            est.add(rng.random(3))
        pc = est.result(processor=processor, run_id=prelim_id)
        pc_hashes[processor] = write_principal_component(pc, pc_path)

    pilots = []
    counted_so_far = 0
    default_not_exercised = {2} if n_pilots >= 3 else set()
    not_exercised_set = (
        not_exercised_pilots if not_exercised_pilots is not None else default_not_exercised
    )

    for pilot_index in range(n_pilots):
        not_exercised = pilot_index in not_exercised_set
        counted_index = None if not_exercised else counted_so_far
        if not not_exercised:
            counted_so_far += 1

        pilot = {}
        for arm_index, arm in enumerate(ARMS):
            run_id = f"{arm}_{pilot_index}"
            pilot[arm] = run_id
            study = f"workspace_mediation_pilot_{arm}"
            if wrong_study_run_arm == (run_id, arm):
                study = "wrong_study"
            _write_manifest(
                root / "runs" / run_id / "manifest.json",
                run_id,
                seed=200 + pilot_index,
                study=study,
            )

            path = _record_path(root, run_id)

            time_step = competitive_time_step if arm == "competitive" else 1.0

            if arm == "competitive":
                level = 0.10
            elif arm == "matched":
                level = (
                    0.10
                    if counted_index is None
                    else 0.10 - 0.02 * (counted_index - 1.5)
                )
            else:  # pooled
                level = (
                    0.10
                    if counted_index is None
                    else 0.10 - 2 * 0.02 * (counted_index - 1.5)
                )

            for proc_index, processor in enumerate(PROCESSORS):
                # Deterministic alternating noise so every tail has equal spread.
                noise = [0.002 * (-1) ** k for k in range(1, N_REPORTS + 1)]
                for k in range(1, N_REPORTS + 1):
                    gain = level + 2.0 * math.exp(-k / 2.0) + noise[k - 1]
                    record: dict[str, Any] = {
                        "run_id": run_id,
                        "event_type": _report_type(processor),
                        "processor": processor,
                        "entity_time_s": float(k * time_step),
                        "context_gain": float(gain),
                        "awake": True,
                    }
                    if wrong_entity_time_run == run_id and k == 1 and processor == "topos":
                        del record["entity_time_s"]
                    _append_record(path, record)

                # One null-gain report and one awake=False report, both ignored.
                _append_record(
                    path,
                    {
                        "run_id": run_id,
                        "event_type": _report_type(processor),
                        "processor": processor,
                        "entity_time_s": float((N_REPORTS + 1) * time_step),
                        "context_gain": None,
                        "awake": True,
                    },
                )
                _append_record(
                    path,
                    {
                        "run_id": run_id,
                        "event_type": _report_type(processor),
                        "processor": processor,
                        "entity_time_s": float((N_REPORTS + 2) * time_step),
                        "context_gain": 0.5,
                        "awake": False,
                    },
                )

            # Broadcasts.
            for tick in range(10):
                n_scores = 3 if not_exercised else 7
                inhibited = True if not_exercised else tick % 2 == 1
                scores = {str(i): 1.0 for i in range(n_scores)}
                _append_record(
                    path,
                    {
                        "run_id": run_id,
                        "event_type": "workspace.broadcast",
                        "arm": arm,
                        "coalition_capacity": 5,
                        "salience_scores": scores,
                        "inhibited": inhibited,
                    },
                )

            # Ladder records only in competitive runs.
            if arm == "competitive":
                for proc_index, processor in enumerate(PROCESSORS):
                    # Deterministic alternating noise so every tail has equal spread.
                    noise = [0.002 * (-1) ** k for k in range(1, N_REPORTS + 1)]
                    for k in range(1, N_REPORTS + 1):
                        gain = level + 2.0 * math.exp(-k / 2.0) + noise[k - 1]
                        r_factor = 0.0 if counted_index is None else (counted_index - 1.5)
                        gain_with = [
                            float(gain) + scale * e * (1.0 + 0.1 * r_factor)
                            for e in E_LADDER
                        ]
                        gain_noise = [
                            float(gain) + 0.0005 * r_factor for _ in E_LADDER
                        ]
                        pc_sha = pc_hashes[processor]
                        if wrong_pc_sha_run_processor == (run_id, processor) and k == 1:
                            pc_sha = "0" * 64
                        _append_record(
                            path,
                            {
                                "run_id": run_id,
                                "event_type": "positive_control.ladder",
                                "processor": processor,
                                "entity_time_s": float(k * time_step),
                                "gain": float(gain),
                                "gain_with": gain_with,
                                "gain_noise": gain_noise,
                                "snr": list(SNR_LADDER),
                                "pc_sha256": pc_sha,
                            },
                        )
                    _append_record(
                        path,
                        {
                            "run_id": run_id,
                            "event_type": "positive_control.result",
                            "processor": processor,
                            "mode": "ladder",
                            "final": True,
                            "failed": False,
                            "pc_sha256": pc_hashes[processor],
                        },
                    )

        pilots.append(pilot)

    plan = {"preliminary_run": prelim_id, "pilots": pilots}
    return plan, root


def _report_type(processor: str) -> str:
    return {
        "topos": "topos.report",
        "audition": "audition.perception",
        "soma": "soma.report",
    }[processor]


def test_calibrate_completes_except_always_blocked(tmp_path: Path) -> None:
    plan, root = _build_evaluation_tree(tmp_path, n_pilots=5)
    record = calibrate(plan, root=root, n_cal=4, mser_ignore_end=5)

    always_blocked = {
        "theta_band",
        "b_band",
        "age_bins",
        "min_effect_threshold_contrast",
        "tone_bins",
        "min_effect_tone",
    }
    assert set(record["blocked"].keys()) == always_blocked

    for entry in record["inputs"]["pilots"]:
        assert isinstance(entry["counted"], bool)
    assert sum(1 for entry in record["inputs"]["pilots"] if entry["counted"]) == 4

    values = record["values"]
    assert values["n_attempted"] == 5
    assert values["n_not_exercised"] == 1
    assert values["n_counted"] == 4
    assert abs(values["r_ne"] - 0.2) < 1e-9
    assert values["n_exact"] == stable_run_count()
    assert values["k_n_exact"] == sign_test_critical_count(values["n_exact"])
    assert abs(values["power_at_n_exact"] - float(sign_test_power(values["n_exact"]))) < 1e-9
    assert values["n_run_planned"] == 128

    assert isinstance(values["t_learn_s"], int)
    assert 5 <= values["t_learn_s"] <= 30

    expected_matched = statistics.stdev([-0.03, -0.01, 0.01, 0.03])
    assert abs(values["s_cal"]["matched"] - expected_matched) < 0.003
    assert abs(values["s_cal"]["pooled"] - 2 * expected_matched) < 0.006

    theta_pc = values["theta_pc"]
    assert theta_pc == 0.5 * min(values["s_cal"].values())
    assert values["min_effect"] == theta_pc / 2.0

    for processor in PROCESSORS:
        choice = interpolate_snr(
            SNR_LADDER,
            values["ladder_mean_effect"][processor]["informative"],
            theta_pc,
        )
        assert values["snr"][processor] == choice.snr
        assert 4 < choice.snr < 16

    assert values["min_reports"] == max(values["n_pc"].values())

    for arm in ARMS:
        for processor in PROCESSORS:
            assert len(values["report_rates"][arm][processor]) == 4

    for processor in PROCESSORS:
        for ctl in CONTROLS:
            check = values["report_rate_check"][processor][ctl]
            assert "mean_on" in check
            assert "mean_ctl" in check
            assert "sd_ctl" in check
            assert check["exceeds_control_sd"] is False

    assert "report_rate" not in record["blocked"]

    out = tmp_path / "settings.json"
    digest = write_settings_record(record, out)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["record_sha256"] == digest


def test_calibrate_default_mser_computes_t_learn(tmp_path: Path) -> None:
    plan, root = _build_evaluation_tree(tmp_path, n_pilots=5)
    record = calibrate(plan, root=root, n_cal=4)

    assert isinstance(record["values"]["t_learn_s"], int)
    assert "t_learn_s" not in record["blocked"]
    assert record["values"]["n_run_planned"] == 128

    constants = record["constants"]
    assert constants["mser_ignore_end"] == calibration_rules.MSER_IGNORE_END
    assert constants["mser_min_batches"] == calibration_rules.MSER_MIN_BATCHES

    values = record["values"]
    assert values["s_cal"] is not None
    assert values["snr"] is not None
    assert values["min_reports"] is not None


def test_calibrate_reads_mser_ignore_end_from_rules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(calibration_rules, "MSER_IGNORE_END", 6)
    plan, root = _build_evaluation_tree(tmp_path, n_pilots=5)
    record = calibrate(plan, root=root, n_cal=4)
    assert isinstance(record["values"]["t_learn_s"], int)
    assert record["constants"]["mser_ignore_end"] == 6


def test_calibrate_explicit_none_mser_ignore_end_blocks_t_learn(tmp_path: Path) -> None:
    plan, root = _build_evaluation_tree(tmp_path, n_pilots=5)
    record = calibrate(plan, root=root, n_cal=4, mser_ignore_end=None)
    assert record["values"]["t_learn_s"] is None
    assert "t_learn_s" in record["blocked"]


def test_calibrate_short_pilots_blocks_t_learn(tmp_path: Path) -> None:
    plan, root = _build_evaluation_tree(tmp_path, n_pilots=5, n_reports=45)
    record = calibrate(plan, root=root, n_cal=4)
    assert record["values"]["t_learn_s"] is None
    assert "t_learn_s" in record["blocked"]
    reason = record["blocked"]["t_learn_s"]
    assert "batch means" in reason
    assert "too short" in reason


def test_main_writes_record_and_returns_incomplete(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan, root = _build_evaluation_tree(tmp_path, n_pilots=5)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    out = tmp_path / "settings.json"
    ret = main([str(plan_path), "--out", str(out), "--root", str(root)])
    captured = capsys.readouterr().out
    assert ret == 1
    assert out.is_file()
    assert "record_sha256" in captured


def test_main_missing_run_returns_two_and_writes_nothing(tmp_path: Path) -> None:
    plan = {"preliminary_run": "missing", "pilots": [{"competitive": "c", "matched": "m", "pooled": "p"}]}
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    out = tmp_path / "settings.json"
    ret = main([str(plan_path), "--out", str(out), "--root", str(tmp_path)])
    assert ret == 2
    assert not out.exists()


def test_report_without_entity_time_s_raises(tmp_path: Path) -> None:
    plan, root = _build_evaluation_tree(
        tmp_path, n_pilots=5, wrong_entity_time_run="competitive_0"
    )
    with pytest.raises(CalibrationError, match="competitive_0"):
        calibrate(plan, root=root, n_cal=4, mser_ignore_end=5)


def test_wrong_manifest_study_raises(tmp_path: Path) -> None:
    plan, root = _build_evaluation_tree(
        tmp_path, n_pilots=5, wrong_study_run_arm=("matched_0", "matched")
    )
    with pytest.raises(CalibrationError, match="workspace_mediation_pilot_matched"):
        calibrate(plan, root=root, n_cal=4, mser_ignore_end=5)


def test_ladder_different_pc_sha256_blocks_snr(tmp_path: Path) -> None:
    plan, root = _build_evaluation_tree(
        tmp_path, n_pilots=5, wrong_pc_sha_run_processor=("competitive_0", "topos")
    )
    record = calibrate(plan, root=root, n_cal=4, mser_ignore_end=5)

    assert record["values"]["snr"] is None
    assert "snr" in record["blocked"]
    assert "different principal component" in record["blocked"]["snr"]
    assert record["blocked"]["min_reports"] == "depends on snr"


def test_ladder_means_below_theta_pc_blocks_snr(tmp_path: Path) -> None:
    plan, root = _build_evaluation_tree(tmp_path, n_pilots=5, scale=0.01)
    record = calibrate(plan, root=root, n_cal=4, mser_ignore_end=5)
    assert record["values"]["snr"] is None
    assert "snr" in record["blocked"]
    assert str(SNR_LADDER[-1]) in record["blocked"]["snr"]
    assert "256.0" in record["blocked"]["snr"]
    assert record["blocked"]["min_reports"] == "depends on snr"
    assert record["values"]["min_reports"] is None
    assert record["values"]["s2"] is None
    assert record["values"]["n_pc"] is None


def test_extra_pilot_after_counted_raises(tmp_path: Path) -> None:
    plan, root = _build_evaluation_tree(tmp_path, n_pilots=6)
    with pytest.raises(CalibrationError, match="after the counted pilots"):
        calibrate(plan, root=root, n_cal=4, mser_ignore_end=5)


def test_manifest_seed_string_raises(tmp_path: Path) -> None:
    plan, root = _build_evaluation_tree(tmp_path, n_pilots=5)
    bad_manifest = root / "runs" / "competitive_0" / "manifest.json"
    loaded = json.loads(bad_manifest.read_text(encoding="utf-8"))
    loaded["seed"] = "not-an-int"
    bad_manifest.write_text(json.dumps(loaded), encoding="utf-8")
    with pytest.raises(CalibrationError, match="competitive_0"):
        calibrate(plan, root=root, n_cal=4, mser_ignore_end=5)


def test_all_not_exercised_blocks_n_run_planned(tmp_path: Path) -> None:
    plan, root = _build_evaluation_tree(
        tmp_path, n_pilots=1, not_exercised_pilots={0}
    )
    record = calibrate(plan, root=root)
    assert record["values"]["n_run_planned"] is None
    assert "n_run_planned" in record["blocked"]
    assert "pilots" in record["blocked"]


def test_ladder_failed_true_blocks_snr(tmp_path: Path) -> None:
    plan, root = _build_evaluation_tree(tmp_path, n_pilots=5)
    path = _record_path(root, "competitive_0")
    _append_record(
        path,
        {
            "run_id": "competitive_0",
            "event_type": "positive_control.result",
            "processor": "topos",
            "mode": "ladder",
            "final": True,
            "failed": True,
        },
    )
    record = calibrate(plan, root=root, n_cal=4, mser_ignore_end=5)

    assert record["values"]["snr"] is None
    assert "snr" in record["blocked"]
    assert "did not finish cleanly" in record["blocked"]["snr"]
    assert record["blocked"]["min_reports"] == "depends on snr"


def test_report_rate_mismatch_is_recorded_not_blocked(tmp_path: Path) -> None:
    plan, root = _build_evaluation_tree(
        tmp_path, n_pilots=5, competitive_time_step=2.0
    )
    record = calibrate(plan, root=root, n_cal=4, mser_ignore_end=5)

    assert "report_rate" not in record["blocked"]
    assert not any(
        "report_rate" in reason for reason in record["blocked"].values()
    )
    assert record["values"]["t_learn_s"] is not None
    for processor in PROCESSORS:
        for ctl in CONTROLS:
            assert (
                record["values"]["report_rate_check"][processor][ctl][
                    "exceeds_control_sd"
                ]
                is True
            )


def test_not_exercised_reason_never_operated() -> None:
    broadcasts = [
        {
            "coalition_capacity": 5,
            "salience_scores": {"a": 1.0, "b": 2.0, "c": 3.0},
            "inhibited": False,
        }
    ]
    assert not_exercised_reason(broadcasts) == "competition never operated"


def test_not_exercised_reason_no_accessed_broadcast() -> None:
    broadcasts = [
        {
            "coalition_capacity": 5,
            "salience_scores": {str(i): 1.0 for i in range(7)},
            "inhibited": True,
        }
    ]
    assert not_exercised_reason(broadcasts) == "no accessed broadcast"


def test_not_exercised_reason_none() -> None:
    broadcasts = [
        {
            "coalition_capacity": 5,
            "salience_scores": {str(i): 1.0 for i in range(7)},
            "inhibited": False,
        }
    ]
    assert not_exercised_reason(broadcasts) is None


def test_headline_returns_none_when_processor_missing() -> None:
    ig = {"topos": 1.0, "audition": None, "soma": 1.0}
    assert headline(ig) is None


def test_headline_returns_mean() -> None:
    ig = {processor: 2.0 for processor in PROCESSORS}
    assert headline(ig) == 2.0


def test_information_gain_uses_strictly_after_t_learn() -> None:
    reports = {
        processor: [(1.0, 1.0), (2.0, 2.0), (3.0, 3.0)] for processor in PROCESSORS
    }
    ig = information_gain(reports, 2.0)
    assert ig == {processor: 3.0 for processor in PROCESSORS}



def test_main_rejects_non_object_plan(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("[1, 2]")
    out = tmp_path / "settings.json"
    assert main([str(plan_path), "--out", str(out), "--root", str(tmp_path)]) == 2
    assert not out.exists()


def test_load_records_for_runs_accepts_generator(tmp_path: Path) -> None:
    records_file = tmp_path / "research_events-2026-10-11.jsonl"
    records_file.write_text(
        '{"run_id": "a", "event_type": "x"}\n'
        '{"run_id": "b", "event_type": "x"}\n'
    )
    result = load_records_for_runs((run_id for run_id in ["a", "b"]), root=tmp_path)
    assert set(result) == {"a", "b"}
    for run_id in ("a", "b"):
        total = sum(len(records) for records in result[run_id].by_stream.values())
        assert total == 1
