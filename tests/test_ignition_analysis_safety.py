# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The study analysis lists the safety-relevant step records.

Steps with a supervisor restart are listed beside the others (a restart does
not fail a step). A count the runner could not read, because the incident log
is encrypted, is counted again with the operator's state key installed.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from kaine.research.ignition_study.analysis import run_analysis
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor


@pytest.fixture(autouse=True)
def _reset_encryptor():
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


def _make_study_dir(tmp_path: Path) -> Path:
    study_dir = tmp_path / "study"
    study_dir.mkdir()
    manifest = tmp_path / "programme.toml"
    manifest.write_text("items = []\n")
    plan = {
        "study_id": "safety-test",
        "repo_root": str(tmp_path / "repo"),
        "base_modules": ["interoception", "sequence", "vision", "audition", "language"],
        "order": ["affect"],
        "programme": {
            "manifest": str(manifest),
            "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        },
        "redis": {
            "base_url": "redis://127.0.0.1:6479",
            "db": {"development": 10, "branch": 11, "repeat": 12, "accumulate": 13},
        },
        "collections": {
            "development": "s_g_",
            "branch": "s_b_",
            "repeat": "s_r_",
            "accumulate": "s_a_",
        },
    }
    (study_dir / "study.json").write_text(json.dumps(plan, indent=2, sort_keys=True))
    return study_dir


def _write_steps(study_dir: Path, steps: list[dict[str, Any]]) -> None:
    with (study_dir / "steps.jsonl").open("w", encoding="utf-8") as fh:
        for rec in steps:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")


def _step(line: str, step: int, **extra: Any) -> dict[str, Any]:
    rec = {
        "line": line,
        "step": step,
        "outcome": "complete",
        "run_id": None,
        "started_at": "2026-10-31T10:00:00+00:00",
        "modules": ["interoception"],
    }
    rec.update(extra)
    return rec


def test_steps_with_restarts_are_listed(tmp_path: Path):
    study_dir = _make_study_dir(tmp_path)
    _write_steps(
        study_dir,
        [
            _step("development", 0, supervisor_restarts=1),
            _step("branch", 0, supervisor_restarts=0),
            _step("repeat", 0, supervisor_restarts=3),
            _step("branch", 1, outcome="failed:exit:1"),
        ],
    )
    json_path, md_path = run_analysis(study_dir)
    report = json.loads(json_path.read_text())
    assert report["supervisor_restarts"] == [
        {"line": "development", "step": 0, "supervisor_restarts": 1},
        {"line": "repeat", "step": 0, "supervisor_restarts": 3},
    ]
    md = md_path.read_text()
    assert "## Supervisor restarts" in md
    assert "| development | 0 | 1 |" in md
    assert "| repeat | 0 | 3 |" in md


def test_no_restarts_says_so(tmp_path: Path):
    study_dir = _make_study_dir(tmp_path)
    _write_steps(study_dir, [_step("development", 0, supervisor_restarts=0)])
    _, md_path = run_analysis(study_dir)
    assert "No completed step had a supervisor restart." in md_path.read_text()


def test_an_encrypted_incident_log_is_counted_with_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("KAINE_STATE_KEY", key)
    encryptor = StateEncryptor(CryptoConfig(enabled=True))

    study_dir = _make_study_dir(tmp_path)
    incidents = study_dir / "development" / "state" / "cycle" / "incidents"
    incidents.mkdir(parents=True)
    with (incidents / "incidents-2026-10-31.jsonl").open("w") as fh:
        for ts in ("2026-10-31T09:00:00+00:00", "2026-10-31T11:00:00+00:00"):
            rec = {"ts": ts, "module": "vision", "transition": "restart"}
            fh.write(encryptor.encrypt_text(json.dumps(rec)) + "\n")
    # The runner could not read it without the key.
    _write_steps(
        study_dir,
        [_step("development", 0, supervisor_restarts=None, supervisor_restarts_unreadable_lines=2)],
    )
    json_path, _ = run_analysis(study_dir)
    report = json.loads(json_path.read_text())
    # Only the restart dated inside the step counts.
    assert report["supervisor_restarts"] == [
        {"line": "development", "step": 0, "supervisor_restarts": 1}
    ]


def test_an_unreadable_count_stays_unknown_without_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("KAINE_STATE_KEY", raising=False)
    study_dir = _make_study_dir(tmp_path)
    incidents = study_dir / "development" / "state" / "cycle" / "incidents"
    incidents.mkdir(parents=True)
    (incidents / "incidents-2026-10-31.jsonl").write_text("not-json-ciphertext\n")
    _write_steps(study_dir, [_step("development", 0, supervisor_restarts=None)])
    json_path, md_path = run_analysis(study_dir)
    report = json.loads(json_path.read_text())
    assert report["supervisor_restarts"] == [
        {"line": "development", "step": 0, "supervisor_restarts": None}
    ]
    assert "| development | 0 | unknown |" in md_path.read_text()
