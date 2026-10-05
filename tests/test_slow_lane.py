# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Guard the slow-test lane: every slow test file is in the path filter list,
the patterns and marker registration are sound, and the workflow runs slow
tests when expected.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"
PATHS_FILE = ROOT / ".github" / "slow-test-paths.txt"
WORKFLOW_FILE = ROOT / ".github" / "workflows" / "tests.yml"
PYPROJECT_FILE = ROOT / "pyproject.toml"


def _is_slow_marker_node(node: ast.expr) -> bool:
    """Return True if the AST node is the attribute chain pytest.mark.slow,
    whether called or not.
    """
    if isinstance(node, ast.Call):
        node = node.func
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "slow"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "pytest"
    )


def _contains_slow_marker(node: ast.expr) -> bool:
    """Return True if the expression contains pytest.mark.slow, including
    inside list/tuple/set literals.
    """
    if _is_slow_marker_node(node):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return any(_contains_slow_marker(elt) for elt in node.elts)
    return False


def _has_module_pytestmark_slow(tree: ast.Module) -> bool:
    """Detect a module-level `pytestmark` assignment whose value contains
    pytest.mark.slow.
    """
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == "pytestmark":
                    if _contains_slow_marker(stmt.value):
                        return True
        elif isinstance(stmt, ast.AnnAssign):
            if (
                isinstance(stmt.target, ast.Name)
                and stmt.target.id == "pytestmark"
                and stmt.value is not None
                and _contains_slow_marker(stmt.value)
            ):
                return True
    return False


class _DecoratorVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.found = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check(node.decorator_list)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check(node.decorator_list)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._check(node.decorator_list)
        self.generic_visit(node)

    def _check(self, decorator_list: list[ast.expr]) -> None:
        if self.found:
            return
        for dec in decorator_list:
            if _is_slow_marker_node(dec):
                self.found = True
                return


def _has_decorator_slow(tree: ast.Module) -> bool:
    visitor = _DecoratorVisitor()
    visitor.visit(tree)
    return visitor.found


def _collect_slow_test_files() -> list[str]:
    slow_files: list[str] = []
    for path in TESTS_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            raise AssertionError(f"Syntax error in {path}: {exc}") from exc
        if _has_module_pytestmark_slow(tree) or _has_decorator_slow(tree):
            slow_files.append(path.relative_to(ROOT).as_posix())
    return sorted(slow_files)


def _collect_patterns() -> list[str]:
    patterns: list[str] = []
    for line in PATHS_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(stripped)
    return patterns


SLOW_FILES = _collect_slow_test_files()
SLOW_PATTERNS = _collect_patterns()


def test_at_least_one_slow_test_exists() -> None:
    assert SLOW_FILES, "No slow-marked test files found under tests/"


def test_every_slow_file_is_listed() -> None:
    unlisted: list[str] = []
    for rel_path in SLOW_FILES:
        if not any(re.search(pattern, rel_path) for pattern in SLOW_PATTERNS):
            unlisted.append(rel_path)
    assert not unlisted, (
        "Slow test files not matched by any pattern in "
        f"{PATHS_FILE.relative_to(ROOT)}: " + ", ".join(unlisted)
    )


def test_slow_path_patterns_are_sound() -> None:
    for pattern in SLOW_PATTERNS:
        re.compile(pattern)  # raises if invalid
        assert not re.search(pattern, ""), (
            f"Pattern {pattern!r} matches the empty string; "
            "it would mark every changed path as slow"
        )


def test_slow_marker_is_registered() -> None:
    with PYPROJECT_FILE.open("rb") as fh:
        data = tomllib.load(fh)
    markers = (
        data.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("markers", [])
    )
    assert any(
        isinstance(entry, str) and entry.startswith("slow:") for entry in markers
    ), f"No pytest marker starting with 'slow:' found in {markers!r}"


def _load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW_FILE.read_text(encoding="utf-8"))


def _workflow_on_block() -> dict:
    workflow = _load_workflow()
    # PyYAML parses the key `on` as the boolean True.
    return workflow.get("on") or workflow.get(True) or {}


def test_workflow_triggers_include_schedule_and_pull_request() -> None:
    on = _workflow_on_block()
    assert "schedule" in on, "Workflow is missing the schedule trigger"
    assert "pull_request" in on, "Workflow is missing the pull_request trigger"


def test_workflow_path_filters_include_slow_paths_file() -> None:
    on = _workflow_on_block()
    paths = on.get("push", {}).get("paths", [])
    assert ".github/slow-test-paths.txt" in paths, (
        "push path filter is missing .github/slow-test-paths.txt"
    )


def test_required_suite_always_starts_for_pull_requests_and_the_merge_queue() -> None:
    # pytest is a required check. A required check that a path filter never
    # starts would leave the pull request, or its merge-queue batch, waiting.
    on = _workflow_on_block()
    assert "merge_group" in on, "Workflow is missing the merge_group trigger"
    for trigger in ("pull_request", "merge_group"):
        assert "paths" not in (on.get(trigger) or {}), (
            f"{trigger} must not be path-filtered"
        )


def test_slow_lane_diffs_a_merge_queue_batch_against_its_base() -> None:
    steps = _load_workflow().get("jobs", {}).get("pytest", {}).get("steps", [])
    lane = next((s for s in steps if s.get("id") == "lane"), None)
    assert lane is not None, "Missing the slow-lane step (id: lane)"
    assert "github.event.merge_group.base_sha" in lane.get("run", ""), (
        "The slow lane does not diff a merge-queue batch against its base"
    )


def test_workflow_offline_step_excludes_slow_tests() -> None:
    steps = _load_workflow().get("jobs", {}).get("pytest", {}).get("steps", [])
    step = next(
        (s for s in steps if s.get("name") == "Run the offline test suite"), None
    )
    assert step is not None, "Missing 'Run the offline test suite' step"
    run = step.get("run", "")
    assert '-m "not slow"' in run, "Offline step does not filter out slow tests"
    assert "-n auto" in run, "Offline step is not running with -n auto"


def test_workflow_slow_step_is_wired() -> None:
    steps = _load_workflow().get("jobs", {}).get("pytest", {}).get("steps", [])
    step = next((s for s in steps if s.get("name") == "Run the slow tests"), None)
    assert step is not None, "Missing 'Run the slow tests' step"
    assert "steps.lane.outputs.slow" in str(step.get("if", "")), (
        "Slow step condition does not reference the lane output"
    )
    run = step.get("run", "")
    assert "-m slow" in run, "Slow step does not select the slow marker"
