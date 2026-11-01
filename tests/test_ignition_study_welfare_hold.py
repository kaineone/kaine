# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The study runner reads each step's welfare exposure and holds for review.

A stand-in cycle (the runner tests' own) writes state/welfare/exposure.json at
exit as the real cycle does. The runner copies a record bound to the step's
run and boot into the step record, and does not start the next step after a
missing, unreadable, unbound or incomplete record, or one that shows an
indicator crossing, until ack-welfare answers continue or stop.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from kaine.research.ignition_study.__main__ import main as study_main
from kaine.research.ignition_study.runner import (
    StudyError,
    StudyRunner,
    StudyWelfareHold,
    read_step_exposure,
)
from tests.test_ignition_study_runner import (
    STANDIN_SCRIPT,
    _create_study,
    _load_steps,
    _run,
    _runner,
    known_modules,  # noqa: F401  (fixture)
)


def _study(tmp_path: Path):
    study_dir = _create_study(tmp_path, viewings=1)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    return study_dir, script


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_a_valid_record_is_copied_and_the_run_goes_on(tmp_path, known_modules):  # noqa: F811
    study_dir, script = _study(tmp_path)
    assert _run(_runner(study_dir, script)) == "complete"
    steps = _load_steps(study_dir)
    assert all(s["outcome"] == "complete" for s in steps)
    for s in steps:
        exposure = s["welfare_exposure"]
        assert exposure["run_id"] == s["run_id"]
        assert "welfare_hold" not in s
    assert len(steps) == 5


@pytest.mark.parametrize(
    ("mode", "reason", "copied"),
    [
        ("crossing", "indicator_crossing", True),
        ("protective", "protective_response", True),
        ("responses_malformed", "protective_response", True),
        ("missing", "missing", False),
        ("other_run", "other_run", False),
        ("restart", "incomplete_coverage", True),
        ("unreadable", "unreadable", False),
    ],
)
def test_the_run_holds_after_a_step_that_needs_review(
    tmp_path, known_modules, monkeypatch, mode, reason, copied  # noqa: F811
):
    study_dir, script = _study(tmp_path)
    monkeypatch.setenv("IGNITION_STANDIN_EXPOSURE", mode)
    held = _run(_runner(study_dir, script))
    assert isinstance(held, dict) and "held" in held
    record = held["held"]
    assert record["line"] == "development" and record["outcome"] == "complete"
    assert reason in record["welfare_hold"]["reasons"]
    assert ("welfare_exposure" in record) is copied
    # The next step did not start.
    assert [s["line"] for s in _load_steps(study_dir)] == ["development"]
    status = StudyRunner(study_dir).status()
    assert "Welfare hold: development step 0" in status
    assert "ack-welfare" in status and "--step development/0" in status
    assert "Next: held for welfare review" in status


def test_continue_releases_the_hold_and_never_touches_the_step_state(
    tmp_path, known_modules, monkeypatch  # noqa: F811
):
    study_dir, script = _study(tmp_path)
    monkeypatch.setenv("IGNITION_STANDIN_EXPOSURE", "crossing")
    assert "held" in _run(_runner(study_dir, script))
    state = study_dir / "development" / "state"
    before = _tree_digest(state)
    ack = StudyRunner(study_dir).acknowledge_welfare("development", 0, "continue")
    assert ack["decision"] == "continue"
    assert set(ack) == {"line", "step", "decision", "acknowledged_at", "step_ended_at", "reasons"}
    assert _tree_digest(state) == before
    acks = [json.loads(line) for line in (study_dir / "welfare_acks.jsonl").read_text().splitlines()]
    assert [a["decision"] for a in acks] == ["continue"]
    # The next run starts the next step (the stand-in now writes clean records).
    monkeypatch.delenv("IGNITION_STANDIN_EXPOSURE")
    assert _run(_runner(study_dir, script)) == "complete"
    assert [s["line"] for s in _load_steps(study_dir)][:2] == ["development", "branch"]


def test_stop_ends_the_line_and_keeps_its_preservations(tmp_path, known_modules, monkeypatch):  # noqa: F811
    study_dir, script = _study(tmp_path)
    monkeypatch.setenv("IGNITION_STANDIN_EXPOSURE", "crossing")
    held = _run(_runner(study_dir, script))
    bundle = Path(held["held"]["bundle"])
    state = study_dir / "development" / "state"
    before = _tree_digest(state)
    StudyRunner(study_dir).acknowledge_welfare("development", 0, "stop")
    assert _tree_digest(state) == before
    monkeypatch.delenv("IGNITION_STANDIN_EXPOSURE")
    # Every line starts from this seed, so nothing else starts.
    assert _run(_runner(study_dir, script)) == "complete"
    assert [s["line"] for s in _load_steps(study_dir)] == ["development"]
    assert bundle.is_dir()
    assert "Stopped after a welfare review" in StudyRunner(study_dir).status()


def test_an_old_record_left_in_the_step_does_not_release_the_hold(
    tmp_path, known_modules, monkeypatch  # noqa: F811
):
    """A record from an earlier attempt (or a restored bundle) is bound to another run."""
    study_dir, script = _study(tmp_path)
    old = study_dir / "development" / "state" / "welfare" / "exposure.json"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text(json.dumps({
        "schema": 1, "run_id": "an-earlier-boot", "boot_started_at": "2026-10-01T00:00:00+00:00",
        "monitor": {"awake_seconds": 10.0, "rests_requested": 0, "freezes_placed": 0, "indicators": {"x": {}}},
        "producer_restarts": 0, "covered_awake_seconds": 10.0, "affect_summary_interval_s": 300.0,
    }))
    # The boot neither removes it (as a crashed boot that never reached the
    # cycle would not) nor writes its own.
    monkeypatch.setenv("IGNITION_STANDIN_KEEP_EXPOSURE", "1")
    monkeypatch.setenv("IGNITION_STANDIN_EXPOSURE", "missing")
    held = _run(_runner(study_dir, script))
    assert held["held"]["welfare_hold"]["reasons"] == ["other_run"]
    assert "welfare_exposure" not in held["held"]


def test_a_crash_after_a_revive_whose_bundle_held_an_old_record_holds(
    tmp_path, known_modules, monkeypatch  # noqa: F811
):
    study_dir, script = _study(tmp_path)
    assert _run(_runner(study_dir, script)) == "complete"
    # A later boot of the first viewing whose revived state held the seed's
    # record and that crashed before writing its own: the record on disk is
    # bound to the seed's run, not to the new boot's.
    steps = _load_steps(study_dir)
    seed_record = study_dir / "development" / "state" / "welfare" / "exposure.json"
    branch_record = study_dir / "branch" / "0" / "state" / "welfare" / "exposure.json"
    branch_record.write_text(seed_record.read_text())
    from kaine.research.ignition_study.runner import read_step_exposure

    exposure, reasons = read_step_exposure(
        study_dir / "branch" / "0",
        run_id=steps[1]["run_id"] + "-retry",
        since_iso=steps[1]["started_at"],
    )
    assert exposure is None and reasons == ["other_run"]


def test_ack_welfare_refuses_without_a_pending_hold(tmp_path, known_modules):  # noqa: F811
    study_dir, script = _study(tmp_path)
    assert _run(_runner(study_dir, script)) == "complete"
    with pytest.raises(StudyError, match="no welfare hold is pending"):
        StudyRunner(study_dir).acknowledge_welfare("development", 0, "continue")


def test_the_cli_answers_a_hold(tmp_path, known_modules, monkeypatch, capsys):  # noqa: F811
    study_dir, script = _study(tmp_path)
    monkeypatch.setenv("IGNITION_STANDIN_EXPOSURE", "crossing")
    assert "held" in _run(_runner(study_dir, script))
    monkeypatch.setenv("KAINE_DATA_ROOT", str(tmp_path))
    rc = study_main([
        "ack-welfare", "--study-dir", str(study_dir), "--step", "development/0", "--decision", "continue",
    ])
    assert rc == 0
    assert "Recorded continue for development step 0" in capsys.readouterr().out
    assert study_main([
        "ack-welfare", "--study-dir", str(study_dir), "--step", "development/0", "--decision", "continue",
    ]) == 2
    assert study_main([
        "ack-welfare", "--study-dir", str(study_dir), "--step", "nonsense", "--decision", "stop",
    ]) == 2


# --- a protective response that is not a crossing (E-R1) ---------------------------


def _bound_record(line_dir: Path, **monitor_overrides) -> tuple[str, str]:
    """Write a clean exposure record bound to a run and boot; returns (run_id, since)."""
    names = ["boredom_deprived", "social_drive_deprived", "restlessness_deprived",
             "negative_valence", "boredom_uncontrolled", "restlessness_uncontrolled"]
    monitor = {
        "awake_seconds": 599.0, "rests_requested": 0, "freezes_placed": 0, "responses": {},
        "indicators": {n: {"max_value": 0.1, "crossings": 0, "rests_requested": 0,
                           "freezes_placed": 0} for n in names},
    }
    monitor.update(monitor_overrides)
    since = "2026-10-31T10:00:00+00:00"
    path = line_dir / "state" / "welfare" / "exposure.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": 1, "run_id": "r1", "boot_started_at": since, "monitor": monitor,
        "producer_restarts": 0, "covered_awake_seconds": 599.0, "affect_summary_interval_s": 300.0,
    }))
    return "r1", since


def test_an_ended_boot_with_unavailable_indicators_holds(tmp_path):
    """The review's case: action "end", the affect stream fell silent, the net
    preserved and ended the boot. No freeze, no rest, no crossing: only the
    response count shows it, and it holds."""
    run_id, since = _bound_record(tmp_path, responses={"indicators_unavailable": 1})
    exposure, reasons = read_step_exposure(tmp_path, run_id=run_id, since_iso=since)
    assert exposure is not None
    assert reasons == ["protective_response"]


@pytest.mark.parametrize("responses", [{"sustained_distress": 1}, None, [], "x", {"x": "1"}])
def test_any_response_or_an_unreadable_response_count_holds(tmp_path, responses):
    run_id, since = _bound_record(tmp_path, responses=responses)
    _, reasons = read_step_exposure(tmp_path, run_id=run_id, since_iso=since)
    assert "protective_response" in reasons


def test_a_clean_monitor_has_no_protective_response(tmp_path):
    run_id, since = _bound_record(tmp_path)
    _, reasons = read_step_exposure(tmp_path, run_id=run_id, since_iso=since)
    assert reasons == []


@pytest.mark.parametrize(
    "boot_started_at", ["2026-10-31T09:00:00+00:00", None, "not a time"]
)
def test_a_record_of_this_run_from_an_earlier_boot_holds(tmp_path, boot_started_at):
    """The boot-time binding alone: the run id matches, the boot started before
    the step (or has no readable start), so the record is not this boot's."""
    run_id, since = _bound_record(tmp_path)
    path = tmp_path / "state" / "welfare" / "exposure.json"
    data = json.loads(path.read_text())
    data["boot_started_at"] = boot_started_at
    path.write_text(json.dumps(data))
    exposure, reasons = read_step_exposure(tmp_path, run_id=run_id, since_iso=since)
    assert exposure is None
    assert reasons == ["other_boot"]


# --- a failed step after a crossing is not retried unreviewed (E-R2) ---------------


def _failed_after(tmp_path: Path, monkeypatch, exposure_mode: str):
    """branch 1 fails (missing preservation); its boot wrote ``exposure_mode``."""
    study_dir, script = _study(tmp_path)
    monkeypatch.setenv("IGNITION_STANDIN_SCENARIO", "missing_preservation")
    monkeypatch.setenv("IGNITION_STANDIN_SCENARIO_EXPOSURE", exposure_mode)
    failed = _run(_runner(study_dir, script))
    assert failed["outcome"] == "failed:missing_preservation"
    assert (failed["line"], failed["step"]) == ("branch", 1)
    monkeypatch.delenv("IGNITION_STANDIN_SCENARIO")
    monkeypatch.delenv("IGNITION_STANDIN_SCENARIO_EXPOSURE")
    return study_dir, script, failed


@pytest.mark.parametrize(("mode", "reason"), [("crossing", "indicator_crossing"),
                                              ("protective", "protective_response")])
def test_retry_failed_refuses_while_the_failed_boot_awaits_review(
    tmp_path, known_modules, monkeypatch, mode, reason  # noqa: F811
):
    study_dir, script, failed = _failed_after(tmp_path, monkeypatch, mode)
    assert reason in failed["welfare_hold"]["reasons"]
    steps_before = len(_load_steps(study_dir))
    with pytest.raises(StudyWelfareHold) as exc:
        _runner(study_dir, script).run(retry_failed=True)
    assert exc.value.record["outcome"] == "failed:missing_preservation"
    # Nothing was booted.
    assert len(_load_steps(study_dir)) == steps_before
    status = StudyRunner(study_dir).status()
    assert "Welfare hold: failed branch step 1" in status
    assert "--retry-failed refuses" in status
    assert "--step branch/1" in status
    assert "Next: answer the welfare hold" in status
    # ack-welfare answers the failed step; the retry then boots it.
    ack = StudyRunner(study_dir).acknowledge_welfare("branch", 1, "continue")
    assert ack["step_ended_at"] == failed["ended_at"]
    assert _run(_runner(study_dir, script), retry=True) == "complete"
    steps = _load_steps(study_dir)
    assert [(s["line"], s["step"], s["outcome"]) for s in steps[-2:]] == [
        ("branch", 1, "complete"), ("accumulate", 1, "complete"),
    ]


def test_the_cli_reports_the_failed_steps_hold(tmp_path, known_modules, monkeypatch, capsys):  # noqa: F811
    study_dir, script, _ = _failed_after(tmp_path, monkeypatch, "crossing")
    monkeypatch.setenv("KAINE_DATA_ROOT", str(tmp_path))
    capsys.readouterr()
    assert study_main(["run", "--study-dir", str(study_dir)]) == 1
    err = capsys.readouterr().err
    assert "Study halted: failed:missing_preservation at branch step 1" in err
    assert "Welfare hold: failed branch step 1" in err
    assert study_main(["run", "--study-dir", str(study_dir), "--retry-failed"]) == 4
    err = capsys.readouterr().err
    assert "The step is not retried until a person answers" in err
    assert study_main([
        "ack-welfare", "--study-dir", str(study_dir), "--step", "branch/1", "--decision", "continue",
    ]) == 0


def test_stop_on_a_failed_step_ends_its_line_and_is_never_retried(
    tmp_path, known_modules, monkeypatch  # noqa: F811
):
    study_dir, script, _ = _failed_after(tmp_path, monkeypatch, "crossing")
    StudyRunner(study_dir).acknowledge_welfare("branch", 1, "stop")
    with pytest.raises(StudyError, match="stopped after a welfare review"):
        _runner(study_dir, script).run(retry_failed=True)
    # The rest of the study goes on without the stopped line.
    assert _run(_runner(study_dir, script)) == "complete"
    steps = _load_steps(study_dir)
    assert [(s["line"], s["step"]) for s in steps if s["outcome"] == "complete"][-1] == ("accumulate", 1)
    assert not any(s["line"] == "branch" and s["step"] == 1 and s["outcome"] == "complete" for s in steps)


def test_a_record_missing_after_a_crash_is_shown_but_does_not_block_a_retry(
    tmp_path, known_modules, monkeypatch  # noqa: F811
):
    study_dir, script = _study(tmp_path)
    # The first viewing exits 7 before it could write a record.
    monkeypatch.setenv("IGNITION_STANDIN_SCENARIO", "revive_refused")
    failed = _run(_runner(study_dir, script))
    assert failed["outcome"].startswith("failed")
    assert failed["welfare_hold"]["reasons"] == ["missing"]
    status = StudyRunner(study_dir).status()
    assert "Welfare hold: failed branch step 0 (missing)" in status
    assert "a retry is not blocked" in status
    monkeypatch.delenv("IGNITION_STANDIN_SCENARIO")
    assert _run(_runner(study_dir, script), retry=True) == "complete"
