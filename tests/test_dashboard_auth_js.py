# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE_TEMPLATE = ROOT / "kaine" / "dashboard" / "templates" / "_base.html"
AUTH_JS = ROOT / "kaine" / "dashboard" / "static" / "dashboard_auth.js"
AUTH_HARNESS = ROOT / "tests" / "js" / "dashboard_auth_harness.js"


def test_base_template_loads_auth_script_first():
    html = BASE_TEMPLATE.read_text(encoding="utf-8")
    head_match = re.search(r"<head\b[^>]*>(.*?)</head>", html, re.IGNORECASE | re.DOTALL)
    assert head_match, "_base.html has no <head> section"

    head = head_match.group(1)
    scripts = re.findall(r"<script\b[^>]*>", head, re.IGNORECASE | re.DOTALL)
    assert scripts, "expected at least one <script> in <head>"

    # The storage helper only defines a function and fetches nothing, so it may
    # load first; dashboard_auth.js must still wrap fetch before any other script.
    others = [s for s in scripts if "/static/dashboard_legacy_storage.js" not in s]
    assert others, "expected dashboard_auth.js in <head>"
    assert "/static/dashboard_auth.js" in others[0], (
        "dashboard_auth.js must be the first script loaded in <head> after the storage helper"
    )


def test_logout_button_in_base_template():
    html = BASE_TEMPLATE.read_text(encoding="utf-8")
    assert 'id="dashboard-logout"' in html, "rail logout button missing"

    match = re.search(
        r'<button\b[^>]*\bid="dashboard-logout"[^>]*>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    assert match, "could not locate the logout button tag"

    tag = match.group(0)
    assert not re.search(r"\bon\w+\s*=", tag, re.IGNORECASE), (
        "logout button must not use inline event-handler attributes"
    )


def test_dashboard_auth_js_required_content():
    text = AUTH_JS.read_text(encoding="utf-8")

    for needle in ("X-Dashboard-Session-Key", "kaine.dashboard.sessionKey", "localStorage"):
        assert needle in text, f"{needle!r} missing from dashboard_auth.js"

    for forbidden in ("document.cookie", "eval("):
        assert forbidden not in text, f"{forbidden!r} must not appear in dashboard_auth.js"


def test_dashboard_auth_js_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")

    result = subprocess.run(
        [node, "--check", str(AUTH_JS)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"node --check failed for {AUTH_JS}:\n{result.stdout}\n{result.stderr}"
    )


def test_dashboard_auth_js_behavioural():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")

    result = subprocess.run(
        [node, "tests/js/dashboard_auth_harness.js"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"behavioural harness failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
