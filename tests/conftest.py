# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import os

import pytest

from kaine.bus import reset_bus_for_tests
from kaine.bus.config import BusConfig


@pytest.fixture(autouse=True)
def _reset_bus_singleton():
    reset_bus_for_tests()
    yield
    reset_bus_for_tests()


@pytest.fixture(autouse=True)
def _save_restore_state_encryptor():
    """Save and restore the process-global state encryptor around each test."""
    from kaine.security import crypto as crypto_module

    previous = getattr(crypto_module, "_active", None)
    yield
    crypto_module._active = previous


@pytest.fixture(autouse=True)
def _save_restore_data_root():
    """Save and restore the process-wide data root around each test, so a test
    that installs one cannot redirect later tests' relative state paths."""
    from kaine import storage

    previous = storage.data_root()
    yield
    storage.set_data_root(previous)


@pytest.fixture
def bus_config_with_password() -> BusConfig:
    return BusConfig(password="test-password", audit_required=False)


@pytest.fixture
async def fake_async_bus(bus_config_with_password):
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    # Same pool size as the production bus client (redis-py 8 caps an unset
    # pool at 100).
    client = fakeredis.FakeRedis(
        decode_responses=True, max_connections=BusConfig().max_connections
    )
    from kaine.bus.client import AsyncBus
    bus = AsyncBus(bus_config_with_password, client=client)
    yield bus
    await bus.close()


def pytest_collection_modifyitems(config, items):
    if os.environ.get("KAINE_REDIS_PASSWORD"):
        return
    skip_integration = pytest.mark.skip(
        reason="KAINE_REDIS_PASSWORD not set; integration tests need authenticated Redis"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
