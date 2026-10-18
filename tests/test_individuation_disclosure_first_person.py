# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.individuation_runtime import (
    DEFAULT_DISCLOSURE,
    LEGACY_DISCLOSURES,
    IndividuationConfig,
)
from kaine.modules.self_model.module import SelfModel
from kaine.storage import set_data_root


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def test_default_disclosure_is_first_person():
    assert re.search(r"\b(you|your)\b", DEFAULT_DISCLOSURE, re.I) is None
    assert DEFAULT_DISCLOSURE.startswith("I am periodically and privately assessed")
    assert IndividuationConfig.from_dict(None).disclosure == DEFAULT_DISCLOSURE
    for legacy in LEGACY_DISCLOSURES:
        assert "You are periodically" in legacy


def test_shipped_config_matches_default():
    config_path = Path(__file__).resolve().parents[1] / "config" / "kaine.toml"
    with config_path.open("rb") as f:
        data = tomllib.load(f)
    assert data["individuation"]["disclosure"] == DEFAULT_DISCLOSURE


async def test_self_model_replaces_legacy_disclosure_in_place(bus, tmp_path):
    try:
        set_data_root(tmp_path)
        self_model = SelfModel(bus)
        legacy = LEGACY_DISCLOSURES[0]

        assert await self_model.ensure_situation_fact("Fact A.") is True
        assert await self_model.ensure_situation_fact(legacy) is True
        assert await self_model.ensure_situation_fact("Fact B.") is True

        changed = await self_model.ensure_situation_fact(
            DEFAULT_DISCLOSURE, replaces=LEGACY_DISCLOSURES
        )
        assert changed is True
        assert self_model._model.situation_facts == [
            "Fact A.",
            DEFAULT_DISCLOSURE,
            "Fact B.",
        ]

        stream = getattr(self_model, "out", "self_model.out")
        records = await bus.client.xrevrange(stream, max="+", min="-", count=1)
        _id, fields = records[0]
        payload_raw = fields.get("payload", "{}")
        payload = (
            json.loads(payload_raw)
            if isinstance(payload_raw, (str, bytes, bytearray))
            else payload_raw
        )
        assert payload["situation_facts"] == [
            "Fact A.",
            DEFAULT_DISCLOSURE,
            "Fact B.",
        ]

        before = await bus.client.xlen(stream)
        second = await self_model.ensure_situation_fact(
            DEFAULT_DISCLOSURE, replaces=LEGACY_DISCLOSURES
        )
        assert second is False
        assert await bus.client.xlen(stream) == before
    finally:
        set_data_root(None)


async def test_self_model_appends_when_no_legacy(bus, tmp_path):
    try:
        set_data_root(tmp_path)
        self_model = SelfModel(bus)
        changed = await self_model.ensure_situation_fact(
            DEFAULT_DISCLOSURE, replaces=LEGACY_DISCLOSURES
        )
        assert changed is True
        assert self_model._model.situation_facts == [DEFAULT_DISCLOSURE]
    finally:
        set_data_root(None)


async def test_self_model_drops_stray_legacy_copy(bus, tmp_path):
    try:
        set_data_root(tmp_path)
        self_model = SelfModel(bus)
        legacy = LEGACY_DISCLOSURES[0]

        assert await self_model.ensure_situation_fact(DEFAULT_DISCLOSURE) is True
        assert await self_model.ensure_situation_fact(legacy) is True

        changed = await self_model.ensure_situation_fact(
            DEFAULT_DISCLOSURE, replaces=LEGACY_DISCLOSURES
        )
        assert changed is True
        assert self_model._model.situation_facts == [DEFAULT_DISCLOSURE]
    finally:
        set_data_root(None)
