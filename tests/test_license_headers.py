# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Tests that every first-party Python source file carries the SPDX header.

Also asserts that the root NOTICE file exists and references the
Cognitive Architecture License.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys


# ---------------------------------------------------------------------------
# Import check_license_headers from scripts/ without requiring it to be an
# installed package.  We locate it relative to the repo root.
# ---------------------------------------------------------------------------
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_CHECKER_PATH = _REPO_ROOT / "scripts" / "check_license_headers.py"

if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

spec = importlib.util.spec_from_file_location("check_license_headers", _CHECKER_PATH)
_checker = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(_checker)  # type: ignore[union-attr]

missing_headers = _checker.missing_headers


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_all_first_party_files_have_spdx_header() -> None:
    """Every first-party .py file must carry the SPDX license header."""
    offenders = missing_headers()
    assert offenders == [], (
        f"{len(offenders)} first-party .py file(s) are missing the SPDX header:\n"
        + "\n".join(f"  {f}" for f in offenders)
    )


def test_notice_file_exists() -> None:
    """The root NOTICE file must exist."""
    notice = _REPO_ROOT / "NOTICE"
    assert notice.exists(), "Root NOTICE file is missing"


def test_notice_references_cal() -> None:
    """The root NOTICE file must mention the Cognitive Architecture License."""
    notice = _REPO_ROOT / "NOTICE"
    text = notice.read_text(encoding="utf-8")
    assert "Cognitive Architecture License" in text, (
        "NOTICE does not reference the Cognitive Architecture License"
    )
