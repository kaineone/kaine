# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Install-target extras tests for the sherpa-onnx Tier 1 profile."""

from __future__ import annotations

from typing import Any

import pytest

from kaine.install_target import Target, plan_for

_TARGETS: dict[str, tuple[str, str]] = {
    "desktop-cuda": ("cuda", "x86_64"),
    "desktop-rocm": ("rocm", "x86_64"),
    "desktop-xpu": ("xpu", "x86_64"),
    "desktop-cpu": ("cpu", "x86_64"),
    "macos": ("mps", "arm64"),
    "termux": ("cpu", "aarch64"),
    "aarch64-cpu": ("cpu", "aarch64"),
    "jetson": ("cuda", "aarch64"),
}


def _plan_for(name: str) -> Any:
    flavor, arch = _TARGETS[name]
    return plan_for(Target(name, flavor, arch, "", {}))


def test_aarch64_cpu_and_jetson_include_speech_edge() -> None:
    assert _plan_for("aarch64-cpu").extras == "full,speech-edge"
    assert _plan_for("jetson").extras == "full,speech-edge"


@pytest.mark.parametrize(
    "name",
    [
        "desktop-cpu",
        "desktop-cuda",
        "desktop-rocm",
        "desktop-xpu",
        "macos",
    ],
)
def test_desktop_targets_keep_full_extras(name: str) -> None:
    assert _plan_for(name).extras == "full"


def test_termux_keeps_memory_edge_extras() -> None:
    assert _plan_for("termux").extras == "memory-edge"
