# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Supervisor treats stale modules as alive while the lockstep barrier is active."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from kaine.cycle.supervisor import Supervisor, SupervisorConfig


def _make(provider):
    return Supervisor(
        registry=[],
        fork_manager=None,
        kaine_config={},
        config=SupervisorConfig.from_section({}),
        rebuild_module=lambda name: None,
        bus=None,
        barrier_active_provider=provider,
    )


async def _stale_module():
    task = asyncio.create_task(asyncio.sleep(10))
    module = SimpleNamespace(
        name="slow_module",
        _tasks=[task],
        _stopped=None,
        heartbeat_age=lambda: 1e9,
    )
    return module, task


@pytest.mark.asyncio
async def test_supervisor_alive_during_barrier():
    sup = _make(lambda: True)
    module, task = await _stale_module()
    try:
        assert sup.assess(module).state == "alive"
    finally:
        task.cancel()


@pytest.mark.asyncio
async def test_supervisor_hung_without_barrier():
    sup = _make(lambda: False)
    module, task = await _stale_module()
    try:
        assert sup.assess(module).state == "hung"
    finally:
        task.cancel()
