# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from kaine.research.ignition_study.plan import init_study, validate_plan
from kaine.research.ignition_study.runner import StudyHalted, StudyRunner

BASE_MODULES = ["soma", "chronos", "topos", "audition", "lingua", "thymos", "hypnos"]
ORDER = ["mnemos"]


@pytest.fixture
def known_modules(monkeypatch):
    names = BASE_MODULES + [
        "echo",
        "nous",
        "mnemos",
        "eidolon",
        "thymos",
        "praxis",
        "lingua",
        "vox",
        "audition",
        "hypnos",
        "empatheia",
        "phantasia",
        "perception",
        "mundus",
    ]
    monkeypatch.setattr("kaine.boot.known_module_names", lambda: names)
    monkeypatch.setenv("KAINE_REDIS_PASSWORD", "test-redis-pw")
    monkeypatch.delenv("KAINE_REDIS_USERNAME", raising=False)
    monkeypatch.delenv("KAINE_REDIS_URL", raising=False)
    for name in (
        "IGNITION_STANDIN_SCENARIO",
        "IGNITION_STANDIN_MANIFEST",
        "IGNITION_STANDIN_BLOOM_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    return names


def _write_repo(repo_root: Path) -> None:
    cfg = repo_root / "config"
    cfg.mkdir(parents=True)
    (cfg / "profiles").mkdir()
    (cfg / "kaine.toml").write_text(
        "[modules]\n"
        "echo = false\n"
        "soma = false\n"
        "[topos]\n"
        'encoder_local_dir = "state/models"\n'
    )


def _create_study(
    tmp_path: Path,
    viewings: int = 1,
    *,
    gestation_budget_seconds: float = 1000.0,
    viewing_budget_seconds: float = 1000.0,
) -> Path:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    manifest = repo_root / "programme.toml"
    manifest.write_text("[programme]\n")
    sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    plan = {
        "study_id": "viability-test",
        "repo_root": str(repo_root),
        "base_modules": BASE_MODULES,
        "order": ORDER[:viewings],
        "programme": {"manifest": str(manifest), "sha256": sha},
        "redis": {
            "base_url": "redis://127.0.0.1:6479",
            "db": {"gestation": 10, "branch": 11, "repeat": 12, "accumulate": 13},
        },
        "collections": {
            "gestation": "r_g_",
            "branch": "r_b_",
            "repeat": "r_r_",
            "accumulate": "r_a_",
        },
        "viewing_budget_seconds": viewing_budget_seconds,
        "gestation_budget_seconds": gestation_budget_seconds,
    }
    study_dir = tmp_path / "study"
    init_study(study_dir, validate_plan(plan))
    return study_dir


def _runner(
    study_dir: Path, script: Path, wall_clock: Any = None, **kwargs: Any
) -> StudyRunner:
    defaults = {
        "cycle_command": [sys.executable, str(script), "cycle"],
        "control_command": [sys.executable, str(script), "control"],
        "poll_seconds": 0.01,
        "preserve_wait_seconds": 2.0,
        "birth_bloom_margin_seconds": 0.0,
        "flush_db": lambda url: None,
    }
    if wall_clock is not None:
        defaults["wall_clock"] = wall_clock
    defaults.update(kwargs)
    return StudyRunner(study_dir, **defaults)


class _FakeProc:
    def __init__(self, exit_after_polls: int | None = None):
        self.pid = 12345
        self._exit_after_polls = exit_after_polls
        self._poll_count = 0
        self._terminated = False
        self.terminate_calls = 0

    def poll(self) -> int | None:
        if self._terminated:
            return 0
        if self._exit_after_polls is not None:
            self._poll_count += 1
            if self._poll_count >= self._exit_after_polls:
                return 0
        return None

    def terminate(self) -> None:
        self.terminate_calls += 1
        self._terminated = True

    def wait(self, timeout: float | None = None) -> int:
        self._terminated = True
        return 0


def _run_step_capture(
    study_dir: Path,
    runner: StudyRunner,
    step: dict[str, Any],
    line: str,
    k: int,
    modules: list[str],
    overlay_hash: str,
    run_id: str | None,
    monkeypatch,
    *,
    write_viability_after_calls: int | None = None,
    viability_payload: dict[str, Any] | None = None,
    proc_exits_after_polls: int | None = None,
):
    line_dir = (
        study_dir / "branch" / str(k)
        if line == "branch"
        else study_dir / line
    )
    (line_dir / "state" / "lifecycle").mkdir(parents=True, exist_ok=True)
    (line_dir / "marker.txt").write_text("keep")

    proc = _FakeProc(exit_after_polls=proc_exits_after_polls)
    calls = 0

    def fake_sleep(seconds: float) -> None:
        nonlocal calls
        calls += 1
        if write_viability_after_calls is not None and calls == write_viability_after_calls:
            path = line_dir / "state" / "lifecycle" / "gestation_viability.json"
            if viability_payload is not None:
                path.write_text(json.dumps(viability_payload))
            else:
                path.write_text("not json {")

    runner.sleep = fake_sleep
    runner.popen = lambda *args, **kwargs: proc

    def fail_preserve(*args, **kwargs):
        raise AssertionError("_request_preserve must not be called for unviable gestation")

    monkeypatch.setattr(runner, "_request_preserve", fail_preserve)

    try:
        # _run_step takes the step as _next_step returns it.
        record = runner._run_step(
            {"line": line, "k": k, "revived_from": step.get("revived_from"), "is_retry": False}
        )
        return record, proc, line_dir
    except StudyHalted as exc:
        return exc.record, proc, line_dir


def test_gestation_unviable_stops_gracefully(tmp_path: Path, known_modules, monkeypatch):
    # A short budget: if the runner failed to stop the cycle it would reach the
    # timeout path and request a preservation, which fails this test quickly.
    study_dir = _create_study(tmp_path, viewings=1, gestation_budget_seconds=5.0)
    script = tmp_path / "dummy.py"
    script.write_text("")
    runner = _runner(study_dir, script)

    verdict = {
        "verdict": "unviable",
        "rule": "R1",
        "reason": "entrainment collapsed",
        "lived_hours": 0.5,
        "evidence": {"loss": 0.9, "stage": "early"},
    }

    record, proc, line_dir = _run_step_capture(
        study_dir,
        runner,
        step={"kind": "gestation", "modules": BASE_MODULES, "budget_seconds": 1000.0},
        line="gestation",
        k=0,
        modules=BASE_MODULES,
        overlay_hash=hashlib.sha256(b"overlay").hexdigest(),
        run_id="run-unviable-1",
        monkeypatch=monkeypatch,
        write_viability_after_calls=2,
        viability_payload=verdict,
    )

    assert proc.terminate_calls == 1
    assert record["outcome"] == "failed:gestation_unviable"
    assert record["viability"]["rule"] == "R1"

    note = line_dir / "ENDED-NOTE.md"
    assert note.exists()
    note_text = note.read_text()
    assert "R1" in note_text
    assert "entrainment collapsed" in note_text

    assert (line_dir / "marker.txt").exists()


def test_malformed_viability_file_is_ignored(tmp_path: Path, known_modules, monkeypatch):
    study_dir = _create_study(tmp_path, viewings=1, gestation_budget_seconds=1000.0)
    script = tmp_path / "dummy.py"
    script.write_text("")
    runner = _runner(study_dir, script)

    record, proc, line_dir = _run_step_capture(
        study_dir,
        runner,
        step={"kind": "gestation", "modules": BASE_MODULES, "budget_seconds": 1000.0},
        line="gestation",
        k=0,
        modules=BASE_MODULES,
        overlay_hash=hashlib.sha256(b"overlay").hexdigest(),
        run_id="run-malformed-1",
        monkeypatch=monkeypatch,
        write_viability_after_calls=2,
        viability_payload=None,
        proc_exits_after_polls=5,
    )

    assert proc.terminate_calls == 0
    assert record["outcome"] != "failed:gestation_unviable"
    assert not (line_dir / "ENDED-NOTE.md").exists()
    assert (line_dir / "marker.txt").exists()


def test_viability_file_during_viewing_is_ignored(tmp_path: Path, known_modules, monkeypatch):
    study_dir = _create_study(tmp_path, viewings=1, gestation_budget_seconds=1000.0)
    script = tmp_path / "dummy.py"
    script.write_text("")
    runner = _runner(study_dir, script)

    verdict = {
        "verdict": "unviable",
        "rule": "R2",
        "reason": "not relevant",
        "lived_hours": 1.0,
        "evidence": {"x": 1},
    }

    record, proc, line_dir = _run_step_capture(
        study_dir,
        runner,
        step={
            "kind": "viewing",
            "modules": BASE_MODULES,
            "budget_seconds": 1000.0,
            "revived_from": "some-prior-preservation",
        },
        line="branch",
        k=0,
        modules=BASE_MODULES,
        overlay_hash=hashlib.sha256(b"overlay").hexdigest(),
        run_id="run-viewing-1",
        monkeypatch=monkeypatch,
        write_viability_after_calls=1,
        viability_payload=verdict,
        proc_exits_after_polls=5,
    )

    assert proc.terminate_calls == 0
    assert record["outcome"] != "failed:gestation_unviable"
    assert not (line_dir / "ENDED-NOTE.md").exists()
    assert (line_dir / "marker.txt").exists()


def test_verdict_from_an_earlier_attempt_is_ignored(tmp_path: Path, known_modules, monkeypatch):
    """A retried gestation must not be stopped by the previous attempt's verdict."""
    import os
    import time

    study_dir = _create_study(tmp_path, viewings=1, gestation_budget_seconds=1000.0)
    script = tmp_path / "dummy.py"
    script.write_text("")
    runner = _runner(study_dir, script)
    line_dir = study_dir / "gestation"
    stale = line_dir / "state" / "lifecycle" / "gestation_viability.json"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text(json.dumps({"verdict": "unviable", "rule": "R3", "reason": "old", "lived_hours": 60.0, "evidence": {}}))
    past = time.time() - 3600
    os.utime(stale, (past, past))

    record, proc, _ = _run_step_capture(
        study_dir,
        runner,
        step={"kind": "gestation"},
        line="gestation",
        k=0,
        modules=BASE_MODULES,
        overlay_hash=hashlib.sha256(b"overlay").hexdigest(),
        run_id="run-retry-1",
        monkeypatch=monkeypatch,
        proc_exits_after_polls=5,
    )

    assert proc.terminate_calls == 0
    assert record["outcome"] != "failed:gestation_unviable"


def test_verdict_after_birth_is_ignored(
    tmp_path: Path, known_modules, monkeypatch: pytest.MonkeyPatch
) -> None:
    study_dir = _create_study(tmp_path, viewings=1, gestation_budget_seconds=5.0)
    script = tmp_path / "dummy.py"
    script.write_text("")
    runner = _runner(study_dir, script)

    proc = _FakeProc(exit_after_polls=6)
    runner.popen = lambda *args, **kwargs: proc

    monkeypatch.setattr(
        runner,
        "_read_child_runtime",
        lambda *args, **kwargs: {"run_id": "r1", "developmental_stage": {"stage": "embodied"}},
    )
    monkeypatch.setattr(runner, "_birth_bloom_over", lambda *args, **kwargs: True)

    reasons: list[str] = []

    def fake_preserve(*args, **kwargs):
        if len(args) >= 2:
            reasons.append(args[1])
        return (None, None, None, True)

    monkeypatch.setattr(runner, "_request_preserve", fake_preserve)

    line_dir = study_dir / "gestation"
    (line_dir / "state" / "lifecycle").mkdir(parents=True, exist_ok=True)

    calls = 0

    def fake_sleep(seconds: float) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            path = line_dir / "state" / "lifecycle" / "gestation_viability.json"
            path.write_text(
                json.dumps({"verdict": "unviable", "rule": "R3", "reason": "test"})
            )

    runner.sleep = fake_sleep

    try:
        record = runner._run_step(
            {"line": "gestation", "k": 0, "revived_from": None, "is_retry": False}
        )
    except StudyHalted as exc:
        record = exc.record

    assert proc.terminate_calls == 0
    assert "birth" in reasons
    assert record["outcome"] != "failed:gestation_unviable"


def test_failed_terminate_is_retried(
    tmp_path: Path, known_modules, monkeypatch: pytest.MonkeyPatch
) -> None:
    study_dir = _create_study(tmp_path, viewings=1, gestation_budget_seconds=5.0)
    script = tmp_path / "dummy.py"
    script.write_text("")
    runner = _runner(study_dir, script)

    class _FlakyFakeProc(_FakeProc):
        def terminate(self) -> None:
            self.terminate_calls += 1
            if self.terminate_calls == 1:
                raise OSError("busy")
            self.returncode = 0

    monkeypatch.setattr(sys.modules[__name__], "_FakeProc", _FlakyFakeProc)

    verdict = {
        "verdict": "unviable",
        "rule": "R1",
        "reason": "entrainment collapsed",
        "lived_hours": 0.5,
        "evidence": {"loss": 0.9, "stage": "early"},
    }

    record, proc, line_dir = _run_step_capture(
        study_dir,
        runner,
        step={"kind": "gestation", "modules": BASE_MODULES, "budget_seconds": 1000.0},
        line="gestation",
        k=0,
        modules=BASE_MODULES,
        overlay_hash=hashlib.sha256(b"overlay").hexdigest(),
        run_id="run-unviable-retry",
        monkeypatch=monkeypatch,
        write_viability_after_calls=2,
        viability_payload=verdict,
        proc_exits_after_polls=6,
    )

    assert proc.terminate_calls == 2
    assert record["outcome"] == "failed:gestation_unviable"


def test_coarse_mtime_accepted_with_slack(
    tmp_path: Path, known_modules, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A verdict whose real mtime is slightly before step start is accepted.

    On kernels with coarse file timestamps the wall clock can lead the file
    mtime by a tick. The runner tolerates this without accepting stale files.
    """
    study_dir = _create_study(tmp_path, viewings=1, gestation_budget_seconds=5.0)
    script = tmp_path / "dummy.py"
    script.write_text("")
    runner = _runner(
        study_dir, script, wall_clock=lambda: time.time() + 1.0
    )

    class _FlakyFakeProc(_FakeProc):
        def terminate(self) -> None:
            self.terminate_calls += 1
            if self.terminate_calls == 1:
                raise OSError("busy")
            self.returncode = 0

    monkeypatch.setattr(sys.modules[__name__], "_FakeProc", _FlakyFakeProc)

    verdict = {
        "verdict": "unviable",
        "rule": "R1",
        "reason": "entrainment collapsed",
        "lived_hours": 0.5,
        "evidence": {"loss": 0.9, "stage": "early"},
    }

    record, proc, line_dir = _run_step_capture(
        study_dir,
        runner,
        step={"kind": "gestation", "modules": BASE_MODULES, "budget_seconds": 1000.0},
        line="gestation",
        k=0,
        modules=BASE_MODULES,
        overlay_hash=hashlib.sha256(b"overlay").hexdigest(),
        run_id="run-coarse-mtime",
        monkeypatch=monkeypatch,
        write_viability_after_calls=2,
        viability_payload=verdict,
        proc_exits_after_polls=6,
    )

    assert proc.terminate_calls == 2
    assert record["outcome"] == "failed:gestation_unviable"


def test_stale_verdict_rejected(
    tmp_path: Path, known_modules, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A verdict written long before the step started is still treated as stale."""
    study_dir = _create_study(tmp_path, viewings=1, gestation_budget_seconds=5.0)
    script = tmp_path / "dummy.py"
    script.write_text("")
    runner = _runner(
        study_dir, script, wall_clock=lambda: time.time() + 30.0
    )

    verdict = {
        "verdict": "unviable",
        "rule": "R1",
        "reason": "entrainment collapsed",
        "lived_hours": 0.5,
        "evidence": {"loss": 0.9, "stage": "early"},
    }

    record, proc, line_dir = _run_step_capture(
        study_dir,
        runner,
        step={"kind": "gestation", "modules": BASE_MODULES, "budget_seconds": 1000.0},
        line="gestation",
        k=0,
        modules=BASE_MODULES,
        overlay_hash=hashlib.sha256(b"overlay").hexdigest(),
        run_id="run-stale-verdict",
        monkeypatch=monkeypatch,
        write_viability_after_calls=2,
        viability_payload=verdict,
        proc_exits_after_polls=6,
    )

    assert proc.terminate_calls == 0
    assert record["outcome"] != "failed:gestation_unviable"
