# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.protocols import ModuleRegistryProtocol
from kaine.modules.base import BaseModule
from kaine.modules.registry import ModuleRegistry


class _A(BaseModule):
    name = "a-mod"


class _B(BaseModule):
    name = "b-mod"


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def test_registry_satisfies_cycle_protocol(bus: AsyncBus):
    reg = ModuleRegistry()
    assert isinstance(reg, ModuleRegistryProtocol)


def test_register_and_active_streams(bus: AsyncBus):
    reg = ModuleRegistry()
    a = _A(bus)
    reg.register(a)
    assert "a-mod" in reg
    assert reg.active_streams() == ["a-mod.out"]
    assert reg.get("a-mod") is a


def test_duplicate_registration_rejected(bus: AsyncBus):
    reg = ModuleRegistry()
    reg.register(_A(bus))
    with pytest.raises(ValueError):
        reg.register(_A(bus))


def test_unregister_removes_from_active_streams(bus: AsyncBus):
    reg = ModuleRegistry()
    a = _A(bus)
    b = _B(bus)
    reg.register(a)
    reg.register(b)
    reg.unregister("a-mod")
    assert "a-mod" not in reg
    assert reg.active_streams() == ["b-mod.out"]


def test_unregister_missing_raises(bus: AsyncBus):
    reg = ModuleRegistry()
    with pytest.raises(KeyError):
        reg.unregister("nope")


def test_len_and_all_modules(bus: AsyncBus):
    reg = ModuleRegistry()
    assert len(reg) == 0
    reg.register(_A(bus))
    reg.register(_B(bus))
    assert len(reg) == 2
    names = sorted(m.name for m in reg.all_modules())
    assert names == ["a-mod", "b-mod"]
