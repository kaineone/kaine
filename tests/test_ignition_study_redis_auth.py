# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from kaine.bus.config import load_bus_config, resolve_redis_auth
from kaine.research.ignition_study.plan import validate_plan
from kaine.research.ignition_study.runner import StudyError
from tests.test_ignition_study_runner import (
    BASE_MODULES,
    ORDER,
    STANDIN_SCRIPT,
    _create_study,
    _run,
    _runner,
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
    return names


def _make_plan(tmp_path: Path, base_url: str = "redis://127.0.0.1:6479") -> dict:
    repo_root = tmp_path / "repo"
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
    manifest = repo_root / "programme.toml"
    manifest.write_text("[programme]\n")
    sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    return {
        "study_id": "auth-test",
        "repo_root": str(repo_root),
        "base_modules": BASE_MODULES,
        "order": ORDER,
        "programme": {"manifest": str(manifest), "sha256": sha},
        "redis": {
            "base_url": base_url,
            "db": {"gestation": 10, "main": 11, "control": 12},
        },
        "collections": {"gestation": "r_g_", "main": "r_m_", "control": "r_c_"},
        "viewings_per_line": 2,
        "viewing_budget_seconds": 5.0,
        "gestation_budget_seconds": 5.0,
    }


def test_resolve_redis_auth_env_wins(tmp_path: Path):
    env = {
        "KAINE_REDIS_USERNAME": "env_user",
        "KAINE_REDIS_PASSWORD": "env_pw",
    }
    secrets = tmp_path / "secrets.toml"
    secrets.write_text('[redis]\nusername = "sec_user"\npassword = "sec_pw"\n')
    assert resolve_redis_auth(env, secrets) == ("env_user", "env_pw")


def test_resolve_redis_auth_secrets_fallback(tmp_path: Path):
    secrets = tmp_path / "secrets.toml"
    secrets.write_text('[redis]\nusername = "sec_user"\npassword = "sec_pw"\n')
    assert resolve_redis_auth({}, secrets) == ("sec_user", "sec_pw")


def test_resolve_redis_auth_neither_absent(tmp_path: Path):
    assert resolve_redis_auth({}, tmp_path / "missing.toml") == (None, None)


def test_resolve_redis_auth_empty_env_as_absent(tmp_path: Path):
    env = {"KAINE_REDIS_PASSWORD": ""}
    secrets = tmp_path / "secrets.toml"
    secrets.write_text('[redis]\npassword = "sec_pw"\n')
    assert resolve_redis_auth(env, secrets) == (None, "sec_pw")


@pytest.mark.parametrize(
    "base_url, match",
    [
        (
            "redis://:pw@127.0.0.1:6479",
            "redis.base_url must not contain credentials",
        ),
        (
            "redis://u:pw@h:1",
            "redis.base_url must not contain credentials",
        ),
        ("http://127.0.0.1:6479", "scheme must be redis or rediss"),
        ("redis://127.0.0.1:6479/3", "path must be empty or '/'"),
    ],
)
def test_validate_plan_rejects_bad_base_url(
    tmp_path: Path, base_url: str, match: str
):
    plan = _make_plan(tmp_path, base_url)
    with pytest.raises(ValueError, match=match):
        validate_plan(plan)


def test_validate_plan_accepts_clean_base_url(tmp_path: Path):
    plan = _make_plan(tmp_path, "redis://127.0.0.1:6479")
    validated = validate_plan(plan)
    assert validated["redis"]["base_url"] == "redis://127.0.0.1:6479"


def test_runner_embeds_escaped_password(tmp_path: Path, known_modules, monkeypatch):
    password = "p@ss:w/rd"
    monkeypatch.setenv("KAINE_REDIS_PASSWORD", password)
    study_dir = _create_study(tmp_path, viewings=2)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    result = _run(_runner(study_dir, script))
    assert result == "complete"

    env_logs = [
        json.loads(line)
        for line in (study_dir / "env_log.jsonl").read_text().splitlines()
        if line.strip()
    ]
    by_line = {e["line"]: e for e in env_logs}
    for line, db in [("gestation", 10), ("main", 11), ("control", 12)]:
        url = by_line[line]["redis_url"]
        assert (
            load_bus_config(
                env={"KAINE_REDIS_URL": url},
                secrets_toml=tmp_path / "none.toml",
            ).url
            == url
        )
        parsed = urlsplit(url)
        assert unquote(parsed.password or "") == password
        assert parsed.scheme == "redis"
        assert int(parsed.path.lstrip("/")) == db


def test_runner_fails_without_password(tmp_path: Path, known_modules, monkeypatch):
    monkeypatch.delenv("KAINE_REDIS_PASSWORD", raising=False)
    study_dir = _create_study(tmp_path, viewings=2)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    with pytest.raises(StudyError):
        _run(_runner(study_dir, script))
    assert not (study_dir / "env_log.jsonl").exists()


def test_password_not_recorded(tmp_path: Path, known_modules, monkeypatch):
    password = "p@ss:w/rd"
    monkeypatch.setenv("KAINE_REDIS_PASSWORD", password)
    study_dir = _create_study(tmp_path, viewings=1)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)
    _run(_runner(study_dir, script))

    study_text = (study_dir / "study.json").read_text()
    steps_text = (study_dir / "steps.jsonl").read_text()
    assert password not in study_text
    assert password not in steps_text
    encoded = "p%40ss%3Aw%2Frd"
    assert encoded not in study_text
    assert encoded not in steps_text


def test_resume_rejects_legacy_plan_with_credentials(
    tmp_path: Path, known_modules, monkeypatch
):
    monkeypatch.setenv("KAINE_REDIS_PASSWORD", "test-redis-pw")
    study_dir = _create_study(tmp_path, viewings=2)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)

    study_path = study_dir / "study.json"
    plan = json.loads(study_path.read_text())
    plan["redis"]["base_url"] = "redis://:oldpw@127.0.0.1:6479"
    study_path.write_text(json.dumps(plan))

    with pytest.raises(StudyError, match="study.json") as exc_info:
        _runner(study_dir, script)
    assert "oldpw" not in str(exc_info.value)


def test_resume_rejects_legacy_plan_with_path(
    tmp_path: Path, known_modules, monkeypatch
):
    monkeypatch.setenv("KAINE_REDIS_PASSWORD", "test-redis-pw")
    study_dir = _create_study(tmp_path, viewings=2)
    script = tmp_path / "standin.py"
    script.write_text(STANDIN_SCRIPT)

    study_path = study_dir / "study.json"
    plan = json.loads(study_path.read_text())
    plan["redis"]["base_url"] = "redis://127.0.0.1:6479/3"
    study_path.write_text(json.dumps(plan))

    with pytest.raises(StudyError, match="study.json"):
        _runner(study_dir, script)
