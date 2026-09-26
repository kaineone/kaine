# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.cycle.incident_log import IncidentLog
from kaine.cycle.preservation_monitor import WelfareProtectiveMonitor, WelfareResponseConfig


class _DummyForkManager:
    async def preserve_live(self, *args, **kwargs):
        class _Result:
            preservation_id = "preservation-1"
            snapshot_id = "snapshot-1"

        return _Result()


def _make_monitor(on_response=None):
    monitor = WelfareProtectiveMonitor(
        registry=object(),
        fork_manager=_DummyForkManager(),
        config=WelfareResponseConfig(action="notify"),
        bus=object(),
        incident_log=IncidentLog(enabled=False, path="ignored", name="test"),
        on_response=on_response,
    )

    async def _noop(*args, **kwargs):
        return None

    monitor._record = _noop
    return monitor


@pytest.mark.asyncio
async def test_welfare_on_response_called():
    called = []

    def cb(action):
        called.append(action)

    monitor = _make_monitor(on_response=cb)
    await monitor._respond("sustained_distress")
    assert called == ["notify"]


@pytest.mark.asyncio
async def test_welfare_on_response_error_does_not_propagate():
    def cb(action):
        raise RuntimeError("callback failed")

    monitor = _make_monitor(on_response=cb)
    await monitor._respond("sustained_distress")
