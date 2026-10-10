# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Target detection and extras planning for the KAINE installer.

This module intentionally imports only the Python standard library (plus
``kaine.hostmem.is_tegra``, which is stdlib + ctypes only) so it can be run
before the package is installed:

    PYTHONPATH=<repo> python3 -m kaine.install_target

The detection ladder orders checks from most specific to most general:
Termux, macOS, Linux Tegra, then Linux x86_64/aarch64/other.  Every
filesystem, environment and subprocess access is made through injectable
callables so tests can fake every input.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from kaine.hostmem import is_tegra


@dataclass(frozen=True)
class Target:
    name: str
    flavor: str
    arch: str
    reason: str
    details: dict[str, Any]


@dataclass(frozen=True)
class Plan:
    extras: str
    runs: list[str]
    will_not_run: list[tuple[str, str]]
    system_packages: dict[str, list[str]]
    notes: list[str]


def _read_text(path: str, *, encoding: str = "utf-8") -> str | None:
    try:
        with open(path, encoding=encoding, errors="replace") as f:
            return f.read()
    except Exception:
        return None


def _prefix_contains(prefix: str, token: str) -> bool:
    return token in prefix.lower()


def _parse_cuda_version(output: str) -> str | None:
    for line in output.splitlines():
        if "CUDA Version" in line:
            parts = line.split("CUDA Version")
            if len(parts) > 1:
                return parts[-1].strip().strip(": ")
    return None


def _dir_exists(path: str) -> bool:
    try:
        return Path(path).is_dir()
    except Exception:
        return False


_SYSTEM_PACKAGES = {
    "apt": ["python3", "python3-venv", "python3-dev", "git", "build-essential", "redis-server", "curl"],
    "dnf": ["python3", "python3-devel", "git", "gcc", "gcc-c++", "make", "redis", "curl"],
    "pacman": ["python", "git", "base-devel", "redis", "curl"],
    "pkg": ["python", "git", "rust", "binutils", "redis", "python-numpy", "python-cryptography", "curl"],
    "brew": ["python", "git", "redis"],
}


def detect_target(
    *,
    env: dict[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., Any] = subprocess.run,
    read_text: Callable[[str], str | None] = _read_text,
    machine: Callable[[], str] = platform.machine,
    system: Callable[[], str] = platform.system,
    is_tegra: Callable[[], tuple[bool, str]] = is_tegra,
    dir_exists: Callable[[str], bool] | None = None,
) -> Target:
    env = env or {}
    dir_exists = dir_exists or _dir_exists
    arch = machine()
    sysname = system()

    # 1. Termux (Android) — most specific first.
    termux_version = env.get("TERMUX_VERSION")
    prefix = env.get("PREFIX")
    if termux_version or (prefix and _prefix_contains(prefix, "com.termux")):
        return Target(
            name="termux",
            flavor="cpu",
            arch=arch,
            reason="Termux environment detected",
            details={"termux_version": termux_version, "prefix": prefix},
        )

    # 2. macOS.
    if sysname == "Darwin":
        flavor = "mps" if arch == "arm64" else "cpu"
        return Target(
            name="macos",
            flavor=flavor,
            arch=arch,
            reason="macOS detected",
            details={"system": sysname, "arch": arch},
        )

    # Architecture gate: no accelerator probe can make an unsupported
    # architecture installable (there are no wheels for it).
    if sysname == "Linux" and arch not in ("x86_64", "aarch64", "arm64"):
        return Target(
            name="unsupported",
            flavor="cpu",
            arch=arch,
            reason=f"no supported install path for the {arch} architecture",
            details={},
        )

    # 3. Linux aarch64 Tegra / Jetson.
    if sysname == "Linux" and arch == "aarch64":
        tegra, tegra_reason = is_tegra()
        if tegra:
            release_text = read_text("/etc/nv_tegra_release")
            tegra_release = None
            if release_text:
                lines = [line.strip() for line in release_text.strip().splitlines() if line.strip()]
                if lines:
                    tegra_release = lines[0][:120]
            nvidia_cuda_ver = None
            nvidia_path = which("nvidia-smi")
            if nvidia_path:
                try:
                    list_result = run(
                        [nvidia_path, "-L"],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=10,
                    )
                    if list_result.returncode == 0:
                        top_result = run(
                            [nvidia_path],
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=10,
                        )
                        if top_result.returncode == 0:
                            nvidia_cuda_ver = _parse_cuda_version(top_result.stdout)
                except (OSError, subprocess.SubprocessError):
                    # nvidia-smi missing, not executable, or hung (timeout): the
                    # host is still a Jetson by its Tegra marker, so only the
                    # CUDA version detail is omitted.
                    pass
            details: dict[str, Any] = {"tegra": tegra_reason}
            if tegra_release:
                details["tegra_release"] = tegra_release
            if nvidia_cuda_ver:
                details["nvidia_cuda"] = nvidia_cuda_ver
            return Target(
                name="jetson",
                flavor="cuda",
                arch=arch,
                reason="NVIDIA Tegra / Jetson marker detected",
                details=details,
            )

    # 4. Desktop NVIDIA CUDA.
    if sysname == "Linux":
        nvidia_path = which("nvidia-smi")
        if nvidia_path:
            try:
                result = run(
                    [nvidia_path, "-L"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
                if result.returncode == 0:
                    return Target(
                        name="desktop-cuda",
                        flavor="cuda",
                        arch=arch,
                        reason="nvidia-smi -L succeeded",
                        details={"nvidia_smi": "available"},
                    )
            except (OSError, subprocess.SubprocessError):
                # nvidia-smi missing, not executable, or hung: this host is not
                # classified as desktop-cuda and detection falls through to the
                # next rung.
                pass

    # 5. Desktop AMD ROCm.
    if sysname == "Linux" and (which("rocm-smi") or dir_exists("/opt/rocm")):
        return Target(
            name="desktop-rocm",
            flavor="rocm",
            arch=arch,
            reason="ROCm detected",
            details={},
        )

    # 6. Desktop Intel XPU.
    if sysname == "Linux" and (which("xpu-smi") or which("sycl-ls")):
        return Target(
            name="desktop-xpu",
            flavor="xpu",
            arch=arch,
            reason="Intel XPU detected",
            details={},
        )

    # 7. Generic Linux x86_64 desktop CPU.
    if sysname == "Linux" and arch == "x86_64":
        return Target(
            name="desktop-cpu",
            flavor="cpu",
            arch=arch,
            reason="Generic x86_64 Linux desktop",
            details={"system": sysname, "arch": arch},
        )

    # 8. Generic Linux aarch64 CPU.
    if sysname == "Linux" and arch == "aarch64":
        return Target(
            name="aarch64-cpu",
            flavor="cpu",
            arch=arch,
            reason="Generic aarch64 Linux CPU host",
            details={"system": sysname, "arch": arch},
        )

    # 9. Anything else is unsupported.
    return Target(
        name="unsupported",
        flavor="",
        arch=arch,
        reason=f"Unsupported machine/architecture: {arch}",
        details={"system": sysname, "arch": arch},
    )


def plan_for(target: Target) -> Plan:
    extras: str
    runs: list[str]
    will_not_run: list[tuple[str, str]]
    system_packages: dict[str, list[str]]
    notes: list[str]

    if target.name == "termux":
        extras = "memory-edge"
        runs = [
            "mnemos (with sqlite_vec backend)",
            "memory",
            "edge",
            "thymos",
            "lingua",
            "syneidesis",
            "soma (NumPy CfC)",
            "chronos (NumPy CfC)",
            'audition (with [audition].backend = "sherpa_onnx")',
            'vox (with [vox].backend = "sherpa_onnx")',
            'nous (with [nous].backend = "numpy")',
            'phantasia (with [phantasia].engine = "numpy")',
        ]
        will_not_run = [
            ("topos", "needs torch for its video encoder; no Termux build"),
            ("mnemos with qdrant", "no Qdrant build for Android; use [mnemos].backend = \"sqlite_vec\""),
        ]
        system_packages = {"pkg": list(_SYSTEM_PACKAGES["pkg"])}
        notes = [
            "Termux installs the memory and edge extras only.",
            'Nous needs [nous].backend = "numpy" and Phantasia needs [phantasia].engine = "numpy" there (the Tier 1 profile sets both; the Tier 0 profile sets the Nous backend and lists Phantasia as unsupported).',
            'Speech needs the speech-edge extra and its models: pkg install python-numpy, then pip install sherpa-onnx, then python -m kaine.setup.speech_models. The sherpa-onnx Termux wheels are new upstream and unproven on a device here.',
            'Audition on Termux: set [audition].vad_backend = "rms" (webrtcvad ships only in the audio extra, which pulls torch).',
        ]
    elif target.name == "unsupported":
        extras = ""
        runs = []
        will_not_run = [("all modules", target.reason)]
        system_packages = {}
        notes = [f"Installation refused: {target.reason}"]
    else:
        if target.name in ("aarch64-cpu", "jetson"):
            extras = "full,speech-edge"
        else:
            extras = "full"
        runs = ["all modules"]
        will_not_run = []
        system_packages = {k: list(v) for k, v in _SYSTEM_PACKAGES.items()}
        if target.name == "desktop-cuda":
            notes = ["Desktop CUDA host can run the full distribution."]
        elif target.name == "desktop-rocm":
            notes = ["Desktop ROCm host can run the full distribution."]
        elif target.name == "desktop-xpu":
            notes = ["Desktop Intel XPU host can run the full distribution."]
        elif target.name == "desktop-cpu":
            notes = ["Desktop CPU host can run the full distribution."]
        elif target.name == "jetson":
            notes = ["Jetson Tegra CUDA host can run the full distribution (aarch64 cu13x wheel)."]
        elif target.name == "aarch64-cpu":
            notes = ["aarch64 CPU host can run the full distribution."]
        elif target.name == "macos":
            notes = ["macOS host can run the full distribution."]
        else:
            notes = [f"Unknown target {target.name}; defaulting to full extras."]

    return Plan(
        extras=extras,
        runs=runs,
        will_not_run=will_not_run,
        system_packages=system_packages,
        notes=notes,
    )


def _format_plan(target: Target, plan: Plan) -> str:
    lines = [f"KAINE install target: {target.name} (flavor: {target.flavor}, arch: {target.arch})"]
    for note in plan.notes:
        lines.append(f"  note: {note}")
    lines.append(f"  extras plan: {plan.extras or '(none)'}")
    if plan.runs:
        lines.append("  will run:")
        for item in plan.runs:
            lines.append(f"    - {item}")
    if plan.will_not_run:
        lines.append("  will NOT run:")
        for item, reason in plan.will_not_run:
            lines.append(f"    - {item}: {reason}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kaine.install_target")
    parser.add_argument("--json", action="store_true", help="emit JSON and exit")
    parser.add_argument("--flavor-only", action="store_true", help="emit only the wheel flavor")
    args = parser.parse_args(argv)

    target = detect_target()
    plan = plan_for(target)

    if args.flavor_only:
        print(target.flavor)
        return 0
    if args.json:
        payload = {
            "target": dataclasses.asdict(target),
            "plan": {
                "extras": plan.extras,
                "runs": plan.runs,
                "will_not_run": [{"module": m, "reason": r} for m, r in plan.will_not_run],
                "system_packages": plan.system_packages,
                "notes": plan.notes,
            },
        }
        print(json.dumps(payload, indent=2))
        return 0

    print(_format_plan(target, plan))

    if target.name == "unsupported":
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
