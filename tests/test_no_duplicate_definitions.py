# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""No scope under kaine/ may define the same name twice in its own body.

A second definition silently shadows the first, leaving dead code that drifts.
Three scopes are checked, at any depth: module bodies (functions and classes),
class bodies (methods) and function bodies (nested functions). Only direct
body members count, so alternatives in different branches of if/else and
try/except/else/finally are exempt. Also exempt: a property getter followed by
``@<name>.setter`` / ``@<name>.deleter`` definitions, ``typing.overload``
stubs, and ``@<name>.register`` registrations.
"""

import ast
from pathlib import Path

import pytest

KAINE_ROOT = Path(__file__).resolve().parent.parent / "kaine"

# (module path relative to kaine/, container, name) triples pending review.
ALLOWLIST: set[tuple[str, str, str]] = set()

_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
_ACCESSORS = {"setter", "deleter", "getter", "register"}


def _is_overload(deco: ast.expr) -> bool:
    if isinstance(deco, ast.Call):
        deco = deco.func
    if isinstance(deco, ast.Name):
        return deco.id == "overload"
    return isinstance(deco, ast.Attribute) and deco.attr == "overload"


def _is_accessor(deco: ast.expr, name: str) -> bool:
    """True for ``@<name>.setter`` and friends, or any ``@<x>.register``."""
    if isinstance(deco, ast.Call):
        deco = deco.func
    if not (isinstance(deco, ast.Attribute) and deco.attr in _ACCESSORS):
        return False
    if deco.attr == "register":
        return True
    return isinstance(deco.value, ast.Name) and deco.value.id == name


def _check_body(
    body: list[ast.stmt], kinds: tuple[type, ...], module: str, container: str
) -> list[str]:
    problems: list[str] = []
    seen: dict[str, int] = {}
    overloaded: set[str] = set()
    for node in body:
        if not isinstance(node, kinds):
            continue
        name = node.name  # type: ignore[attr-defined]
        decos = getattr(node, "decorator_list", [])
        is_overload = any(_is_overload(d) for d in decos)
        if is_overload:
            overloaded.add(name)
        allowed = (
            is_overload
            or name in overloaded
            or any(_is_accessor(d, name) for d in decos)
            or (module, container, name) in ALLOWLIST
        )
        if name in seen and not allowed:
            problems.append(
                f"{module}: {container}: {name} defined at line {seen[name]} and line {node.lineno}"
            )
        seen.setdefault(name, node.lineno)
    return problems


def find_duplicates(source: str, module: str = "<module>") -> list[str]:
    """Return one message per duplicate definition found in ``source``."""
    tree = ast.parse(source, filename=module)
    problems = _check_body(tree.body, (*_FUNCS, ast.ClassDef), module, "<module>")

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                qual = f"{prefix}{child.name}"
                problems.extend(_check_body(child.body, _FUNCS, module, qual))
                visit(child, qual + ".")
            elif isinstance(child, _FUNCS):
                qual = f"{prefix}{child.name}"
                problems.extend(_check_body(child.body, _FUNCS, module, qual))
                visit(child, qual + ".")
            else:
                visit(child, prefix)

    visit(tree, "")
    return problems


def _duplicates() -> list[str]:
    problems: list[str] = []
    for path in sorted(KAINE_ROOT.rglob("*.py")):
        rel = path.relative_to(KAINE_ROOT).as_posix()
        problems.extend(find_duplicates(path.read_text(encoding="utf-8"), rel))
    return problems


def test_no_duplicate_definitions() -> None:
    problems = _duplicates()
    assert not problems, "duplicate definitions:\n" + "\n".join(problems)


def test_reports_duplicate_method() -> None:
    src = (
        "class C:\n"
        "    def observe(self):\n"
        "        return 1\n"
        "    def observe(self):\n"
        "        return 2\n"
    )
    assert find_duplicates(src, "m.py") == ["m.py: C: observe defined at line 2 and line 4"]


def test_reports_duplicate_nested_function() -> None:
    src = "def outer():\n    def helper():\n        pass\n    def helper():\n        pass\n"
    assert find_duplicates(src, "m.py") == ["m.py: outer: helper defined at line 2 and line 4"]


def test_reports_duplicate_module_function_and_async_method() -> None:
    src = "def f(): ...\ndef f(): ...\nclass C:\n    async def g(self): ...\n    async def g(self): ...\n"
    assert len(find_duplicates(src)) == 2


def test_property_setter_and_deleter_allowed() -> None:
    src = (
        "class C:\n"
        "    @property\n"
        "    def x(self): return 1\n"
        "    @x.setter\n"
        "    def x(self, v): ...\n"
        "    @x.deleter\n"
        "    def x(self): ...\n"
    )
    assert find_duplicates(src) == []


def test_overload_stubs_allowed() -> None:
    src = (
        "import typing\n"
        "from typing import overload\n"
        "class C:\n"
        "    @overload\n"
        "    def f(self, a: int) -> int: ...\n"
        "    @typing.overload\n"
        "    def f(self, a: str) -> str: ...\n"
        "    def f(self, a): return a\n"
    )
    assert find_duplicates(src) == []


def test_if_else_and_try_branches_allowed() -> None:
    src = (
        "if X:\n"
        "    def f(): ...\n"
        "else:\n"
        "    def f(): ...\n"
        "class C:\n"
        "    if X:\n"
        "        def m(self): ...\n"
        "    else:\n"
        "        def m(self): ...\n"
        "def outer():\n"
        "    try:\n"
        "        def h(): ...\n"
        "    except ImportError:\n"
        "        def h(): ...\n"
    )
    assert find_duplicates(src) == []


def test_singledispatch_register_allowed() -> None:
    src = (
        "@singledispatch\n"
        "def f(x): ...\n"
        "@f.register\n"
        "def _(x: int): ...\n"
        "@f.register\n"
        "def _(x: str): ...\n"
    )
    assert find_duplicates(src) == []


@pytest.mark.parametrize("depth", [1, 2])
def test_nested_class_method_duplicate_found(depth: int) -> None:
    inner = "class In:\n    def a(self): ...\n    def a(self): ...\n"
    src = "def f():\n    " + inner.replace("\n", "\n    ").rstrip() + "\n" if depth == 2 else inner
    assert len(find_duplicates(src)) == 1
