# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The full-repository dry run of the rename codemod over a clone; slow because it plans every tracked file twice."""

import collections
import importlib.util
import pathlib
import subprocess
import sys
import types

import pytest

pytestmark = pytest.mark.slow


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


def test_full_repo_dry_run_deterministic(codemod, table, tmp_path: pathlib.Path):
    root = pathlib.Path(__file__).resolve().parents[1]
    worktree = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
    )
    if worktree.returncode != 0 or worktree.stdout.strip() != "true":
        pytest.skip("not a git worktree")

    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", "--no-local", str(root), str(clone)],
        check=True,
    )

    all_scopes = set(table.SCOPES)
    plan1 = codemod.plan(clone, table, all_scopes)
    plan2 = codemod.plan(clone, table, all_scopes)

    report1 = codemod.render_report(plan1, "dry-run")
    report2 = codemod.render_report(plan2, "dry-run")
    assert report1 == report2

    renamed = collections.Counter()
    for result in plan1.results.values():
        for change in result.changes:
            renamed[change.name] += 1

    for key in table.MODULES:
        if key not in table.GUARDED:
            assert renamed[key] > 0, key

    for path, result in plan1.results.items():
        if result.skipped and path.startswith("kaine/"):
            assert "tokenize" not in result.skipped, path

    for old, new, _scope in plan1.moves:
        assert not codemod.is_excluded(old, table), old
        assert not codemod.is_excluded(new, table), new

    for path in plan1.results:
        assert not codemod.is_excluded(path, table), path

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=clone,
        capture_output=True,
        text=True,
        check=True,
    )
    assert status.stdout == ""
