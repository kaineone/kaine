# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""JavaScript tests for the Nexus caretaker banner."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "kaine" / "nexus" / "static"
TEMPLATE_DIR = ROOT / "kaine" / "nexus" / "templates"
SOURCE = STATIC_DIR / "nexus_caretaker.js"
BANNER = TEMPLATE_DIR / "_caretaker_banner.html"
BASE = TEMPLATE_DIR / "_base.html"
HARNESS = ROOT / "tests" / "js" / "nexus_caretaker_harness.js"


def test_nexus_caretaker_js_syntax():
    if not shutil.which("node"):
        pytest.skip("node not available")
    result = subprocess.run(
        ["node", "--check", str(SOURCE)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not shutil.which("node"), reason="node not available")
def test_nexus_caretaker_js_harness():
    result = subprocess.run(
        ["node", str(HARNESS)],
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    print(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads(result.stdout.splitlines()[-1])
    assert output["ok"] is True


def test_base_html_includes_caretaker_banner():
    text = BASE.read_text(encoding="utf-8")
    assert '{% include "_caretaker_banner.html" %}' in text


def test_base_html_loads_caretaker_script():
    text = BASE.read_text(encoding="utf-8")
    assert re.search(
        r'<script[^>]*(?:nexus_caretaker\.js[^>]*defer|defer[^>]*nexus_caretaker\.js)',
        text,
        re.DOTALL,
    )


def test_caretaker_banner_no_inline_handlers():
    text = BANNER.read_text(encoding="utf-8")
    assert not re.search(r"\son\w+\s*=", text, re.IGNORECASE)
