# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the Nous active-inference health probe (pymdp + jax import check)."""
from __future__ import annotations

import builtins

import pytest

from kaine.nexus.health import DOWN, UP, nous_health_probe


@pytest.mark.asyncio
async def test_probe_healthy_when_pymdp_and_jax_importable():
    pytest.importorskip("pymdp")
    pytest.importorskip("jax")
    status, detail = await nous_health_probe()
    assert status == UP
    assert "jax" in detail.lower()


@pytest.mark.asyncio
async def test_probe_unhealthy_on_import_error(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pymdp" or name.startswith("pymdp."):
            raise ImportError("pymdp not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    status, detail = await nous_health_probe()
    assert status == DOWN
    assert "import failed" in detail


def test_probe_has_no_binary_path_reference():
    import inspect

    src = inspect.getsource(nous_health_probe)
    # No binary-path plumbing remains; the probe imports pymdp/jax instead.
    assert "binary_path" not in src
    assert "os.access" not in src
    assert "external/OpenNARS" not in src
