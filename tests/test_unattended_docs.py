# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Docs-consistency checks for unattended boot."""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _refusal_rows() -> dict[str, str]:
    text = (_REPO_ROOT / "docs" / "for-researchers.md").read_text()
    rows: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\|\s*`(\d+)`\s*\|", line.strip())
        if match:
            rows[match.group(1)] = line.strip()
    return rows


def test_refusal_table_keeps_2_and_5_and_adds_6():
    rows = _refusal_rows()
    assert rows["2"] == (
        "| `2` | Operator-present gate: neither `KAINE_CYCLE_OPERATOR_PRESENT=1` "
        "nor research mode |"
    )
    assert rows["5"] == (
        "| `5` | Research safety net not live and verified "
        "(one or more of the five conditions failed) |"
    )
    assert "unattended" in rows["6"].lower()


def test_operations_guide_documents_unattended_starts():
    operations = (_REPO_ROOT / "docs" / "operations.md").read_text()
    assert any(
        line.strip().lstrip("#").strip() == "Unattended starts"
        for line in operations.splitlines()
    )
    assert "KAINE_CYCLE_UNATTENDED" in operations
    assert re.search(r"exit\s+`?6`?", operations)
