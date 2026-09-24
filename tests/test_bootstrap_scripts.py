# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import os
import shutil
import stat
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def fake_repo(tmp_path):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "kaine").mkdir(parents=True)
    (root / "compose").mkdir(parents=True)
    (root / "config").mkdir(parents=True)
    (root / "bin").mkdir(parents=True)

    shutil.copy2(REPO / "scripts" / "redis-bootstrap.sh", root / "scripts" / "redis-bootstrap.sh")
    shutil.copy2(REPO / "scripts" / "qdrant-bootstrap.sh", root / "scripts" / "qdrant-bootstrap.sh")

    # Only the files `python3 -m kaine.secrets_file` imports. The scripts run
    # under the system python3 with no venv, so if the package's import chain
    # ever grows a dependency outside these (stdlib-only) files, these tests
    # fail rather than a fresh install.
    for name in ("__init__.py", "hardware.py", "secrets_file.py"):
        shutil.copy2(REPO / "kaine" / name, root / "kaine" / name)

    shutil.copy2(REPO / "config" / "secrets.example.toml", root / "config" / "secrets.example.toml")

    stubs = {
        "docker": "#!/bin/sh\nexit 0\n",
        "redis-cli": "#!/bin/sh\necho PONG\n",
        "curl": "#!/bin/sh\nexit 0\n",
        "sleep": "#!/bin/sh\nexit 0\n",
    }
    for name, body in stubs.items():
        path = root / "bin" / name
        path.write_text(body)
        path.chmod(0o755)

    return root


def _run(root, name, *flags):
    return subprocess.run(
        ["bash", str(root / "scripts" / name), *flags],
        env={**os.environ, "PATH": f"{root / 'bin'}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=60,
    )


def _parse_env(path):
    values = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


def _load_toml(path):
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_redis_fresh(fake_repo):
    r = _run(fake_repo, "redis-bootstrap.sh")
    assert r.returncode == 0

    env = _parse_env(fake_repo / "compose" / ".env")
    secrets = _load_toml(fake_repo / "config" / "secrets.toml")
    pw = env["KAINE_REDIS_PASSWORD"]

    assert secrets["redis"]["password"] == pw
    assert len(pw) == 64
    assert all(c in "0123456789abcdef" for c in pw)
    assert stat.S_IMODE((fake_repo / "compose" / ".env").stat().st_mode) == 0o600
    assert stat.S_IMODE((fake_repo / "config" / "secrets.toml").stat().st_mode) == 0o600
    assert pw not in r.stdout and pw not in r.stderr


def test_qdrant_then_redis_keeps_key(fake_repo):
    rq = _run(fake_repo, "qdrant-bootstrap.sh")
    assert rq.returncode == 0

    env1 = _parse_env(fake_repo / "compose" / ".env")
    key1 = env1["KAINE_QDRANT_API_KEY"]
    secrets1 = _load_toml(fake_repo / "config" / "secrets.toml")
    assert secrets1["qdrant"]["api_key"] == key1
    assert key1 not in rq.stdout and key1 not in rq.stderr

    rr = _run(fake_repo, "redis-bootstrap.sh")
    assert rr.returncode == 0

    env2 = _parse_env(fake_repo / "compose" / ".env")
    assert env2["KAINE_QDRANT_API_KEY"] == key1
    secrets2 = _load_toml(fake_repo / "config" / "secrets.toml")
    assert secrets2["qdrant"]["api_key"] == key1


def test_redis_idempotence_and_rotate(fake_repo):
    _run(fake_repo, "redis-bootstrap.sh")
    pw = _parse_env(fake_repo / "compose" / ".env")["KAINE_REDIS_PASSWORD"]

    _run(fake_repo, "redis-bootstrap.sh")
    assert _parse_env(fake_repo / "compose" / ".env")["KAINE_REDIS_PASSWORD"] == pw

    _run(fake_repo, "redis-bootstrap.sh", "--keep-password")
    assert _parse_env(fake_repo / "compose" / ".env")["KAINE_REDIS_PASSWORD"] == pw

    r = _run(fake_repo, "redis-bootstrap.sh", "--rotate")
    new_pw = _parse_env(fake_repo / "compose" / ".env")["KAINE_REDIS_PASSWORD"]
    secrets = _load_toml(fake_repo / "config" / "secrets.toml")
    assert new_pw != pw
    assert secrets["redis"]["password"] == new_pw
    assert new_pw not in r.stdout and new_pw not in r.stderr


def test_qdrant_idempotence_and_rotate(fake_repo):
    _run(fake_repo, "qdrant-bootstrap.sh")
    key = _parse_env(fake_repo / "compose" / ".env")["KAINE_QDRANT_API_KEY"]

    _run(fake_repo, "qdrant-bootstrap.sh")
    assert _parse_env(fake_repo / "compose" / ".env")["KAINE_QDRANT_API_KEY"] == key

    _run(fake_repo, "qdrant-bootstrap.sh", "--keep-key")
    assert _parse_env(fake_repo / "compose" / ".env")["KAINE_QDRANT_API_KEY"] == key

    r = _run(fake_repo, "qdrant-bootstrap.sh", "--rotate")
    new_key = _parse_env(fake_repo / "compose" / ".env")["KAINE_QDRANT_API_KEY"]
    secrets = _load_toml(fake_repo / "config" / "secrets.toml")
    assert new_key != key
    assert secrets["qdrant"]["api_key"] == new_key
    assert new_key not in r.stdout and new_key not in r.stderr


def test_redis_preserves_other_table_password(fake_repo):
    secrets_path = fake_repo / "config" / "secrets.toml"
    secrets_path.write_text(
        '[other]\npassword = "keep-me"\n\n[redis]\npassword = "placeholder-to-be-replaced"\n',
        encoding="utf-8",
    )

    _run(fake_repo, "redis-bootstrap.sh")

    secrets = _load_toml(secrets_path)
    assert secrets["other"]["password"] == "keep-me"
    assert secrets["redis"]["password"] != "placeholder-to-be-replaced"


def test_no_secret_in_output(fake_repo):
    r_redis = _run(fake_repo, "redis-bootstrap.sh")
    r_qdrant = _run(fake_repo, "qdrant-bootstrap.sh")

    env = _parse_env(fake_repo / "compose" / ".env")
    pw = env["KAINE_REDIS_PASSWORD"]
    key = env["KAINE_QDRANT_API_KEY"]

    combined = r_redis.stdout + r_redis.stderr + r_qdrant.stdout + r_qdrant.stderr
    assert pw not in combined
    assert key not in combined


@pytest.mark.parametrize("name", ["redis-bootstrap.sh", "qdrant-bootstrap.sh"])
def test_help(name, fake_repo):
    r = _run(fake_repo, name, "--help")
    assert r.returncode == 0
    assert "--rotate" in r.stdout
    assert not any(line.startswith("set -") for line in r.stdout.splitlines())


@pytest.mark.parametrize("name", ["redis-bootstrap.sh", "qdrant-bootstrap.sh"])
def test_unknown_flag(name, fake_repo):
    r = _run(fake_repo, name, "--bogus")
    assert r.returncode == 2
