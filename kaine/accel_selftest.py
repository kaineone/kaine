# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Numerical self-test for accelerator backends used by the KAINE installer.

After GPU wheel installation the installer runs this short self-test on the
target device (default CUDA).  A handful of common operations are executed in
reduced precision and compared against a float32 CPU reference.  If any check
produces non-finite values or exceeds its tolerance, the installer should fall
back to CPU wheels.

The module never raises: per-check failures are returned in the ``checks``
list and the top-level ``ok`` flag is set to ``False``.  If torch cannot be
imported or the requested accelerator is unavailable the self-test is reported
as ``skipped`` (which the installer treats as a GPU-path failure).

For hosts without native float16 support on CPU, the float16 checks are
transparently emulated with float32 math so that the comparison machinery can
still be validated; the GPU path always uses the requested dtype.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional


def _make_result(
    ok: bool,
    skipped: bool,
    reason: str,
    checks: List[Dict[str, Any]],
    device_name: Optional[str],
    torch_version: Optional[str],
) -> Dict[str, Any]:
    return {
        "ok": ok,
        "skipped": skipped,
        "reason": reason,
        "checks": checks,
        "device_name": device_name,
        "torch_version": torch_version,
    }


def run_selftest(
    device: str = "cuda", *, seed: int = 0, torch_module: Any = None
) -> Dict[str, Any]:
    """Run a short numerical self-test on ``device`` and return a result dict.

    Parameters
    ----------
    device:
        Accelerator to test (``"cuda"`` by default, or ``"cpu"``).
    seed:
        RNG seed used to generate the reference inputs on the CPU.
    torch_module:
        Optional torch-compatible object, useful for unit tests.

    Returns
    -------
    dict
        ``{"ok": bool, "skipped": bool, "reason": str,
          "checks": [...], "device_name": str|None,
          "torch_version": str|None}``
    """
    # Lazy torch import (or use injected module).
    torch = torch_module
    if torch is None:
        try:
            import torch as _torch
            torch = _torch
        except Exception as exc:  # pragma: no cover - defensive
            return _make_result(
                ok=False,
                skipped=True,
                reason=f"torch import failed: {exc.__class__.__name__}",
                checks=[],
                device_name=None,
                torch_version=None,
            )

    torch_version = getattr(torch, "__version__", None)

    # GPU not usable -> skipped (installer treats as a GPU-path failure).
    if device == "cuda" and not torch.cuda.is_available():
        return _make_result(
            ok=False,
            skipped=True,
            reason="CUDA not available",
            checks=[],
            device_name=None,
            torch_version=torch_version,
        )

    try:
        device_name = (
            torch.cuda.get_device_name(device) if device == "cuda" else str(device)
        )
    except Exception:
        device_name = str(device)

    checks: List[Dict[str, Any]] = []
    gen = torch.Generator(device="cpu").manual_seed(seed)

    # Fixed-seed reference inputs, always float32 on CPU.
    size = 512
    A_f32 = torch.rand((size, size), generator=gen, dtype=torch.float32, device="cpu")
    B_f32 = torch.rand((size, size), generator=gen, dtype=torch.float32, device="cpu")

    N, C, H, W = 2, 16, 64, 64
    conv_in_f32 = torch.rand(
        (N, C, H, W), generator=gen, dtype=torch.float32, device="cpu"
    )
    conv_w_f32 = torch.rand(
        (32, C, 3, 3), generator=gen, dtype=torch.float32, device="cpu"
    )
    conv_b_f32 = torch.rand((32,), generator=gen, dtype=torch.float32, device="cpu")

    soft_in_f32 = torch.rand((64, 1024), generator=gen, dtype=torch.float32, device="cpu")

    # CPU references.
    ref_matmul = torch.matmul(A_f32, B_f32)
    ref_conv = torch.nn.functional.conv2d(
        conv_in_f32, conv_w_f32, bias=conv_b_f32, padding=1
    )
    ref_soft = torch.nn.functional.softmax(soft_in_f32, dim=-1)

    TOL = {torch.float16: 2e-2, torch.bfloat16: 5e-2, torch.float32: 1e-4}

    def _record_failure(name: str, dtype: str, exc_name: str, **extra: Any) -> None:
        checks.append(
            {
                "name": name,
                "dtype": dtype,
                "finite": False,
                "max_rel_err": None,
                "ok": False,
                "exc": exc_name,
                **extra,
            }
        )

    def _compare(
        name: str,
        dtype_str: str,
        ref: Any,
        dev_out: Any,
        tol: float,
        *,
        pre_entry: Optional[Dict[str, Any]] = None,
    ) -> bool:
        entry = pre_entry or {"name": name, "dtype": dtype_str}
        try:
            if device == "cuda":
                torch.cuda.synchronize()
            out_cpu = dev_out.to(device="cpu", dtype=torch.float32)
            finite = bool(torch.isfinite(out_cpu).all())
            if not finite:
                entry.update({"finite": False, "max_rel_err": None, "ok": False})
                checks.append(entry)
                return False
            ref_cpu = ref.to(device="cpu", dtype=torch.float32)
            max_diff = (out_cpu - ref_cpu).abs().max().item()
            max_ref = ref_cpu.abs().max().item()
            rel_err = max_diff / max(max_ref, 1e-6)
            ok = rel_err <= tol
            entry.update({"finite": finite, "max_rel_err": rel_err, "ok": ok})
            checks.append(entry)
            return ok
        except Exception as exc:
            entry.update(
                {
                    "finite": False,
                    "max_rel_err": None,
                    "ok": False,
                    "exc": exc.__class__.__name__,
                }
            )
            checks.append(entry)
            return False

    def _run_op(
        name: str, dtype_str: str, ref: Any, compute: Any, dtype_enum: Any
    ) -> bool:
        """Compute ``compute(dtype)`` on device and compare to ``ref``.

        If float16 is not supported on a non-CUDA device, fall back to float32
        math and record that the half-precision check was emulated.  The GPU
        path always uses the requested dtype.
        """
        try:
            dev_out = compute(dtype_enum)
        except Exception as exc:
            if dtype_enum == torch.float16 and device != "cuda":
                try:
                    dev_out = compute(torch.float32)
                    emulated_entry = {
                        "name": name,
                        "dtype": dtype_str,
                        "emulated": True,
                        "reason": (
                            f"float16 not supported on {device}; "
                            "validated with float32 math"
                        ),
                    }
                    return _compare(
                        name,
                        dtype_str,
                        ref,
                        dev_out,
                        TOL[torch.float32],
                        pre_entry=emulated_entry,
                    )
                except Exception:
                    pass
            _record_failure(name, dtype_str, exc.__class__.__name__)
            return False
        return _compare(name, dtype_str, ref, dev_out, TOL[dtype_enum])

    # (1) matmul in float16 and, when supported, bfloat16.
    def matmul(dtype: Any) -> Any:
        return torch.matmul(
            A_f32.to(device=device, dtype=dtype),
            B_f32.to(device=device, dtype=dtype),
        )

    ok = _run_op("matmul", "float16", ref_matmul, matmul, torch.float16)

    bf16_supported = False
    try:
        bf16_supported = bool(torch.cuda.is_bf16_supported())
    except Exception:
        bf16_supported = False
    if device == "cuda" and bf16_supported:
        ok = _run_op("matmul", "bfloat16", ref_matmul, matmul, torch.bfloat16) and ok
    else:
        checks.append(
            {
                "name": "matmul",
                "dtype": "bfloat16",
                "skipped": True,
                "reason": "bfloat16 not supported on this device",
                "finite": None,
                "max_rel_err": None,
                "ok": True,
            }
        )

    # (2) conv2d in float16.
    def conv2d(dtype: Any) -> Any:
        return torch.nn.functional.conv2d(
            conv_in_f32.to(device=device, dtype=dtype),
            conv_w_f32.to(device=device, dtype=dtype),
            bias=conv_b_f32.to(device=device, dtype=dtype),
            padding=1,
        )

    ok = _run_op("conv2d", "float16", ref_conv, conv2d, torch.float16) and ok

    # (3) softmax in float16.
    def softmax(dtype: Any) -> Any:
        return torch.nn.functional.softmax(
            soft_in_f32.to(device=device, dtype=dtype), dim=-1
        )

    ok = _run_op("softmax", "float16", ref_soft, softmax, torch.float16) and ok

    # (4) matmul in float32.
    ok = _run_op("matmul", "float32", ref_matmul, matmul, torch.float32) and ok

    if device == "cuda":
        try:
            torch.cuda.synchronize()
        except Exception:
            pass

    reason = "passed" if ok else "accelerator self-test failed"
    return _make_result(
        ok=ok,
        skipped=False,
        reason=reason,
        checks=checks,
        device_name=device_name,
        torch_version=torch_version,
    )


def _print_summary(result: Dict[str, Any]) -> None:
    status = "OK" if result["ok"] else "FAILED"
    if result["skipped"]:
        status = "SKIPPED"
    print(f"Accelerator self-test: {status}")
    print(f"  reason: {result['reason']}")
    print(f"  device_name: {result.get('device_name')}")
    print(f"  torch_version: {result.get('torch_version')}")
    print("  checks:")
    for c in result["checks"]:
        extra = ""
        if c.get("skipped"):
            extra = " [skipped]"
        elif c.get("emulated"):
            extra = " [emulated]"
        print(
            f"    {c['name']:<10} {c['dtype']:<10} finite={c.get('finite')} "
            f"max_rel_err={c.get('max_rel_err')} ok={c['ok']}{extra}"
        )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="KAINE accelerator numerical self-test"
    )
    parser.add_argument(
        "--device", default="cuda", help="device to test (default: cuda)"
    )
    parser.add_argument(
        "--json", action="store_true", help="emit JSON instead of human summary"
    )
    args = parser.parse_args(argv)

    result = run_selftest(device=args.device)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _print_summary(result)

    if result["skipped"]:
        return 2
    if result["ok"]:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
