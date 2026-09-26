# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""JavaScript tests for the Nexus birth development panel."""

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
SOURCE = STATIC_DIR / "nexus_birth.js"
PANEL = TEMPLATE_DIR / "_development_panel.html"
HARNESS = ROOT / "tests" / "js" / "nexus_birth_harness.js"


def test_nexus_birth_js_syntax():
    if not shutil.which("node"):
        pytest.skip("node not available")
    result = subprocess.run(
        ["node", "--check", str(SOURCE)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not shutil.which("node"), reason="node not available")
def test_nexus_birth_js_harness():
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


def test_development_panel_no_inline_handlers():
    text = PANEL.read_text(encoding="utf-8")
    assert not re.search(r"\son\w+\s*=", text, re.IGNORECASE)
