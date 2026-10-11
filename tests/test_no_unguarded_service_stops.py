# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Source guard: every process-control site must be in the allowlist."""

from __future__ import annotations

import ast
from pathlib import Path

ALLOWED_STOP_SITES = {
    # Guarded by is_shared(config, "model_server"); returns early when shared.
    ("kaine/organ_server/lifecycle.py", "cmd_stop"),
    # Only reached when hot_swap_mode="restart_service"; make_hypnos forces
    # hot_swap_mode to "manual" whenever the model server is shared.
    ("kaine/modules/hypnos/hot_swap.py", "_do_restart_service"),
}


def _function_for_line(tree: ast.AST, lineno: int) -> str:
    """Return the innermost function/method that contains ``lineno``."""
    best = "<module>"
    best_span = float("inf")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", start)
            if start <= lineno <= end:
                span = end - start
                if span < best_span:
                    best_span = span
                    best = node.name
    return best


def test_no_unreviewed_service_stops():
    repo_root = Path(__file__).resolve().parents[1]
    kaine_dir = repo_root / "kaine"
    found: set[tuple[str, str]] = set()

    for path in kaine_dir.rglob("*.py"):
        rel = path.relative_to(repo_root).as_posix()
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        # Any list literal that begins with "systemctl" and contains a stop verb.
        for node in ast.walk(tree):
            if isinstance(node, ast.List) and node.elts:
                first = node.elts[0]
                if isinstance(first, ast.Constant) and first.value == "systemctl":
                    for elt in node.elts[1:]:
                        if (
                            isinstance(elt, ast.Constant)
                            and isinstance(elt.value, str)
                            and elt.value in {"stop", "restart", "disable"}
                        ):
                            func = _function_for_line(tree, node.lineno)
                            found.add((rel, func))
                            break

        # os.kill(...) calls; signal 0 is a liveness probe, not a stop.
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_os_kill = (
                isinstance(func, ast.Attribute)
                and func.attr == "kill"
                and isinstance(func.value, ast.Name)
                and func.value.id == "os"
            ) or (isinstance(func, ast.Name) and func.id == "kill")
            if not is_os_kill:
                continue
            if len(node.args) < 2:
                continue
            sig_arg = node.args[1]
            if isinstance(sig_arg, ast.Constant) and sig_arg.value == 0:
                continue
            func = _function_for_line(tree, getattr(node, "lineno", 1))
            found.add((rel, func))

    assert found == ALLOWED_STOP_SITES
