# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json
import subprocess
import sys
from pathlib import Path

from kaine import install_target
from kaine.install_target import Target, detect_target, plan_for

REPO = Path(__file__).resolve().parents[1]


def _fake_run(mapping=None):
    mapping = mapping or {}

    def run(args, **kwargs):
        key = tuple(args)
        ret = mapping.get(key, {"returncode": 0, "stdout": "", "stderr": ""})

        class Result:
            returncode = ret["returncode"]
            stdout = ret.get("stdout", "")
            stderr = ret.get("stderr", "")

        return Result()

    return run


def _fake_which(mapping):
    def which(name):
        return mapping.get(name)
    return which


def _fake_read_text(mapping):
    def read_text(path):
        return mapping.get(path)
    return read_text


# --- target detection ladder ------------------------------------------------

def test_termux_by_version():
    t = detect_target(which=lambda _n: None, dir_exists=lambda _p: False,
        env={"TERMUX_VERSION": "0.118"},
        machine=lambda: "aarch64",
        system=lambda: "Linux",
    )
    assert t.name == "termux"
    assert t.flavor == "cpu"
    assert t.arch == "aarch64"


def test_termux_by_prefix():
    t = detect_target(which=lambda _n: None, dir_exists=lambda _p: False,
        env={"PREFIX": "/data/data/com.termux/files/usr"},
        machine=lambda: "aarch64",
        system=lambda: "Linux",
    )
    assert t.name == "termux"
    assert t.flavor == "cpu"


def test_macos_arm64_uses_mps():
    t = detect_target(which=lambda _n: None, dir_exists=lambda _p: False, machine=lambda: "arm64", system=lambda: "Darwin")
    assert t.name == "macos"
    assert t.flavor == "mps"


def test_macos_x86_uses_cpu():
    t = detect_target(which=lambda _n: None, dir_exists=lambda _p: False, machine=lambda: "x86_64", system=lambda: "Darwin")
    assert t.name == "macos"
    assert t.flavor == "cpu"


def test_jetson_without_nvidia_smi():
    t = detect_target(dir_exists=lambda _p: False,
        machine=lambda: "aarch64",
        system=lambda: "Linux",
        is_tegra=lambda: (True, "/etc/nv_tegra_release present (R35.4.1)"),
        which=lambda _: None,
        read_text=_fake_read_text({"/etc/nv_tegra_release": "R35 (release), REVISION: 4.1\n"}),
    )
    assert t.name == "jetson"
    assert t.flavor == "cuda"
    assert t.details["tegra_release"] == "R35 (release), REVISION: 4.1"


def test_jetson_with_working_nvidia_smi_still_jetson():
    t = detect_target(dir_exists=lambda _p: False,
        machine=lambda: "aarch64",
        system=lambda: "Linux",
        is_tegra=lambda: (True, "device-tree model contains 'Orin'"),
        which=_fake_which({"nvidia-smi": "/usr/bin/nvidia-smi"}),
        run=_fake_run({("/usr/bin/nvidia-smi", "-L"): {"returncode": 0, "stdout": ""}}),
        read_text=lambda _: None,
    )
    assert t.name == "jetson"
    assert t.flavor == "cuda"


def test_desktop_cuda():
    t = detect_target(dir_exists=lambda _p: False,
        machine=lambda: "x86_64",
        system=lambda: "Linux",
        which=_fake_which({"nvidia-smi": "/usr/bin/nvidia-smi"}),
        run=_fake_run({("/usr/bin/nvidia-smi", "-L"): {"returncode": 0, "stdout": ""}}),
    )
    assert t.name == "desktop-cuda"
    assert t.flavor == "cuda"


def test_desktop_rocm():
    t = detect_target(dir_exists=lambda _p: False,
        machine=lambda: "x86_64",
        system=lambda: "Linux",
        which=_fake_which({"rocm-smi": "/opt/rocm/bin/rocm-smi"}),
    )
    assert t.name == "desktop-rocm"
    assert t.flavor == "rocm"


def test_desktop_xpu():
    t = detect_target(dir_exists=lambda _p: False,
        machine=lambda: "x86_64",
        system=lambda: "Linux",
        which=_fake_which({"sycl-ls": "/usr/bin/sycl-ls"}),
    )
    assert t.name == "desktop-xpu"
    assert t.flavor == "xpu"


def test_desktop_cpu():
    t = detect_target(dir_exists=lambda _p: False,
        machine=lambda: "x86_64",
        system=lambda: "Linux",
        which=lambda _: None,
    )
    assert t.name == "desktop-cpu"
    assert t.flavor == "cpu"


def test_aarch64_cpu():
    t = detect_target(which=lambda _n: None, dir_exists=lambda _p: False,
        machine=lambda: "aarch64",
        system=lambda: "Linux",
        is_tegra=lambda: (False, "not tegra"),
    )
    assert t.name == "aarch64-cpu"
    assert t.flavor == "cpu"


def test_unsupported_armv7l():
    t = detect_target(which=lambda _n: None, dir_exists=lambda _p: False, machine=lambda: "armv7l", system=lambda: "Linux")
    assert t.name == "unsupported"
    assert "armv7l" in t.reason


def test_unsupported_riscv64():
    t = detect_target(which=lambda _n: None, dir_exists=lambda _p: False, machine=lambda: "riscv64", system=lambda: "Linux")
    assert t.name == "unsupported"
    assert "riscv64" in t.reason


# --- plan -------------------------------------------------------------------

def test_plan_termux():
    plan = plan_for(Target("termux", "cpu", "aarch64", "", {}))
    assert plan.extras == "memory-edge"
    assert "pkg" in plan.system_packages
    assert "apt" not in plan.system_packages
    runs_text = " ".join(plan.runs)
    assert "soma" in runs_text
    assert "chronos" in runs_text
    assert "nous" in runs_text
    assert "phantasia" in runs_text
    assert "audition" in runs_text
    assert "vox" in runs_text
    modules = {m for m, _ in plan.will_not_run}
    assert "topos" in modules
    assert "phantasia" not in modules
    assert any("qdrant" in m for m, _ in plan.will_not_run)
    assert not any(m in {"soma", "chronos", "nous"} for m, _ in plan.will_not_run)


def test_plan_unsupported():
    plan = plan_for(Target("unsupported", "", "riscv64", "bad arch", {}))
    assert plan.extras == ""
    assert any("all modules" in m for m, _ in plan.will_not_run)
    assert "Installation refused" in plan.notes[0]


def test_plan_desktop_cuda():
    plan = plan_for(Target("desktop-cuda", "cuda", "x86_64", "", {}))
    assert plan.extras == "full"
    assert plan.runs == ["all modules"]
    assert plan.will_not_run == []
    assert "apt" in plan.system_packages


def test_plan_jetson():
    plan = plan_for(Target("jetson", "cuda", "aarch64", "", {}))
    assert plan.extras == "full,speech-edge"


def test_plan_macos():
    plan = plan_for(Target("macos", "mps", "arm64", "", {}))
    assert plan.extras == "full"


# --- CLI --------------------------------------------------------------------

def test_cli_flavor_only(monkeypatch, capsys):
    monkeypatch.setattr(
        install_target,
        "detect_target",
        lambda **_: Target("jetson", "cuda", "aarch64", "", {}),
    )
    assert install_target.main(["--flavor-only"]) == 0
    assert capsys.readouterr().out.strip() == "cuda"


def test_cli_json(monkeypatch, capsys):
    monkeypatch.setattr(
        install_target,
        "detect_target",
        lambda **_: Target("termux", "cpu", "aarch64", "", {}),
    )
    assert install_target.main(["--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["target"]["name"] == "termux"
    assert data["plan"]["extras"] == "memory-edge"
    assert any(item["module"] == "topos" for item in data["plan"]["will_not_run"])


def test_cli_unsupported_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(
        install_target,
        "detect_target",
        lambda **_: Target("unsupported", "", "riscv64", "bad arch", {}),
    )
    assert install_target.main([]) == 3
    out = capsys.readouterr().out
    assert "Installation refused" in out
    assert "bad arch" in out


def test_cli_real_flavor_only_is_valid():
    """Smoke-test the probe on the host running the test suite."""
    result = subprocess.run(
        [str(Path(sys.executable).parent / "python3"), "-m", "kaine.install_target", "--flavor-only"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode in (0, 3)
    flavor = result.stdout.strip()
    assert flavor in {"", "cpu", "cuda", "rocm", "xpu", "mps"}


def test_an_accelerator_cannot_make_an_unsupported_arch_installable():
    t = detect_target(
        dir_exists=lambda _p: False,
        which=_fake_which({"nvidia-smi": "/usr/bin/nvidia-smi"}),
        run=_fake_run({("/usr/bin/nvidia-smi", "-L"): {"returncode": 0, "stdout": ""}}),
        machine=lambda: "riscv64",
        system=lambda: "Linux",
    )
    assert t.name == "unsupported"
    assert "riscv64" in t.reason


def test_jetson_nvidia_smi_timeout_still_jetson_without_cuda_detail():
    def raising_run(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=10)

    t = detect_target(
        dir_exists=lambda _p: False,
        machine=lambda: "aarch64",
        system=lambda: "Linux",
        is_tegra=lambda: (True, "device-tree model contains 'Jetson'"),
        which=_fake_which({"nvidia-smi": "/usr/bin/nvidia-smi"}),
        run=raising_run,
        read_text=lambda _: None,
    )
    assert t.name == "jetson"
    assert t.flavor == "cuda"
    assert "nvidia_cuda" not in t.details


def test_desktop_nvidia_smi_oserror_falls_through():
    def raising_run(args, **kwargs):
        raise OSError("exec format error")

    t = detect_target(
        dir_exists=lambda _p: False,
        machine=lambda: "x86_64",
        system=lambda: "Linux",
        is_tegra=lambda: (False, "no tegra marker"),
        which=_fake_which({"nvidia-smi": "/usr/bin/nvidia-smi"}),
        run=raising_run,
    )
    assert t.name != "desktop-cuda"
    assert t.name == "desktop-cpu"


def test_nvidia_smi_calls_pass_a_timeout():
    calls = []

    def recording_run(args, **kwargs):
        calls.append(kwargs)

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    t = detect_target(
        dir_exists=lambda _p: False,
        machine=lambda: "x86_64",
        system=lambda: "Linux",
        is_tegra=lambda: (False, "no tegra marker"),
        which=_fake_which({"nvidia-smi": "/usr/bin/nvidia-smi"}),
        run=recording_run,
    )
    assert t.name == "desktop-cuda"
    assert calls
    for kwargs in calls:
        assert kwargs.get("timeout") == 10
