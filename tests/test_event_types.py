# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import ast
from pathlib import Path

import kaine.bus.event_types as event_types

_ROOT = Path(__file__).resolve().parent.parent


def test_constants_are_strings_without_whitespace() -> None:
    for name in dir(event_types):
        if name.startswith("_") or not name.isupper():
            continue
        value = getattr(event_types, name)
        if isinstance(value, tuple):
            assert value, f"{name} is empty"
            for item in value:
                assert isinstance(item, str) and item
                assert not any(ch.isspace() for ch in item)
        else:
            assert isinstance(value, str) and value
            assert not any(ch.isspace() for ch in value)


def test_event_types_module_imports_nothing_from_kaine() -> None:
    path = _ROOT / "kaine" / "bus" / "event_types.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("kaine"), alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert not node.module.startswith("kaine"), node.module
            if node.level:
                # relative imports cannot reach kaine
                pass


def test_workspace_and_cycle_compare_no_type_literals() -> None:
    from tests.test_conventions import count_calls

    for base in ("kaine/workspace", "kaine/cycle"):
        for path in sorted((_ROOT / base).rglob("*.py")):
            counts = count_calls(path.read_text(encoding="utf-8"))
            assert counts["type_literal"] == 0, (path, counts["type_literal"])
