# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import os
import shutil
import subprocess
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_QUADLET_SRC = _REPO_ROOT / "quadlet"
_SCRIPT_SRC = _REPO_ROOT / "scripts" / "install-quadlet.sh"


def _make_checkout(root: Path) -> Path:
    quadlet_dst = root / "quadlet"
    scripts_dst = root / "scripts"
    config_dst = root / "config"
    compose_dst = root / "compose"
    quadlet_dst.mkdir(parents=True)
    scripts_dst.mkdir()
    config_dst.mkdir()
    compose_dst.mkdir()
    shutil.copytree(_QUADLET_SRC, quadlet_dst, dirs_exist_ok=True)
    shutil.copy2(_SCRIPT_SRC, scripts_dst / "install-quadlet.sh")
    (config_dst / "kaine.operator.toml").write_text("[operator]\n")
    (compose_dst / ".env").write_text("KAINE_REDIS_PASSWORD=pw\n")
    return scripts_dst / "install-quadlet.sh"


def _container_section(path: Path, section: str) -> list[str]:
    lines: list[str] = []
    current: str | None = None
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            continue
        if current == section:
            lines.append(raw)
    return lines


def test_compose_no_secrets_toml_volumes() -> None:
    compose = yaml.safe_load((_REPO_ROOT / "compose" / "kaine.yml").read_text())
    for name, svc in compose.get("services", {}).items():
        volumes = svc.get("volumes", [])
        for vol in volumes:
            if isinstance(vol, str) and "secrets.toml" in vol:
                raise AssertionError(
                    f"{name} still mounts secrets.toml: {vol!r}"
                )


def test_compose_cycle_study_env_file() -> None:
    compose = yaml.safe_load((_REPO_ROOT / "compose" / "kaine.yml").read_text())
    expected = [{"path": "./caretaker.env", "required": False}]
    for name in ("kaine-cycle", "kaine-study"):
        svc = compose["services"][name]
        assert svc.get("env_file") == expected, f"{name} env_file mismatch"
        assert "KAINE_DASHBOARD_TOKEN" not in svc.get("environment", {}), name


def test_compose_dashboard_token_env() -> None:
    compose = yaml.safe_load((_REPO_ROOT / "compose" / "kaine.yml").read_text())
    env = compose["services"]["kaine-dashboard"].get("environment", {})
    assert "KAINE_DASHBOARD_TOKEN" in env
    assert "secrets.toml" not in str(env.get("KAINE_DASHBOARD_TOKEN", ""))


def test_quadlet_no_secrets_toml() -> None:
    for path in (_REPO_ROOT / "quadlet").glob("*.container"):
        assert "secrets.toml" not in path.read_text(), f"{path.name} still mentions secrets.toml"


def test_quadlet_caretaker_env_file() -> None:
    for name in ("kaine-cycle", "kaine-cycle-unattended"):
        path = _REPO_ROOT / "quadlet" / f"{name}.container"
        container = "\n".join(_container_section(path, "Container"))
        service = "\n".join(_container_section(path, "Service"))
        assert (
            "EnvironmentFile=@KAINE_ROOT@/compose/caretaker.env" in container
        ), f"{name} missing caretaker env file in [Container]"
        assert (
            "EnvironmentFile=@KAINE_ROOT@/compose/.env" in service
        ), f"{name} missing compose/.env in [Service]"


def test_quadlet_dashboard_token_env() -> None:
    path = _REPO_ROOT / "quadlet" / "kaine-dashboard.container"
    container = "\n".join(_container_section(path, "Container"))
    assert (
        "Environment=KAINE_DASHBOARD_TOKEN=${KAINE_DASHBOARD_TOKEN}" in container
    ), "dashboard missing token env"


def test_dockerignore_ignores_env_files() -> None:
    dockerignore = (_REPO_ROOT / ".dockerignore").read_text().splitlines()
    assert "compose/*.env" in dockerignore


def test_install_quadlet_creates_caretaker_env(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    dest = tmp_path / "dest"
    script = _make_checkout(root)
    result = subprocess.run(
        [
            "bash",
            str(script),
            "--root",
            str(root),
            "--dest",
            str(dest),
            "--generator",
            "none",
        ],
        env={**os.environ, "HOME": str(tmp_path / "home")},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    caretaker = root / "compose" / "caretaker.env"
    assert caretaker.exists()
    assert caretaker.stat().st_mode & 0o777 == 0o600, oct(caretaker.stat().st_mode)
    assert caretaker.read_bytes() == b""

    assert "created compose/caretaker.env (empty, mode 600) for caretaker tokens" in result.stdout


def test_install_quadlet_preserves_existing_caretaker_env(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    dest = tmp_path / "dest"
    script = _make_checkout(root)

    caretaker = root / "compose" / "caretaker.env"
    original = b"KAINE_CARETAKER_TOKEN_NTFY=secret\n"
    caretaker.write_bytes(original)
    caretaker.chmod(0o600)

    result = subprocess.run(
        [
            "bash",
            str(script),
            "--root",
            str(root),
            "--dest",
            str(dest),
            "--generator",
            "none",
        ],
        env={**os.environ, "HOME": str(tmp_path / "home")},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    assert caretaker.read_bytes() == original
    assert "created compose/caretaker.env" not in result.stdout


def test_install_quadlet_dry_run_no_caretaker_env(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    dest = tmp_path / "dest"
    script = _make_checkout(root)

    result = subprocess.run(
        [
            "bash",
            str(script),
            "--root",
            str(root),
            "--dest",
            str(dest),
            "--generator",
            "none",
            "--dry-run",
        ],
        env={**os.environ, "HOME": str(tmp_path / "home")},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    caretaker = root / "compose" / "caretaker.env"
    assert not caretaker.exists()
    assert "would create compose/caretaker.env" in result.stdout
