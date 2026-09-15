# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Evaluate CUDA accelerator/runtime compatibility mismatch."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class MismatchVerdict:
    status: str
    reasons: list[str] = field(default_factory=list)
    cuda_version_ok: bool | None = None
    arch_ok: bool | None = None
    ptx_arch: str = ""


def _extract_sm_number(arch: str) -> int | None:
    m = re.match(r"^(?:sm|compute)_(\d+)", arch)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _parse_major_minor(version: str) -> tuple[int, int] | None:
    parts = version.split(".")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def evaluate_mismatch(
    driver_cuda_version: str | None,
    torch_cuda_version: str | None,
    compute_capability: tuple[int, int] | None,
    arch_list: list[str] | None,
) -> MismatchVerdict:
    if driver_cuda_version is None:
        return MismatchVerdict(status="skipped")

    if torch_cuda_version is None:
        return MismatchVerdict(status="unknown", reasons=["torch has no CUDA build"])

    driver_ver = _parse_major_minor(driver_cuda_version)
    torch_ver = _parse_major_minor(torch_cuda_version)

    if driver_ver is None or torch_ver is None:
        return MismatchVerdict(status="unknown", reasons=["invalid CUDA version format"])

    reasons: list[str] = []
    cuda_version_ok: bool | None = None
    arch_ok: bool | None = None
    ptx_arch: str = ""

    if torch_ver[0] > driver_ver[0]:
        cuda_version_ok = False
        reasons.append(
            f"torch CUDA {torch_cuda_version} requires newer driver than {driver_cuda_version}"
        )
    else:
        cuda_version_ok = True

    if compute_capability is None or arch_list is None:
        arch_ok = None
        if cuda_version_ok is False:
            return MismatchVerdict(
                status="mismatch",
                reasons=reasons,
                cuda_version_ok=cuda_version_ok,
                arch_ok=arch_ok,
            )
        return MismatchVerdict(
            status="unknown",
            reasons=["missing compute capability or arch list"],
            cuda_version_ok=cuda_version_ok,
            arch_ok=arch_ok,
        )

    sm_num = compute_capability[0] * 10 + compute_capability[1]

    if f"sm_{sm_num}" in arch_list:
        arch_ok = True
        status = "compatible"
    else:
        ptx_candidates = []
        for arch in arch_list:
            if arch.startswith("compute_") or "+PTX" in arch:
                num = _extract_sm_number(arch)
                if num is not None:
                    ptx_candidates.append((num, arch))
        valid_ptx = [(num, arch) for num, arch in ptx_candidates if num <= sm_num]
        if valid_ptx:
            best = max(valid_ptx, key=lambda x: x[0])
            ptx_arch = best[1]
            arch_ok = True
            status = "ptx_jit"
        else:
            arch_ok = False
            reasons.append(
                f"no SASS for sm_{sm_num} and no compatible PTX in {arch_list}"
            )
            status = "mismatch"

    if reasons:
        status = "mismatch"

    return MismatchVerdict(
        status=status,
        reasons=reasons,
        cuda_version_ok=cuda_version_ok,
        arch_ok=arch_ok,
        ptx_arch=ptx_arch,
    )
