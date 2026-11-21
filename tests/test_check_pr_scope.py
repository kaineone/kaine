# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Tests for tools/maintainer/check_pr_scope.py."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "maintainer" / "check_pr_scope.py"
)


def _load_module() -> object:
    spec = importlib.util.spec_from_file_location("check_pr_scope", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


check = _load_module()

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not installed"
)


COMMIT_COUNTER = 0


def run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def head_sha(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def commit(repo: Path, filename: str | None = None, content: str | None = None) -> None:
    global COMMIT_COUNTER
    COMMIT_COUNTER += 1
    if filename is None:
        filename = f"file{COMMIT_COUNTER}.txt"
    path = repo / filename
    path.write_text(content or f"content {COMMIT_COUNTER}\n")
    run_git(repo, "add", str(path))
    run_git(repo, "commit", "-q", "-m", f"commit {COMMIT_COUNTER}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-q", "-b", "main")
    run_git(repo, "config", "user.name", "test")
    run_git(repo, "config", "user.email", "test@example.invalid")
    run_git(repo, "config", "commit.gpgsign", "false")
    commit(repo, "initial.txt", "initial\n")
    return repo


def test_small_branch_passes(repo: Path, capsys: pytest.CaptureFixture) -> None:
    base = head_sha(repo)
    run_git(repo, "checkout", "-q", "-b", "feature")
    commit(repo, "a.txt")
    commit(repo, "b.txt")
    head = head_sha(repo)

    assert check.main([base, head, "--repo", str(repo)]) == 0
    captured = capsys.readouterr()
    assert "pr-scope:" in captured.out


def test_too_many_commits_fails(repo: Path, capsys: pytest.CaptureFixture) -> None:
    base = head_sha(repo)
    run_git(repo, "checkout", "-q", "-b", "feature")
    for _ in range(16):
        commit(repo)
    head = head_sha(repo)

    assert check.main([base, head, "--repo", str(repo)]) == 1
    captured = capsys.readouterr()
    assert "commit limit exceeded" in captured.out


def test_max_files_fails(repo: Path, capsys: pytest.CaptureFixture) -> None:
    base = head_sha(repo)
    run_git(repo, "checkout", "-q", "-b", "feature")
    for i in range(4):
        commit(repo, f"f{i}.txt")
    head = head_sha(repo)

    assert check.main([base, head, "--repo", str(repo), "--max-files", "3"]) == 1
    captured = capsys.readouterr()
    assert "file limit exceeded" in captured.out


def test_allow_large_passes(repo: Path, capsys: pytest.CaptureFixture) -> None:
    base = head_sha(repo)
    run_git(repo, "checkout", "-q", "-b", "feature")
    for _ in range(16):
        commit(repo)
    head = head_sha(repo)

    assert check.main([base, head, "--repo", str(repo), "--allow-large"]) == 0
    captured = capsys.readouterr()
    assert "allowed: --allow-large" in captured.out


def test_merge_main_excludes_main_commits_and_files(repo: Path) -> None:
    # Create a small branch from current main.
    run_git(repo, "checkout", "-q", "-b", "feature")
    commit(repo, "branch1.txt")
    commit(repo, "branch2.txt")

    # Advance main with many commits/files.
    run_git(repo, "checkout", "-q", "main")
    for _ in range(20):
        commit(repo)
    main_head = head_sha(repo)

    # A stale branch (main moved on, branch not updated) counts only its own work.
    run_git(repo, "checkout", "-q", "feature")
    assert check.measure(str(repo), main_head, head_sha(repo)) == (2, 2)

    # Merge main into the feature branch.
    run_git(repo, "checkout", "-q", "feature")
    run_git(repo, "merge", "--no-edit", "main")
    branch_head = head_sha(repo)

    commits, files = check.measure(str(repo), main_head, branch_head)
    assert commits == 2
    assert files == 2


def test_bad_ref_returns_git_error(repo: Path) -> None:
    base = head_sha(repo)
    bad_head = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    assert check.main([base, bad_head, "--repo", str(repo)]) == 2
