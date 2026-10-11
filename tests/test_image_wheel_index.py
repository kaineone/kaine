# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

_EXPECTED = {
    "cuda": "https://download.pytorch.org/whl/cu126",
    "cpu": "https://download.pytorch.org/whl/cpu",
    "xpu": "https://download.pytorch.org/whl/xpu",
    "mps": None,
    "rocm": None,
}


def _wheel_index():
    repo = str(_REPO_ROOT)
    if repo not in sys.path:
        sys.path.insert(0, repo)
    import kaine.wheel_index

    return kaine.wheel_index


def test_image_index_table():
    mod = _wheel_index()
    for flavor, expected in _EXPECTED.items():
        assert mod.image_index(flavor) == expected
    with pytest.raises(KeyError):
        mod.image_index("tpu")


def test_torch_requirement_repo_pyproject():
    mod = _wheel_index()
    spec = mod.torch_requirement(_REPO_ROOT / "pyproject.toml")
    assert spec.startswith("torch")
    assert any(op in spec for op in ("<", ">", "="))


def test_torch_requirement_fallback_to_project_dependencies(tmp_path):
    mod = _wheel_index()
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\nversion = "0.1"\n'
        'dependencies = ["torch>=2.0"]\n'
        'optional-dependencies = {core = ["numpy"]}\n'
    )
    assert mod.torch_requirement(pyproject) == "torch>=2.0"


def test_torch_requirement_missing_file(tmp_path):
    mod = _wheel_index()
    with pytest.raises(ValueError, match="not found"):
        mod.torch_requirement(tmp_path / "missing.toml")


def test_torch_requirement_no_torch(tmp_path):
    mod = _wheel_index()
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "demo"\nversion = "0.1"\n')
    with pytest.raises(ValueError, match="torch dependency"):
        mod.torch_requirement(pyproject)


def _prepare_wheelidx(tmp_path: Path) -> Path:
    wheelidx = tmp_path / "wheelidx"
    wheelidx.mkdir()
    (wheelidx / "__init__.py").write_text("")
    shutil.copy(_REPO_ROOT / "kaine" / "wheel_index.py", wheelidx / "wheel_index.py")
    shutil.copy(_REPO_ROOT / "kaine" / "wheel_data.py", wheelidx / "wheel_data.py")
    shutil.copy(_REPO_ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    return tmp_path


def test_build_stage_image_index(tmp_path):
    root = _prepare_wheelidx(tmp_path)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    for flavor, expected in _EXPECTED.items():
        result = subprocess.run(
            [sys.executable, "-m", "wheelidx.wheel_index", "--image-index", flavor],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == (expected or "")

    bad = subprocess.run(
        [sys.executable, "-m", "wheelidx.wheel_index", "--image-index", "tpu"],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert bad.returncode == 2
    assert bad.stdout.strip() == ""


def test_build_stage_torch_spec(tmp_path):
    root = _prepare_wheelidx(tmp_path)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wheelidx.wheel_index",
            "--torch-spec",
            str(root / "pyproject.toml"),
        ],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    mod = _wheel_index()
    assert result.stdout.strip() == mod.torch_requirement(_REPO_ROOT / "pyproject.toml")
