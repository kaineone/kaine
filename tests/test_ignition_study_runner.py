# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import hashlib
import json
import sys
import textwrap
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from kaine.research.ignition_study.plan import init_study, validate_plan
from kaine.research.ignition_study.runner import (
    StudyComplete,
    StudyError,
    StudyHalted,
    StudyLocked,
    StudyRunner,
)

BASE_MODULES = ["soma", "chronos", "topos", "audition", "lingua", "thymos", "hypnos"]
ORDER = [
    "mnemos",
    "phantasia",
    "nous",
    "eidolon",
    "empatheia",
    "vox",
    "praxis",
    "perception",
    "mundus",
]

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

    def write_json(path, data):
        # Atomic, as the real cycle and control CLI write these files: a
        # reader polling the file never sees it empty or half-written.
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, path)

    def write_request(state_dir, reason, stop):
        req_id = secrets.token_hex(16)
        req = {"request_id": req_id, "reason": reason, "stop": stop, "requested_at": utc_iso()}
        write_json(state_dir / "preserve_request.json", req)
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
                    write_json(state_dir / "preserve_result.json", res)
                    (state_dir / "runtime.json").unlink(missing_ok=True)
                    return
            time.sleep(0.05)
        print("Stand-in cycle timed out waiting for preserve request", file=sys.stderr)
        sys.exit(1)

    def maybe_write_manifest(bundle_dir):
        # Unset: a successful preservation's manifest (world model captured).
        manifest = os.environ.get("IGNITION_STANDIN_MANIFEST", "true")
        if manifest == "missing":
            return
        if manifest == "true":
            data = {"world_model_captured": True}
        elif manifest == "false":
            data = {"world_model_captured": False}
        elif manifest == "unreadable":
            (bundle_dir / "manifest.json").write_text("not json")
            return
        else:
            data = {"world_model_captured": False}
        write_json(bundle_dir / "manifest.json", data)

    def cycle(args):
        cwd = Path.cwd()
        if cwd.parent.name == "branch":
            line = "branch"
            study_dir = cwd.parent.parent
        else:
            line = cwd.name
            study_dir = cwd.parent
        state_dir = cwd / "state" / "cycle"
        state_dir.mkdir(parents=True, exist_ok=True)
        backups_dir = study_dir / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        bundle_dir = backups_dir / secrets.token_hex(8)
        bundle_dir.mkdir()
        maybe_write_manifest(bundle_dir)

        env_log = study_dir / "env_log.jsonl"
        with open(env_log, "a") as f:
            print(json.dumps({
                "line": line,
                "k": int(cwd.name) if line == "branch" else None,
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
            if scenario == "missing_preservation" and view_n == 3:
                active_scenario = scenario
            elif scenario != "missing_preservation" and view_n == 1:
                active_scenario = scenario

        if active_scenario == "revive_refused":
            sys.exit(7)

        run_id = secrets.token_hex(8)
        runtime = {
            "pid": os.getpid(),
            "run_id": run_id,
            "developmental_stage": {"stage": "embodied"},
        }
        write_json(state_dir / "runtime.json", runtime)

        if not is_viewing:
            # Born: the stage file names when the birth bloom ends (already
            # over unless IGNITION_STANDIN_BLOOM_SECONDS puts it ahead), or
            # omits the field when IGNITION_STANDIN_BLOOM_SECONDS is "none".
            (study_dir / "embodied_at.txt").write_text(str(time.time()))
            lifecycle_dir = cwd / "state" / "lifecycle"
            lifecycle_dir.mkdir(parents=True, exist_ok=True)
            stage = {"stage": "embodied"}
            bloom = os.environ.get("IGNITION_STANDIN_BLOOM_SECONDS", "0")
            if bloom != "none":
                ends = datetime.fromtimestamp(time.time() + float(bloom), timezone.utc)
                stage["birth_bloom_ends_at"] = ends.isoformat()
            write_json(lifecycle_dir / "stage.json", stage)
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
            write_json(state_dir / "preserve_result.json", res)
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
                    "k": int(cwd.name) if line == "branch" else None,
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
        write_json(state_dir / "preserve_result.json", res)
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
    order: list[str] = ORDER,
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
        "order": order[:viewings],
        "programme": {"manifest": str(manifest), "sha256": sha},
        "redis": {
            "base_url": "redis://127.0.0.1:6479",
            "db": {"gestation": 10, "branch": 11, "repeat": 12, "accumulate": 13},
        },
        "collections": {"gestation": "r_g_", "branch": "r_b_", "repeat": "r_r_", "accumulate": "r_a_"},
        "viewing_budget_seconds": viewing_budget_seconds,
        "gestation_budget_seconds": gestation_budget_seconds,
    }
    study_dir = tmp_path / "study"
    init_study(study_dir, validate_plan(plan))
    return study_dir


def _runner(study_dir: Path, script: Path, *, flush_log: list[str] | None = None, **kwargs) -> StudyRunner:
    if flush_log is None:
        flush_log = []
    defaults = {
        "cycle_command": [sys.executable, str(script), "cycle"],
        "control_command": [sys.executable, str(script), "control"],
        "poll_seconds": 0.05,
        "preserve_wait_seconds": 2.0,
        "birth_bloom_margin_seconds": 0.0,
        "flush_db": lambda url: flush_log.append(url),
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


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _expected_line_dir(study_dir: Path, line: str, k: int) -> Path:
    if line == "branch":
        return study_dir / "branch" / str(k)
    return study_dir / line


def _read_overlay(line_dir: Path) -> dict:
    with open(line_dir / "config" / "kaine.operator.toml", "rb") as f:
        return tomllib.load(f)


def test_dry_run_e2e(tmp_path: Path, known_modules):
    study_dir = _create_study(tmp_path, viewings=2)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    flush_log: list[str] = []
    started_before_flush: list[int] = []
    env_log_path = study_dir / "env_log.jsonl"

    def flush(url: str) -> None:
        # How many children had started when this step's bus was flushed.
        started_before_flush.append(
            len(_load_jsonl(env_log_path)) if env_log_path.exists() else 0
        )
        flush_log.append(url)

    result = _run(_runner(study_dir, script, flush_db=flush))

    steps = _load_steps(study_dir)
    assert len(steps) == 7
    assert result == "complete"

    expected_order = [
        ("gestation", 0),
        ("branch", 0),
        ("repeat", 0),
        ("branch", 1),
        ("accumulate", 1),
        ("branch", 2),
        ("accumulate", 2),
    ]
    for i, (expected_line, expected_step) in enumerate(expected_order):
        assert steps[i]["line"] == expected_line
        assert steps[i]["step"] == expected_step
        assert steps[i]["outcome"] == "complete"

    p0 = steps[0]["bundle"]
    b0 = steps[1]["bundle"]
    a1 = steps[4]["bundle"]

    assert steps[1]["revived_from"] == p0
    assert steps[2]["revived_from"] == p0
    assert steps[3]["revived_from"] == p0
    assert steps[4]["revived_from"] == b0
    assert steps[5]["revived_from"] == p0
    assert steps[6]["revived_from"] == a1

    base = set(BASE_MODULES)
    assert set(steps[0]["modules"]) == base
    assert set(steps[1]["modules"]) == base
    assert set(steps[2]["modules"]) == base
    assert set(steps[3]["modules"]) == base | {ORDER[0]}
    assert set(steps[4]["modules"]) == base | {ORDER[0]}
    assert set(steps[5]["modules"]) == base | {ORDER[0], ORDER[1]}
    assert set(steps[6]["modules"]) == base | {ORDER[0], ORDER[1]}

    env_logs = [
        json.loads(line)
        for line in (study_dir / "env_log.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert all(e["research_mode"] == "1" for e in env_logs)
    by_line = {e["line"]: e for e in env_logs}
    assert by_line["gestation"]["redis_url"].endswith("/10")
    assert by_line["branch"]["redis_url"].endswith("/11")
    assert by_line["repeat"]["redis_url"].endswith("/12")
    assert by_line["accumulate"]["redis_url"].endswith("/13")
    assert by_line["branch"]["models_dir"] == str(
        (tmp_path / "repo" / "state" / "models").resolve()
    )

    assert all("overlay_sha256" in s and "run_id" in s for s in steps)
    repo_config = tmp_path / "repo" / "config"
    for s in steps:
        expected_dir = _expected_line_dir(study_dir, s["line"], s["step"])
        assert s["ignition_log_dir"] == str(expected_dir / "data" / "ignition")
        overlay = _read_overlay(expected_dir)
        assert overlay["ignition_log"]["directory"] == "data/ignition"
        assert (expected_dir / "config" / "kaine.toml").resolve() == (
            repo_config / "kaine.toml"
        ).resolve()
        assert (expected_dir / "config" / "profiles").is_symlink()
    # Every child ran in its step's own working directory.
    assert [(e["line"], e["k"]) for e in env_logs] == [
        ("gestation", None),
        ("branch", 0),
        ("repeat", None),
        ("branch", 1),
        ("accumulate", None),
        ("branch", 2),
        ("accumulate", None),
    ]
    # The seed is born automatically; the being in the seed never waits on
    # an operator acknowledgement.
    seed_overlay = _read_overlay(study_dir / "gestation")
    assert seed_overlay["developmental_stage"]["require_operator_ack_for_birth"] is False
    # Phantasia's world model is checked wherever it is enabled.
    for s in steps:
        if "phantasia" in s["modules"]:
            assert s["world_model_captured"] is True
        else:
            assert s["world_model_captured"] is None

    expected_prefixes = [
        ("gestation", 0, "r_g_"),
        ("branch", 0, "r_b_0_"),
        ("repeat", 0, "r_r_"),
        ("branch", 1, "r_b_1_"),
        ("accumulate", 1, "r_a_"),
        ("branch", 2, "r_b_2_"),
        ("accumulate", 2, "r_a_"),
    ]
    for line, k, expected_prefix in expected_prefixes:
        ld = _expected_line_dir(study_dir, line, k)
        overlay = _read_overlay(ld)
        assert overlay["mnemos"]["collection_prefix"] == expected_prefix
        assert overlay["empatheia"]["collection"] == expected_prefix

    # One flush per step, on that step's own database, before its child
    # started, with the same authenticated URL the child was given.
    assert len(flush_log) == 7
    assert [urlsplit(url).path for url in flush_log] == [
        "/10", "/11", "/12", "/11", "/13", "/11", "/13",
    ]
    assert flush_log == [e["redis_url"] for e in env_logs]
    assert started_before_flush == list(range(7))

    revived = [
        json.loads(line)
        for line in (study_dir / "revived_from_log.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert len(revived) == 6
    assert revived[0] == {"line": "branch", "k": 0, "revived_from": p0, "bundle": steps[1]["bundle"]}
    assert revived[1] == {"line": "repeat", "k": None, "revived_from": p0, "bundle": steps[2]["bundle"]}
    assert revived[2] == {"line": "branch", "k": 1, "revived_from": p0, "bundle": steps[3]["bundle"]}
    assert revived[3] == {"line": "accumulate", "k": None, "revived_from": b0, "bundle": steps[4]["bundle"]}
    assert revived[4] == {"line": "branch", "k": 2, "revived_from": p0, "bundle": steps[5]["bundle"]}
    assert revived[5] == {"line": "accumulate", "k": None, "revived_from": a1, "bundle": steps[6]["bundle"]}

    _all_bundles_exist(steps)


def test_resume_skips_completed_steps(tmp_path: Path, known_modules):
    study_dir = _create_study(tmp_path, viewings=2)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)

    p0_bundle = str(study_dir / "backups" / "p0")
    Path(p0_bundle).mkdir(parents=True)
    b0_bundle = str(study_dir / "backups" / "b0")
    Path(b0_bundle).mkdir(parents=True)

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
            "ignition_log_dir": str(study_dir / "gestation"),
            "overlay_sha256": "x",
            "outcome": "complete",
        },
        {
            "line": "branch",
            "step": 0,
            "modules": BASE_MODULES,
            "started_at": "t2",
            "ended_at": "t3",
            "exit_code": 0,
            "revived_from": p0_bundle,
            "preservation_id": "b0",
            "bundle": b0_bundle,
            "run_id": "r1",
            "ignition_log_dir": str(study_dir / "branch" / "0"),
            "overlay_sha256": "y",
            "outcome": "complete",
        },
    ]
    with open(study_dir / "steps.jsonl", "a") as f:
        for r in records:
            print(json.dumps(r), file=f)

    flush_log: list[str] = []
    assert _run(_runner(study_dir, script, flush_log=flush_log)) == "complete"
    steps = _load_steps(study_dir)
    assert len(steps) == 7
    # The completed seed and branch 0 are not run again; the resume starts at
    # the repeat, the first incomplete step, and flushes only the steps it runs.
    env_logs = _load_jsonl(study_dir / "env_log.jsonl")
    assert [(e["line"], e["k"]) for e in env_logs] == [
        ("repeat", None),
        ("branch", 1),
        ("accumulate", None),
        ("branch", 2),
        ("accumulate", None),
    ]
    assert [urlsplit(url).path for url in flush_log] == ["/12", "/11", "/13", "/11", "/13"]
    assert steps[0]["line"] == "gestation"
    assert steps[1]["line"] == "branch" and steps[1]["step"] == 0
    assert steps[2]["line"] == "repeat" and steps[2]["revived_from"] == p0_bundle
    assert steps[3]["line"] == "branch" and steps[3]["step"] == 1 and steps[3]["revived_from"] == p0_bundle
    assert steps[4]["line"] == "accumulate" and steps[4]["step"] == 1 and steps[4]["revived_from"] == b0_bundle
    assert steps[5]["line"] == "branch" and steps[5]["step"] == 2 and steps[5]["revived_from"] == p0_bundle
    assert steps[6]["line"] == "accumulate" and steps[6]["step"] == 2
    assert steps[6]["revived_from"] == steps[4]["bundle"]

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
    assert steps[1]["line"] == "branch" and steps[1]["step"] == 0
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
    assert steps[1]["line"] == "branch" and steps[1]["step"] == 0
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
    assert steps[1]["line"] == "branch" and steps[1]["step"] == 0
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
    assert len(steps) == 8

    assert steps[0]["outcome"] == "complete"
    assert steps[1]["line"] == "branch" and steps[1]["step"] == 0
    assert steps[1]["outcome"] == "failed:exit:7"

    retry = steps[2]
    assert retry["line"] == "branch" and retry["step"] == 0
    assert retry["outcome"] == "complete"
    assert retry["revived_from"] == steps[1]["revived_from"]
    assert retry["bundle"] != steps[1]["bundle"]

    assert steps[3]["line"] == "repeat"
    assert steps[4]["line"] == "branch" and steps[4]["step"] == 1
    assert steps[5]["line"] == "accumulate" and steps[5]["step"] == 1
    assert steps[6]["line"] == "branch" and steps[6]["step"] == 2
    assert steps[7]["line"] == "accumulate" and steps[7]["step"] == 2
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
    assert steps[1]["outcome"] == "complete" and steps[1]["line"] == "branch" and steps[1]["step"] == 0
    assert steps[2]["outcome"] == "complete" and steps[2]["line"] == "repeat" and steps[2]["step"] == 0
    assert steps[3]["line"] == "branch" and steps[3]["step"] == 1
    assert steps[3]["outcome"] == "failed:missing_preservation"
    assert result["outcome"] == "failed:missing_preservation"

    _all_bundles_exist(steps)


def test_stale_request_pair_not_complete(tmp_path: Path, known_modules):
    study_dir = _create_study(tmp_path, viewings=1)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    runner = _runner(study_dir, script)

    line_dir = study_dir / "branch" / "0"
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


def test_phantasia_world_model_true(tmp_path: Path, known_modules, monkeypatch):
    study_dir = _create_study(tmp_path, viewings=2, order=["phantasia"])
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    monkeypatch.setenv("IGNITION_STANDIN_MANIFEST", "true")

    result = _run(_runner(study_dir, script))
    steps = _load_steps(study_dir)

    assert result == "complete"
    assert len(steps) == 5

    phantasia_steps = [s for s in steps if "phantasia" in s["modules"]]
    assert len(phantasia_steps) == 2
    assert all(s["world_model_captured"] is True for s in phantasia_steps)
    for s in steps:
        if "phantasia" not in s["modules"]:
            assert s["world_model_captured"] is None

    _all_bundles_exist(steps)


def test_phantasia_world_model_false(tmp_path: Path, known_modules, monkeypatch):
    study_dir = _create_study(tmp_path, viewings=2, order=["phantasia"])
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    monkeypatch.setenv("IGNITION_STANDIN_MANIFEST", "false")

    result = _run(_runner(study_dir, script))
    steps = _load_steps(study_dir)

    assert isinstance(result, dict)
    assert result["outcome"] == "failed:world_model_not_captured"
    assert len(steps) == 4

    phantasia_step = steps[3]
    assert phantasia_step["line"] == "branch" and phantasia_step["step"] == 1
    assert "phantasia" in phantasia_step["modules"]
    assert phantasia_step["outcome"] == "failed:world_model_not_captured"
    assert phantasia_step["world_model_captured"] is False

    _all_bundles_exist(steps)


def test_phantasia_manifest_missing(tmp_path: Path, known_modules, monkeypatch):
    study_dir = _create_study(tmp_path, viewings=2, order=["phantasia"])
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    monkeypatch.setenv("IGNITION_STANDIN_MANIFEST", "missing")

    result = _run(_runner(study_dir, script))
    steps = _load_steps(study_dir)

    assert isinstance(result, dict)
    assert result["outcome"] == "failed:manifest_unreadable"
    assert len(steps) == 4

    phantasia_step = steps[3]
    assert phantasia_step["line"] == "branch" and phantasia_step["step"] == 1
    assert "phantasia" in phantasia_step["modules"]
    assert phantasia_step["outcome"] == "failed:manifest_unreadable"
    assert phantasia_step["world_model_captured"] is False

    _all_bundles_exist(steps)


def test_no_phantasia_completes_without_manifest(
    tmp_path: Path, known_modules, monkeypatch
):
    study_dir = _create_study(tmp_path, viewings=2, order=["mnemos", "nous"])
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    monkeypatch.setenv("IGNITION_STANDIN_MANIFEST", "missing")

    result = _run(_runner(study_dir, script))
    steps = _load_steps(study_dir)

    assert result == "complete"
    assert len(steps) == 7
    assert all(s["world_model_captured"] is None for s in steps)

    _all_bundles_exist(steps)


@pytest.mark.parametrize(
    "text, expected",
    [
        ('{"world_model_captured": true}', (None, True)),
        ('{"world_model_captured": false}', ("failed:world_model_not_captured", False)),
        ('{"world_model_captured": "yes"}', ("failed:world_model_not_captured", False)),
        ("{}", ("failed:world_model_not_captured", False)),
        ("not json", ("failed:manifest_unreadable", False)),
        ("[true]", ("failed:manifest_unreadable", False)),
    ],
)
def test_check_phantasia_manifest(tmp_path: Path, text: str, expected):
    from kaine.research.ignition_study.runner import _check_phantasia_manifest

    (tmp_path / "manifest.json").write_text(text)
    assert _check_phantasia_manifest(str(tmp_path)) == expected


def _birth_request_time(study_dir: Path) -> float:
    from datetime import datetime

    req = json.loads(
        (study_dir / "gestation" / "state" / "cycle" / "preserve_request.json").read_text()
    )
    assert req["reason"] == "birth"
    return datetime.fromisoformat(req["requested_at"]).timestamp()


def test_birth_preservation_waits_for_the_bloom_end(tmp_path: Path, known_modules, monkeypatch):
    from datetime import datetime

    study_dir = _create_study(tmp_path, viewings=1)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    monkeypatch.setenv("IGNITION_STANDIN_BLOOM_SECONDS", "0.8")
    # A long fallback: only the stage file's bloom end can release the request.
    assert _run(_runner(study_dir, script, birth_bloom_margin_seconds=60.0)) == "complete"

    stage = json.loads(
        (study_dir / "gestation" / "state" / "lifecycle" / "stage.json").read_text()
    )
    bloom_end = datetime.fromisoformat(stage["birth_bloom_ends_at"]).timestamp()
    assert _birth_request_time(study_dir) >= bloom_end
    assert _load_steps(study_dir)[0]["outcome"] == "complete"


def test_birth_preservation_waits_the_fallback_without_a_bloom_end(
    tmp_path: Path, known_modules, monkeypatch
):
    study_dir = _create_study(tmp_path, viewings=1)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    monkeypatch.setenv("IGNITION_STANDIN_BLOOM_SECONDS", "none")
    # The child's own configured bloom length, plus the margin.
    with open(tmp_path / "repo" / "config" / "kaine.toml", "a") as fh:
        fh.write("[perception_feed.womb]\nbirth_transition_seconds = 0.4\n")
    assert _run(_runner(study_dir, script, birth_bloom_margin_seconds=0.3)) == "complete"

    stage = json.loads(
        (study_dir / "gestation" / "state" / "lifecycle" / "stage.json").read_text()
    )
    assert "birth_bloom_ends_at" not in stage
    embodied_at = float((study_dir / "embodied_at.txt").read_text())
    assert _birth_request_time(study_dir) - embodied_at >= 0.4 + 0.3


def test_runner_refuses_the_operator_bus_database(tmp_path: Path, known_modules, monkeypatch):
    study_dir = _create_study(tmp_path, viewings=1)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)

    # The operator's own configured bus database.
    operator = tmp_path / "repo" / "config" / "kaine.operator.toml"
    operator.write_text("[redis]\ndb = 11\n")
    with pytest.raises(StudyError, match="operator"):
        _runner(study_dir, script)
    operator.unlink()

    # The bus the runner's own environment points at.
    monkeypatch.setenv("KAINE_REDIS_URL", "redis://:pw@127.0.0.1:6479/12")
    with pytest.raises(StudyError, match="operator") as exc_info:
        _runner(study_dir, script)
    assert "pw" not in str(exc_info.value)
    monkeypatch.delenv("KAINE_REDIS_URL")

    # A hand-edited plan naming database 0, the operator's live bus.
    study_path = study_dir / "study.json"
    plan = json.loads(study_path.read_text())
    plan["redis"]["db"]["repeat"] = 0
    study_path.write_text(json.dumps(plan))
    flush_log: list[str] = []
    with pytest.raises(StudyError, match="1..15"):
        _runner(study_dir, script, flush_log=flush_log).run()
    assert flush_log == []
    assert not (study_dir / "steps.jsonl").exists()


def test_flush_failure_stops_before_the_step(tmp_path: Path, known_modules, monkeypatch):
    password = "flush-secret-pw"
    monkeypatch.setenv("KAINE_REDIS_PASSWORD", password)
    study_dir = _create_study(tmp_path, viewings=1)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)

    def failing_flush(url: str) -> None:
        raise ConnectionError(f"cannot reach {url}")

    with pytest.raises(StudyError, match="bus database 10") as exc_info:
        _runner(study_dir, script, flush_db=failing_flush).run()
    assert password not in str(exc_info.value)
    assert not (study_dir / "env_log.jsonl").exists()
    assert not (study_dir / "steps.jsonl").exists()


# --------------------------------------------------------------------------- #
# The operator's bus database, as the bus itself resolves it
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "files, env_url",
    [
        # secrets.toml [redis].url, which load_bus_config uses as the bus URL.
        ({"secrets.toml": '[redis]\nurl = "redis://:sekrit@127.0.0.1:6479/11"\n'}, None),
        # A string [redis].db, which load_bus_config int()s.
        ({"kaine.operator.toml": '[redis]\ndb = "12"\n'}, None),
        # ?db= in the URL, which redis-py honours over the path.
        ({}, "redis://:sekrit@127.0.0.1:6479/0?db=13"),
    ],
)
def test_runner_refuses_the_operator_database_as_the_bus_resolves_it(
    tmp_path: Path, known_modules, monkeypatch, files, env_url
):
    study_dir = _create_study(tmp_path, viewings=1)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    cfg = tmp_path / "repo" / "config"
    for name, text in files.items():
        (cfg / name).write_text(text)
        (cfg / name).chmod(0o600)
    if env_url:
        monkeypatch.setenv("KAINE_REDIS_URL", env_url)
    with pytest.raises(StudyError, match="operator") as exc_info:
        _runner(study_dir, script)
    assert "sekrit" not in str(exc_info.value)


@pytest.mark.parametrize(
    "files, env_url",
    [
        ({"kaine.operator.toml": "[redis\ndb = 3\n"}, None),
        ({"kaine.operator.toml": '[redis]\ndb = "eleven"\n'}, None),
        ({"secrets.toml": '[redis]\nurl = "http://:sekrit@127.0.0.1:6479/11"\n'}, None),
        ({}, "redis://:sekrit@127.0.0.1:6479/0?db=twelve"),
    ],
)
def test_runner_refuses_when_the_operator_database_is_unknown(
    tmp_path: Path, known_modules, monkeypatch, files, env_url
):
    study_dir = _create_study(tmp_path, viewings=1)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    cfg = tmp_path / "repo" / "config"
    for name, text in files.items():
        (cfg / name).write_text(text)
        (cfg / name).chmod(0o600)
    if env_url:
        monkeypatch.setenv("KAINE_REDIS_URL", env_url)
    with pytest.raises(StudyError, match="cannot determine the operator's bus database") as exc_info:
        _runner(study_dir, script)
    assert "sekrit" not in str(exc_info.value)


def test_operator_database_is_checked_again_before_every_flush(
    tmp_path: Path, known_modules
):
    study_dir = _create_study(tmp_path, viewings=1)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    operator = tmp_path / "repo" / "config" / "kaine.operator.toml"
    flush_log: list[str] = []

    def flush(url: str) -> None:
        flush_log.append(url)
        # While the seed gestates, the operator moves their bus to database 11.
        operator.write_text("[redis]\ndb = 11\n")

    with pytest.raises(StudyError, match="operator"):
        _runner(study_dir, script, flush_db=flush).run()
    # The seed ran on database 10; branch 0 (database 11) never flushed or ran.
    assert [urlsplit(u).path for u in flush_log] == ["/10"]
    assert [(e["line"], e["k"]) for e in _load_jsonl(study_dir / "env_log.jsonl")] == [
        ("gestation", None)
    ]
    assert [(s["line"], s["outcome"]) for s in _load_steps(study_dir)] == [
        ("gestation", "complete")
    ]


# --------------------------------------------------------------------------- #
# A cycle left running is never flushed under or doubled
# --------------------------------------------------------------------------- #


def test_failed_timeout_preservation_records_a_critical_step(
    tmp_path: Path, known_modules
):
    import subprocess
    import time

    from kaine.research.ignition_study.runner import CHILD_FILE, StudyCritical

    # A budget no real start-up approaches: only the first run's programme
    # clock (below) exhausts it, so the retry never times out on a slow host.
    budget = 30.0
    study_dir = _create_study(
        tmp_path, viewings=1, gestation_budget_seconds=budget, viewing_budget_seconds=budget
    )
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    procs: list[subprocess.Popen] = []

    # The first run's programme clock stands still until the stand-in seed is
    # up (its stage file is its last write before it waits for the birth
    # request), then jumps past the budget: the timeout fires on a running
    # seed however long the child took to start.
    stage_file = study_dir / "gestation" / "state" / "lifecycle" / "stage.json"
    programme_time = [0.0]

    def first_run_sleep(_seconds: float) -> None:
        deadline = time.monotonic() + 60.0
        while not stage_file.exists():
            if time.monotonic() > deadline:
                raise AssertionError("the stand-in seed never started")
            time.sleep(0.01)
        programme_time[0] = budget + 1.0

    def popen(*args, **kwargs):
        proc = subprocess.Popen(*args, **kwargs)
        procs.append(proc)
        return proc

    def alive(pid: int) -> bool:
        return any(p.pid == pid and p.poll() is None for p in procs)

    # The control CLI fails, so neither the birth nor the timeout preservation
    # succeeds and the stand-in seed keeps running.
    failing_control = [sys.executable, "-c", "raise SystemExit(3)"]
    try:
        with pytest.raises(StudyCritical, match="still running"):
            _runner(
                study_dir,
                script,
                control_command=failing_control,
                popen=popen,
                cycle_alive=alive,
                clock=lambda: programme_time[0],
                sleep=first_run_sleep,
            ).run()
        assert len(procs) == 1 and procs[0].poll() is None
        steps = _load_steps(study_dir)
        assert len(steps) == 1
        assert steps[0]["line"] == "gestation" and steps[0]["step"] == 0
        assert steps[0]["outcome"] == "failed:critical"
        assert steps[0]["pid"] == procs[0].pid
        marker = json.loads((study_dir / "gestation" / CHILD_FILE).read_text())
        assert marker["pid"] == procs[0].pid

        # The study halts on the critical step...
        flush_log: list[str] = []
        halted = _run(_runner(study_dir, script, flush_log=flush_log, cycle_alive=alive))
        assert halted["outcome"] == "failed:critical"
        # ...and a retry refuses while the seed is still running: nothing is
        # flushed and no second cycle starts in the same state directory.
        with pytest.raises(StudyError, match=f"pid {procs[0].pid}"):
            _runner(
                study_dir, script, flush_log=flush_log, popen=popen, cycle_alive=alive
            ).run(retry_failed=True)
        assert flush_log == []
        assert len(procs) == 1
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
            p.wait()

    # Once the operator has stopped it, the retry runs.  The control CLI waits
    # long enough for a slowly starting seed to answer the birth request.
    retry = _runner(study_dir, script, cycle_alive=alive, preserve_wait_seconds=budget)
    assert _run(retry, retry=True) == "complete"
    assert [s["outcome"] for s in _load_steps(study_dir)] == [
        "failed:critical", "complete", "complete", "complete", "complete", "complete",
    ]


GESTATING_SCRIPT = textwrap.dedent(
    '''\
    import sys
    import time
    from pathlib import Path

    # A seed still gestating: it writes nothing and waits to be released.
    release = Path(sys.argv[1])
    deadline = time.monotonic() + 60
    while not release.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    '''
)


@pytest.mark.parametrize("foreign", ["before_spawn", "after_spawn", "reused_pid"])
def test_an_earlier_childs_runtime_never_triggers_the_birth_preservation(
    tmp_path: Path, known_modules, foreign: str
):
    """runtime.json saying "embodied" that the child this attempt started did
    not write never preserves that child: not one left by an earlier child
    (a retry), not one naming another pid that lands while it gestates, and
    not an earlier child's record whose pid the new child happens to reuse."""
    import subprocess

    study_dir = _create_study(tmp_path, viewings=1, gestation_budget_seconds=3600.0)
    gestating = tmp_path / "gestating.py"
    gestating.write_text(GESTATING_SCRIPT)
    release = tmp_path / "release"
    control_log = tmp_path / "control_calls.txt"
    control = [
        sys.executable,
        "-c",
        f"open({str(control_log)!r}, 'a').write('called\\n'); raise SystemExit(3)",
    ]

    line_dir = study_dir / "gestation"
    runtime_path = line_dir / "state" / "cycle" / "runtime.json"
    runtime_path.parent.mkdir(parents=True)
    stage_path = line_dir / "state" / "lifecycle" / "stage.json"
    stage_path.parent.mkdir(parents=True)
    # The earlier child was born and its bloom is long over.
    stage_path.write_text(
        json.dumps({"stage": "embodied", "birth_bloom_ends_at": "2000-01-01T00:00:00+00:00"})
    )
    earlier_pid = 4_000_000
    earlier = {
        "pid": earlier_pid,
        "run_id": "earlier-run",
        "developmental_stage": {"stage": "embodied"},
    }
    earlier_text = json.dumps(earlier)
    if foreign in ("before_spawn", "reused_pid"):
        runtime_path.write_text(earlier_text)

    class _ReusedPid:
        """The new child, reported under the earlier child's pid."""

        def __init__(self, proc: subprocess.Popen) -> None:
            self._proc = proc
            self.pid = earlier_pid

        def poll(self):  # noqa: ANN201
            return self._proc.poll()

    procs: list[subprocess.Popen] = []

    def popen(*args, **kwargs):
        proc = subprocess.Popen(*args, **kwargs)
        procs.append(proc)
        if foreign == "after_spawn":
            runtime_path.write_text(earlier_text)
        if foreign == "reused_pid":
            return _ReusedPid(proc)
        return proc

    # Programme time moves one poll per sleep; the seed is released only after
    # the runner has read runtime.json on several polls while it gestates.
    programme_time = [0.0]
    polls = [0]

    def sleep(seconds: float) -> None:
        programme_time[0] += seconds
        polls[0] += 1
        if polls[0] == 5:
            release.touch()

    try:
        with pytest.raises(StudyHalted) as exc_info:
            _runner(
                study_dir,
                gestating,
                cycle_command=[sys.executable, str(gestating), str(release)],
                control_command=control,
                popen=popen,
                cycle_alive=lambda pid: False,
                clock=lambda: programme_time[0],
                sleep=sleep,
            ).run()
    finally:
        release.touch()
        for p in procs:
            if p.poll() is None:
                p.kill()
            p.wait()

    assert polls[0] >= 5
    assert not control_log.exists(), "a birth preservation was requested"
    record = exc_info.value.record
    assert record["line"] == "gestation"
    assert record["outcome"] == "failed:missing_preservation"
    assert record["run_id"] is None
    # The earlier child's runtime metadata is left in place, never deleted.
    assert runtime_path.read_text() == earlier_text


@pytest.mark.parametrize("where", ["gestation", "branch/0"])
@pytest.mark.parametrize("record", ["child", "runtime"])
def test_resume_refuses_while_a_started_cycle_is_alive(
    tmp_path: Path, known_modules, where: str, record: str
):
    from kaine.research.ignition_study.runner import CHILD_FILE

    study_dir = _create_study(tmp_path, viewings=1)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    # A killed runner left its child running: the runner's own record of the
    # child, or the cycle's runtime.json, names its pid.
    step_dir = study_dir / where
    if record == "child":
        path = step_dir / CHILD_FILE
    else:
        path = step_dir / "state" / "cycle" / "runtime.json"
        path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"pid": 4242}))
    checked: list[int] = []

    def alive(pid: int) -> bool:
        checked.append(pid)
        return pid == 4242

    flush_log: list[str] = []
    with pytest.raises(StudyError, match="pid 4242"):
        _runner(study_dir, script, flush_log=flush_log, cycle_alive=alive).run()
    assert 4242 in checked
    assert flush_log == []
    assert not (study_dir / "env_log.jsonl").exists()
    assert not (study_dir / "steps.jsonl").exists()

    # The same pid, no longer a cycle, does not block the study.
    assert _run(_runner(study_dir, script, cycle_alive=lambda pid: False)) == "complete"


def test_cycle_process_alive_checks_the_command_line():
    import subprocess

    from kaine.research.ignition_study.runner import _cycle_process_alive

    sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
    cycle = subprocess.Popen([*sleeper, "kaine.cycle"])
    other = subprocess.Popen(sleeper)
    try:
        assert _cycle_process_alive(cycle.pid) is True
        # A live pid that is not a cycle is not one.
        assert _cycle_process_alive(other.pid) is False
    finally:
        for p in (cycle, other):
            p.kill()
            p.wait()
    assert _cycle_process_alive(cycle.pid) is False


# --------------------------------------------------------------------------- #
# The birth bloom fallback follows the child's configuration
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "womb_toml, expected",
    [
        (None, "default"),
        ("birth_transition_seconds = 12.5\n", 12.5),
        ("birth_transition_seconds = 99.0\n", "max"),
        ('birth_transition_seconds = "soon"\n', "max"),
    ],
)
def test_birth_bloom_fallback_follows_the_child_configuration(
    tmp_path: Path, known_modules, womb_toml, expected
):
    import os

    from kaine.modules.womb_signal import WombParams
    from kaine.research.ignition_study.runner import BIRTH_BLOOM_MAX_SECONDS

    study_dir = _create_study(tmp_path, viewings=1)
    if womb_toml is not None:
        with open(tmp_path / "repo" / "config" / "kaine.toml", "a") as fh:
            fh.write("[perception_feed.womb]\n" + womb_toml)
    runner = _runner(study_dir, tmp_path / "unused.py", birth_bloom_margin_seconds=1.5)
    got = runner._birth_bloom_fallback_seconds(study_dir / "gestation", dict(os.environ))
    if expected == "default":
        assert got == WombParams().birth_transition_seconds + 1.5
    elif expected == "max":
        assert got == BIRTH_BLOOM_MAX_SECONDS + 1.5
    else:
        assert got == expected + 1.5


# --------------------------------------------------------------------------- #
# A study claims each database it flushes
# --------------------------------------------------------------------------- #


class _FakePipeline:
    def __init__(self, client: "_FakeRedis") -> None:
        self.client = client
        self.queued: list[tuple] = []
        self.in_multi = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def watch(self, key: str) -> None:
        self.client.ops.append(("watch", key))

    def get(self, key: str):
        assert not self.in_multi
        self.client.ops.append(("get", key))
        value = self.client.data.get(key)
        return value.encode() if isinstance(value, str) else value

    def multi(self) -> None:
        self.in_multi = True

    def flushdb(self) -> None:
        assert self.in_multi
        self.queued.append(("flushdb",))

    def set(self, key: str, value: str) -> None:
        assert self.in_multi
        self.queued.append(("set", key, value))

    def execute(self) -> None:
        if self.client.watch_error:
            import redis

            raise redis.WatchError("watched key changed")
        for op in self.queued:
            self.client.ops.append(op)
            if op[0] == "flushdb":
                self.client.data.clear()
            else:
                self.client.data[op[1]] = op[2]


class _FakeRedis:
    def __init__(self, data: dict | None = None, watch_error: bool = False) -> None:
        self.data = dict(data or {})
        self.ops: list[tuple] = []
        self.closed = False
        self.watch_error = watch_error

    def pipeline(self, transaction: bool = True) -> _FakePipeline:
        assert transaction
        return _FakePipeline(self)

    def close(self) -> None:
        self.closed = True


def test_default_flush_claims_each_study_database(tmp_path: Path, known_modules):
    from kaine.research.ignition_study.runner import STUDY_OWNER_KEY

    study_dir = _create_study(tmp_path, viewings=1)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    servers = {
        "/10": _FakeRedis({"leftover": "x"}),
        # This study's own claim from an earlier run: flushed again.
        "/11": _FakeRedis({STUDY_OWNER_KEY: "runner-test", "leftover": "y"}),
        "/12": _FakeRedis(),
        "/13": _FakeRedis(),
    }
    assert (
        _run(
            _runner(
                study_dir,
                script,
                flush_db=None,
                redis_client_factory=lambda url: servers[urlsplit(url).path],
            )
        )
        == "complete"
    )
    for fake in servers.values():
        assert fake.data == {STUDY_OWNER_KEY: "runner-test"}
        assert fake.closed
        # Checked, then flushed and re-claimed in one transaction.
        kinds = [op[0] for op in fake.ops]
        assert kinds[:4] == ["watch", "get", "flushdb", "set"]


def test_default_flush_refuses_another_studys_database(tmp_path: Path, known_modules):
    from kaine.research.ignition_study.runner import STUDY_OWNER_KEY, StudyDatabaseClaimed

    study_dir = _create_study(tmp_path, viewings=1)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    other = _FakeRedis({STUDY_OWNER_KEY: "other-study", "their-stream": "data"})
    with pytest.raises(StudyDatabaseClaimed, match="other-study"):
        _runner(
            study_dir,
            script,
            flush_db=None,
            redis_client_factory=lambda url: other,
        ).run()
    assert other.data == {STUDY_OWNER_KEY: "other-study", "their-stream": "data"}
    assert all(op[0] != "flushdb" for op in other.ops)
    assert other.closed
    assert not (study_dir / "env_log.jsonl").exists()
    assert not (study_dir / "steps.jsonl").exists()


def test_default_flush_refuses_a_concurrent_claim():
    from kaine.research.ignition_study.runner import (
        StudyDatabaseClaimed,
        _claim_and_flush_redis_db,
    )

    fake = _FakeRedis({"k": "v"}, watch_error=True)
    with pytest.raises(StudyDatabaseClaimed):
        _claim_and_flush_redis_db("redis://:pw@h:1/10", "s", lambda url: fake)
    assert fake.data == {"k": "v"}
    assert fake.closed


# --------------------------------------------------------------------------- #
# A seed preserved but never recorded is adopted, not gestated again
# --------------------------------------------------------------------------- #


def _write_pair(line_dir: Path, reason: str, bundle: Path) -> None:
    state = line_dir / "state" / "cycle"
    state.mkdir(parents=True, exist_ok=True)
    rid = "b" * 32
    (state / "preserve_request.json").write_text(
        json.dumps({"request_id": rid, "reason": reason, "stop": True, "requested_at": "t0"})
    )
    (state / "preserve_result.json").write_text(
        json.dumps(
            {
                "request_id": rid,
                "ok": True,
                "preservation_id": "p-born",
                "bundle": str(bundle),
                "error": None,
                "finished_at": "t1",
            }
        )
    )


def test_resume_adopts_an_unrecorded_birth_preservation(tmp_path: Path, known_modules):
    study_dir = _create_study(tmp_path, viewings=1)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    seed = study_dir / "backups" / "seed"
    seed.mkdir(parents=True)
    _write_pair(study_dir / "gestation", "birth", seed)

    flush_log: list[str] = []
    assert _run(_runner(study_dir, script, flush_log=flush_log)) == "complete"
    steps = _load_steps(study_dir)
    assert steps[0]["line"] == "gestation" and steps[0]["outcome"] == "complete"
    assert steps[0]["bundle"] == str(seed)
    assert steps[0]["preservation_id"] == "p-born"
    assert steps[0]["adopted"] is True
    # No second gestation: the first child is branch 0, revived from the seed.
    env_logs = _load_jsonl(study_dir / "env_log.jsonl")
    assert env_logs[0]["line"] == "branch"
    assert "/10" not in [urlsplit(u).path for u in flush_log]
    assert all(s["revived_from"] == str(seed) for s in steps[1:4])


def test_resume_gestates_when_the_pair_is_not_a_birth(tmp_path: Path, known_modules):
    study_dir = _create_study(tmp_path, viewings=1)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    old = study_dir / "backups" / "old"
    old.mkdir(parents=True)
    _write_pair(study_dir / "gestation", "timeout", old)

    assert _run(_runner(study_dir, script)) == "complete"
    steps = _load_steps(study_dir)
    assert "adopted" not in steps[0]
    assert steps[0]["bundle"] != str(old)
    assert _load_jsonl(study_dir / "env_log.jsonl")[0]["line"] == "gestation"
