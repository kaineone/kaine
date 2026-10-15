# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""A built wheel carries every kaine package and every runtime data file.

Every install today is editable, so a gap in the packaging metadata goes
unnoticed until someone installs a wheel. This test builds the real wheel from
the source tree and compares it with the tree itself.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import zipfile
from email.parser import HeaderParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "kaine"

# Files in the source tree that are documentation for developers, not runtime data.
NOT_SHIPPED_SUFFIXES = {".md", ".pyc"}

# The legal files pyproject.toml lists under project.license-files.
LICENCE_FILES = ("LICENSE.md", "NOTICE", "THIRD_PARTY_LICENSES.md")


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
def wheel_path(tmp_path_factory) -> Path:
    # Build from a clean copy: setuptools reuses a stale build/ directory, which
    # would hide a packaging gap behind files from an earlier build.
    src = tmp_path_factory.mktemp("src")
    for name in ("pyproject.toml", "README.md", *LICENCE_FILES):
        shutil.copy2(ROOT / name, src / name)
    shutil.copytree(
        PACKAGE_ROOT, src / "kaine", ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    out = tmp_path_factory.mktemp("wheel")
    cmd = [sys.executable, "-m", "pip", "wheel", str(src), "--no-deps", "--quiet", "-w", str(out)]
    # Build offline with the installed setuptools when there is one; otherwise let
    # pip fetch the build backend (CI has network). Never skip: a packaging gap
    # must fail the suite wherever it runs.
    if importlib.util.find_spec("setuptools") is not None:
        cmd.append("--no-build-isolation")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-2000:]
    wheels = list(out.glob("kaine-*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]


@pytest.fixture(scope="module")
def wheel_names(wheel_path: Path) -> set[str]:
    with zipfile.ZipFile(wheel_path) as zf:
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


def test_wheel_declares_licence_expression_and_files(wheel_path: Path) -> None:
    """PEP 639 licence metadata must appear in the wheel core metadata."""
    with zipfile.ZipFile(wheel_path) as zf:
        metadata_names = [name for name in zf.namelist() if name.endswith(".dist-info/METADATA")]
        assert len(metadata_names) == 1, metadata_names
        metadata = zf.read(metadata_names[0]).decode("utf-8")
    dist_info = metadata_names[0].removesuffix("/METADATA")
    msg = HeaderParser().parsestr(metadata)
    assert msg["License-Expression"] == "LicenseRef-CAL-0.5"
    assert set(msg.get_all("License-File") or []) == set(LICENCE_FILES)
    assert msg["License"] is None
    assert not any(c.startswith("License ::") for c in (msg.get_all("Classifier") or []))
    with zipfile.ZipFile(wheel_path) as zf:
        for name in LICENCE_FILES:
            assert f"{dist_info}/licenses/{name}" in zf.namelist()
