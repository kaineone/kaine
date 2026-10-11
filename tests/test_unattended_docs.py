# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Docs-consistency checks for unattended boot."""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _refusal_rows() -> dict[str, str]:
    text = (_REPO_ROOT / "docs" / "14-for-researchers.md").read_text()
    rows: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\|\s*`(\d+)`\s*\|", line.strip())
        if match:
            rows[match.group(1)] = line.strip()
    return rows


def test_refusal_table_keeps_2_and_5_and_adds_6():
    rows = _refusal_rows()
    assert rows["2"] == (
        "| `2` | Operator-present gate: none of `KAINE_CYCLE_OPERATOR_PRESENT=1`, "
        "research mode or unattended mode |"
    )
    assert rows["5"] == (
        "| `5` | Research safety net not live and verified "
        "(one or more of the six conditions failed) |"
    )
    assert rows["6"] == "| `6` | Unattended gate: one or more of its nine conditions failed |"
    # The organ content gate and the individuation refusal have their own codes.
    assert "organ content gate" in rows["9"].lower()
    assert "individuation" in rows["10"].lower()


def test_operations_guide_documents_unattended_starts():
    operations = (_REPO_ROOT / "docs" / "11-preservation.md").read_text()
    assert any(
        line.strip().lstrip("#").strip() == "Unattended starts"
        for line in operations.splitlines()
    )
    assert "KAINE_CYCLE_UNATTENDED" in operations
    assert re.search(r"exit\s+`?6`?", operations)


def test_preservation_guide_lists_nine_unattended_conditions():
    operations = (_REPO_ROOT / "docs" / "11-preservation.md").read_text()
    assert "Every unattended start checks nine conditions" in operations
    assert "The individuation requirement applies to research mode only" not in operations


def test_researchers_guide_counts_all_six_net_conditions_for_unattended():
    researchers = (_REPO_ROOT / "docs" / "14-for-researchers.md").read_text()
    assert "Besides the six research-safety-net conditions" in researchers
    assert "all but the individuation" not in researchers
