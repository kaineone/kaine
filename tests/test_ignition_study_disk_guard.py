# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import hashlib
import textwrap
from pathlib import Path

import pytest

from kaine.research.ignition_study.plan import validate_plan
from kaine.research.ignition_study.runner import StudyCritical, StudyError, StudyRunner
from tests.test_ignition_study_runner import (
    STANDIN_SCRIPT,
    _create_study,
    _load_steps,
    _run,
    _runner,
)

# Re-use the imported stand-in script so the test module loads the same helpers.
_ = STANDIN_SCRIPT


@pytest.fixture
def known_modules(monkeypatch):
    names = [
        "soma",
        "chronos",
        "topos",
        "audition",
        "lingua",
        "thymos",
        "hypnos",
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


def _long_cycle_script() -> str:
    return textwrap.dedent(
        """\
        import argparse
        import sys
        import time

        def main():
            parser = argparse.ArgumentParser()
            parser.add_argument("cmd")
            args = parser.parse_args()
            if args.cmd == "cycle":
                time.sleep(2.0)
            sys.exit(0)

        main()
        """
    )


def _short_cycle_script() -> str:
    return textwrap.dedent(
        """\
        import argparse
        import sys
        import time

        def main():
            parser = argparse.ArgumentParser()
            parser.add_argument("cmd")
            args = parser.parse_args()
            if args.cmd == "cycle":
                time.sleep(0.3)
            sys.exit(0)

        main()
        """
    )


def test_pre_step_disk_refusal(tmp_path, known_modules):
    study_dir = _create_study(tmp_path, viewing_budget_seconds=60.0)
    script = tmp_path / "cycle.py"
    script.write_text(_long_cycle_script())
    flush_log = []

    class LowDisk:
        def __init__(self):
            self.calls = 0

        def __call__(self, path: Path):
            self.calls += 1
            total = 100 * 2**30
            return type("U", (), {"total": total, "free": 10 * 2**30})()

    low = LowDisk()

    def never_popen(*args, **kwargs):
        raise AssertionError("StudyRunner must not spawn a cycle when disk is low")

    runner = _runner(
        study_dir,
        script,
        flush_db=lambda url: flush_log.append(url),
        disk_usage=low,
        popen=never_popen,
    )
    with pytest.raises(StudyError, match=r"free disk space"):
        runner.run()
    assert low.calls >= 1
    assert not flush_log
    assert not (study_dir / "steps.jsonl").exists()


def test_mid_step_disk_low_preserve_and_record(tmp_path, known_modules, monkeypatch):
    study_dir = _create_study(tmp_path, viewing_budget_seconds=60.0)
    script = tmp_path / "cycle.py"
    script.write_text(_short_cycle_script())

    requests = []

    def fake_request(self, line_dir, reason, stop=False, wait=None):
        requests.append((str(line_dir), reason, stop, wait))
        Req = type("Req", (), {"reason": reason, "request_id": "disk-low-req"})
        Res = {"ok": True, "bundle": str(line_dir / "bundle"), "preservation_id": "p1"}
        return Req, Res, True, True

    monkeypatch.setattr(StudyRunner, "_request_preserve", fake_request)

    class Disk:
        def __init__(self):
            self.calls = 0

        def __call__(self, path: Path):
            self.calls += 1
            total = 100 * 2**30
            # call 1 is the pre-step guard; later calls are poll checks
            free = 50 * 2**30 if self.calls <= 1 else 5 * 2**30
            return type("U", (), {"total": total, "free": free})()

    runner = _runner(
        study_dir,
        script,
        disk_usage=Disk(),
        poll_seconds=0.05,
        preserve_wait_seconds=0.1,
    )
    record = _run(runner)
    assert isinstance(record, dict)
    assert record["outcome"] == "failed:disk_low"
    assert record["disk_low_preserved"] is True
    assert len(requests) == 1
    assert requests[0][1] == "disk_low"
    assert requests[0][2] is True


def test_mid_step_disk_low_preserve_failure_is_critical(
    tmp_path, known_modules, monkeypatch
):
    study_dir = _create_study(tmp_path, viewing_budget_seconds=60.0)
    script = tmp_path / "cycle.py"
    script.write_text(_long_cycle_script())

    requests = []

    def fake_request(self, line_dir, reason, stop=False, wait=None):
        requests.append((reason, stop))
        Req = type("Req", (), {"reason": reason, "request_id": "disk-low-fail"})
        return Req, None, False, False

    monkeypatch.setattr(StudyRunner, "_request_preserve", fake_request)

    class LowDisk:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, path: Path):
            self.calls += 1
            total = 100 * 2**30
            # Call 1 is the pre-step guard; the disk fills during the step.
            free = 50 * 2**30 if self.calls <= 1 else 5 * 2**30
            return type("U", (), {"total": total, "free": free})()

    runner = _runner(
        study_dir,
        script,
        disk_usage=LowDisk(),
        poll_seconds=0.05,
        preserve_wait_seconds=0.1,
    )
    with pytest.raises(StudyCritical, match=r"disk_low preservation failed"):
        runner.run()
    steps = _load_steps(study_dir)
    assert steps[-1]["outcome"] == "failed:critical"
    assert "pid" in steps[-1]
    assert len(requests) == 1
    assert requests[0] == ("disk_low", True)


def _valid_plan(tmp_path: Path) -> dict:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "config").mkdir()
    (repo_root / "config" / "profiles").mkdir()
    (repo_root / "config" / "kaine.toml").write_text("[modules]\necho = false\n")
    manifest = repo_root / "programme.toml"
    manifest.write_text("[programme]\n")
    sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    return {
        "study_id": "plan-disk-test",
        "repo_root": str(repo_root),
        "base_modules": [
            "soma",
            "chronos",
            "topos",
            "audition",
            "lingua",
            "thymos",
            "hypnos",
        ],
        "order": ["mnemos", "phantasia"],
        "programme": {"manifest": str(manifest), "sha256": sha},
        "redis": {
            "base_url": "redis://127.0.0.1:6479",
            "db": {"gestation": 10, "branch": 11, "repeat": 12, "accumulate": 13},
        },
        "collections": {
            "gestation": "t_g_",
            "branch": "t_b_",
            "repeat": "t_r_",
            "accumulate": "t_a_",
        },
    }


def test_min_free_gb_defaults_and_validation(tmp_path, known_modules):
    plan = _valid_plan(tmp_path)
    assert validate_plan(dict(plan))["min_free_gb"] == 20.0

    plan["min_free_gb"] = 10
    assert validate_plan(plan)["min_free_gb"] == 10

    plan["min_free_gb"] = 0
    assert validate_plan(plan)["min_free_gb"] == 0

    plan["min_free_gb"] = -1
    with pytest.raises(ValueError, match="min_free_gb"):
        validate_plan(plan)

    plan["min_free_gb"] = True
    with pytest.raises(ValueError, match="min_free_gb"):
        validate_plan(plan)

    plan["min_free_gb"] = "20"
    with pytest.raises(ValueError, match="min_free_gb"):
        validate_plan(plan)
