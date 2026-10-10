# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The cycle boot's calls, in boot order, for tests that pin that order.

``_boot_and_run`` cannot run in tests (it boots an entity), so order tests
read its source instead. The boot runs the phases listed in ``_BOOT_PHASES``,
then ``_run_until_stopped``, then ``_shutdown``; this walks them in that order.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path


def boot_functions() -> list[ast.AST]:
    """The boot's function definitions in the order the boot runs them."""
    spec = importlib.util.find_spec("kaine.cycle.__main__")
    assert spec is not None and spec.origin is not None
    tree = ast.parse(Path(spec.origin).read_text())
    defs = {
        n.name: n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    phases = next(
        n.value
        for n in tree.body
        if isinstance(n, ast.Assign)
        and isinstance(n.targets[0], ast.Name)
        and n.targets[0].id == "_BOOT_PHASES"
    )
    names = [e.id for e in phases.elts] + ["_run_until_stopped", "_shutdown"]
    return [defs[name] for name in names]


def boot_calls() -> list[tuple[str, ast.Call]]:
    """Every call the boot makes, as ``(callee name, node)``, in boot order."""
    out: list[tuple[str, ast.Call]] = []
    for fn in boot_functions():
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
        calls.sort(key=lambda n: (n.lineno, n.col_offset))
        for n in calls:
            f = n.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            out.append((name, n))
    return out


def first_index(name: str) -> int:
    """Position of the boot's first call to ``name``."""
    for i, (callee, _) in enumerate(boot_calls()):
        if callee == name:
            return i
    raise AssertionError(f"{name} is never called during boot")
