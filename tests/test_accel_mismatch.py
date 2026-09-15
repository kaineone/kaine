# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
from kaine.setup.accel_mismatch import evaluate_mismatch


def test_exact_sass_match():
    verdict = evaluate_mismatch(
        driver_cuda_version="13.2",
        torch_cuda_version="13.2",
        compute_capability=(8, 9),
        arch_list=["sm_50", "sm_60", "sm_70", "sm_80", "sm_89", "sm_90", "compute_90"],
    )
    assert verdict.status == "compatible"
    assert verdict.cuda_version_ok is True
    assert verdict.arch_ok is True


def test_same_major_ptx_jit():
    verdict = evaluate_mismatch(
        driver_cuda_version="13.2",
        torch_cuda_version="13.2",
        compute_capability=(8, 7),
        arch_list=["sm_50", "sm_60", "sm_70", "sm_80", "sm_86", "sm_90", "compute_80"],
    )
    assert verdict.status == "ptx_jit"
    assert verdict.arch_ok is True
    assert verdict.ptx_arch == "compute_80"


def test_cross_major_ptx_jit():
    verdict = evaluate_mismatch(
        driver_cuda_version="13.2",
        torch_cuda_version="12.8",
        compute_capability=(12, 0),
        arch_list=["sm_50", "sm_60", "sm_70", "sm_80", "sm_86", "sm_90", "sm_100", "compute_90"],
    )
    assert verdict.status == "ptx_jit"
    assert verdict.ptx_arch == "compute_90"
    assert verdict.cuda_version_ok is True


def test_hard_mismatch_no_coverage():
    verdict = evaluate_mismatch(
        driver_cuda_version="13.2",
        torch_cuda_version="12.8",
        compute_capability=(8, 7),
        arch_list=["sm_90", "sm_100", "compute_90"],
    )
    assert verdict.status == "mismatch"
    assert verdict.arch_ok is False
    assert verdict.cuda_version_ok is True
    assert len(verdict.reasons) == 1


def test_cuda_version_mismatch():
    verdict = evaluate_mismatch(
        driver_cuda_version="11.8",
        torch_cuda_version="12.8",
        compute_capability=(8, 6),
        arch_list=["sm_86"],
    )
    assert verdict.status == "mismatch"
    assert verdict.cuda_version_ok is False
    assert verdict.arch_ok is True


def test_cpu_only_skip():
    verdict = evaluate_mismatch(
        driver_cuda_version=None,
        torch_cuda_version="12.8",
        compute_capability=(8, 6),
        arch_list=["sm_86"],
    )
    assert verdict.status == "skipped"


def test_no_torch_cuda():
    verdict = evaluate_mismatch(
        driver_cuda_version="13.2",
        torch_cuda_version=None,
        compute_capability=(8, 6),
        arch_list=["sm_86"],
    )
    assert verdict.status == "unknown"


def test_unknown_arch():
    verdict = evaluate_mismatch(
        driver_cuda_version="13.2",
        torch_cuda_version="13.2",
        compute_capability=None,
        arch_list=None,
    )
    assert verdict.status == "unknown"
    assert verdict.cuda_version_ok is True
    assert verdict.arch_ok is None


def test_jetson_orin_scenario():
    verdict = evaluate_mismatch(
        driver_cuda_version="13.2",
        torch_cuda_version="12.8",
        compute_capability=(8, 7),
        arch_list=["sm_50", "sm_60", "sm_70", "sm_80", "sm_86", "sm_90", "sm_100", "compute_90"],
    )
    assert verdict.status == "mismatch"


def test_sm90_ptx_plus():
    verdict = evaluate_mismatch(
        driver_cuda_version="13.2",
        torch_cuda_version="13.2",
        compute_capability=(12, 0),
        arch_list=["sm_90+PTX"],
    )
    assert verdict.status == "ptx_jit"
    assert verdict.ptx_arch == "sm_90+PTX"
