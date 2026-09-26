# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for Mundus dormancy during gestation."""

from __future__ import annotations

import asyncio

import pytest

from kaine.modules.mundus.adapters.stub import StubAdapter
from kaine.modules.mundus.module import Mundus


class _FailingProbeAdapter(StubAdapter):
    async def probe(self) -> bool:
        raise RuntimeError("probe refused")


class _SlowProbeAdapter(StubAdapter):
    async def probe(self) -> bool:
        await asyncio.sleep(60)
        return True


@pytest.mark.asyncio
async def test_dormant_initialize_opens_nothing(fake_async_bus, monkeypatch) -> None:
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    adapter = StubAdapter()
    mundus = Mundus(fake_async_bus, adapter=adapter, enabled=True, dormant=True)

    await mundus.initialize()

    assert not adapter.opened
    assert mundus._tasks == []
    assert mundus.dormant is True


@pytest.mark.asyncio
async def test_probe_available_true_while_dormant(fake_async_bus, monkeypatch) -> None:
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    adapter = StubAdapter()
    mundus = Mundus(fake_async_bus, adapter=adapter, enabled=True, dormant=True)

    assert await mundus.probe_available() is True
    assert not adapter.opened


@pytest.mark.asyncio
async def test_probe_available_false_when_not_approved(fake_async_bus, monkeypatch) -> None:
    monkeypatch.delenv("KAINE_MUNDUS_OPERATOR_APPROVED", raising=False)
    adapter = StubAdapter()
    mundus = Mundus(fake_async_bus, adapter=adapter, enabled=True, dormant=True)

    assert await mundus.probe_available() is False


@pytest.mark.asyncio
async def test_probe_available_false_when_probe_raises(fake_async_bus, monkeypatch) -> None:
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    adapter = _FailingProbeAdapter()
    mundus = Mundus(fake_async_bus, adapter=adapter, enabled=True, dormant=True)

    assert await mundus.probe_available(timeout_s=1.0) is False
    # A probe()-based check never opens the body, so there is nothing to close.
    assert adapter.opened is False


@pytest.mark.asyncio
async def test_probe_available_false_when_probe_times_out(fake_async_bus, monkeypatch) -> None:
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    adapter = _SlowProbeAdapter()
    mundus = Mundus(fake_async_bus, adapter=adapter, enabled=True, dormant=True)

    assert await mundus.probe_available(timeout_s=0.05) is False
    # A probe()-based check never opens the body, so there is nothing to close.
    assert adapter.opened is False


@pytest.mark.asyncio
async def test_activate_starts_mundus_and_returns_true(fake_async_bus, monkeypatch) -> None:
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    adapter = StubAdapter()
    mundus = Mundus(fake_async_bus, adapter=adapter, enabled=True, dormant=True)

    ok = await mundus.activate()
    assert ok is True
    assert mundus._tasks != []
    assert mundus.dormant is False
    assert adapter.opened is True

    await mundus.shutdown()


@pytest.mark.asyncio
async def test_activate_when_not_approved_returns_false(fake_async_bus, monkeypatch) -> None:
    monkeypatch.delenv("KAINE_MUNDUS_OPERATOR_APPROVED", raising=False)
    adapter = StubAdapter()
    mundus = Mundus(fake_async_bus, adapter=adapter, enabled=True, dormant=True)

    ok = await mundus.activate()
    assert ok is False
    assert mundus._tasks == []


@pytest.mark.asyncio
async def test_shutdown_cleans_up_after_activate(fake_async_bus, monkeypatch) -> None:
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    adapter = StubAdapter()
    mundus = Mundus(fake_async_bus, adapter=adapter, enabled=True, dormant=True)

    await mundus.activate()
    await mundus.shutdown()

    assert adapter.closed is True
    assert all(t.done() for t in mundus._tasks)


async def test_probe_result_false_means_unavailable(fake_async_bus, monkeypatch):
    """An adapter whose probe answers False is unavailable (the answer is used,
    not just the absence of an exception), and nothing is opened or closed."""
    from kaine.modules.mundus.adapters.stub import StubAdapter
    from kaine.modules.mundus.module import Mundus

    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")

    class _NoBody(StubAdapter):
        closed = 0

        async def probe(self) -> bool:
            return False

        async def close(self) -> None:
            type(self).closed += 1
            await super().close()

    mundus = Mundus(fake_async_bus, adapter=_NoBody(), enabled=True, dormant=True)
    assert await mundus.probe_available() is False
    assert _NoBody.closed == 0
