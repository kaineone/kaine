# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Tests for kaine.accel_selftest."""

from __future__ import annotations

import json
import types
from typing import Any

import pytest

from kaine.accel_selftest import main, run_selftest


def test_cpu_selftest_ok():
    """The CPU path validates the comparison machinery and must pass."""
    pytest.importorskip("torch")
    result = run_selftest(device="cpu")
    assert result["ok"] is True
    assert result["skipped"] is False
    for check in result["checks"]:
        assert check["ok"] is True
        if not check.get("skipped"):
            assert check["finite"] is True


def test_cuda_unavailable_is_skipped(monkeypatch):
    """A CUDA request on a host without CUDA is reported as skipped."""
    fake_torch = types.SimpleNamespace(
        __version__="fake-torch",
        cuda=types.SimpleNamespace(is_available=lambda: False),
    )
    result = run_selftest(device="cuda", torch_module=fake_torch)
    assert result["ok"] is False
    assert result["skipped"] is True

    monkeypatch.setattr("kaine.accel_selftest.run_selftest", lambda **kwargs: result)
    assert main(["--device", "cuda"]) == 2


def test_half_matmul_nan_fails():
    """A poisoned half-precision matmul is detected as non-finite."""
    real_torch = pytest.importorskip("torch")

    fake = types.SimpleNamespace(**vars(real_torch))
    real_matmul = real_torch.matmul

    def nan_matmul(a: Any, b: Any, *args: Any, **kwargs: Any) -> Any:
        # Emulate a half matmul (so the test works even on CPU-only hosts) and
        # then poison the result with NaN.
        if a.dtype == real_torch.float16 or getattr(b, "dtype", None) == real_torch.float16:
            a_f32 = a.to(dtype=real_torch.float32)
            b_f32 = b.to(dtype=real_torch.float32) if hasattr(b, "to") else b
            out = real_matmul(a_f32, b_f32, *args, **kwargs).to(dtype=real_torch.float16)
            return out * float("nan")
        return real_matmul(a, b, *args, **kwargs)

    fake.matmul = nan_matmul
    fake.cuda = types.SimpleNamespace(
        is_available=lambda: False,
        is_bf16_supported=lambda: False,
        get_device_name=lambda idx: None,
        synchronize=lambda: None,
    )

    result = run_selftest(device="cpu", torch_module=fake)
    assert result["ok"] is False
    failing_half_matmul = [
        c
        for c in result["checks"]
        if c["name"] == "matmul" and c["dtype"] == "float16" and not c["ok"]
    ]
    assert failing_half_matmul
    assert failing_half_matmul[0]["finite"] is False


def test_cuda_synchronize_failure_is_reported():
    """A failing final torch.cuda.synchronize() is reported as a hard failure."""
    real_torch = pytest.importorskip("torch")

    def boom():
        raise RuntimeError("synchronize boom")

    fake = types.SimpleNamespace(**vars(real_torch))
    fake.cuda = types.SimpleNamespace(
        is_available=lambda: True,
        is_bf16_supported=lambda: False,
        get_device_name=lambda idx: "Fake CUDA",
        synchronize=boom,
    )

    result = run_selftest(device="cuda", torch_module=fake)
    assert result["ok"] is False
    assert result["skipped"] is False
    assert "torch.cuda.synchronize()" in result["reason"]
    assert "RuntimeError" in result["reason"]


def test_main_json_cpu(capsys):
    """``--json`` emits valid JSON and exits 0 on a passing CPU run."""
    pytest.importorskip("torch")
    rc = main(["--device", "cpu", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "ok" in data
    assert data["ok"] is True
