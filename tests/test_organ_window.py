# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the on-device voice-alignment GPU window (unload→train→reload).

Covers the single-GPU bracket happy path, the failed-training-still-reloads
guarantee, the multi-GPU skip, the manual-mode skip, and the boundary-neutral
window-state seam organ-dependent consumers read.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pytest

from kaine.modules.hypnos.organ_window import (
    MULTI_GPU_CONCURRENT_HEADROOM_GB,
    PHASE_IDLE,
    OrganServerController,
    run_with_organ_window,
    second_gpu_has_room,
)
from kaine.modules.hypnos.voice_alignment import TrainingResult
from kaine.organ_window_state import organ_unloaded, read_window_state


def _result(accepted: bool, adapter: Optional[Path] = None) -> TrainingResult:
    return TrainingResult(
        accepted=accepted,
        adapter_path=adapter,
        capability_loss=0.0,
        reason="accepted" if accepted else "rejected",
        samples_used=3,
    )


class RecordingController(OrganServerController):
    """Controller whose stop/start/probe are scripted and recorded."""

    def __init__(
        self,
        *,
        stop_ok: bool = True,
        start_ok: bool = True,
        answers: bool = True,
        answers_on_rollback: bool = True,
        preflight_ok: bool = True,
    ) -> None:
        self.events: list[tuple[str, Any]] = []
        self._stop_ok = stop_ok
        self._start_ok = start_ok
        self._answers = answers
        self._answers_on_rollback = answers_on_rollback
        self._preflight_ok_v = preflight_ok
        self._start_count = 0
        super().__init__(config={})

    def unload(self) -> bool:
        self.events.append(("unload", None))
        return self._stop_ok

    def reload(self, *, adapter_path: Optional[Path]) -> bool:
        self._start_count += 1
        self.events.append(("reload", str(adapter_path) if adapter_path else None))
        if not self._start_ok:
            return False
        # First reload (with adapter) vs a rollback reload (without).
        if adapter_path is not None:
            return self._answers
        return self._answers_on_rollback


# --------------------------------------------------------------------------
# multi-GPU detection
# --------------------------------------------------------------------------


def test_second_gpu_has_room_true_when_other_device_clears_headroom():
    def host():
        return {
            "cuda_devices": [
                {"device": "cuda:0", "free_vram_gb": 1.0},
                {"device": "cuda:1", "free_vram_gb": MULTI_GPU_CONCURRENT_HEADROOM_GB + 1},
            ]
        }

    assert second_gpu_has_room(serve_device="cuda:0", host_describer=host) is True


def test_second_gpu_has_room_false_on_single_gpu():
    def host():
        return {"cuda_devices": [{"device": "cuda:0", "free_vram_gb": 11.6}]}

    assert second_gpu_has_room(serve_device="cuda:0", host_describer=host) is False


def test_second_gpu_has_room_ignores_the_serve_device_even_if_huge():
    # The serve device holding the organ is excluded; only OTHER devices count.
    def host():
        return {"cuda_devices": [{"device": "cuda:0", "free_vram_gb": 80.0}]}

    assert second_gpu_has_room(serve_device="cuda:0", host_describer=host) is False


def test_second_gpu_has_room_false_when_describe_raises():
    def host():
        raise RuntimeError("no torch")

    assert second_gpu_has_room(serve_device="cuda:0", host_describer=host) is False


# --------------------------------------------------------------------------
# the bracket
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bracket_happy_path_unload_train_reload(tmp_path):
    state = tmp_path / "organ_window.json"
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    ctrl = RecordingController()

    async def train():
        # While training, the window state must report the organ as unloaded.
        assert organ_unloaded(path=state) is True
        return _result(accepted=True, adapter=adapter)

    result, window = await run_with_organ_window(
        train=train,
        config={},
        serve_device="cuda:0",
        hot_swap_mode="restart_service",
        controller=ctrl,
        host_describer=lambda: {"cuda_devices": [{"device": "cuda:0", "free_vram_gb": 11.6}]},
        state_path=state,
    )

    assert result.accepted is True
    assert window.bracketed is True
    assert window.organ_restored is True
    assert window.error is None
    # Real unload BEFORE train and a reload AFTER, with the accepted adapter.
    kinds = [e[0] for e in ctrl.events]
    assert kinds == ["unload", "reload"]
    assert ctrl.events[1][1] == str(adapter)  # reloaded WITH the adapter
    # Window resolves to idle; consumers resume.
    assert organ_unloaded(path=state) is False
    final = read_window_state(path=state)
    assert final["phase"] == PHASE_IDLE
    assert final["last_adapter_accepted"] is True


@pytest.mark.asyncio
async def test_bracket_reloads_unchanged_when_adapter_vetoed(tmp_path):
    state = tmp_path / "organ_window.json"
    ctrl = RecordingController()

    async def train():
        return _result(accepted=False)  # vetoed / no adapter

    result, window = await run_with_organ_window(
        train=train,
        config={},
        serve_device="cuda:0",
        hot_swap_mode="restart_service",
        controller=ctrl,
        host_describer=lambda: {"cuda_devices": [{"device": "cuda:0", "free_vram_gb": 11.6}]},
        state_path=state,
    )

    assert result.accepted is False
    assert window.organ_restored is True
    # Reloaded with NO adapter (organ unchanged).
    assert ctrl.events[1] == ("reload", None)


@pytest.mark.asyncio
async def test_failed_training_still_reloads_a_working_organ(tmp_path):
    """A training crash must NOT leave the entity voiceless: the organ reloads."""
    state = tmp_path / "organ_window.json"
    ctrl = RecordingController()

    async def train():
        raise RuntimeError("trainer exploded mid-step")

    result, window = await run_with_organ_window(
        train=train,
        config={},
        serve_device="cuda:0",
        hot_swap_mode="restart_service",
        controller=ctrl,
        host_describer=lambda: {"cuda_devices": [{"device": "cuda:0", "free_vram_gb": 11.6}]},
        state_path=state,
    )

    assert result is None
    assert window.bracketed is True
    assert window.organ_restored is True  # organ restored despite the crash
    assert window.error is not None and "RuntimeError" in window.error
    # The organ WAS reloaded (unchanged, no adapter) after the crash.
    assert ("reload", None) in ctrl.events
    assert organ_unloaded(path=state) is False


@pytest.mark.asyncio
async def test_adapter_reload_failure_rolls_back_to_pretraining_organ(tmp_path):
    """If reloading WITH the adapter fails, roll back to the pre-training organ."""
    state = tmp_path / "organ_window.json"
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    # Reload-with-adapter fails to answer; the rollback reload (no adapter) works.
    ctrl = RecordingController(answers=False, answers_on_rollback=True)

    async def train():
        return _result(accepted=True, adapter=adapter)

    result, window = await run_with_organ_window(
        train=train,
        config={},
        serve_device="cuda:0",
        hot_swap_mode="restart_service",
        controller=ctrl,
        host_describer=lambda: {"cuda_devices": [{"device": "cuda:0", "free_vram_gb": 11.6}]},
        state_path=state,
    )

    assert result.accepted is True
    assert window.organ_restored is True  # rollback succeeded
    kinds = [e for e in ctrl.events]
    # unload → reload(adapter) [fails] → reload(None) [rollback succeeds]
    assert kinds == [
        ("unload", None),
        ("reload", str(adapter)),
        ("reload", None),
    ]


@pytest.mark.asyncio
async def test_multi_gpu_host_skips_the_bracket(tmp_path):
    state = tmp_path / "organ_window.json"
    ctrl = RecordingController()

    async def train():
        # Organ is NOT unloaded on a multi-GPU host.
        assert organ_unloaded(path=state) is False
        return _result(accepted=True)

    result, window = await run_with_organ_window(
        train=train,
        config={},
        serve_device="cuda:0",
        hot_swap_mode="restart_service",
        controller=ctrl,
        host_describer=lambda: {
            "cuda_devices": [
                {"device": "cuda:0", "free_vram_gb": 3.0},
                {"device": "cuda:1", "free_vram_gb": MULTI_GPU_CONCURRENT_HEADROOM_GB + 2},
            ]
        },
        state_path=state,
    )

    assert window.bracketed is False
    assert "multi-GPU" in (window.skipped_reason or "")
    assert ctrl.events == []  # no unload/reload happened


@pytest.mark.asyncio
async def test_manual_mode_skips_the_bracket(tmp_path):
    state = tmp_path / "organ_window.json"
    ctrl = RecordingController()

    async def train():
        return _result(accepted=True)

    result, window = await run_with_organ_window(
        train=train,
        config={},
        serve_device="cuda:0",
        hot_swap_mode="manual",
        controller=ctrl,
        host_describer=lambda: {"cuda_devices": [{"device": "cuda:0", "free_vram_gb": 11.6}]},
        state_path=state,
    )

    assert window.bracketed is False
    assert "manual" in (window.skipped_reason or "")
    assert ctrl.events == []


def test_window_state_seam_round_trips(tmp_path):
    from kaine.organ_window_state import (
        PHASE_RESTING,
        write_window_state,
    )

    state = tmp_path / "w.json"
    assert organ_unloaded(path=state) is False  # absent → organ available
    write_window_state(PHASE_RESTING, detail="x", path=state)
    assert organ_unloaded(path=state) is True
    write_window_state(PHASE_IDLE, last_adapter_accepted=True, path=state)
    assert organ_unloaded(path=state) is False
    assert read_window_state(path=state)["last_adapter_accepted"] is True
