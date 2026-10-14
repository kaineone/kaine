# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import os
import subprocess
from pathlib import Path

import pytest

from kaine import legacy_names

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "prepare-headless-host.sh"

OLD_FLAG = next(e["old"] for e in legacy_names.CLI_FLAGS if e["new"] == "--serve-dashboard")


@pytest.mark.skipif(os.geteuid() == 0, reason="script refuses root")
def test_prepare_headless_host_deprecated_dashboard_flag_still_recognized(tmp_path):
    result = subprocess.run(
        ["bash", str(_SCRIPT), "--dry-run", "--phase1", OLD_FLAG],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "is deprecated, use --serve-dashboard" in result.stderr
    assert "serve-dashboard=1" in result.stdout


@pytest.mark.skipif(os.geteuid() == 0, reason="script refuses root")
def test_prepare_headless_host_new_dashboard_flag_is_recognized(tmp_path):
    result = subprocess.run(
        ["bash", str(_SCRIPT), "--dry-run", "--phase1", "--serve-dashboard"],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "serve-dashboard=1" in result.stdout
    assert "is deprecated" not in result.stderr
