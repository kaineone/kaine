# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import hashlib
import json
import sys
import textwrap
from pathlib import Path

import pytest

from kaine.research.ignition_study.plan import init_study, validate_plan
from kaine.research.ignition_study.runner import (
    StudyComplete,
    StudyHalted,
    StudyLocked,
    StudyRunner,
)

BASE_MODULES = ["soma", "chronos", "topos", "audition", "lingua"]
ORDER = ["thymos", "mnemos", "hypnos"]

STANDIN_SCRIPT = textwrap.dedent(
    '''\
    import argparse
    import json
    import os
    import secrets
    import sys
    import time
    from datetime import datetime, timezone
    from pathlib import Path

    def utc_iso():
        return datetime.now(timezone.utc).isoformat()

    def write_request(state_dir, reason, stop):
        req_id = secrets.token_hex(16)
        req = {"request_id": req_id, "reason": reason, "stop": stop, "requested_at": utc_iso()}
        (state_dir / "preserve_request.json").write_text(json.dumps(req))
        return req

    def wait_for_request(state_dir, reason, stop, bundle_dir, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            req_path = state_dir / "preserve_request.json"
            if req_path.exists():
                req = json.loads(req_path.read_text())
                if reason is None or req.get("reason") == reason:
                    res = {
                        "request_id": req["request_id"],
                        "ok": True,
                        "preservation_id": "p-" + secrets.token_hex(4),
                        "bundle": str(bundle_dir),
                        "error": None,
                        "finished_at": utc_iso(),
                    }
                    (state_dir / "preserve_result.json").write_text(json.dumps(res))
                    (state_dir / "runtime.json").unlink(missing_ok=True)
                    return
            time.sleep(0.05)
        print("Stand-in cycle timed out waiting for preserve request", file=sys.stderr)
        sys.exit(1)

    def cycle(args):
        cwd = Path.cwd()
        line = cwd.name
        state_dir = cwd / "state" / "cycle"
        state_dir.mkdir(parents=True, exist_ok=True)
        study_dir = cwd.parent
        backups_dir = study_dir / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        bundle_dir = backups_dir / secrets.token_hex(8)
        bundle_dir.mkdir()

        env_log = study_dir / "env_log.jsonl"
        with open(env_log, "a") as f:
            print(json.dumps({
                "line": line,
                "research_mode": os.environ.get("KAINE_RESEARCH_MODE"),
                "redis_url": os.environ.get("KAINE_REDIS_URL"),
                "models_dir": os.environ.get("KAINE_MODELS_DIR"),
            }), file=f)

        is_viewing = bool(args.revive)
        scenario = os.environ.get("IGNITION_STANDIN_SCENARIO")
        counter_path = study_dir / ".viewing_counter"
        view_n = 0
        if is_viewing:
            try:
                view_n = int(counter_path.read_text())
            except Exception:
                view_n = 0
            view_n += 1
            counter_path.write_text(str(view_n))

        active_scenario = None
        if is_viewing and scenario:
            if scenario == "missing_preservation" and line == "main" and view_n == 3:
                active_scenario = scenario
            elif scenario != "missing_preservation" and view_n == 1:
                active_scenario = scenario

        if active_scenario == "revive_refused":
            sys.exit(7)

        run_id = secrets.token_hex(8)
        stage = "embodied" if is_viewing else "gestation"
        runtime = {
            "pid": os.getpid(),
            "run_id": run_id,
            "developmental_stage": {"stage": stage},
        }
        (state_dir / "runtime.json").write_text(json.dumps(runtime))

        if not is_viewing:
            time.sleep(0.05)
            runtime["developmental_stage"]["stage"] = "embodied"
            (state_dir / "runtime.json").write_text(json.dumps(runtime))
            wait_for_request(state_dir, "birth", True, bundle_dir)
            return

        if active_scenario == "missing_preservation":
            time.sleep(0.1)
            (state_dir / "runtime.json").unlink(missing_ok=True)
            return

        if active_scenario == "preserve_fail":
            req = write_request(state_dir, "programme end", True)
            res = {
                "request_id": req["request_id"],
                "ok": False,
                "preservation_id": "p-fail",
                "bundle": str(bundle_dir),
                "error": "fake failure",
                "finished_at": utc_iso(),
            }
            (state_dir / "preserve_result.json").write_text(json.dumps(res))
            time.sleep(0.1)
            (state_dir / "runtime.json").unlink(missing_ok=True)
            return

        if active_scenario == "timeout":
            wait_for_request(state_dir, None, True, bundle_dir)
            return

        if is_viewing:
            with open(study_dir / "revived_from_log.jsonl", "a") as f:
                print(json.dumps({
                    "line": line,
                    "revived_from": args.revive,
                    "bundle": str(bundle_dir),
                }), file=f)

        req = write_request(state_dir, "programme end", True)
        res = {
            "request_id": req["request_id"],
            "ok": True,
            "preservation_id": "p-" + secrets.token_hex(4),
            "bundle": str(bundle_dir),
            "error": None,
            "finished_at": utc_iso(),
        }
        (state_dir / "preserve_result.json").write_text(json.dumps(res))
        time.sleep(0.1)
        (state_dir / "runtime.json").unlink(missing_ok=True)

    def control(args):
        cwd = Path.cwd()
        state_dir = cwd / "state" / "cycle"
        state_dir.mkdir(parents=True, exist_ok=True)
        req = write_request(state_dir, args.reason, args.stop)
        deadline = time.monotonic() + args.wait
        while time.monotonic() < deadline:
            res_path = state_dir / "preserve_result.json"
            if res_path.exists():
                res = json.loads(res_path.read_text())
                if res.get("request_id") == req["request_id"]:
                    if res.get("ok"):
                        print("Preserved:", res.get("bundle"))
                        return 0
                    print("Preservation failed:", res.get("error"))
                    return 1
            time.sleep(0.05)
        print("Timeout waiting for preservation result")
        return 2

    def main():
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command", required=True)
        cyc = sub.add_parser("cycle")
        cyc.add_argument("--revive")
        ctr = sub.add_parser("control")
        pres = ctr.add_subparsers(dest="ctrl_cmd", required=True)
        p = pres.add_parser("preserve")
        p.add_argument("--reason", default="operator")
        p.add_argument("--stop", action="store_true")
        p.add_argument("--wait", type=float, default=120.0)
        args = parser.parse_args()
        if args.command == "cycle":
            cycle(args)
        elif args.command == "control":
            return control(args)
        return 0

    if __name__ == "__main__":
        raise SystemExit(main())
    '''
)


@pytest.fixture
def known_modules(monkeypatch):
    names = [
        "echo",
        "soma",
        "chronos",
        "topos",
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
    return names


def _write_repo(repo_root: Path) -> None:
    cfg = repo_root / "config"
    cfg.mkdir(parents=True)
    (cfg / "profiles").mkdir()
    (cfg / "kaine.toml").write_text(
        '[modules]\n'
        'echo = false\n'
        'soma = false\n'
        '[topos]\n'
        'encoder_local_dir = "state/models"\n'
    )


def _create_study(
    tmp_path: Path,
    viewings: int = 2,
    *,
    viewing_budget_seconds: float = 5.0,
    gestation_budget_seconds: float = 5.0,
) -> Path:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    manifest = repo_root / "programme.toml"
    manifest.write_text("[programme]\n")
    sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    plan = {
        "study_id": "runner-test",
        "repo_root": str(repo_root),
        "base_modules": BASE_MODULES,
        "order": ORDER,
        "programme": {"manifest": str(manifest), "sha256": sha},
        "redis": {
            "base_url": "redis://127.0.0.1:6479",
            "db": {"gestation": 10, "main": 11, "control": 12},
        },
        "collections": {"gestation": "r_g_", "main": "r_m_", "control": "r_c_"},
        "viewings_per_line": viewings,
        "viewing_budget_seconds": viewing_budget_seconds,
        "gestation_budget_seconds": gestation_budget_seconds,
    }
    study_dir = tmp_path / "study"
    init_study(study_dir, validate_plan(plan))
    return study_dir


def _runner(study_dir: Path, script: Path, **kwargs) -> StudyRunner:
    defaults = {
        "cycle_command": [sys.executable, str(script), "cycle"],
        "control_command": [sys.executable, str(script), "control"],
        "poll_seconds": 0.05,
        "preserve_wait_seconds": 2.0,
    }
    defaults.update(kwargs)
    return StudyRunner(study_dir, **defaults)


def _run(runner: StudyRunner, retry: bool = False):
    try:
        runner.run(retry_failed=retry)
        return "complete"
    except StudyHalted as exc:
        return exc.record
    except StudyComplete:
        return "complete"


def _load_steps(study_dir: Path) -> list[dict]:
    path = study_dir / "steps.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _all_bundles_exist(steps: list[dict]) -> None:
    for rec in steps:
        if rec.get("bundle"):
            assert Path(rec["bundle"]).exists()


def test_dry_run_e2e(tmp_path: Path, known_modules):
    study_dir = _create_study(tmp_path, viewings=2)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    result = _run(_runner(study_dir, script))

    steps = _load_steps(study_dir)
    assert len(steps) == 5
    assert result == "complete"

    assert steps[0]["line"] == "gestation"
    for i, (expected_line, expected_step) in enumerate(
        [("gestation", 0), ("main", 0), ("control", 0), ("main", 1), ("control", 1)]
    ):
        assert steps[i]["line"] == expected_line
        assert steps[i]["step"] == expected_step
        assert steps[i]["outcome"] == "complete"

    p0 = steps[0]["bundle"]
    assert steps[1]["revived_from"] == p0
    assert steps[2]["revived_from"] == p0
    assert steps[3]["revived_from"] == steps[1]["bundle"]
    assert steps[4]["revived_from"] == steps[2]["bundle"]

    base = set(BASE_MODULES)
    assert set(steps[0]["modules"]) == base
    assert set(steps[1]["modules"]) == base
    assert set(steps[2]["modules"]) == base
    assert set(steps[3]["modules"]) == base | {ORDER[0]}
    assert set(steps[4]["modules"]) == base

    env_logs = [
        json.loads(line)
        for line in (study_dir / "env_log.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert all(e["research_mode"] == "1" for e in env_logs)
    by_line = {e["line"]: e for e in env_logs}
    assert by_line["gestation"]["redis_url"].endswith("/10")
    assert by_line["main"]["redis_url"].endswith("/11")
    assert by_line["control"]["redis_url"].endswith("/12")
    assert by_line["main"]["models_dir"] == str(
        (tmp_path / "repo" / "state" / "models").resolve()
    )

    assert all("overlay_sha256" in s and "run_id" in s for s in steps)
    assert all(
        s["ignition_log_dir"] == str(study_dir / s["line"] / "data" / "ignition")
        for s in steps
    )

    revived = [
        json.loads(line)
        for line in (study_dir / "revived_from_log.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert len(revived) == 4
    assert revived[0] == {"line": "main", "revived_from": p0, "bundle": steps[1]["bundle"]}
    assert revived[1] == {"line": "control", "revived_from": p0, "bundle": steps[2]["bundle"]}

    _all_bundles_exist(steps)


def test_resume_skips_completed_steps(tmp_path: Path, known_modules):
    study_dir = _create_study(tmp_path, viewings=2)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)

    p0_bundle = str(study_dir / "backups" / "p0")
    Path(p0_bundle).mkdir(parents=True)
    m0_bundle = str(study_dir / "backups" / "m0")
    Path(m0_bundle).mkdir(parents=True)

    records = [
        {
            "line": "gestation",
            "step": 0,
            "modules": BASE_MODULES,
            "started_at": "t0",
            "ended_at": "t1",
            "exit_code": 0,
            "revived_from": None,
            "preservation_id": "p0",
            "bundle": p0_bundle,
            "run_id": "r0",
            "ignition_log_dir": str(study_dir / "gestation" / "data" / "ignition"),
            "overlay_sha256": "x",
            "outcome": "complete",
        },
        {
            "line": "main",
            "step": 0,
            "modules": BASE_MODULES,
            "started_at": "t2",
            "ended_at": "t3",
            "exit_code": 0,
            "revived_from": p0_bundle,
            "preservation_id": "m0",
            "bundle": m0_bundle,
            "run_id": "r1",
            "ignition_log_dir": str(study_dir / "main" / "data" / "ignition"),
            "overlay_sha256": "y",
            "outcome": "complete",
        },
    ]
    with open(study_dir / "steps.jsonl", "a") as f:
        for r in records:
            print(json.dumps(r), file=f)

    _run(_runner(study_dir, script))
    steps = _load_steps(study_dir)
    assert len(steps) == 5
    assert steps[0]["line"] == "gestation"
    assert steps[1]["line"] == "main"
    assert steps[2]["line"] == "control" and steps[2]["revived_from"] == p0_bundle
    assert steps[3]["line"] == "main" and steps[3]["revived_from"] == m0_bundle
    assert steps[4]["line"] == "control"

    _all_bundles_exist(steps)


def test_halt_revive_refused(tmp_path: Path, known_modules, monkeypatch):
    study_dir = _create_study(tmp_path, viewings=2)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    monkeypatch.setenv("IGNITION_STANDIN_SCENARIO", "revive_refused")

    result = _run(_runner(study_dir, script))
    steps = _load_steps(study_dir)

    assert len(steps) == 2
    assert steps[0]["outcome"] == "complete"
    assert steps[1]["line"] == "main" and steps[1]["step"] == 0
    assert steps[1]["outcome"] == "failed:exit:7"
    assert result["outcome"] == "failed:exit:7"

    _all_bundles_exist(steps)


def test_halt_preserve_failed(tmp_path: Path, known_modules, monkeypatch):
    study_dir = _create_study(tmp_path, viewings=2)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    monkeypatch.setenv("IGNITION_STANDIN_SCENARIO", "preserve_fail")

    result = _run(_runner(study_dir, script))
    steps = _load_steps(study_dir)

    assert len(steps) == 2
    assert steps[0]["outcome"] == "complete"
    assert steps[1]["line"] == "main" and steps[1]["step"] == 0
    assert steps[1]["outcome"] == "failed:preservation"
    assert result["outcome"] == "failed:preservation"

    _all_bundles_exist(steps)


def test_halt_timeout(tmp_path: Path, known_modules, monkeypatch):
    study_dir = _create_study(tmp_path, viewings=2, viewing_budget_seconds=0.3)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    monkeypatch.setenv("IGNITION_STANDIN_SCENARIO", "timeout")

    result = _run(_runner(study_dir, script))
    steps = _load_steps(study_dir)

    assert len(steps) == 2
    assert steps[0]["outcome"] == "complete"
    assert steps[1]["line"] == "main" and steps[1]["step"] == 0
    assert steps[1]["outcome"] == "failed:timeout"
    assert result["outcome"] == "failed:timeout"

    _all_bundles_exist(steps)


def test_retry_failed_repeats_same_start_bundle(tmp_path: Path, known_modules, monkeypatch):
    study_dir = _create_study(tmp_path, viewings=2)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)

    monkeypatch.setenv("IGNITION_STANDIN_SCENARIO", "revive_refused")
    _run(_runner(study_dir, script))

    monkeypatch.delenv("IGNITION_STANDIN_SCENARIO", raising=False)
    result = _run(_runner(study_dir, script), retry=True)

    steps = _load_steps(study_dir)
    assert len(steps) == 6

    assert steps[0]["outcome"] == "complete"
    assert steps[1]["line"] == "main" and steps[1]["step"] == 0
    assert steps[1]["outcome"] == "failed:exit:7"

    retry = steps[2]
    assert retry["line"] == "main" and retry["step"] == 0
    assert retry["outcome"] == "complete"
    assert retry["revived_from"] == steps[1]["revived_from"]
    assert retry["bundle"] != steps[1]["bundle"]

    assert steps[3]["line"] == "control"
    assert steps[4]["line"] == "main"
    assert steps[5]["line"] == "control"
    assert result == "complete"

    _all_bundles_exist(steps)


def test_study_lock_excludes_second_runner(tmp_path: Path, known_modules):
    study_dir = _create_study(tmp_path, viewings=1)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)

    first = _runner(study_dir, script)
    first._acquire_lock()
    try:
        second = _runner(study_dir, script)
        with pytest.raises(StudyLocked):
            second.run()
    finally:
        first._release_lock()


def test_halt_missing_preservation(tmp_path: Path, known_modules, monkeypatch):
    study_dir = _create_study(tmp_path, viewings=2)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    monkeypatch.setenv("IGNITION_STANDIN_SCENARIO", "missing_preservation")

    result = _run(_runner(study_dir, script))
    steps = _load_steps(study_dir)

    assert len(steps) == 4
    assert steps[0]["outcome"] == "complete" and steps[0]["line"] == "gestation"
    assert steps[1]["outcome"] == "complete" and steps[1]["line"] == "main" and steps[1]["step"] == 0
    assert steps[2]["outcome"] == "complete" and steps[2]["line"] == "control" and steps[2]["step"] == 0
    assert steps[3]["line"] == "main" and steps[3]["step"] == 1
    assert steps[3]["outcome"] == "failed:missing_preservation"
    assert result["outcome"] == "failed:missing_preservation"

    _all_bundles_exist(steps)


def test_stale_request_pair_not_complete(tmp_path: Path, known_modules):
    study_dir = _create_study(tmp_path, viewings=1)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    runner = _runner(study_dir, script)

    line_dir = study_dir / "main"
    state_dir = line_dir / "state" / "cycle"
    state_dir.mkdir(parents=True)
    bundle_dir = line_dir / "data" / "backups" / "stale"
    bundle_dir.mkdir(parents=True)

    req = {
        "request_id": "5" * 32,
        "reason": "programme end",
        "stop": True,
        "requested_at": "t0",
    }
    res = {
        "request_id": "5" * 32,
        "ok": True,
        "preservation_id": "p-stale",
        "bundle": str(bundle_dir),
        "error": None,
        "finished_at": "t1",
    }
    (state_dir / "preserve_request.json").write_text(json.dumps(req))
    (state_dir / "preserve_result.json").write_text(json.dumps(res))

    req_obj, res_obj = runner._read_preserve_pair(
        line_dir, prior_request_id="5" * 32
    )
    assert req_obj is not None
    assert res_obj is None

    outcome = runner._determine_outcome(
        "viewing", 0, req_obj, res_obj, False, revived_from="some-other-bundle"
    )
    assert outcome == "failed:missing_preservation"


def test_line_overlay_is_owner_only(tmp_path):
    import stat

    from kaine.research.ignition_study.runner import _write_text_atomic

    target = tmp_path / "kaine.operator.toml"
    _write_text_atomic(target, "[lingua]\napi_key = \"k\"\n")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def _outcome_pair(reason: str, bundle: str):
    from kaine.cycle.preserve_watch import PreserveRequest

    rid = "a" * 32
    req = PreserveRequest(request_id=rid, reason=reason, stop=True, requested_at="t0")
    res = {"request_id": rid, "ok": True, "preservation_id": "p", "bundle": bundle}
    return req, res


def test_outcome_requires_the_step_reason(tmp_path: Path, known_modules):
    study_dir = _create_study(tmp_path, viewings=1)
    runner = _runner(study_dir, tmp_path / "unused.py")
    req, res = _outcome_pair("operator", "/b/new")
    assert (
        runner._determine_outcome("viewing", 0, req, res, False, revived_from="/b/old")
        == "failed:reason:operator"
    )
    req, res = _outcome_pair("programme end", "/b/new")
    assert (
        runner._determine_outcome("gestation", 0, req, res, False, revived_from=None)
        == "failed:reason:programme end"
    )


def test_outcome_refuses_the_start_bundle_as_result(tmp_path: Path, known_modules):
    study_dir = _create_study(tmp_path, viewings=1)
    runner = _runner(study_dir, tmp_path / "unused.py")
    req, res = _outcome_pair("programme end", "/b/same")
    assert (
        runner._determine_outcome("viewing", 0, req, res, False, revived_from="/b/same")
        == "failed:stale_bundle"
    )
    req, res = _outcome_pair("programme end", "/b/new")
    assert (
        runner._determine_outcome("viewing", 0, req, res, False, revived_from="/b/same")
        == "complete"
    )
