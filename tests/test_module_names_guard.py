# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Grep guard for module rename completion.

The guard checks that once a scope is marked done, no remaining tracked file
contains a name that should have been renamed in that scope. The test code does
not spell any old module name; all names come from the mapping table.
"""

import importlib.util
import pathlib
import re
import subprocess
import sys
import types

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_codemod() -> types.ModuleType:
    repo = pathlib.Path(__file__).resolve().parents[1]
    path = repo / "tools" / "maintainer" / "rename_modules.py"
    spec = importlib.util.spec_from_file_location("rename_modules", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["rename_modules"] = module
    spec.loader.exec_module(module)
    return module


CODEMOD = _load_codemod()
TABLE = CODEMOD.load_table(REPO_ROOT / "kaine" / "legacy_names.py")


@pytest.fixture(scope="module")
def codemod() -> types.ModuleType:
    return CODEMOD


@pytest.fixture(scope="module")
def table(codemod) -> types.ModuleType:
    return TABLE


def test_scope_status_is_well_formed(table):
    assert set(table.SCOPE_STATUS.keys()) == set(table.SCOPES)
    assert all(value in ("pending", "done") for value in table.SCOPE_STATUS.values())


@pytest.mark.parametrize("scope", TABLE.SCOPES)
def test_done_scope_is_clean(codemod, table, scope):
    if table.SCOPE_STATUS[scope] != "done":
        pytest.skip(f"scope {scope} pending")

    plan = codemod.plan(REPO_ROOT, table, {scope})
    messages = []
    for result in plan.results.values():
        for change in result.changes:
            messages.append(f"{change.path}:{change.line} {change.rule}")
    for old, new, move_scope in plan.moves:
        messages.append(f"{old} -> {new} {move_scope}")

    assert not messages, "\n".join(messages)


def test_no_capitalized_old_name(codemod, table):
    if any(table.SCOPE_STATUS[s] != "done" for s in table.SCOPES):
        pytest.skip("scopes still pending")

    files = [
        p
        for p in codemod.tracked_files(REPO_ROOT)
        if not (
            codemod.is_excluded(p, table)
            or p == "kaine/legacy_names.py"
            or p.startswith("tests/fixtures/rename_modules/")
        )
    ]

    found = scan_capitalized(REPO_ROOT, files, table.GUARD_NAMES)
    assert found == []


def scan_capitalized(root: pathlib.Path, files: list[str], names: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for rel in files:
        path = root / rel
        data = path.read_bytes()
        if b"\x00" in data[:8192]:
            continue
        text = data.decode("utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for name in names:
                pattern = rf"(?<![A-Za-z]){re.escape(name)}(?![a-z])"
                for _ in re.finditer(pattern, line):
                    found.append(f"{rel}:{line_no} {name}")
    return found


def test_scanner_reports_file_and_line(tmp_path: pathlib.Path, table):
    name = table.GUARD_NAMES[0]
    path = tmp_path / "x.md"
    path.write_text(f"\n{name}\n", encoding="utf-8")

    assert scan_capitalized(tmp_path, ["x.md"], (name,)) == [f"x.md:2 {name}"]


def test_check_mode_flags_a_planted_name(codemod, table, tmp_path: pathlib.Path, capsys):
    old_class = next(iter(table.MODULES.values()))["old_class"]
    repo = tmp_path / "repo"
    repo.mkdir()
    docs = repo / "docs"
    docs.mkdir()
    (docs / "file.md").write_text(f"{old_class} runs.\n", encoding="utf-8")

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"], cwd=repo, check=True)

    exit_code = codemod.main(["--check", "--scope", "prose", "--root", str(repo)])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "docs/file.md" in out
