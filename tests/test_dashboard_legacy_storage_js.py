# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE_TEMPLATE = ROOT / "kaine" / "dashboard" / "templates" / "_base.html"
LEGACY_STORAGE_JS = ROOT / "kaine" / "dashboard" / "static" / "dashboard_legacy_storage.js"
LEGACY_STORAGE_HARNESS = ROOT / "tests" / "js" / "dashboard_legacy_storage_harness.js"


def test_dashboard_legacy_storage_js_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")

    result = subprocess.run(
        [node, "--check", str(LEGACY_STORAGE_JS)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"node --check failed for {LEGACY_STORAGE_JS}:\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_dashboard_legacy_storage_js_behavioural():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")

    result = subprocess.run(
        [node, str(LEGACY_STORAGE_HARNESS)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"behavioural test script failed:\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_base_template_loads_legacy_storage_before_auth():
    content = BASE_TEMPLATE.read_text()
    legacy_pos = content.find("/static/dashboard_legacy_storage.js")
    auth_pos = content.find("/static/dashboard_auth.js")
    assert legacy_pos != -1, "_base.html should load dashboard_legacy_storage.js"
    assert auth_pos != -1, "_base.html should load dashboard_auth.js"
    assert legacy_pos < auth_pos, "legacy storage script must load before auth script"


def test_dashboard_scripts_migrate_their_storage_keys():
    static = ROOT / "kaine" / "dashboard" / "static"
    auth = (static / "dashboard_auth.js").read_text(encoding="utf-8")
    main = (static / "dashboard.js").read_text(encoding="utf-8")
    assert "DashboardLegacyStorage.migrate(window.localStorage, STORAGE_KEY)" in auth
    assert "DashboardLegacyStorage.migrate(window.sessionStorage, STORE_KEY)" in main
