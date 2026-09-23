# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_install_module() -> ...:
    repo_root = _repo_root()
    spec = importlib.util.spec_from_file_location(
        "kaine_install_module", repo_root / "scripts" / "install.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_extract_pins_maps_null_to_none() -> None:
    module = _load_install_module()
    data = {
        "torch_version": "2.7.0",
        "torchvision_version": None,
        "torchaudio_version": "None",
        "selftest_required": True,
    }
    torch_pin, tv_pin, ta_pin, selftest = module._extract_pins(data)
    assert torch_pin == "2.7.0"
    assert tv_pin is None
    assert ta_pin is None
    assert selftest is True


def test_extract_pins_missing_keys_are_none() -> None:
    module = _load_install_module()
    torch_pin, tv_pin, ta_pin, selftest = module._extract_pins({})
    assert torch_pin is None
    assert tv_pin is None
    assert ta_pin is None
    assert selftest is False


def test_rocm_version_from_file(tmp_path: Path) -> None:
    module = _load_install_module()
    version_file = tmp_path / "version"
    version_file.write_text("7.2.0-12345\n", encoding="utf-8")
    assert module._rocm_version_from_file(version_file) == "7.2"


def test_rocm_gfx_from_text_order_stable_unique() -> None:
    module = _load_install_module()
    text = "Name: gfx1100\nName: gfx1100\nName: gfx90a\n"
    assert module._rocm_gfx_from_text(text) == ("gfx1100", "gfx90a")


def _skip_if_resolver_missing() -> None:
    repo_root = _repo_root()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    proc = subprocess.run(
        [sys.executable, "-c", "import kaine.wheel_index"],
        cwd=repo_root,
        env=env,
        capture_output=True,
    )
    if proc.returncode != 0:
        pytest.skip("kaine.wheel_index is not importable in this environment")


def test_print_index_rocm_resolves_with_env() -> None:
    _skip_if_resolver_missing()
    repo_root = _repo_root()
    env = os.environ.copy()
    env["KAINE_ROCM_VERSION"] = "7.2"
    env["KAINE_ROCM_GFX"] = "gfx1100"
    env["PYTHONPATH"] = str(repo_root) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    result = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "install.py"), "--print-index", "rocm"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "https://download.pytorch.org/whl/rocm7.2"


def test_print_index_rocm_no_index_for_unsupported_version() -> None:
    _skip_if_resolver_missing()
    repo_root = _repo_root()
    env = os.environ.copy()
    env["KAINE_ROCM_VERSION"] = "6.2"
    env["PYTHONPATH"] = str(repo_root) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    result = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "install.py"), "--print-index", "rocm"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "no ROCm wheel index carries" in result.stderr
