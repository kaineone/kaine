# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE_TEMPLATE = ROOT / "kaine" / "nexus" / "templates" / "_base.html"
AUTH_JS = ROOT / "kaine" / "nexus" / "static" / "nexus_auth.js"
AUTH_HARNESS = ROOT / "tests" / "js" / "nexus_auth_harness.js"


def test_base_template_loads_auth_script_first():
    html = BASE_TEMPLATE.read_text(encoding="utf-8")
    head_match = re.search(r"<head\b[^>]*>(.*?)</head>", html, re.IGNORECASE | re.DOTALL)
    assert head_match, "_base.html has no <head> section"

    head = head_match.group(1)
    scripts = re.findall(r"<script\b[^>]*>", head, re.IGNORECASE | re.DOTALL)
    assert scripts, "expected at least one <script> in <head>"

    first_script = scripts[0]
    assert "/static/nexus_auth.js" in first_script, (
        "nexus_auth.js must be the first script loaded in <head>"
    )


def test_nexus_auth_js_required_content():
    text = AUTH_JS.read_text(encoding="utf-8")

    for needle in ("X-Nexus-Session-Key", "kaine.nexus.sessionKey", "localStorage"):
        assert needle in text, f"{needle!r} missing from nexus_auth.js"

    for forbidden in ("document.cookie", "eval("):
        assert forbidden not in text, f"{forbidden!r} must not appear in nexus_auth.js"


def test_nexus_auth_js_syntax():
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


def test_nexus_auth_js_behavioural():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")

    result = subprocess.run(
        [node, "tests/js/nexus_auth_harness.js"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"behavioural harness failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
