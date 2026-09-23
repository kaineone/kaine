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


def test_index_tag_extraction() -> None:
    module = _load_install_module()
    assert module._index_tag("https://download.pytorch.org/whl/cu130") == "cu130"
    assert module._index_tag("https://download.pytorch.org/whl/cpu/") == "cpu"
    assert module._index_tag("https://example.invalid/custom") == "custom"
    assert module._index_tag(None) == ""
    assert module._index_tag("") == ""


def test_is_pytorch_whl_url_recognises_pytorch_indices() -> None:
    module = _load_install_module()
    assert module._is_pytorch_whl_url("https://download.pytorch.org/whl/cu130")
    assert module._is_pytorch_whl_url("https://download.pytorch.org/whl/cpu")
    assert not module._is_pytorch_whl_url("https://example.invalid/custom")
    assert not module._is_pytorch_whl_url(None)
    assert not module._is_pytorch_whl_url("")


def test_needs_force_reinstall_tag_rule() -> None:
    module = _load_install_module()
    cu130_url = "https://download.pytorch.org/whl/cu130"
    cpu_url = "https://download.pytorch.org/whl/cpu"
    custom_url = "https://example.invalid/custom"

    assert module._needs_force_reinstall("cu126", "cu130", cu130_url)
    assert not module._needs_force_reinstall("cu130", "cu130", cu130_url)
    # An untagged wheel counts as cpu.
    assert not module._needs_force_reinstall("", "cpu", cpu_url)
    assert module._needs_force_reinstall("", "cu130", cu130_url)
    # Non-PyTorch indices never force based on tags.
    assert not module._needs_force_reinstall("cpu", "cu130", custom_url)
    assert not module._needs_force_reinstall("", "", custom_url)


def test_accel_fallback_marker_round_trip(tmp_path: Path) -> None:
    module = _load_install_module()
    marker_path = tmp_path / "kaine-accel-fallback.json"
    module._write_accel_fallback_marker(
        marker_path,
        reason="GPU numerical self-test failed",
        index_url="https://download.pytorch.org/whl/cu130",
        torch="2.14.0",
    )
    marker = module._read_accel_fallback_marker(marker_path)
    assert marker is not None
    assert marker["reason"] == "GPU numerical self-test failed"
    assert marker["index_url"] == "https://download.pytorch.org/whl/cu130"
    assert marker["torch"] == "2.14.0"
    assert "date" in marker


def test_marker_matches_when_all_same() -> None:
    module = _load_install_module()
    marker = {
        "index_url": "https://download.pytorch.org/whl/cu130",
        "torch": "2.14.0",
    }
    assert module._marker_matches(
        marker,
        index_url="https://download.pytorch.org/whl/cu130",
        torch_pin="2.14.0",
        installed_base=None,
    )


def test_marker_matches_falls_back_to_installed_base() -> None:
    module = _load_install_module()
    marker = {
        "index_url": "https://download.pytorch.org/whl/cu130",
        "torch": "2.14.0",
    }
    assert module._marker_matches(
        marker,
        index_url="https://download.pytorch.org/whl/cu130",
        torch_pin=None,
        installed_base="2.14.0",
    )


def test_marker_mismatches_when_torch_differs() -> None:
    module = _load_install_module()
    marker = {
        "index_url": "https://download.pytorch.org/whl/cu130",
        "torch": "2.14.0",
    }
    assert not module._marker_matches(
        marker,
        index_url="https://download.pytorch.org/whl/cu130",
        torch_pin="2.15.0",
        installed_base=None,
    )


def test_marker_mismatches_when_index_differs() -> None:
    module = _load_install_module()
    marker = {
        "index_url": "https://download.pytorch.org/whl/cu130",
        "torch": "2.14.0",
    }
    assert not module._marker_matches(
        marker,
        index_url="https://download.pytorch.org/whl/cu126",
        torch_pin="2.14.0",
        installed_base=None,
    )


def test_torchaudio_should_uninstall_logic() -> None:
    module = _load_install_module()
    cu130 = "https://download.pytorch.org/whl/cu130"
    cu126 = "https://download.pytorch.org/whl/cu126"
    cpu = "https://download.pytorch.org/whl/cpu"
    custom = "https://example.invalid/custom"

    # Mismatching base version is always uninstalled.
    assert module._torchaudio_should_uninstall("2.10.0", "2.11.0", cu130)
    # Matching base but mismatching PyTorch wheel tag is uninstalled.
    assert module._torchaudio_should_uninstall("2.11.0+cu126", "2.11.0", cu130)
    # Matching base and tag is kept.
    assert not module._torchaudio_should_uninstall("2.11.0+cu130", "2.11.0", cu130)
    # An untagged wheel counts as cpu and is kept on the CPU index.
    assert not module._torchaudio_should_uninstall("2.11.0", "2.11.0", cpu)
    # No target pin means any installed torchaudio is stale.
    assert module._torchaudio_should_uninstall("2.11.0", None, cu130)
    # Non-PyTorch indices do not force-tag stale.
    assert not module._torchaudio_should_uninstall("2.11.0+cu126", "2.11.0", custom)
    # Wheel tag mismatches against the chosen cu126 index.
    assert module._torchaudio_should_uninstall("2.11.0+cu130", "2.11.0", cu126)
    # Absent torchaudio is never uninstalled.
    assert not module._torchaudio_should_uninstall(None, "2.11.0", cu130)
    assert not module._torchaudio_should_uninstall("", "2.11.0", cu130)


def test_rocm_version_from_file(tmp_path: Path) -> None:
    module = _load_install_module()
    version_file = tmp_path / "version"
    version_file.write_text("7.2.0-12345\n", encoding="utf-8")
    assert module._rocm_version_from_file(version_file) == "7.2"


def test_rocm_gfx_parsing_filters_igpu_generic_and_gfx000() -> None:
    module = _load_install_module()
    text = (
        "  Name: gfx1036\n"
        "  Name: gfx1100\n"
        "  Name: gfx11-generic\n"
        "  Name: gfx000\n"
        "  Name: gfx1100\n"
    )
    assert module._rocm_gfx_from_text(text) == ("gfx1036", "gfx1100")


def test_rocm_agent_enumerator_parsing() -> None:
    module = _load_install_module()
    text = "gfx1036\ngfx1100\ngfx11-generic\ngfx000\ngfx1100\n"
    assert module._rocm_gfx_from_agent_text(text) == ("gfx1036", "gfx1100")


def test_rocm_agent_enumerator_parsing_full_line() -> None:
    module = _load_install_module()
    text = "amdgcn-amd-amdhsa--gfx90a\n gfx1100:xnack- \ngfx11-generic\n"
    assert module._rocm_gfx_from_agent_text(text) == ("gfx1100",)


def test_rocm_gfx_text_strips_feature_suffixes() -> None:
    module = _load_install_module()
    text = (
        "Name: gfx90a:xnack-\n"
        "Name: gfx90a:sramecc+:xnack-\n"
        "Name: gfx000\n"
        "Name: gfx90a:xnack-\n"
    )
    assert module._rocm_gfx_from_text(text) == ("gfx90a",)


def test_rocm_agent_text_strips_feature_suffixes() -> None:
    module = _load_install_module()
    text = (
        "gfx90a:xnack-\n"
        "gfx90a:sramecc+:xnack-\n"
        "gfx000\n"
        "gfx90a:xnack-\n"
    )
    assert module._rocm_gfx_from_agent_text(text) == ("gfx90a",)


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


def _load_twi_helpers() -> ...:
    """Load the shim harness from the install.sh integration tests."""
    spec = importlib.util.spec_from_file_location(
        "_kaine_twi_helpers", _repo_root() / "tests" / "test_install_wheel_index.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _torch_install_lines(pip_log: str, include_audio: bool = False) -> list[str]:
    """Return pip argv lines that installed torch/torchvision/torchaudio.

    The pip shim in the integration harness records only the arguments it was
    called with, so the lines start with ``install`` rather than ``pip``.
    """
    lines: list[str] = []
    for line in pip_log.splitlines():
        tokens = line.split()
        if "install" not in tokens:
            continue
        has_torch = any(t.startswith(("torch==", "torch>=")) for t in tokens)
        has_tv = "torchvision" in tokens
        has_ta = "torchaudio" in tokens
        if has_torch or has_tv or (include_audio and has_ta):
            lines.append(line)
    return lines


@pytest.mark.skipif(
    os.name != "posix" or shutil.which("bash") is None,
    reason="bash/POSIX shell unavailable; parity tests cannot exercise install.sh",
)
def test_parity_cuda_132_no_wizard(tmp_path_factory: pytest.TempPathFactory) -> None:
    """``install.sh`` and ``install.py`` issue the same torch install argv for CUDA."""
    twi = _load_twi_helpers()
    flags = ["--cuda", "--no-wizard"]
    env = {"KAINE_WHEEL_PROBE_NVML": "0"}

    sh_tmp = tmp_path_factory.mktemp("sh")
    py_tmp = tmp_path_factory.mktemp("py")

    proc_sh, log_sh = twi._run_install(
        sh_tmp,
        flags,
        installer="install.sh",
        nvidia_cuda="13.2",
        extra_env=env,
    )
    proc_py, log_py = twi._run_install(
        py_tmp,
        flags,
        installer="install.py",
        nvidia_cuda="13.2",
        extra_env=env,
    )

    sh_lines = _torch_install_lines(log_sh)
    py_lines = _torch_install_lines(log_py)

    assert sh_lines == py_lines, (
        f"pip argv for torch/torchvision install differs between install.sh "
        f"and install.py\nsh:\n{log_sh}\npy:\n{log_py}\n"
        f"sh exit={proc_sh.returncode}, py exit={proc_py.returncode}"
    )


@pytest.mark.skipif(
    os.name != "posix" or shutil.which("bash") is None,
    reason="bash/POSIX shell unavailable; parity tests cannot exercise install.sh",
)
def test_parity_rocm_with_rocminfo_sample(tmp_path_factory: pytest.TempPathFactory) -> None:
    """``install.sh`` and ``install.py`` issue the same torch install argv for ROCm."""
    twi = _load_twi_helpers()
    flags = ["--rocm", "--no-wizard"]
    env = {"KAINE_ROCM_VERSION": "7.2"}

    sh_tmp = tmp_path_factory.mktemp("sh")
    py_tmp = tmp_path_factory.mktemp("py")

    proc_sh, log_sh = twi._run_install(
        sh_tmp,
        flags,
        installer="install.sh",
        rocm=True,
        rocminfo_sample=True,
        extra_env=env,
    )
    proc_py, log_py = twi._run_install(
        py_tmp,
        flags,
        installer="install.py",
        rocm=True,
        rocminfo_sample=True,
        extra_env=env,
    )

    sh_lines = _torch_install_lines(log_sh)
    py_lines = _torch_install_lines(log_py)

    assert sh_lines == py_lines, (
        f"pip argv for torch/torchvision install differs between install.sh "
        f"and install.py\nsh:\n{log_sh}\npy:\n{log_py}\n"
        f"sh exit={proc_sh.returncode}, py exit={proc_py.returncode}"
    )


@pytest.mark.skipif(
    os.name != "posix" or shutil.which("bash") is None,
    reason="bash/POSIX shell unavailable; parity tests cannot exercise install.sh",
)
def test_parity_rocm_research(tmp_path_factory: pytest.TempPathFactory) -> None:
    """``install.sh`` and ``install.py`` resolve ROCm --research identically."""
    twi = _load_twi_helpers()
    flags = ["--rocm", "--no-wizard", "--research"]
    env = {"KAINE_ROCM_VERSION": "7.2"}

    sh_tmp = tmp_path_factory.mktemp("sh")
    py_tmp = tmp_path_factory.mktemp("py")

    proc_sh, log_sh = twi._run_install(
        sh_tmp,
        flags,
        installer="install.sh",
        rocm=True,
        rocminfo_sample=True,
        extra_env=env,
    )
    proc_py, log_py = twi._run_install(
        py_tmp,
        flags,
        installer="install.py",
        rocm=True,
        rocminfo_sample=True,
        extra_env=env,
    )

    sh_lines = _torch_install_lines(log_sh, include_audio=True)
    py_lines = _torch_install_lines(log_py, include_audio=True)

    assert sh_lines == py_lines, (
        f"pip argv differs between install.sh and install.py for ROCm --research\n"
        f"sh:\n{log_sh}\npy:\n{log_py}\n"
        f"sh exit={proc_sh.returncode}, py exit={proc_py.returncode}"
    )


@pytest.mark.skipif(
    os.name != "posix" or shutil.which("bash") is None,
    reason="bash/POSIX shell unavailable; parity tests cannot exercise install.sh",
)
def test_parity_cuda_coherent_torchaudio(tmp_path_factory: pytest.TempPathFactory) -> None:
    """``install.sh`` and ``install.py`` resolve the same coherent audio stack."""
    twi = _load_twi_helpers()
    flags = ["--cuda", "--no-wizard"]
    env = {"KAINE_WHEEL_PROBE_NVML": "0"}

    sh_tmp = tmp_path_factory.mktemp("sh")
    py_tmp = tmp_path_factory.mktemp("py")

    proc_sh, log_sh = twi._run_install(
        sh_tmp,
        flags,
        installer="install.sh",
        nvidia_cuda="13.2",
        fake_torchaudio="2.11.0+cu130",
        extra_env=env,
    )
    proc_py, log_py = twi._run_install(
        py_tmp,
        flags,
        installer="install.py",
        nvidia_cuda="13.2",
        fake_torchaudio="2.11.0+cu130",
        extra_env=env,
    )

    sh_lines = _torch_install_lines(log_sh, include_audio=True)
    py_lines = _torch_install_lines(log_py, include_audio=True)

    assert sh_lines == py_lines, (
        f"pip argv differs between install.sh and install.py for coherent torchaudio\n"
        f"sh:\n{log_sh}\npy:\n{log_py}\n"
        f"sh exit={proc_sh.returncode}, py exit={proc_py.returncode}"
    )
