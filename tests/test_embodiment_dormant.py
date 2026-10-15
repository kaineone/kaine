# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for embodiment dormancy during the developmental phase."""

from __future__ import annotations

import asyncio

import pytest

from kaine.modules.embodiment.adapters.stub import StubAdapter
from kaine.modules.embodiment.module import Embodiment


class _FailingProbeAdapter(StubAdapter):
    async def probe(self) -> bool:
        raise RuntimeError("probe refused")


class _SlowProbeAdapter(StubAdapter):
    async def probe(self) -> bool:
        await asyncio.sleep(60)
        return True


@pytest.mark.asyncio
async def test_dormant_initialize_opens_nothing(fake_async_bus, monkeypatch) -> None:
    monkeypatch.setenv("KAINE_EMBODIMENT_OPERATOR_APPROVED", "1")
    adapter = StubAdapter()
    embodiment = Embodiment(fake_async_bus, adapter=adapter, enabled=True, dormant=True)

    await embodiment.initialize()

    assert not adapter.opened
    assert embodiment._tasks == []
    assert embodiment.dormant is True


@pytest.mark.asyncio
async def test_probe_available_true_while_dormant(fake_async_bus, monkeypatch) -> None:
    monkeypatch.setenv("KAINE_EMBODIMENT_OPERATOR_APPROVED", "1")
    adapter = StubAdapter()
    embodiment = Embodiment(fake_async_bus, adapter=adapter, enabled=True, dormant=True)

    assert await embodiment.probe_available() is True
    assert not adapter.opened


@pytest.mark.asyncio
async def test_probe_available_false_when_not_approved(fake_async_bus, monkeypatch) -> None:
    monkeypatch.delenv("KAINE_EMBODIMENT_OPERATOR_APPROVED", raising=False)
    adapter = StubAdapter()
    embodiment = Embodiment(fake_async_bus, adapter=adapter, enabled=True, dormant=True)

    assert await embodiment.probe_available() is False


@pytest.mark.asyncio
async def test_probe_available_false_when_probe_raises(fake_async_bus, monkeypatch) -> None:
    monkeypatch.setenv("KAINE_EMBODIMENT_OPERATOR_APPROVED", "1")
    adapter = _FailingProbeAdapter()
    embodiment = Embodiment(fake_async_bus, adapter=adapter, enabled=True, dormant=True)

    assert await embodiment.probe_available(timeout_s=1.0) is False
    # A probe()-based check never opens the body, so there is nothing to close.
    assert adapter.opened is False


@pytest.mark.asyncio
async def test_probe_available_false_when_probe_times_out(fake_async_bus, monkeypatch) -> None:
    monkeypatch.setenv("KAINE_EMBODIMENT_OPERATOR_APPROVED", "1")
    adapter = _SlowProbeAdapter()
    embodiment = Embodiment(fake_async_bus, adapter=adapter, enabled=True, dormant=True)

    assert await embodiment.probe_available(timeout_s=0.05) is False
    # A probe()-based check never opens the body, so there is nothing to close.
    assert adapter.opened is False


@pytest.mark.asyncio
async def test_activate_starts_embodiment_and_returns_true(fake_async_bus, monkeypatch) -> None:
    monkeypatch.setenv("KAINE_EMBODIMENT_OPERATOR_APPROVED", "1")
    adapter = StubAdapter()
    embodiment = Embodiment(fake_async_bus, adapter=adapter, enabled=True, dormant=True)

    ok = await embodiment.activate()
    assert ok is True
    assert embodiment._tasks != []
    assert embodiment.dormant is False
    assert adapter.opened is True

    await embodiment.shutdown()


@pytest.mark.asyncio
async def test_activate_when_not_approved_returns_false(fake_async_bus, monkeypatch) -> None:
    monkeypatch.delenv("KAINE_EMBODIMENT_OPERATOR_APPROVED", raising=False)
    adapter = StubAdapter()
    embodiment = Embodiment(fake_async_bus, adapter=adapter, enabled=True, dormant=True)

    ok = await embodiment.activate()
    assert ok is False
    assert embodiment._tasks == []


@pytest.mark.asyncio
async def test_shutdown_cleans_up_after_activate(fake_async_bus, monkeypatch) -> None:
    monkeypatch.setenv("KAINE_EMBODIMENT_OPERATOR_APPROVED", "1")
    adapter = StubAdapter()
    embodiment = Embodiment(fake_async_bus, adapter=adapter, enabled=True, dormant=True)

    await embodiment.activate()
    await embodiment.shutdown()

    assert adapter.closed is True
    assert all(t.done() for t in embodiment._tasks)


async def test_probe_result_false_means_unavailable(fake_async_bus, monkeypatch):
    """An adapter whose probe answers False is unavailable (the answer is used,
    not just the absence of an exception), and nothing is opened or closed."""
    from kaine.modules.embodiment.adapters.stub import StubAdapter
    from kaine.modules.embodiment.module import Embodiment

    monkeypatch.setenv("KAINE_EMBODIMENT_OPERATOR_APPROVED", "1")

    class _NoBody(StubAdapter):
        closed = 0

        async def probe(self) -> bool:
            return False

        async def close(self) -> None:
            type(self).closed += 1
            await super().close()

    embodiment = Embodiment(fake_async_bus, adapter=_NoBody(), enabled=True, dormant=True)
    assert await embodiment.probe_available() is False
    assert _NoBody.closed == 0
