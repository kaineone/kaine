# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the offline positive-control verdict checker."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kaine.experiment.positive_control import (
    PROCESSORS,
    RESULT_EVENT_TYPE,
    main,
    run_verdict,
    verdict_from_records,
)
from kaine.modules.positive_control import PROCESSORS as MODULE_PROCESSORS
from kaine.modules.positive_control import RESULT_EVENT_TYPE as MODULE_RESULT_EVENT_TYPE


def _result(processor: str, passed: Any, **overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "event_type": RESULT_EVENT_TYPE,
        "processor": processor,
        "n_reports": 200,
        "min_reports": 100,
        "ig_with": 0.06,
        "ig_without": 0.01,
        "ig_noise": 0.01,
        "effect": 0.05,
        "noise_effect": 0.0,
        "min_effect": 0.01,
        "snr": 10.0,
        "detected": True,
        "noise_detected": False,
        "passed": passed,
        "failed": False,
        "final": True,
        "run_id": "r1",
    }
    record.update(overrides)
    return record


def test_verdict_passes_when_all_processors_pass():
    records = [_result(p, True) for p in PROCESSORS]
    verdict = verdict_from_records(records)
    assert verdict["passed"] is True
    for processor in PROCESSORS:
        assert verdict["processors"][processor]["passed"] is True
        assert verdict["reasons"][processor] == "passed"


def test_verdict_fails_when_processor_missing():
    records = [_result("topos", True), _result("audition", True)]
    verdict = verdict_from_records(records)
    assert verdict["passed"] is False
    assert verdict["missing"] == ["soma"]
    assert verdict["reasons"]["soma"] == "no result"


def test_verdict_fails_when_last_record_does_not_pass():
    records = [
        _result("topos", True),
        _result("audition", True),
        _result("soma", True, effect=0.005, ig_with=0.015),
    ]
    verdict = verdict_from_records(records)
    assert verdict["passed"] is False
    assert "soma" in verdict["not_passed"]
    assert verdict["reasons"]["soma"] == "the informative component was not detected"


def test_verdict_checks_every_record_for_each_processor():
    # An earlier failed record defeats a later passing terminal record.
    records = [
        _result("topos", True),
        _result("audition", True),
        _result("soma", True, failed=True),
        _result("soma", True),
    ]
    verdict = verdict_from_records(records)
    assert verdict["passed"] is False
    assert "soma" in verdict["not_passed"]
    assert verdict["reasons"]["soma"] == "the control failed"

    # Two terminal records mean the control restarted.
    records = [
        _result("topos", True),
        _result("audition", True),
        _result("soma", True),
        _result("soma", True),
    ]
    verdict = verdict_from_records(records)
    assert verdict["passed"] is False
    assert "soma" in verdict["not_passed"]
    assert (
        verdict["reasons"]["soma"]
        == "more than one terminal record (the control restarted)"
    )

    # A cumulative record after the terminal record is a protocol violation.
    records = [
        _result("topos", True),
        _result("audition", True),
        _result("soma", True),
        _result("soma", True, final=False, n_reports=250),
    ]
    verdict = verdict_from_records(records)
    assert verdict["passed"] is False
    assert "soma" in verdict["not_passed"]
    assert (
        verdict["reasons"]["soma"] == "a record follows the terminal record"
    )

    # A fresh control inside the same run_id creates more than one terminal record.
    records = [
        _result("topos", True),
        _result("audition", True),
        _result("soma", True, n_reports=100, final=False),
        _result("soma", True, n_reports=200, final=False),
        _result("soma", True, n_reports=200),
        _result("soma", True, n_reports=50, final=False),
        _result("soma", True, n_reports=150),
    ]
    verdict = verdict_from_records(records)
    assert verdict["passed"] is False
    assert "soma" in verdict["not_passed"]
    assert (
        verdict["reasons"]["soma"]
        == "more than one terminal record (the control restarted)"
    )


def test_terminal_record_must_have_consistent_ig_fields():
    records = [
        _result("topos", True),
        _result("audition", True),
        _result("soma", True, ig_with=0.03, ig_without=0.01),
    ]
    verdict = verdict_from_records(records)
    assert verdict["passed"] is False
    assert "soma" in verdict["not_passed"]
    assert (
        verdict["reasons"]["soma"]
        == "effect does not match ig_with minus ig_without"
    )


def test_verdict_ignores_other_event_types():
    records = [
        _result("topos", True),
        _result("audition", True),
        _result("soma", True),
        {"event_type": "topos.report", "processor": "soma", "passed": False},
    ]
    verdict = verdict_from_records(records)
    assert verdict["passed"] is True


def _write_run(root: Path, run_id: str, records: list[dict[str, Any]]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "positive_control-2026-01-01.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n"
    )


def test_main_returns_zero_for_passing_run(tmp_path, capsys):
    root = tmp_path / "r1"
    records = [_result(p, True, run_id="r1") for p in PROCESSORS]
    _write_run(root, "r1", records)
    assert main(["r1", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "all processors pass: yes" in out
    assert "parse_errors: 0" in out


def test_main_returns_one_for_failing_run(tmp_path, capsys):
    root = tmp_path / "r1"
    records = [_result(p, True, run_id="r1") for p in ("topos", "audition")]
    records.append(_result("soma", False, run_id="r1", effect=0.001))
    _write_run(root, "r1", records)
    assert main(["r1", "--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "all processors pass: no" in out


def test_main_json_flag_prints_parseable_json(tmp_path, capsys):
    root = tmp_path / "r1"
    records = [_result(p, True, run_id="r1") for p in PROCESSORS]
    _write_run(root, "r1", records)
    assert main(["r1", "--root", str(root), "--json"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["passed"] is True
    assert parsed["parse_errors"] == 0
    assert set(parsed["reasons"]) == set(PROCESSORS)


def test_constants_match_the_module():
    assert PROCESSORS == MODULE_PROCESSORS
    assert RESULT_EVENT_TYPE == MODULE_RESULT_EVENT_TYPE


def test_verdict_fails_when_the_last_record_marks_a_failure():
    records = [_result(p, True) for p in PROCESSORS]
    records.append(_result("soma", False, failed=True))
    verdict = verdict_from_records(records)
    assert verdict["passed"] is False
    assert "soma" in verdict["not_passed"]
    assert verdict["reasons"]["soma"] == "the control failed"


def test_verdict_fails_when_failed_is_true_even_if_passed_is_true():
    records = [_result(p, True) for p in PROCESSORS]
    records.append(_result("soma", True, failed=True))
    verdict = verdict_from_records(records)
    assert verdict["passed"] is False
    assert "soma" in verdict["not_passed"]


def test_stale_cumulative_pass_fails_without_terminal_record():
    records = [
        _result("topos", True),
        _result("audition", True),
        _result("soma", True),
        _result("soma", True, final=False),
    ]
    verdict = verdict_from_records(records)
    assert verdict["passed"] is False
    assert "soma" in verdict["not_passed"]
    assert verdict["reasons"]["soma"] == "a record follows the terminal record"


def test_passed_flag_is_not_trusted():
    records = [_result(p, False) for p in PROCESSORS]
    verdict = verdict_from_records(records)
    assert verdict["passed"] is True
    for processor in PROCESSORS:
        assert verdict["reasons"][processor] == "passed"


def test_low_effect_fails():
    records = [_result(p, True) for p in PROCESSORS]
    records[-1] = _result("soma", True, effect=0.005, ig_with=0.015)
    verdict = verdict_from_records(records)
    assert verdict["passed"] is False
    assert "soma" in verdict["not_passed"]
    assert verdict["reasons"]["soma"] == "the informative component was not detected"


def test_n_reports_below_min_reports_fails():
    records = [_result(p, True) for p in PROCESSORS]
    records[-1] = _result("soma", True, n_reports=50)
    verdict = verdict_from_records(records)
    assert verdict["passed"] is False
    assert "soma" in verdict["not_passed"]
    assert verdict["reasons"]["soma"] == "n_reports is below min_reports"


def test_non_finite_effect_fails():
    records = [_result(p, True) for p in PROCESSORS]
    records[-1] = _result("soma", True, effect=float("nan"))
    verdict = verdict_from_records(records)
    assert verdict["passed"] is False
    assert "soma" in verdict["not_passed"]
    assert "missing or not finite" in verdict["reasons"]["soma"]


def test_min_effect_zero_fails():
    records = [_result(p, True) for p in PROCESSORS]
    records[-1] = _result("soma", True, min_effect=0.0)
    verdict = verdict_from_records(records)
    assert verdict["passed"] is False
    assert "soma" in verdict["not_passed"]
    assert verdict["reasons"]["soma"] == "min_effect is not above 0"


def test_parse_error_makes_run_fail(tmp_path, capsys):
    root = tmp_path / "r1"
    records = [_result(p, True, run_id="r1") for p in PROCESSORS]
    _write_run(root, "r1", records)
    path = root / "positive_control-2026-01-01.jsonl"
    path.write_text(path.read_text() + "not json\n")
    assert main(["r1", "--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "all processors pass: no" in out
    assert "parse_errors: 1" in out
    assert run_verdict("r1", root=root)["parse_errors"] == 1
