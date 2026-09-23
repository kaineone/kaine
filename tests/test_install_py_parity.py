# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import importlib.util
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _torch_spec_from_pyproject(repo_root: Path) -> str:
    with open(repo_root / "pyproject.toml", "rb") as f:
        deps = tomllib.load(f).get("project", {}).get("dependencies", [])
    for dep in deps:
        if isinstance(dep, str) and re.match(r"^torch\s*[<>=!~]", dep):
            return dep
    raise RuntimeError("no torch dependency found in pyproject.toml")


def test_install_py_print_torch_spec_matches_pyproject() -> None:
    repo_root = _repo_root()
    expected = _torch_spec_from_pyproject(repo_root)
    result = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "install.py"), "--print-torch-spec"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_install_py_and_install_sh_agree_on_torch_spec() -> None:
    repo_root = _repo_root()
    py_result = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "install.py"), "--print-torch-spec"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert py_result.returncode == 0, py_result.stderr

    sh_result = subprocess.run(
        ["bash", str(repo_root / "scripts" / "install.sh"), "--print-torch-spec"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert sh_result.returncode == 0, sh_result.stderr

    assert py_result.stdout.strip() == sh_result.stdout.strip()


def test_torch_spec_tomllib_branch_prefers_torch_over_vision(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\n'
        'name = "demo"\n'
        'dependencies = [\n'
        '    "torchvision>=0.1",\n'
        '    "torch>=9.9,<10",\n'
        ']\n',
        encoding="utf-8",
    )

    repo_root = _repo_root()
    spec = importlib.util.spec_from_file_location(
        "kaine_install_tomllib", repo_root / "scripts" / "install.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.tomllib is not None, "tomllib unavailable on this interpreter"
    assert module.torch_spec(tmp_path) == "torch>=9.9,<10"


def test_torch_spec_regex_fallback(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\n'
        'name = "demo"\n'
        'dependencies = [\n'
        '    "torchvision>=0.1",\n'
        '    "torch>=9.9,<10",\n'
        ']\n',
        encoding="utf-8",
    )

    repo_root = _repo_root()
    spec = importlib.util.spec_from_file_location(
        "kaine_install", repo_root / "scripts" / "install.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Force the regex fallback regardless of the running interpreter.
    module.tomllib = None

    assert module.torch_spec(tmp_path) == "torch>=9.9,<10"
