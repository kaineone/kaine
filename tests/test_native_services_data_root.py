# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for native service data-root awareness."""

import shutil
import subprocess
from pathlib import Path

import pytest

from kaine.setup.data_root import main


def test_main_root_prints_configured_data_root(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "kaine.config.load_kaine_config",
        lambda: {"storage": {"data_root": str(tmp_path)}},
    )
    assert main(["root"]) == 0
    assert capsys.readouterr().out.strip() == str(tmp_path)


@pytest.mark.no_data_root
def test_main_root_prints_nothing_when_unset(monkeypatch, capsys):
    monkeypatch.setattr("kaine.config.load_kaine_config", lambda: {})
    assert main(["root"]) == 0
    assert capsys.readouterr().out == ""


def test_main_bogus_argv_prints_usage_and_returns_2(capsys):
    assert main(["bogus"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage: python -m kaine.setup.data_root root" in captured.err


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_kaine_services_dir_uses_configured_root(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    fake_py = tmp_path / "fake-python"
    fake_py.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-m" ] && [ "$2" = "kaine.setup.data_root" ] && [ "$3" = "root" ]; then\n'
        '    echo /data/root\n'
        "fi\n"
    )
    fake_py.chmod(0o755)
    cmd = (
        f"set -euo pipefail; "
        f"ROOT={repo}; PY={fake_py}; KAINE_SERVICES_SUPERVISOR=pidfile; "
        f"source {repo}/scripts/lib/native-services.sh; kaine_services_dir"
    )
    result = subprocess.run(
        ["bash", "-c", cmd],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "/data/root/state/services"
    assert result.stderr == ""


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_kaine_services_dir_falls_back_to_checkout(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    fake_py = tmp_path / "fake-python"
    fake_py.write_text("#!/bin/sh\n")
    fake_py.chmod(0o755)
    cmd = (
        f"set -euo pipefail; "
        f"ROOT={repo}; PY={fake_py}; KAINE_SERVICES_SUPERVISOR=pidfile; "
        f"source {repo}/scripts/lib/native-services.sh; kaine_services_dir"
    )
    result = subprocess.run(
        ["bash", "-c", cmd],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == f"{repo}/state/services"
    assert result.stderr == ""
