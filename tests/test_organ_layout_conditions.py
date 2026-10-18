# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.individuation_runtime import check_battery_quotes
from kaine.modules.language import FakeChatClient, IntentExpressionLog, Language
from kaine.modules.language import context as context_module
from kaine.modules.language.context import HEARD_QUOTE_LIMIT, layout_digest


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


async def test_probe_conditions_carry_layout_digest(bus, tmp_path, monkeypatch):
    language = Language(
        bus,
        chat_client=FakeChatClient(),
        intent_log=IntentExpressionLog(tmp_path / "i.jsonl"),
        model_id="fake-model",
    )
    c0 = language.probe_conditions()
    assert c0["prompt_layout_digest"] == layout_digest()
    monkeypatch.setattr(context_module, "HEARD_ATTRIBUTION_SAID", "X: ")
    assert language.probe_conditions() != c0


def test_battery_within_quote_limit_passes():
    assert check_battery_quotes(["a" * HEARD_QUOTE_LIMIT, "b  c"]) is None


def test_battery_over_quote_limit_fails_loudly():
    with pytest.raises(ValueError, match="battery prompt 1"):
        check_battery_quotes(["ok", "x" * (HEARD_QUOTE_LIMIT + 1)])


def test_default_battery_fits():
    from kaine.evaluation.preference_battery import DEFAULT_BATTERY

    assert check_battery_quotes(DEFAULT_BATTERY) is None
