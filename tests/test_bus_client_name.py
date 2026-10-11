# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import pytest

from kaine.bus.client import CYCLE_CLIENT_NAME, AsyncBus
from kaine.bus.config import BusConfig


@pytest.fixture
def captured_from_url(monkeypatch):
    calls = []

    def fake_from_url(url, **kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr("kaine.bus.client.aioredis.from_url", fake_from_url)
    return calls


def test_async_bus_passes_client_name(captured_from_url):
    AsyncBus(BusConfig(password="x"), client_name=CYCLE_CLIENT_NAME)
    assert captured_from_url[-1].get("client_name") == CYCLE_CLIENT_NAME


def test_async_bus_omits_client_name_by_default(captured_from_url):
    AsyncBus(BusConfig(password="x"))
    assert "client_name" not in captured_from_url[-1]
