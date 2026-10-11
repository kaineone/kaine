# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the offline positive-control verdict checker."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kaine.experiment.positive_control import (
    PROCESSORS,
    RESULT_EVENT_TYPE,
    main,
    verdict_from_records,
)
from kaine.modules.positive_control import (
    PROCESSORS as MODULE_PROCESSORS,
)
from kaine.modules.positive_control import (
    RESULT_EVENT_TYPE as MODULE_RESULT_EVENT_TYPE,
)


def _result(processor: str, passed: Any, **overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "event_type": RESULT_EVENT_TYPE,
        "processor": processor,
        "n_reports": 1,
        "ig_with": 0.1,
        "ig_without": 0.05,
        "ig_noise": 0.04,
        "effect": 0.05,
        "noise_effect": 0.01,
        "min_effect": 0.01,
        "snr": 10.0,
        "detected": True,
        "noise_detected": False,
        "passed": passed,
        "failed": False,
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


def test_verdict_fails_when_processor_missing():
    records = [_result("topos", True), _result("audition", True)]
    verdict = verdict_from_records(records)
    assert verdict["passed"] is False
    assert verdict["missing"] == ["soma"]


@pytest.mark.parametrize("passed", [False, None])
def test_verdict_fails_when_last_record_does_not_pass(passed):
    records = [
        _result("topos", True),
        _result("audition", True),
        _result("soma", False),
        _result("soma", passed),
    ]
    verdict = verdict_from_records(records)
    assert verdict["passed"] is False
    assert "soma" in verdict["not_passed"]


def test_verdict_uses_last_record_for_each_processor():
    records = [
        _result("topos", False),
        _result("topos", True),
        _result("audition", True),
        _result("soma", True),
    ]
    verdict = verdict_from_records(records)
    assert verdict["passed"] is True
    assert verdict["processors"]["topos"]["passed"] is True


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
    assert "all processors pass: yes" in capsys.readouterr().out


def test_main_returns_one_for_failing_run(tmp_path, capsys):
    root = tmp_path / "r1"
    records = [_result(p, True, run_id="r1") for p in ("topos", "audition")]
    records.append(_result("soma", False, run_id="r1"))
    _write_run(root, "r1", records)
    assert main(["r1", "--root", str(root)]) == 1
    assert "all processors pass: no" in capsys.readouterr().out


def test_main_json_flag_prints_parseable_json(tmp_path, capsys):
    root = tmp_path / "r1"
    records = [_result(p, True, run_id="r1") for p in PROCESSORS]
    _write_run(root, "r1", records)
    assert main(["r1", "--root", str(root), "--json"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["passed"] is True


def test_constants_match_the_module():
    assert PROCESSORS == MODULE_PROCESSORS
    assert RESULT_EVENT_TYPE == MODULE_RESULT_EVENT_TYPE


def test_verdict_fails_when_the_last_record_marks_a_failure():
    records = [_result(p, True) for p in PROCESSORS]
    records.append(_result("soma", False, failed=True))
    verdict = verdict_from_records(records)
    assert verdict["passed"] is False
    assert "soma" in verdict["not_passed"]


def test_verdict_fails_when_failed_is_true_even_if_passed_is_true():
    records = [_result(p, True) for p in PROCESSORS]
    records.append(_result("soma", True, failed=True))
    verdict = verdict_from_records(records)
    assert verdict["passed"] is False
    assert "soma" in verdict["not_passed"]
