# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Backend routing tests for the Nous health probe."""

from __future__ import annotations

import builtins

import pytest

from kaine.nexus.health import DEGRADED, DOWN, UP, nous_health_probe
from kaine.nexus.health.config import build_dependency_specs


def _block_jax_and_pymdp(monkeypatch):
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        top = name.split(".", 1)[0]
        if top in {"jax", "jaxlib", "pymdp"}:
            raise ImportError(f"{name} is blocked in this test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)


def _nous_spec(specs):
    return next(s for s in specs if s.module == "nous")


@pytest.mark.asyncio
async def test_numpy_backend_up_even_when_pymdp_jax_blocked(monkeypatch):
    _block_jax_and_pymdp(monkeypatch)
    status, detail = await nous_health_probe(backend="numpy")
    assert status == UP
    assert "ran one step" in detail


@pytest.mark.asyncio
async def test_numpy_backend_down_on_infer_error(monkeypatch):
    from kaine.modules.nous.numpy_engine import NumpyActiveInferenceEngine

    def broken_infer(*args, **kwargs):
        raise RuntimeError("simulated infer failure")

    monkeypatch.setattr(NumpyActiveInferenceEngine, "infer", broken_infer)
    status, detail = await nous_health_probe(backend="numpy")
    assert status == DOWN
    assert "nous numpy backend failed" in detail


@pytest.mark.asyncio
async def test_unknown_backend_degraded():
    status, detail = await nous_health_probe(backend="bogus")
    assert status == DEGRADED
    assert "not recognised" in detail


@pytest.mark.asyncio
async def test_build_specs_numpy_backend(monkeypatch):
    _block_jax_and_pymdp(monkeypatch)
    specs = build_dependency_specs(
        redis_cfg={"host": "127.0.0.1", "port": 6379},
        qdrant_cfg={},
        qdrant_secret_key=None,
        redis_password=None,
        lingua_cfg={},
        audition_cfg={},
        vox_cfg={},
        nous_cfg={"backend": "numpy"},
        state_encryption_cfg=None,
    )
    spec = _nous_spec(specs)
    assert spec.name == "NumPy active inference"
    status, detail = await spec.probe()
    assert status == UP
    assert "ran one step" in detail


def test_build_specs_defaults_to_pymdp(monkeypatch):
    specs = build_dependency_specs(
        redis_cfg={"host": "127.0.0.1", "port": 6379},
        qdrant_cfg={},
        qdrant_secret_key=None,
        redis_password=None,
        lingua_cfg={},
        audition_cfg={},
        vox_cfg={},
        nous_cfg={},
        state_encryption_cfg=None,
    )
    spec = _nous_spec(specs)
    assert spec.name == "pymdp + JAX"
