# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""A built wheel carries every kaine package and every runtime data file.

Every install today is editable, so a gap in the packaging metadata goes
unnoticed until someone installs a wheel. This test builds the real wheel from
the source tree and compares it with the tree itself.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "kaine"

# Files in the source tree that are documentation for developers, not runtime data.
NOT_SHIPPED_SUFFIXES = {".md", ".pyc"}


def _expected_files() -> set[str]:
    expected = set()
    for path in PACKAGE_ROOT.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.suffix in NOT_SHIPPED_SUFFIXES:
            continue
        expected.add(path.relative_to(ROOT).as_posix())
    return expected


@pytest.fixture(scope="module")
def wheel_names(tmp_path_factory) -> set[str]:
    # Build from a clean copy: setuptools reuses a stale build/ directory, which
    # would hide a packaging gap behind files from an earlier build.
    src = tmp_path_factory.mktemp("src")
    for name in ("pyproject.toml", "README.md", "LICENSE.md"):
        shutil.copy2(ROOT / name, src / name)
    shutil.copytree(
        PACKAGE_ROOT, src / "kaine", ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    out = tmp_path_factory.mktemp("wheel")
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(src), "--no-deps",
         "--no-build-isolation", "--quiet", "-w", str(out)],
        capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0 and "No module named" in proc.stderr:
        pytest.skip(f"wheel build tooling unavailable: {proc.stderr.strip()[-200:]}")
    assert proc.returncode == 0, proc.stderr[-2000:]
    wheels = list(out.glob("kaine-*.whl"))
    assert len(wheels) == 1, wheels
    with zipfile.ZipFile(wheels[0]) as zf:
        return {name for name in zf.namelist() if name.startswith("kaine/")}


def test_wheel_contains_every_package_and_data_file(wheel_names: set[str]) -> None:
    missing = sorted(_expected_files() - wheel_names)
    assert not missing, f"{len(missing)} file(s) missing from the wheel: {missing[:20]}"


def test_wheel_contains_every_subpackage(wheel_names: set[str]) -> None:
    packages = {
        p.parent.relative_to(ROOT).as_posix()
        for p in PACKAGE_ROOT.rglob("__init__.py")
        if "__pycache__" not in p.parts
    }
    missing = sorted(pkg for pkg in packages if f"{pkg}/__init__.py" not in wheel_names)
    assert not missing, f"packages missing from the wheel: {missing}"
