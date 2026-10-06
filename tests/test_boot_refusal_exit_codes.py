# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import ast
from pathlib import Path

from kaine.cycle.__main__ import (
    IDENTITY_REFUSED_EXIT,
    INDIVIDUATION_REFUSED_EXIT,
    ORGAN_GATE_REFUSED_EXIT,
    WELFARE_PRODUCER_REFUSED_EXIT,
)
from kaine.cycle.research_gate import RESEARCH_GATE_EXIT_CODE
from kaine.cycle.revive_boot import REVIVE_REFUSED_EXIT
from kaine.cycle.unattended_gate import UNATTENDED_GATE_EXIT_CODE


def test_boot_refusal_exit_codes_are_distinct_and_documented():
    """Each boot refusal has its own exit code and a matching docs row."""
    codes = {
        1,
        2,
        3,
        4,
        RESEARCH_GATE_EXIT_CODE,
        UNATTENDED_GATE_EXIT_CODE,
        REVIVE_REFUSED_EXIT,
        WELFARE_PRODUCER_REFUSED_EXIT,
        ORGAN_GATE_REFUSED_EXIT,
        INDIVIDUATION_REFUSED_EXIT,
        IDENTITY_REFUSED_EXIT,
        70,
    }
    assert len(codes) == 12, f"Expected 12 distinct codes, got {codes}"

    repo_root = Path(__file__).resolve().parents[1]
    # The boot runs as phases (tests/_boot_sequence.py walks them in order);
    # none of them may return the research gate's code for another refusal.
    from tests._boot_sequence import boot_functions

    for fn in boot_functions():
        for sub in ast.walk(fn):
            if not isinstance(sub, ast.Return):
                continue
            value = sub.value
            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, int)
                and value.value == 5
            ):
                raise AssertionError(
                    f"Found literal return 5 at line {sub.lineno} in {fn.name}"
                )

    docs_path = repo_root / "docs" / "14-for-researchers.md"
    docs_text = docs_path.read_text(encoding="utf-8")
    documented = set()
    for line in docs_text.splitlines():
        if line.startswith("| `"):
            try:
                code_part = line.split("|")[1].strip().strip("`")
                documented.add(int(code_part))
            except (ValueError, IndexError):
                continue

    for code in codes:
        if code == 70:
            continue
        assert code in documented, f"Exit code {code} missing from docs table"
