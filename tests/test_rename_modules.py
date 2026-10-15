# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the module-rename codemod.

All concrete names are loaded from the mapping table. Fixture cases drive the
end-to-end behavior; this file contains no literal old module names.
"""

import ast
import copy
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import types
import uuid

import pytest


def _load_codemod() -> types.ModuleType:
    repo = pathlib.Path(__file__).resolve().parents[1]
    path = repo / "tools" / "maintainer" / "rename_modules.py"
    spec = importlib.util.spec_from_file_location("rename_modules", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["rename_modules"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def codemod() -> types.ModuleType:
    return _load_codemod()


@pytest.fixture(scope="module")
def table(codemod) -> types.ModuleType:
    repo = pathlib.Path(__file__).resolve().parents[1]
    return codemod.load_table(repo / "kaine" / "legacy_names.py")


@pytest.fixture
def repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1]


def _fixture_dir(name: str) -> pathlib.Path:
    base = pathlib.Path(__file__).resolve().parents[1]
    return base / "tests" / "fixtures" / "rename_modules" / name


def _copy_fixture(src: pathlib.Path, dst: pathlib.Path) -> None:
    """Copy a fixture ``before`` tree into a temporary repo, ignoring bytecode."""
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def _fixture_cases():
    base = pathlib.Path(__file__).resolve().parents[1]
    root = base / "tests" / "fixtures" / "rename_modules"
    for d in sorted(root.iterdir()):
        if d.is_dir() and (d / "case.json").is_file():
            yield d


def _git_init(repo: pathlib.Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "-qm", "init"], cwd=repo, check=True)


def _assert_tree(repo: pathlib.Path, case_dir: pathlib.Path, moves: list, applied: bool) -> None:
    before = case_dir / "before"
    after = case_dir / "after"
    before_files = {p.relative_to(before).as_posix() for p in before.rglob("*") if p.is_file()}
    after_files = (
        {p.relative_to(after).as_posix() for p in after.rglob("*") if p.is_file()}
        if after.exists()
        else set()
    )

    result = subprocess.run(
        ["git", "ls-files"], cwd=repo, capture_output=True, text=True, check=True
    )
    tracked = set(result.stdout.splitlines())

    moved_sources = {m[0] for m in moves}
    moved_targets = {m[1] for m in moves}
    expected = (before_files - moved_sources) | moved_targets if applied else before_files
    assert tracked == expected

    for path in tracked:
        repo_file = repo / path
        if path in after_files:
            expected_file = after / path
        else:
            expected_file = before / path
        assert repo_file.read_bytes() == expected_file.read_bytes(), path


@pytest.mark.parametrize("case_dir", _fixture_cases(), ids=lambda d: d.name)
def test_fixture_case(case_dir: pathlib.Path, codemod, tmp_path: pathlib.Path, capsys):
    case = json.loads((case_dir / "case.json").read_text())
    repo = tmp_path / "repo"
    _copy_fixture(case_dir / "before", repo)
    _git_init(repo)

    args = [*case["args"], "--root", str(repo)]
    exit_code = codemod.main(args)
    out = capsys.readouterr().out

    assert exit_code == case.get("expect_exit", 0)
    for substring in case.get("report_contains", []):
        assert substring in out, substring
    for substring in case.get("report_excludes", []):
        assert substring not in out, substring

    applied = "--apply" in case["args"] and exit_code == 0
    _assert_tree(repo, case_dir, case.get("moves", []), applied)


@pytest.mark.parametrize(
    "case_dir",
    [
        d
        for d in _fixture_cases()
        if "--apply" in json.loads((d / "case.json").read_text())["args"]
        and json.loads((d / "case.json").read_text()).get("expect_exit", 0) == 0
    ],
    ids=lambda d: d.name,
)
def test_fixture_idempotent(case_dir: pathlib.Path, codemod, tmp_path: pathlib.Path, capsys):
    case = json.loads((case_dir / "case.json").read_text())
    repo = tmp_path / "repo"
    _copy_fixture(case_dir / "before", repo)
    _git_init(repo)

    first_exit = codemod.main([*case["args"], "--root", str(repo)])
    assert first_exit == 0

    check_args = [a for a in case["args"] if a != "--apply"] + ["--check"]
    second_exit = codemod.main([*check_args, "--root", str(repo)])
    out = capsys.readouterr().out

    assert second_exit == 0
    assert "## moves (0)" in out
    assert "replacements=0" in out


def test_check_before_apply(codemod, tmp_path: pathlib.Path, capsys):
    case_dir = _fixture_dir("rename_all")
    repo = tmp_path / "repo"
    _copy_fixture(case_dir / "before", repo)
    _git_init(repo)

    exit_code = codemod.main(["--check", "--root", str(repo)])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "## moves (5)" in out


def test_dry_run_deterministic(codemod, tmp_path: pathlib.Path, capsys):
    case_dir = _fixture_dir("rename_all")

    def run_once() -> str:
        repo = tmp_path / f"repo_{uuid.uuid4().hex[:8]}"
        _copy_fixture(case_dir / "before", repo)
        _git_init(repo)
        codemod.main(["--root", str(repo)])
        return capsys.readouterr().out

    assert run_once() == run_once()


def test_only_restricts_moves(codemod, table, tmp_path: pathlib.Path, capsys):
    case_dir = _fixture_dir("rename_all")
    repo = tmp_path / "repo"
    _copy_fixture(case_dir / "before", repo)
    _git_init(repo)

    affect_key = next(k for k, v in table.MODULES.items() if v["new_class"] == "Affect")
    exit_code = codemod.main(["--only", affect_key, "--root", str(repo)])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "kaine/modules/affect/module.py" in out
    assert "kaine/workspace/core.py" not in out
    assert "kaine/cycle/supervisor.py" not in out
    assert "tests/test_dashboard_routers.py" not in out


def test_only_and_scope_restrict_override_moves(codemod, table, tmp_path: pathlib.Path, capsys):
    affect_key = next(k for k, v in table.MODULES.items() if v["new_class"] == "Affect")
    sup_key = next(k for k, v in table.MODULES.items() if v["new_class"] == "Supervisor")

    repo = tmp_path / "repo"
    old_dir = repo / "openspec" / "specs" / f"{sup_key}-supervisor"
    old_dir.mkdir(parents=True)
    (old_dir / "spec.md").write_text("# spec\n")
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "x.md").write_text("x\n")
    _git_init(repo)

    codemod.main(["--only", affect_key, "--root", str(repo)])
    out = capsys.readouterr().out
    assert "openspec/specs/supervisor/spec.md" not in out

    codemod.main(["--only", sup_key, "--scope", "identifiers", "--root", str(repo)])
    out = capsys.readouterr().out
    assert "openspec/specs/supervisor/spec.md" not in out

    exit_code = codemod.main(["--only", sup_key, "--scope", "keys", "--root", str(repo)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert (
        f"openspec/specs/{sup_key}-supervisor/spec.md -> openspec/specs/supervisor/spec.md [keys]"
        in out
    )


def _table_namespace(table) -> types.SimpleNamespace:
    ns = types.SimpleNamespace()
    for attr in dir(table):
        if attr.startswith("_"):
            continue
        setattr(ns, attr, copy.deepcopy(getattr(table, attr)))
    return ns


def test_validate_real_table(codemod, table):
    codemod.validate_table(table)


def test_validate_duplicate_new_key(codemod, table):
    ns = _table_namespace(table)
    keys = list(ns.MODULES.keys())
    ns.MODULES[keys[1]]["new_key"] = ns.MODULES[keys[0]]["new_key"]
    with pytest.raises(codemod.TableError):
        codemod.validate_table(ns)


def test_validate_duplicate_new_class(codemod, table):
    ns = _table_namespace(table)
    keys = list(ns.MODULES.keys())
    ns.MODULES[keys[0]]["new_class"] = ns.MODULES[keys[1]]["new_class"]
    with pytest.raises(codemod.TableError):
        codemod.validate_table(ns)


def test_validate_old_key_component(codemod, table):
    ns = _table_namespace(table)
    keys = list(ns.MODULES.keys())
    ns.MODULES[keys[1]]["new_key"] = f"{keys[0]}_x"
    with pytest.raises(codemod.TableError):
        codemod.validate_table(ns)


def test_validate_bad_guard_action(codemod, table):
    ns = _table_namespace(table)
    name = next(iter(ns.GUARDED))
    ns.GUARDED[name]["rules"][0]["action"] = "rename_maybe"
    with pytest.raises(codemod.TableError):
        codemod.validate_table(ns)


def test_validate_bad_scope_status(codemod, table):
    ns = _table_namespace(table)
    scope = ns.SCOPES[0]
    ns.SCOPE_STATUS[scope] = "partly"
    with pytest.raises(codemod.TableError):
        codemod.validate_table(ns)


def test_cli_table_checked_before_root(codemod, table, tmp_path: pathlib.Path, capsys):
    original = pathlib.Path(table.__file__)
    broken = tmp_path / "legacy_names_broken.py"
    broken.write_text(
        original.read_text()
        + "\n_keys = list(MODULES.keys())\n"
        + "MODULES[_keys[1]]['new_key'] = MODULES[_keys[0]]['new_key']\n"
    )

    exit_code = codemod.main(
        ["--table", str(broken), "--root", str(tmp_path / "does-not-exist")]
    )
    err = capsys.readouterr().err

    assert exit_code == 2
    assert "rename_modules: table:" in err


def test_table_has_no_imports(table):
    tree = ast.parse(pathlib.Path(table.__file__).read_text())
    for node in ast.walk(tree):
        assert not isinstance(node, (ast.Import, ast.ImportFrom))


def test_scope_status_five_scopes(table):
    assert set(table.SCOPE_STATUS.keys()) == set(table.SCOPES)
    assert len(table.SCOPES) == 5


def test_is_excluded(codemod, table):
    for pattern in table.EXCLUDED_GLOBS:
        sample = pattern
        if sample.endswith("/"):
            sample = sample[:-1] + "/x.md"
        sample = sample.replace("*", "x")
        assert codemod.is_excluded(sample, table), sample
    assert not codemod.is_excluded("kaine/config.py", table)


def test_accepted_collision_lets_apply_proceed(codemod, table, tmp_path: pathlib.Path, capsys):
    case_dir = _fixture_dir("collision")
    repo = tmp_path / "repo"
    _copy_fixture(case_dir / "before", repo)
    _git_init(repo)

    table_copy = tmp_path / "legacy_names_accepted.py"
    table_copy.write_text(
        pathlib.Path(table.__file__).read_text()
        + '\n_old = [k for k, e in MODULES.items() if e["new_class"] == "Affect"][0]\n'
        + 'ACCEPTED_COLLISIONS.append(("kaine/modules/" + _old + "/helper.py", "Affect"))\n'
    )

    exit_code = codemod.main(
        ["--apply", "--scope", "identifiers", "--table", str(table_copy), "--root", str(repo)]
    )
    out = capsys.readouterr().out

    assert exit_code == 0
    assert " accepted" in out

    result = subprocess.run(
        ["git", "ls-files"], cwd=repo, capture_output=True, text=True, check=True
    )
    assert "kaine/modules/affect/helper.py" in result.stdout.splitlines()

    helper_text = (repo / "kaine/modules/affect/helper.py").read_text()
    assert "class Affect" in helper_text


def test_survey_report(codemod, table, tmp_path: pathlib.Path, capsys):
    case_dir = _fixture_dir("rename_all")
    repo = tmp_path / "repo"
    _copy_fixture(case_dir / "before", repo)
    _git_init(repo)

    exit_code = codemod.main(["--survey", "--root", str(repo)])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert out.startswith("| Name | Paths | Code |")
    for key in list(table.MODULES.keys()) + list(table.DEVELOPMENTAL.keys()):
        assert f"| {key} |" in out, key
    for _name, label in table.SURVEY_EXTRA:
        assert f"| {label} |" in out, label
