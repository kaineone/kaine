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


@pytest.fixture(scope="session")
def codemod() -> types.ModuleType:
    return CODEMOD


@pytest.fixture(scope="session")
def table(codemod) -> types.ModuleType:
    return TABLE


@pytest.fixture(scope="session")
def done_plan(codemod, table):
    done_scopes = [scope for scope in table.SCOPES if table.SCOPE_STATUS[scope] == "done"]
    if not done_scopes:
        return None
    return codemod.plan(REPO_ROOT, table, set(done_scopes))


def test_scope_status_is_well_formed(table):
    assert set(table.SCOPE_STATUS.keys()) == set(table.SCOPES)
    assert all(value in ("pending", "done") for value in table.SCOPE_STATUS.values())


@pytest.mark.slow
@pytest.mark.parametrize("scope", TABLE.SCOPES)
def test_done_scope_is_clean(done_plan, table, scope):
    if table.SCOPE_STATUS[scope] != "done":
        pytest.skip(f"scope {scope} pending")

    messages = []
    for result in done_plan.results.values():
        for change in result.changes:
            if change.scope == scope:
                messages.append(f"{change.path}:{change.line} {change.rule}")
    for old, new, move_scope in done_plan.moves:
        if move_scope == scope:
            messages.append(f"{old} -> {new} {move_scope}")

    assert not messages, "\n".join(messages)


def _guarded_files(codemod, table) -> list[str]:
    return [
        p
        for p in codemod.tracked_files(REPO_ROOT)
        if not (
            codemod.is_excluded(p, table)
            or p == "kaine/legacy_names.py"
            or p.startswith("tests/fixtures/rename_modules/")
        )
    ]


def _allowed_lines(codemod, table, files) -> dict[str, set[int]]:
    allowed: dict[str, set[int]] = {}
    section_files = set(getattr(table, "OLD_NAME_SECTION_FILES", ()))
    markers = getattr(table, "OLD_NAME_SECTION_MARKERS", ())
    line_marker = getattr(table, "OLD_NAME_LINE_MARKER", "")
    for rel in files:
        if rel in section_files:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
            allowed[rel] = codemod.marked_old_name_lines(text, markers, line_marker)
    return allowed


def test_no_capitalized_old_name(codemod, table):
    if any(table.SCOPE_STATUS[s] != "done" for s in table.SCOPES):
        pytest.skip("scopes still pending")

    guarded = _guarded_files(codemod, table)
    found = scan_capitalized(
        REPO_ROOT,
        guarded,
        table.GUARD_NAMES,
        allowed=_allowed_lines(codemod, table, guarded),
    )
    assert found == []


def scan_capitalized(
    root: pathlib.Path,
    files: list[str],
    names: tuple[str, ...],
    *,
    allowed: dict[str, set[int]] | None = None,
) -> list[str]:
    allowed = allowed or {}
    found: list[str] = []
    for rel in files:
        path = root / rel
        data = path.read_bytes()
        if b"\x00" in data[:8192]:
            continue
        text = data.decode("utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if line_no in allowed.get(rel, ()):
                continue
            for name in names:
                pattern = rf"(?<![A-Za-z]){re.escape(name)}(?![a-z])"
                for _ in re.finditer(pattern, line):
                    found.append(f"{rel}:{line_no} {name}")
    return found


def scan_identifiers(
    root: pathlib.Path,
    files: list[str],
    keys: tuple[str, ...],
    kept: tuple[str, ...],
    *,
    allowed: dict[str, set[int]] | None = None,
) -> list[str]:
    allowed = allowed or {}
    found: list[str] = []
    key_set = set(keys)
    kept_set = set(kept)
    for rel in files:
        path = root / rel
        data = path.read_bytes()
        if b"\x00" in data[:8192]:
            continue
        text = data.decode("utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if line_no in allowed.get(rel, ()):
                continue
            for match in re.finditer(r"[A-Za-z0-9_]+", line):
                token = match.group()
                if token in kept_set or "_" not in token:
                    continue
                if any(part in key_set for part in token.split("_")):
                    found.append(f"{rel}:{line_no} {token}")
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


def test_no_identifier_names_an_old_module(codemod, table):
    if any(table.SCOPE_STATUS[s] != "done" for s in table.SCOPES):
        pytest.skip("scopes still pending")

    keys = tuple(
        k
        for k in {*table.MODULES.keys(), *table.DEVELOPMENTAL.keys()}
        if k not in table.GUARDED
    )
    guarded = _guarded_files(codemod, table)
    found = scan_identifiers(
        REPO_ROOT,
        guarded,
        keys,
        table.GUARD_KEPT_IDENTIFIERS,
        allowed=_allowed_lines(codemod, table, guarded),
    )
    assert found == []


def test_identifier_scanner_flags_and_keeps(tmp_path: pathlib.Path, table):
    key = next(k for k in table.MODULES.keys() if k not in table.GUARDED)
    path = tmp_path / "x.py"
    path.write_text(
        "\n".join(
            [
                f"make_{key}()",
                f"_phase_{key} = 1",
                f"{key}_factory",
                f"{key}x_y",
                f"x{key}_y",
                key,
                "kept_" + key,
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert scan_identifiers(tmp_path, ["x.py"], (key,), ("kept_" + key,)) == [
        f"x.py:1 make_{key}",
        f"x.py:2 _phase_{key}",
        f"x.py:3 {key}_factory",
    ]


def test_marked_old_name_lines(codemod, table):
    text = (
        "\n".join(
            [
                "# Title",
                "",
                "### Requirement: Plain thing",
                "body a",
                "#### Scenario: s",
                "body b",
                "### Requirement: Values read under old names",
                "body c",
                "#### Scenario: t",
                "body d",
                "### Requirement: Other",
                "body e " + table.OLD_NAME_LINE_MARKER,
                "body f",
                "```",
                "### not a heading",
                "```",
                "body g",
            ]
        )
        + "\n"
    )
    assert codemod.marked_old_name_lines(
        text,
        table.OLD_NAME_SECTION_MARKERS,
        table.OLD_NAME_LINE_MARKER,
    ) == {7, 8, 9, 10, 12}


def test_old_name_sections_scope_the_scans(codemod, table, tmp_path):
    rel = table.OLD_NAME_SECTION_FILES[0]
    old = table.GUARD_NAMES[0]
    key = next(k for k in table.MODULES.keys() if k not in table.GUARDED)
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        "\n".join(
            [
                "### Requirement: Old names are read",
                f"{old} reads.",
                f"make_{key}()",
                "### Requirement: Other",
                f"{old} runs.",
                f"make_{key}()",
            ]
        )
        + "\n"
    )
    path.write_text(text, encoding="utf-8")
    allowed = {
        rel: codemod.marked_old_name_lines(
            text,
            table.OLD_NAME_SECTION_MARKERS,
            table.OLD_NAME_LINE_MARKER,
        )
    }
    assert scan_capitalized(tmp_path, [rel], (old,), allowed=allowed) == [f"{rel}:5 {old}"]
    assert scan_identifiers(tmp_path, [rel], (key,), (), allowed=allowed) == [f"{rel}:6 make_{key}"]


def test_codemod_skips_marked_sections(codemod, table, tmp_path):
    key = next(k for k in table.MODULES.keys() if k not in table.GUARDED)
    old = table.MODULES[key]["old_class"]
    rel = table.OLD_NAME_SECTION_FILES[0]
    repo = tmp_path / "repo"
    repo.mkdir()
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        "\n".join(
            [
                "### Requirement: Old names are read",
                f"{old} reads.",
                "### Requirement: Other",
                f"{old} runs.",
            ]
        )
        + "\n"
    )
    path.write_text(text, encoding="utf-8")

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"],
        cwd=repo,
        check=True,
    )

    plan = codemod.plan(repo, table, {"prose"})
    lines = {change.line for change in plan.results[rel].changes}
    assert lines == {4}

