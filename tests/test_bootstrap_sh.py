# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _hermetic_run(tmp_path: Path, flags: list[str], stubs: list[str], env: dict[str, str] | None = None):
    home = tmp_path / "home"
    home.mkdir()
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()
    sysbin = tmp_path / "sysbin"
    sysbin.mkdir()

    # Minimal host tools the stubs and bash shebangs need.
    for tool in ("env", "bash", "sh", "cat", "printf", "cut", "mkdir", "rm", "chmod", "ln", "sleep", "true", "false"):
        host = shutil.which(tool)
        if host:
            (sysbin / tool).symlink_to(host)

    log = tmp_path / "argv.log"
    log.write_text("")

    recorder = tmp_path / "record_argv.py"
    recorder.write_text(
        f"""\
import sys, json, pathlib
argv = sys.argv[1:]
pathlib.Path({str(log)!r}).write_text(
    pathlib.Path({str(log)!r}).read_text(encoding="utf-8") + json.dumps(argv) + "\\n",
    encoding="utf-8"
)
"""
    )

    for name in stubs:
        path = stub_dir / name
        path.write_text(
            f"#!/usr/bin/env bash\nset -euo pipefail\nexec {sys.executable} {recorder} {name} \"$@\"\n"
        )
        path.chmod(0o755)

    merged_env = {**os.environ, "HOME": str(home), "PATH": f"{stub_dir}:{sysbin}"}
    if env:
        merged_env.update(env)

    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "bootstrap.sh"), *flags],
        env=merged_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result, log


def _recorded(log: Path) -> list[list[str]]:
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def test_missing_repo_exits_with_guidance(tmp_path):
    result, _log = _hermetic_run(tmp_path, [], ["python3", "git"])
    assert result.returncode != 0
    assert "does not exist" in result.stderr
    assert "--repo" in result.stderr


def test_apt_dry_run_shows_command(tmp_path):
    result, log = _hermetic_run(
        tmp_path,
        ["--dry-run", "--repo", "https://example.test/kaine.git"],
        ["python3", "git", "apt-get", "sudo"],
    )
    assert result.returncode == 0
    assert "sudo apt-get install -y" in result.stdout
    assert "python3-venv" in result.stdout
    assert "redis-server" in result.stdout
    assert "apt-get" not in " ".join(" ".join(a) for a in _recorded(log))
    assert "kaine.cycle" not in result.stdout
    assert "kaine.cycle" not in result.stderr


def test_dnf_dry_run_shows_command(tmp_path):
    result, log = _hermetic_run(
        tmp_path,
        ["--dry-run", "--repo", "https://example.test/kaine.git"],
        ["python3", "git", "dnf", "sudo"],
    )
    assert result.returncode == 0
    assert "sudo dnf install -y" in result.stdout
    assert "redis" in result.stdout
    assert "dnf" not in " ".join(" ".join(a) for a in _recorded(log))


def test_pacman_dry_run_shows_command(tmp_path):
    result, log = _hermetic_run(
        tmp_path,
        ["--dry-run", "--repo", "https://example.test/kaine.git"],
        ["python3", "git", "pacman", "sudo"],
    )
    assert result.returncode == 0
    assert "sudo pacman -S --needed --noconfirm" in result.stdout
    assert "base-devel" in result.stdout
    assert "pacman" not in " ".join(" ".join(a) for a in _recorded(log))


def test_pkg_dry_run_under_termux(tmp_path):
    result, log = _hermetic_run(
        tmp_path,
        ["--dry-run", "--repo", "https://example.test/kaine.git"],
        ["python3", "git", "pkg"],
        env={"TERMUX_VERSION": "0.118"},
    )
    assert result.returncode == 0
    assert "pkg install -y" in result.stdout
    assert "python-numpy" in result.stdout
    assert "rust" in result.stdout
    assert "pkg" not in " ".join(" ".join(a) for a in _recorded(log))


def test_brew_dry_run_shows_command(tmp_path):
    result, log = _hermetic_run(
        tmp_path,
        ["--dry-run", "--repo", "https://example.test/kaine.git"],
        ["python3", "git", "brew"],
    )
    assert result.returncode == 0
    assert "brew install" in result.stdout
    assert "redis" in result.stdout
    assert "brew" not in " ".join(" ".join(a) for a in _recorded(log))


def test_entity_never_started(tmp_path):
    result, log = _hermetic_run(
        tmp_path,
        ["--dry-run", "--repo", "https://example.test/kaine.git"],
        ["python3", "git", "apt-get", "sudo"],
    )
    assert result.returncode == 0
    combined = result.stdout + result.stderr + log.read_text()
    assert "kaine.cycle" not in combined
    assert "kaine.setup" in result.stdout


def test_real_run_executes_non_executable_scripts_and_no_packages_without_yes(tmp_path):
    # The repo's install.sh is mode 644, so bootstrap must run it with bash.
    kaine_dir = tmp_path / "kaine"
    scripts = kaine_dir / "scripts"
    scripts.mkdir(parents=True)
    for name in ("install.sh", "redis-bootstrap.sh", "qdrant-bootstrap.sh"):
        marker = tmp_path / f"{name}.ran"
        script = scripts / name
        script.write_text(f"#!/usr/bin/env bash\nprintf 'ran\\n' > {str(marker)!r}\n")
        script.chmod(0o644)

    result, log = _hermetic_run(
        tmp_path,
        ["--dir", str(kaine_dir)],
        ["python3", "git", "apt-get", "sudo"],
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for name in ("install.sh", "redis-bootstrap.sh", "qdrant-bootstrap.sh"):
        assert (tmp_path / f"{name}.ran").exists(), name
    calls = _recorded(log)
    assert not any(c and c[0] in ("apt-get", "sudo") for c in calls)
    assert not any("kaine.cycle" in " ".join(c) for c in calls)
