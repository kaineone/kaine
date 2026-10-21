# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""No module under kaine/ may define the same top-level function or class twice.

A second definition silently shadows the first, leaving dead code that drifts.
Definitions nested in if/else/try/except branches are exempt (conditional
alternatives are legitimate).
"""

import ast
from pathlib import Path

KAINE_ROOT = Path(__file__).resolve().parent.parent / "kaine"

# (module path relative to kaine/, name) pairs pending review.
ALLOWLIST: set[tuple[str, str]] = set()

_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _duplicates() -> list[str]:
    problems: list[str] = []
    for path in sorted(KAINE_ROOT.rglob("*.py")):
        rel = path.relative_to(KAINE_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        seen: dict[str, int] = {}
        for node in tree.body:
            if not isinstance(node, _DEFS):
                continue
            if node.name in seen and (rel, node.name) not in ALLOWLIST:
                problems.append(
                    f"{rel}: {node.name} defined at line {seen[node.name]} and line {node.lineno}"
                )
            seen.setdefault(node.name, node.lineno)
    return problems


def test_no_duplicate_top_level_names() -> None:
    problems = _duplicates()
    assert not problems, "duplicate top-level definitions:\n" + "\n".join(problems)
