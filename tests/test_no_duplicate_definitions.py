# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""No scope under kaine/ may define the same name twice in its own body.

A second definition silently shadows the first, leaving dead code that drifts.
Three scopes are checked, at any depth: module bodies, class bodies and
function bodies, each for functions and classes. Every block of a compound
statement (each if/elif/else branch, try body, handler, else and finally, with,
for, while and match-case body) is checked as part of its enclosing scope, but
separate branches are exempt from each other. Also exempt: property setters,
deleters and getters of an earlier property, ``overload`` stubs plus at most
one trailing implementation, and ``singledispatch`` registrations.
"""

import ast
import sys
from pathlib import Path

import pytest

KAINE_ROOT = Path(__file__).resolve().parent.parent / "kaine"
MIN_FILES_SCANNED = 400

# (module path relative to kaine/, container, name) triples pending review.
# A stale entry (one matching no current duplicate) fails the test suite.
ALLOWLIST: set[tuple[str, str, str]] = set()

_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)
_DEFS = (*_FUNCS, ast.ClassDef)
_ACCESSORS = {"setter", "deleter", "getter"}
_TYPING_MODULES = {"typing", "typing_extensions"}

Found = tuple[str, str, str, str]  # module, container, name, message


def _child_blocks(stmt: ast.stmt) -> list[list[ast.stmt]]:
    """Statement lists directly owned by a compound statement (same scope)."""
    if isinstance(stmt, ast.If):
        return [stmt.body, stmt.orelse]
    if isinstance(stmt, (ast.Try, ast.TryStar)):
        return [stmt.body, *(h.body for h in stmt.handlers), stmt.orelse, stmt.finalbody]
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        return [stmt.body]
    if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
        return [stmt.body, stmt.orelse]
    if isinstance(stmt, ast.Match):
        return [case.body for case in stmt.cases]
    return []


def _blocks(body: list[ast.stmt]) -> list[list[ast.stmt]]:
    out = [body]
    for stmt in body:
        for sub in _child_blocks(stmt):
            out.extend(_blocks(sub))
    return out


def _overload_names(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Names bound to ``overload`` and names bound to the typing modules."""
    funcs = {"overload"}
    mods = set(_TYPING_MODULES)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in _TYPING_MODULES:
            funcs.update(a.asname or a.name for a in node.names if a.name == "overload")
        elif isinstance(node, ast.Import):
            mods.update(a.asname for a in node.names if a.name in _TYPING_MODULES and a.asname)
    return funcs, mods


def _target(deco: ast.expr) -> ast.expr:
    return deco.func if isinstance(deco, ast.Call) else deco


def _is_overload(deco: ast.expr, aliases: tuple[set[str], set[str]]) -> bool:
    funcs, mods = aliases
    d = _target(deco)
    if isinstance(d, ast.Name):
        return d.id in funcs
    return (
        isinstance(d, ast.Attribute)
        and d.attr == "overload"
        and isinstance(d.value, ast.Name)
        and d.value.id in mods
    )


def _is_property(deco: ast.expr) -> bool:
    d = _target(deco)
    return (isinstance(d, ast.Name) and d.id in {"property", "abstractproperty"}) or (
        isinstance(d, ast.Attribute) and d.attr in {"property", "abstractproperty"}
    )


def _accessor_of(deco: ast.expr, name: str) -> bool:
    d = _target(deco)
    return (
        isinstance(d, ast.Attribute)
        and d.attr in _ACCESSORS
        and isinstance(d.value, ast.Name)
        and d.value.id == name
    )


def _is_dispatch_register(deco: ast.expr, name: str) -> bool:
    """``@<name>.register`` (the first definition is the dispatcher), or any
    ``@x.register`` on a function named ``_``."""
    d = _target(deco)
    if not (isinstance(d, ast.Attribute) and d.attr == "register"):
        return False
    return name == "_" or (isinstance(d.value, ast.Name) and d.value.id == name)


def _check_block(
    body: list[ast.stmt],
    module: str,
    container: str,
    aliases: tuple[set[str], set[str]],
) -> list[Found]:
    found: list[Found] = []
    seen: dict[str, int] = {}
    overloaded: set[str] = set()
    has_impl: set[str] = set()
    properties: set[str] = set()
    for node in body:
        if not isinstance(node, _DEFS):
            continue
        name = node.name
        decos = getattr(node, "decorator_list", [])
        stub = isinstance(node, _FUNCS) and any(_is_overload(d, aliases) for d in decos)
        exempt = False
        if name in seen:
            if stub:
                exempt = name not in has_impl
            elif name in overloaded and name not in has_impl:
                exempt = True
            elif any(_accessor_of(d, name) for d in decos) and name in properties:
                exempt = True
            elif any(_is_dispatch_register(d, name) for d in decos):
                exempt = True
        if name in seen and not exempt:
            found.append(
                (
                    module,
                    container,
                    name,
                    f"{module}: {container}: {name} defined at line {seen[name]}"
                    f" and line {node.lineno}",
                )
            )
        if stub:
            overloaded.add(name)
        else:
            has_impl.add(name)
        if any(_is_property(d) or _accessor_of(d, name) for d in decos) and (
            name not in seen or name in properties or any(_is_property(d) for d in decos)
        ):
            properties.add(name)
        seen.setdefault(name, node.lineno)
    return found


def _scan(source: str, module: str) -> list[Found]:
    tree = ast.parse(source, filename=module)
    aliases = _overload_names(tree)
    found: list[Found] = []

    def check_scope(body: list[ast.stmt], container: str) -> None:
        for block in _blocks(body):
            found.extend(_check_block(block, module, container, aliases))

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (*_DEFS,)):
                qual = f"{prefix}{child.name}"
                check_scope(child.body, qual)
                visit(child, qual + ".")
            else:
                visit(child, prefix)

    check_scope(tree.body, "<module>")
    visit(tree, "")
    return found


def find_duplicates(source: str, module: str = "<module>") -> list[str]:
    """Return one message per duplicate definition found in ``source``."""
    return [msg for m, c, n, msg in _scan(source, module) if (m, c, n) not in ALLOWLIST]


def _scan_kaine() -> tuple[int, list[Found]]:
    files = sorted(KAINE_ROOT.rglob("*.py"))
    found: list[Found] = []
    for path in files:
        rel = path.relative_to(KAINE_ROOT).as_posix()
        found.extend(_scan(path.read_text(encoding="utf-8"), rel))
    return len(files), found


def test_no_duplicate_definitions() -> None:
    count, found = _scan_kaine()
    assert count >= MIN_FILES_SCANNED, f"scan saw only {count} files under {KAINE_ROOT}"
    problems = [msg for m, c, n, msg in found if (m, c, n) not in ALLOWLIST]
    assert not problems, "duplicate definitions:\n" + "\n".join(problems)


def test_allowlist_has_no_stale_entries() -> None:
    _, found = _scan_kaine()
    live = {(m, c, n) for m, c, n, _ in found}
    stale = sorted(ALLOWLIST - live)
    assert not stale, f"ALLOWLIST entries matching no current duplicate: {stale}"


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


def test_duplicates_inside_compound_bodies_reported() -> None:
    src = (
        "if X:\n    def a(): ...\n    def a(): ...\n"
        "elif Y:\n    def b(): ...\n    def b(): ...\n"
        "else:\n    def c(): ...\n    def c(): ...\n"
        "try:\n    def t(): ...\n    def t(): ...\n"
        "except E:\n    def h(): ...\n    def h(): ...\n"
        "else:\n    def o(): ...\n    def o(): ...\n"
        "finally:\n    def f(): ...\n    def f(): ...\n"
        "with W:\n    def w(): ...\n    def w(): ...\n"
        "for i in z:\n    def l(): ...\n    def l(): ...\n"
        "else:\n    def lo(): ...\n    def lo(): ...\n"
        "while Q:\n    def wh(): ...\n    def wh(): ...\n"
        "match v:\n    case 1:\n        def m(): ...\n        def m(): ...\n"
    )
    assert len(find_duplicates(src)) == 12


def test_compound_bodies_reported_in_class_and_function() -> None:
    src = (
        "class C:\n    if X:\n        def a(self): ...\n        def a(self): ...\n"
        "def f():\n    with W:\n        def g(): ...\n        def g(): ...\n"
    )
    assert len(find_duplicates(src)) == 2


def test_register_only_for_dispatcher_or_underscore() -> None:
    ok = "@singledispatch\ndef f(x): ...\n@f.register\ndef _(x): ...\n@f.register\ndef _(x): ...\n"
    assert find_duplicates(ok) == []
    bad = "def f(): ...\n@other.register\ndef f(): ...\n"
    assert len(find_duplicates(bad)) == 1


def test_overload_needs_at_most_one_trailing_implementation() -> None:
    two_impls = (
        "from typing import overload\n@overload\ndef f(a: int): ...\ndef f(a): ...\ndef f(a): ...\n"
    )
    assert len(find_duplicates(two_impls)) == 1
    after_plain = "from typing import overload\ndef f(a): ...\n@overload\ndef f(a: int): ...\n"
    assert len(find_duplicates(after_plain)) == 1
    stub_after_impl = (
        "from typing import overload\n@overload\ndef f(a: int): ...\n"
        "def f(a): ...\n@overload\ndef f(a: str): ...\n"
    )
    assert len(find_duplicates(stub_after_impl)) == 1


def test_nested_class_and_def_class_collision_reported() -> None:
    src = (
        "class C:\n    class In: ...\n    class In: ...\n    def m(self): ...\n    class m: ...\n"
        "def f():\n    class K: ...\n    def K(): ...\n"
    )
    assert len(find_duplicates(src)) == 3


def test_accessor_needs_earlier_property() -> None:
    plain = "class C:\n    def x(self): ...\n    @x.setter\n    def x(self, v): ...\n"
    assert len(find_duplicates(plain)) == 1
    chain = (
        "class C:\n    @property\n    def x(self): ...\n    @x.getter\n    def x(self): ...\n"
        "    @x.setter\n    def x(self, v): ...\n    @x.deleter\n    def x(self): ...\n"
    )
    assert find_duplicates(chain) == []
    other = (
        "class C:\n    @property\n    def x(self): ...\n    @y.setter\n    def x(self, v): ...\n"
    )
    assert len(find_duplicates(other)) == 1


def test_overload_aliases_recognised() -> None:
    variants = [
        "from typing import overload as ov\n@ov\ndef f(a: int): ...\ndef f(a): ...\n",
        "from typing_extensions import overload\n@overload\ndef f(a: int): ...\ndef f(a): ...\n",
        "import typing_extensions as te\n@te.overload\ndef f(a: int): ...\ndef f(a): ...\n",
        "import typing\n@typing.overload\ndef f(a: int): ...\ndef f(a): ...\n",
    ]
    for src in variants:
        assert find_duplicates(src) == [], src
    assert len(find_duplicates("@ov\ndef f(a): ...\ndef f(a): ...\n")) == 1


def test_allowlist_suppresses_planted_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    src = "def f(): ...\ndef f(): ...\n"
    monkeypatch.setattr(sys.modules[__name__], "ALLOWLIST", {("m.py", "<module>", "f")})
    assert find_duplicates(src, "m.py") == []
