# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Backend routing tests for the planning health probe."""

from __future__ import annotations

import builtins

import pytest

from kaine.dashboard.health import DEGRADED, DOWN, UP, planning_health_probe
from kaine.dashboard.health.config import build_dependency_specs


def _block_jax_and_pymdp(monkeypatch):
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        top = name.split(".", 1)[0]
        if top in {"jax", "jaxlib", "pymdp"}:
            raise ImportError(f"{name} is blocked in this test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)


def _planning_spec(specs):
    return next(s for s in specs if s.module == "planning")


@pytest.mark.asyncio
async def test_numpy_backend_up_even_when_pymdp_jax_blocked(monkeypatch):
    _block_jax_and_pymdp(monkeypatch)
    status, detail = await planning_health_probe(backend="numpy")
    assert status == UP
    assert "ran one step" in detail


@pytest.mark.asyncio
async def test_numpy_backend_down_on_infer_error(monkeypatch):
    from kaine.modules.planning.numpy_engine import NumpyActiveInferenceEngine

    def broken_infer(*args, **kwargs):
        raise RuntimeError("simulated infer failure")

    monkeypatch.setattr(NumpyActiveInferenceEngine, "infer", broken_infer)
    status, detail = await planning_health_probe(backend="numpy")
    assert status == DOWN
    assert "planning numpy backend failed" in detail


@pytest.mark.asyncio
async def test_unknown_backend_degraded():
    status, detail = await planning_health_probe(backend="bogus")
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
        language_cfg={},
        audition_cfg={},
        vocal_cfg={},
        planning_cfg={"backend": "numpy"},
        state_encryption_cfg=None,
    )
    spec = _planning_spec(specs)
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
        language_cfg={},
        audition_cfg={},
        vocal_cfg={},
        planning_cfg={},
        state_encryption_cfg=None,
    )
    spec = _planning_spec(specs)
    assert spec.name == "pymdp + JAX"
