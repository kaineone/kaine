# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for residency router notifications in the organ window (task 5.1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from kaine.modules.sleep.organ_window import run_with_organ_window


class _FakeController:
    """Minimal controller for residency tests (no recording needed)."""

    def __init__(self, *, unload_ok: bool = True, reload_ok: bool = True):
        self._unload_ok = unload_ok
        self._reload_ok = reload_ok
        self.unloaded = False
        self.reloaded = False

    def unload(self) -> bool:
        self.unloaded = True
        return self._unload_ok

    def reload(self, *, adapter_path: Optional[Path] = None) -> bool:
        self.reloaded = True
        return self._reload_ok


def _make_router() -> MagicMock:
    router = MagicMock()
    router.before_load = AsyncMock(return_value=True)
    router.before_unload = MagicMock()
    router.after_load = MagicMock()
    router.after_unload = MagicMock()
    router.register = MagicMock()
    return router


def _single_gpu_describer() -> dict[str, Any]:
    return {"cuda_devices": [{"device": "cuda:0", "free_vram_gb": 2.0}]}


@pytest.mark.asyncio
async def test_router_notified_on_bracket(tmp_path: Path) -> None:
    ctrl = _FakeController()
    router = _make_router()

    async def train() -> None:
        return None

    _, result = await run_with_organ_window(
        train=train,
        config={},
        serve_device="cuda:0",
        hot_swap_mode="auto",
        controller=ctrl,
        host_describer=_single_gpu_describer,
        state_path=tmp_path / "organ_window.json",
        router=router,
        organ_footprint_bytes=3_000_000_000,
    )
    assert result.bracketed is True
    assert result.organ_restored is True
    router.before_unload.assert_called_with("organ")
    router.after_unload.assert_called_with("organ")
    router.before_load.assert_called_with("organ", 3_000_000_000)
    router.after_load.assert_called_with("organ")


@pytest.mark.asyncio
async def test_training_footprint_held(tmp_path: Path) -> None:
    ctrl = _FakeController()
    router = _make_router()
    training_calls: list[Any] = []

    async def train() -> None:
        training_calls.append(list(router.register.call_args_list))
        return None

    await run_with_organ_window(
        train=train,
        config={},
        serve_device="cuda:0",
        hot_swap_mode="auto",
        controller=ctrl,
        host_describer=_single_gpu_describer,
        state_path=tmp_path / "organ_window.json",
        router=router,
        training_footprint_bytes=5_000_000_000,
    )
    router.register.assert_called_with("organ_training", 5_000_000_000)
    # Training footprint was admitted before train() and released after.
    assert router.before_load.call_args_list[0] == call("organ_training", 5_000_000_000)
    router.after_load.assert_any_call("organ_training")
    # And released.
    router.before_unload.assert_any_call("organ_training")
    router.after_unload.assert_any_call("organ_training")


@pytest.mark.asyncio
async def test_router_none_unchanged(tmp_path: Path) -> None:
    ctrl = _FakeController()

    async def train() -> None:
        return None

    _, result = await run_with_organ_window(
        train=train,
        config={},
        serve_device="cuda:0",
        hot_swap_mode="auto",
        controller=ctrl,
        host_describer=_single_gpu_describer,
        state_path=tmp_path / "organ_window.json",
        router=None,
    )
    assert result.bracketed is True
    assert result.organ_restored is True


@pytest.mark.asyncio
async def test_router_error_does_not_prevent_reload(tmp_path: Path) -> None:
    ctrl = _FakeController()
    router = _make_router()
    router.before_load = AsyncMock(side_effect=RuntimeError("admission failed"))

    async def train() -> None:
        return None

    _, result = await run_with_organ_window(
        train=train,
        config={},
        serve_device="cuda:0",
        hot_swap_mode="auto",
        controller=ctrl,
        host_describer=_single_gpu_describer,
        state_path=tmp_path / "organ_window.json",
        router=router,
    )
    assert result.bracketed is True
    assert result.organ_restored is True
    assert ctrl.reloaded is True
