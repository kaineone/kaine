# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Deterministic unit tests for tools/maintainer/agent_batch_runner.py."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_SPEC = importlib.util.spec_from_file_location(
    "agent_batch_runner", REPO_ROOT / "tools" / "maintainer" / "agent_batch_runner.py"
)
agent_batch_runner = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(agent_batch_runner)

A = agent_batch_runner


def _tmp_queue(tmp_path: Path, payload) -> Path:
    path = tmp_path / "queue.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestJobQueueNormalization:
    def test_normalize_job_from_string(self):
        job = A.normalize_job("echo hello", index=3)
        assert job["id"] == "job_3"
        assert job["command"] == "echo hello"
        assert job["brief"] is None
        assert job["allow"] == []
        assert job["apply"] is True
        assert job["retries"] == 0
        assert job["lane"] is None
        assert job["model"] is None

    def test_normalize_job_from_non_dict(self):
        job = A.normalize_job(42, index=1)
        assert job["raw"] == {"value": 42}
        assert job["id"] == "job_1"

    def test_normalize_job_id_aliases(self):
        for key in ("id", "name", "title", "task", "job", "job_id"):
            job = A.normalize_job({key: "alpha"}, index=0)
            assert job["id"] == "alpha", key

    def test_normalize_job_brief_and_allow_aliases(self):
        job = A.normalize_job(
            {
                "brief_path": "brief.md",
                "allowed_paths": "src/app.py",
                "verify_commands": ["pytest"],
                "test_command": "pytest -q",
                "worker_command": "worker.py",
                "working_dir": "/tmp/work",
                "timeout_seconds": 30,
                "max_retries": "2",
                "worker_lane": "5",
                "worker_model": "beam:cloud",
                "environment": {"FOO": "bar", "SKIP": None},
            },
            index=0,
        )
        assert job["brief"] == "brief.md"
        assert job["allow"] == ["src/app.py"]
        assert job["verify"] == ["pytest"]
        assert job["tests"] == "pytest -q"
        assert job["command"] == "worker.py"
        assert job["cwd"] == "/tmp/work"
        assert job["timeout"] == 30
        assert job["retries"] == 2
        assert job["lane"] == 5
        assert job["model"] == "beam:cloud"
        assert job["env"] == {"FOO": "bar"}

    def test_normalize_job_defaults_and_invalid_coercion(self):
        job = A.normalize_job(
            {"apply_output": "yes", "retries": "nope", "lane": "bad"}, index=0
        )
        assert job["apply"] is True
        assert job["retries"] == 0
        assert job["lane"] is None
        # apply flag becomes bool
        job2 = A.normalize_job({"apply": 0}, index=0)
        assert job2["apply"] is False

    def test_load_queue_file_and_string(self, tmp_path):
        payload = {"jobs": [{"command": "echo 1"}]}
        qpath = _tmp_queue(tmp_path, payload)
        assert A.load_queue(qpath) == payload
        assert A.load_queue(str(qpath)) == payload
        assert A.load_queue(json.dumps(payload)) == payload

    def test_normalize_queue_extracts_common_keys(self, tmp_path):
        base_jobs = [{"command": "echo 1"}, {"command": "echo 2"}]
        for key in ("jobs", "queue", "tasks", "items", "work", "commands"):
            meta, jobs = A.normalize_queue({key: base_jobs, "lanes": 2})
            assert meta.get("lanes") == 2
            assert len(jobs) == 2
            assert all(j["command"].startswith("echo") for j in jobs)
        # single job object
        meta, jobs = A.normalize_queue({"job": {"command": "echo solo"}})
        assert len(jobs) == 1
        # bare list
        meta, jobs = A.normalize_queue(base_jobs)
        assert meta == {}
        assert len(jobs) == 2
        # unknown dict becomes one job
        meta, jobs = A.normalize_queue({"command": "echo one"})
        assert len(jobs) == 1

    def test_normalize_queue_loads_path(self, tmp_path):
        payload = {"jobs": [{"id": "j1", "command": "echo 1"}]}
        qpath = _tmp_queue(tmp_path, payload)
        meta, jobs = A.normalize_queue(qpath)
        assert meta == payload  # meta is raw dict? queue load loses? meta=data
        assert jobs[0]["id"] == "j1"


class TestLaneAssignment:
    def test_assign_lanes_never_exceeds_max_concurrency(self):
        jobs = [{"id": f"j{i}", "command": f"echo {i}"} for i in range(12)]
        for requested in (1, 2, 3, 4, 5, 10, 100):
            groups = A.assign_lanes(jobs, lanes=requested)
            assert len(groups) == min(requested, A.MAX_CONCURRENCY) or len(groups) <= max(1, min(requested, A.MAX_CONCURRENCY))
            assert len(groups) <= 4
            assert len(groups) <= A.MAX_CONCURRENCY
            assert sum(len(g) for g in groups) == len(jobs)

    def test_assign_lanes_round_robin_for_unassigned(self):
        jobs = [{"id": f"j{i}", "command": f"echo {i}"} for i in range(4)]
        groups = A.assign_lanes(jobs, lanes=2)
        assert [j["id"] for j in groups[0]] == ["j0", "j2"]
        assert [j["id"] for j in groups[1]] == ["j1", "j3"]
        for g in groups:
            for j in g:
                assert 0 <= j["lane"] < 2

    def test_assign_lanes_explicit_lane_modulo(self):
        jobs = [
            {"id": "a", "lane": 0, "command": "x", "brief": None},
            {"id": "b", "lane": 9, "command": "y", "brief": None},
        ]
        # explicit jobs already normalized shape
        groups = A.assign_lanes(jobs, lanes=3)
        assert groups[0][0]["id"] == "a"
        assert groups[0][1]["id"] == "b"  # 9 % 3 == 0
        assert all(j["lane"] in (0, 1, 2) for g in groups for j in g)

    def test_assign_lanes_invalid_lane_falls_back(self, monkeypatch):
        jobs = [{"id": "a", "lane": "not-an-int", "command": "x"}]
        groups = A.assign_lanes(jobs, lanes=2)
        assert groups[0][0]["id"] == "a"
        assert groups[0][0]["lane"] == 0

    def test_assign_lanes_normalizes_raw_jobs(self):
        groups = A.assign_lanes(["echo 1", "echo 2"], lanes=2)
        assert len(groups) == 2
        assert groups[0][0]["command"] == "echo 1"
        assert groups[1][0]["command"] == "echo 2"


class TestPathSafety:
    def test_sanitize_id_removes_separators_and_traversal(self):
        for value in ("../../etc/passwd", "a/b\\c", ".hidden", "///", "  job name  "):
            result = A.sanitize_id(value)
            assert "/" not in result
            assert "\\" not in result
            assert result == result.strip("._-")
        assert A.sanitize_id("../../etc/passwd") == "etc_passwd"
        assert A.sanitize_id("") == "job"

    def test_sanitize_id_keeps_safe_characters(self):
        assert A.sanitize_id("job-1.2_v3") == "job-1.2_v3"

    def test_job_id_path_used_in_process_job_is_sanitized(self, tmp_path, monkeypatch):
        # patch run_ollama_worker to avoid subprocess execution
        monkeypatch.setattr(A, "run_ollama_worker", lambda *a, **k: {"ok": True, "attempts": 1, "files": []})
        # make boundary commands no-ops by no verify/tests
        job = {"id": "../../escape", "command": "echo hi", "apply": False}
        out_root = tmp_path / "out"
        state = A.process_job(job, 0, out_root, repo=None, worker_script=tmp_path / "worker.py",
                              model="m", max_retries=0, timeout=1, semaphore=__import__("threading").Semaphore(1),
                              defaults={}, default_cwd=None)
        out_dir = Path(state["out_dir"])
        assert out_root in out_dir.parents or out_dir.parent == out_root / "lane_0"
        assert ".." not in str(out_dir.relative_to(out_root))
        assert out_dir.name == "escape"
        assert (out_dir / "job_state.json").exists()


class TestReportGeneration:
    def test_render_report_structure(self):
        summary = {
            "lanes": 2,
            "total_jobs": 2,
            "succeeded": 1,
            "failed": 1,
            "out_root": "/tmp/out",
            "jobs": [
                {
                    "job_id": "job_a",
                    "lane": 0,
                    "status": "ok",
                    "boundaries": {"generation": "passed", "apply": "passed", "verify": "skipped", "test": "passed"},
                    "touched_files": ["a.py", "b.py"],
                },
                {
                    "job_id": "job_b",
                    "lane": 1,
                    "status": "failed",
                    "boundaries": {"generation": "failed", "apply": "failed", "verify": "failed", "test": "skipped"},
                    "touched_files": [],
                },
            ],
        }
        report = A._render_report(summary)
        assert report.startswith("# Agent batch run report")
        assert "- Lanes (global max): 2" in report
        assert "- Total jobs: 2" in report
        assert "- Succeeded: 1" in report
        assert "- Failed: 1" in report
        assert "| Job | Lane | Status | Generation | Apply | Verify | Test | Files |" in report
        assert "| job_a | 0 | ok | passed | passed | skipped | passed | a.py, b.py |" in report
        assert "| job_b | 1 | failed | failed | failed | failed | skipped |  |" in report
        assert "## Integration boundaries" in report
        assert "- job_a: crossed generation, apply, test" in report
        assert "- job_b: crossed none" in report
        assert report.endswith("\n")

    def test_main_writes_report(self, tmp_path, monkeypatch):
        queue = {"jobs": []}
        qpath = _tmp_queue(tmp_path, queue)
        report_path = tmp_path / "report.md"
        # dry run avoids worker execution; still writes report
        rc = A.main([str(qpath), "--dry-run", "--report", str(report_path), "-o", str(tmp_path / "out")])
        assert rc == 0
        assert report_path.exists()
        text = report_path.read_text(encoding="utf-8")
        assert "# Agent batch run report" in text


class TestDryRunSuffixHandling:
    def test_dry_run_writes_dry_run_json_not_run_state(self, tmp_path):
        queue = {"jobs": [{"id": "a", "command": "echo hi"}, {"id": "b", "command": "echo bye"}]}
        qpath = _tmp_queue(tmp_path, queue)
        out = tmp_path / "out"
        summary = A.process_queue(qpath, out_root=out, dry_run=True)
        assert (out / "dry_run.json").exists()
        assert not (out / "run_state.json").exists()
        dry = json.loads((out / "dry_run.json").read_text(encoding="utf-8"))
        assert dry["lanes"] == A.MAX_CONCURRENCY
        assert [j["id"] for j in dry["jobs"]] == ["a", "b"]
        assert all("lane" in j for j in dry["jobs"])
        assert summary == dry

    def test_dry_run_suffix_in_main_default_report(self, tmp_path):
        queue = {"jobs": [{"id": "a", "command": "echo hi"}]}
        qpath = _tmp_queue(tmp_path, queue)
        out = tmp_path / "out"
        report = tmp_path / "report.md"
        rc = A.main([str(qpath), "--dry-run", "--report", str(report), "-o", str(out)])
        assert rc == 0
        assert (out / "dry_run.json").exists()
        assert not (out / "run_state.json").exists()
        assert report.exists()

    def test_non_dry_run_with_no_jobs_writes_run_state(self, tmp_path, monkeypatch):
        # avoid worker process by no jobs
        queue = {"jobs": []}
        qpath = _tmp_queue(tmp_path, queue)
        out = tmp_path / "out"
        summary = A.process_queue(qpath, out_root=out, dry_run=False)
        assert (out / "run_state.json").exists()
        assert not (out / "dry_run.json").exists()
        assert summary["total_jobs"] == 0
        assert summary["succeeded"] == 0
        assert summary["failed"] == 0
