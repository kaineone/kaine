# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for scripts/install-quadlet.sh.

These exercise the renderer with a fake checkout and a temporary destination.
They never call a real podman/systemd binary unless a real quadlet generator
is present on the host.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from kaine import legacy_aliases

_REPO_ROOT = Path(__file__).resolve().parent.parent
_QUADLET_SRC = _REPO_ROOT / "quadlet"
_SCRIPT_SRC = _REPO_ROOT / "scripts" / "install-quadlet.sh"


def _empty_dir(path: Path) -> bool:
    return not path.exists() or not any(path.iterdir())


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
    (config_dst / "secrets.toml").write_text("[redis]\n")
    (compose_dst / ".env").write_text("KAINE_REDIS_PASSWORD=pw\n")
    return scripts_dst / "install-quadlet.sh"


def _run(
    script: Path,
    *args: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    home = cwd.parent if cwd else Path("/nonexistent")
    final_env = {**os.environ, "HOME": str(home)}
    if env:
        final_env.update(env)
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=str(cwd) if cwd else None,
        env=final_env,
        capture_output=True,
        text=True,
    )


def test_install_renders_units_for_checkout(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    checkout = tmp_path / "checkout"
    script = _make_checkout(checkout)
    dest = tmp_path / "dest"

    result = _run(
        script,
        "--root",
        str(checkout),
        "--dest",
        str(dest),
        "--generator",
        "none",
        cwd=checkout,
    )
    assert result.returncode == 0, result.stderr

    installed = {p.name for p in dest.iterdir()}
    assert "kaine-cycle.container" in installed
    assert "kaine-dashboard.container" in installed
    assert "kaine-redis.container" in installed
    assert "kaine-qdrant.container" in installed

    cycle = (dest / "kaine-cycle.container").read_text()
    dashboard = (dest / "kaine-dashboard.container").read_text()
    assert f"Volume={checkout}/config/kaine.operator.toml" in cycle
    assert f"Volume={checkout}/config/kaine.operator.toml" in dashboard
    for p in dest.iterdir():
        text = p.read_text()
        assert "@KAINE_ROOT@" not in text, p.name
        assert "projects/kaine" not in text, p.name


def test_secret_using_units_load_env_file(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    checkout = tmp_path / "checkout"
    script = _make_checkout(checkout)
    dest = tmp_path / "dest"

    result = _run(
        script,
        "--root",
        str(checkout),
        "--dest",
        str(dest),
        "--generator",
        "none",
        cwd=checkout,
    )
    assert result.returncode == 0, result.stderr

    env_line = f"EnvironmentFile={checkout}/compose/.env"
    for name in (
        "kaine-cycle.container",
        "kaine-model-server.container",
        "kaine-dashboard.container",
        "kaine-redis.container",
        "kaine-qdrant.container",
    ):
        text = (dest / name).read_text()
        assert env_line in text, f"{name} missing EnvironmentFile line"


def test_unsafe_root_path_with_space_refused(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    checkout = tmp_path / "checkout"
    script = _make_checkout(checkout)

    unsafe = tmp_path / "has space"
    shutil.copytree(checkout, unsafe)

    dest = tmp_path / "dest"
    result = _run(
        script,
        "--root",
        str(unsafe),
        "--dest",
        str(dest),
        "--generator",
        "none",
        cwd=checkout,
    )
    assert result.returncode != 0
    assert "has space" in result.stderr
    assert _empty_dir(dest)


def test_unsafe_root_path_with_colon_refused(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    checkout = tmp_path / "checkout"
    script = _make_checkout(checkout)

    unsafe = tmp_path / "bad:path"
    shutil.copytree(checkout, unsafe)

    dest = tmp_path / "dest"
    result = _run(
        script,
        "--root",
        str(unsafe),
        "--dest",
        str(dest),
        "--generator",
        "none",
        cwd=checkout,
    )
    assert result.returncode != 0
    assert "bad:path" in result.stderr
    assert _empty_dir(dest)


@pytest.mark.parametrize(
    "missing",
    [
        "config/kaine.operator.toml",
        "config/secrets.toml",
        "compose/.env",
    ],
)
def test_missing_required_file_refused(tmp_path: Path, missing: str):
    home = tmp_path / "home"
    home.mkdir()
    checkout = tmp_path / "checkout"
    script = _make_checkout(checkout)
    (checkout / missing).unlink()

    dest = tmp_path / "dest"
    result = _run(
        script,
        "--root",
        str(checkout),
        "--dest",
        str(dest),
        "--generator",
        "none",
        cwd=checkout,
    )
    assert result.returncode != 0
    assert missing in result.stderr
    assert _empty_dir(dest)


def test_unattended_unit_never_installed(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    checkout = tmp_path / "checkout"
    script = _make_checkout(checkout)
    (checkout / "quadlet" / "kaine-cycle-unattended.container").write_text(
        "[Container]\n"
    )

    dest = tmp_path / "dest"
    result = _run(
        script,
        "--root",
        str(checkout),
        "--dest",
        str(dest),
        "--generator",
        "none",
        cwd=checkout,
    )
    assert result.returncode == 0, result.stderr
    assert not (dest / "kaine-cycle-unattended.container").exists()
    assert "kaine-cycle-unattended.container" in result.stdout
    assert "skipped" in result.stdout.lower()


def test_dry_run_writes_nothing(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    checkout = tmp_path / "checkout"
    script = _make_checkout(checkout)
    dest = tmp_path / "dest"

    result = _run(
        script,
        "--root",
        str(checkout),
        "--dest",
        str(dest),
        "--generator",
        "none",
        "--dry-run",
        cwd=checkout,
    )
    assert result.returncode == 0, result.stderr
    assert _empty_dir(dest)
    assert "would install" in result.stdout


def test_fake_generator_failure_aborts_install(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    checkout = tmp_path / "checkout"
    script = _make_checkout(checkout)

    gen = tmp_path / "fake-quadlet.sh"
    gen.write_text("#!/usr/bin/env bash\necho 'bad unit' >&2\nexit 1\n")
    gen.chmod(0o755)

    dest = tmp_path / "dest"
    result = _run(
        script,
        "--root",
        str(checkout),
        "--dest",
        str(dest),
        "--generator",
        str(gen),
        cwd=checkout,
    )
    assert result.returncode != 0
    assert "bad unit" in result.stderr
    assert _empty_dir(dest)


def test_fake_generator_records_stage_dir_not_dest(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    checkout = tmp_path / "checkout"
    script = _make_checkout(checkout)

    recorded = tmp_path / "recorded.txt"
    gen = tmp_path / "fake-quadlet.sh"
    gen.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$QUADLET_UNIT_DIRS\" > {recorded}\nexit 0\n"
    )
    gen.chmod(0o755)

    dest = tmp_path / "dest"
    result = _run(
        script,
        "--root",
        str(checkout),
        "--dest",
        str(dest),
        "--generator",
        str(gen),
        cwd=checkout,
    )
    assert result.returncode == 0, result.stderr
    assert (dest / "kaine-cycle.container").exists()

    stage_dir = recorded.read_text().strip()
    assert stage_dir
    assert Path(stage_dir) != dest


def test_default_dest_honours_xdg_config_home(tmp_path: Path):
    xdg = tmp_path / "xdg"
    xdg.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    checkout = tmp_path / "checkout"
    script = _make_checkout(checkout)

    expected_dest = xdg / "containers" / "systemd"
    result = _run(
        script,
        "--root",
        str(checkout),
        "--generator",
        "none",
        cwd=checkout,
        env={"XDG_CONFIG_HOME": str(xdg)},
    )
    assert result.returncode == 0, result.stderr
    assert (expected_dest / "kaine-cycle.container").exists()


@pytest.mark.skipif(
    not any(
        (p / "quadlet").exists()
        for p in (Path("/usr/libexec/podman"), Path("/usr/lib/podman"))
    ),
    reason="no host quadlet generator available",
)
def test_real_generator_dryrun_succeeds(tmp_path: Path):
    gen = None
    for p in ("/usr/libexec/podman/quadlet", "/usr/lib/podman/quadlet"):
        if Path(p).exists():
            gen = p
            break
    if gen is None:
        pytest.skip("no host quadlet generator available")

    home = tmp_path / "home"
    home.mkdir()
    checkout = tmp_path / "checkout"
    script = _make_checkout(checkout)
    dest = tmp_path / "dest"

    result = _run(
        script,
        "--root",
        str(checkout),
        "--dest",
        str(dest),
        "--generator",
        gen,
        "--dry-run",
        cwd=checkout,
    )
    assert result.returncode == 0, result.stderr


def test_explicit_generator_not_executable_aborts(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    checkout = tmp_path / "checkout"
    script = _make_checkout(checkout)
    dest = tmp_path / "dest"

    missing_gen = tmp_path / "missing-generator"
    result = _run(
        script,
        "--root",
        str(checkout),
        "--dest",
        str(dest),
        "--generator",
        str(missing_gen),
        cwd=checkout,
    )
    assert result.returncode != 0
    assert f"generator not executable: {missing_gen}" in result.stderr
    assert _empty_dir(dest)


OLD = next(f for f in legacy_aliases.name_forms("dashboard") if f != "dashboard")
OLD_UNIT = f"kaine-{OLD}.container"
OLD_SERVICE = f"kaine-{OLD}.service"


def _old_unit_content(checkout: Path) -> str:
    return (
        "# SPDX-License-Identifier: LicenseRef-CAL-0.4\n[Container]\n"
        f"Volume={checkout.resolve()}/config/kaine.operator.toml:/app/config/kaine.operator.toml:ro,Z\n"
    )


def _write_fake_systemctl(tmp_path: Path) -> Path:
    script = tmp_path / "systemctl"
    script.write_text(
        "#!/usr/bin/env bash\n"
        'state_file="${FAKE_SYSTEMCTL_STATE_FILE:-/dev/null}"\n'
        'code_file="${FAKE_SYSTEMCTL_CODE_FILE:-/dev/null}"\n'
        'state="inactive"\n'
        'code=0\n'
        'if [[ -f "$state_file" ]]; then\n'
        '  state="$(cat "$state_file")"\n'
        "fi\n"
        'if [[ -f "$code_file" ]]; then\n'
        '  code="$(cat "$code_file")"\n'
        "fi\n"
        'if [[ "$1" == "--user" && "$2" == "show" && "$3" == "-p" && "$4" == "ActiveState" && "$5" == "--value" ]]; then\n'
        '  printf "%s\\n" "$state"\n'
        '  exit "$code"\n'
        "fi\n"
        "exit 1\n"
    )
    script.chmod(0o755)
    return script


def _make_dest_with_old_unit(dest: Path, content: str) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    old_path = dest / OLD_UNIT
    old_path.write_text(content)
    return old_path


def test_install_removes_old_renamed_unit_when_inactive(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    checkout = tmp_path / "checkout"
    script = _make_checkout(checkout)
    dest = tmp_path / "dest"
    old_path = _make_dest_with_old_unit(dest, _old_unit_content(checkout))
    state_file = tmp_path / "systemctl.state"
    state_file.write_text("inactive")
    code_file = tmp_path / "systemctl.code"
    code_file.write_text("0")
    fake_systemctl = _write_fake_systemctl(tmp_path)

    result = _run(
        script,
        "--root",
        str(checkout),
        "--dest",
        str(dest),
        "--generator",
        "none",
        cwd=checkout,
        env={
            "KAINE_SYSTEMCTL": str(fake_systemctl),
            "FAKE_SYSTEMCTL_STATE_FILE": str(state_file),
            "FAKE_SYSTEMCTL_CODE_FILE": str(code_file),
        },
    )

    assert result.returncode == 0, result.stderr
    assert not old_path.exists()
    assert (dest / "kaine-dashboard.container").exists()
    assert f"removed old unit {OLD_UNIT} (renamed to kaine-dashboard.container)" in result.stdout


def test_install_refuses_when_old_renamed_unit_still_active(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    checkout = tmp_path / "checkout"
    script = _make_checkout(checkout)
    dest = tmp_path / "dest"
    old_path = _make_dest_with_old_unit(dest, _old_unit_content(checkout))
    state_file = tmp_path / "systemctl.state"
    state_file.write_text("active")
    code_file = tmp_path / "systemctl.code"
    code_file.write_text("0")
    fake_systemctl = _write_fake_systemctl(tmp_path)

    result = _run(
        script,
        "--root",
        str(checkout),
        "--dest",
        str(dest),
        "--generator",
        "none",
        cwd=checkout,
        env={
            "KAINE_SYSTEMCTL": str(fake_systemctl),
            "FAKE_SYSTEMCTL_STATE_FILE": str(state_file),
            "FAKE_SYSTEMCTL_CODE_FILE": str(code_file),
        },
    )

    assert result.returncode == 1
    assert old_path.exists()
    assert "systemctl --user stop" in result.stderr
    assert not (dest / "kaine-dashboard.container").exists()


def test_install_leaves_unmanaged_old_unit_in_place(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    checkout = tmp_path / "checkout"
    script = _make_checkout(checkout)
    dest = tmp_path / "dest"
    old_path = _make_dest_with_old_unit(dest, "[Container]\n")
    state_file = tmp_path / "systemctl.state"
    state_file.write_text("inactive")
    code_file = tmp_path / "systemctl.code"
    code_file.write_text("0")
    fake_systemctl = _write_fake_systemctl(tmp_path)

    result = _run(
        script,
        "--root",
        str(checkout),
        "--dest",
        str(dest),
        "--generator",
        "none",
        cwd=checkout,
        env={
            "KAINE_SYSTEMCTL": str(fake_systemctl),
            "FAKE_SYSTEMCTL_STATE_FILE": str(state_file),
            "FAKE_SYSTEMCTL_CODE_FILE": str(code_file),
        },
    )

    assert result.returncode == 0, result.stderr
    assert old_path.exists()
    assert "left" in result.stderr
    assert "it was not installed by this script" in result.stderr
    assert (dest / "kaine-dashboard.container").exists()


def test_install_dry_run_reports_old_renamed_unit_removal(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    checkout = tmp_path / "checkout"
    script = _make_checkout(checkout)
    dest = tmp_path / "dest"
    old_path = _make_dest_with_old_unit(dest, _old_unit_content(checkout))
    state_file = tmp_path / "systemctl.state"
    state_file.write_text("inactive")
    code_file = tmp_path / "systemctl.code"
    code_file.write_text("0")
    fake_systemctl = _write_fake_systemctl(tmp_path)

    result = _run(
        script,
        "--root",
        str(checkout),
        "--dest",
        str(dest),
        "--generator",
        "none",
        "--dry-run",
        cwd=checkout,
        env={
            "KAINE_SYSTEMCTL": str(fake_systemctl),
            "FAKE_SYSTEMCTL_STATE_FILE": str(state_file),
            "FAKE_SYSTEMCTL_CODE_FILE": str(code_file),
        },
    )

    assert result.returncode == 0, result.stderr
    assert old_path.exists()
    assert f"would remove old unit {OLD_UNIT} (renamed to kaine-dashboard.container)" in result.stdout


def test_install_leaves_an_old_unit_rendered_from_another_checkout(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    checkout = tmp_path / "checkout"
    script = _make_checkout(checkout)
    dest = tmp_path / "dest"
    old_path = _make_dest_with_old_unit(
        dest,
        "# SPDX-License-Identifier: LicenseRef-CAL-0.4\n[Container]\n"
        "Volume=/elsewhere/config/kaine.operator.toml:/app/config/kaine.operator.toml:ro,Z\n",
    )
    state_file = tmp_path / "systemctl.state"
    state_file.write_text("inactive")
    code_file = tmp_path / "systemctl.code"
    code_file.write_text("0")
    fake_systemctl = _write_fake_systemctl(tmp_path)

    result = _run(
        script,
        "--root",
        str(checkout),
        "--dest",
        str(dest),
        "--generator",
        "none",
        cwd=checkout,
        env={
            "KAINE_SYSTEMCTL": str(fake_systemctl),
            "FAKE_SYSTEMCTL_STATE_FILE": str(state_file),
            "FAKE_SYSTEMCTL_CODE_FILE": str(code_file),
        },
    )

    assert result.returncode == 0, result.stderr
    assert old_path.exists()


def test_install_refuses_when_systemctl_state_cannot_be_determined(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    checkout = tmp_path / "checkout"
    script = _make_checkout(checkout)
    dest = tmp_path / "dest"
    old_path = _make_dest_with_old_unit(dest, _old_unit_content(checkout))
    state_file = tmp_path / "systemctl.state"
    state_file.write_text("")
    code_file = tmp_path / "systemctl.code"
    code_file.write_text("1")
    fake_systemctl = _write_fake_systemctl(tmp_path)

    result = _run(
        script,
        "--root",
        str(checkout),
        "--dest",
        str(dest),
        "--generator",
        "none",
        cwd=checkout,
        env={
            "KAINE_SYSTEMCTL": str(fake_systemctl),
            "FAKE_SYSTEMCTL_STATE_FILE": str(state_file),
            "FAKE_SYSTEMCTL_CODE_FILE": str(code_file),
        },
    )

    assert result.returncode == 1
    assert old_path.exists()
    assert not (dest / "kaine-dashboard.container").exists()
    assert "systemctl --user stop" in result.stderr


def test_install_refuses_when_old_service_is_activating(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    checkout = tmp_path / "checkout"
    script = _make_checkout(checkout)
    dest = tmp_path / "dest"
    old_path = _make_dest_with_old_unit(dest, _old_unit_content(checkout))
    state_file = tmp_path / "systemctl.state"
    state_file.write_text("activating")
    code_file = tmp_path / "systemctl.code"
    code_file.write_text("0")
    fake_systemctl = _write_fake_systemctl(tmp_path)

    result = _run(
        script,
        "--root",
        str(checkout),
        "--dest",
        str(dest),
        "--generator",
        "none",
        cwd=checkout,
        env={
            "KAINE_SYSTEMCTL": str(fake_systemctl),
            "FAKE_SYSTEMCTL_STATE_FILE": str(state_file),
            "FAKE_SYSTEMCTL_CODE_FILE": str(code_file),
        },
    )

    assert result.returncode == 1
    assert old_path.exists()
    assert not (dest / "kaine-dashboard.container").exists()
    assert "systemctl --user stop" in result.stderr


def test_install_refuses_when_systemctl_binary_is_missing(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    checkout = tmp_path / "checkout"
    script = _make_checkout(checkout)
    dest = tmp_path / "dest"
    old_path = _make_dest_with_old_unit(dest, _old_unit_content(checkout))
    missing_systemctl = tmp_path / "does-not-exist" / "systemctl"

    result = _run(
        script,
        "--root",
        str(checkout),
        "--dest",
        str(dest),
        "--generator",
        "none",
        cwd=checkout,
        env={"KAINE_SYSTEMCTL": str(missing_systemctl)},
    )

    assert result.returncode == 1
    assert old_path.exists()
    assert not (dest / "kaine-dashboard.container").exists()
    assert "systemctl --user stop" in result.stderr


def test_install_removes_old_renamed_unit_when_state_is_failed(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    checkout = tmp_path / "checkout"
    script = _make_checkout(checkout)
    dest = tmp_path / "dest"
    old_path = _make_dest_with_old_unit(dest, _old_unit_content(checkout))
    state_file = tmp_path / "systemctl.state"
    state_file.write_text("failed")
    code_file = tmp_path / "systemctl.code"
    code_file.write_text("0")
    fake_systemctl = _write_fake_systemctl(tmp_path)

    result = _run(
        script,
        "--root",
        str(checkout),
        "--dest",
        str(dest),
        "--generator",
        "none",
        cwd=checkout,
        env={
            "KAINE_SYSTEMCTL": str(fake_systemctl),
            "FAKE_SYSTEMCTL_STATE_FILE": str(state_file),
            "FAKE_SYSTEMCTL_CODE_FILE": str(code_file),
        },
    )

    assert result.returncode == 0, result.stderr
    assert not old_path.exists()
    assert (dest / "kaine-dashboard.container").exists()
    assert f"removed old unit {OLD_UNIT} (renamed to kaine-dashboard.container)" in result.stdout
