# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import hashlib
import subprocess
import textwrap

import pytest

from kaine.research.ignition_study.overlay import build_overlay
from tests.test_ignition_study_runner import (
    _create_study,
    _run,
    _runner,
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


@pytest.fixture
def repo(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    modules = repo_root / "modules"
    for name in (
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
    ):
        (modules / name).mkdir(parents=True, exist_ok=True)

    cfg = repo_root / "config"
    cfg.mkdir()
    (cfg / "kaine.toml").write_text(
        '[inference]\n'
        'server = "http://localhost:8080"\n'
    )
    programme = repo_root / "programme.toml"
    programme.write_text(
        '[programme]\n'
        'name = "storage-sandbox"\n'
    )
    (cfg / "kaine.operator.toml").write_text(
        '[storage]\n'
        f'data_root = "{tmp_path / "operator_root"}"\n'
        '[inference]\n'
        'server = "http://operator.local:8080"\n'
    )
    return repo_root


@pytest.fixture
def plan(repo):
    manifest = repo / "programme.toml"
    sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    return {
        "study_id": "storage-sandbox",
        "repo_root": str(repo),
        "base_modules": ["soma", "chronos", "topos"],
        "order": ["thymos", "mnemos"],
        "programme": {"manifest": str(manifest), "sha256": sha},
        "redis": {
            "base_url": "redis://127.0.0.1:6479",
            "db": {"gestation": 10, "branch": 11, "repeat": 12, "accumulate": 13},
        },
        "collections": {
            "gestation": "g_",
            "branch": "b_",
            "repeat": "r_",
            "accumulate": "a_",
        },
    }


def test_overlay_forces_child_data_root_to_line_directory(repo, plan):
    overlay, _, _ = build_overlay(
        plan,
        "gestation",
        "gestation",
        0,
        repo,
        repo / "config" / "kaine.toml",
        repo / "config" / "kaine.operator.toml",
    )
    assert overlay.get("storage", {}).get("data_root") == "."


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


def test_runner_child_env_strips_kaine_data_root(
    known_modules, tmp_path, monkeypatch
):
    monkeypatch.setenv("KAINE_DATA_ROOT", str(tmp_path / "env_root"))
    study_dir = _create_study(tmp_path, viewing_budget_seconds=60.0)
    script = tmp_path / "cycle.py"
    script.write_text(_short_cycle_script())

    captured: list[dict] = []

    def recording_popen(*args, **kwargs):
        captured.append(dict(kwargs.get("env") or {}))
        return subprocess.Popen(*args, **kwargs)

    runner = _runner(study_dir, script, popen=recording_popen, poll_seconds=0.05)
    _run(runner)

    assert captured
    assert all("KAINE_DATA_ROOT" not in env for env in captured)
