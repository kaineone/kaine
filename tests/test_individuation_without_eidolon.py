# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from unittest.mock import AsyncMock, MagicMock

import pytest

from kaine.cycle.__main__ import _individuation_refusal
from kaine.cycle.individuation_probe import ProbeFailure, build_probe_sampler
from kaine.lifecycle.individuation_store import ProbeSample
from kaine.modules.lingua.client import ChatResponse
from kaine.modules.lingua.module import Lingua


async def test_lingua_holds_and_renders_situation_facts():
    lingua = Lingua(MagicMock(), chat_client=MagicMock(), intent_log=MagicMock())

    assert await lingua.add_situation_fact("fact A") is True
    assert await lingua.add_situation_fact("fact A") is False
    assert lingua._self_model()["situation_facts"] == ["fact A"]

    lingua.set_expects_self_model(False)
    sm = lingua.probe_self_model()
    assert sm is not None
    assert sm["values"] == []
    assert sm["behavioral_norms"] == []
    assert sm["situation_facts"] == ["fact A"]

    lingua.set_expects_self_model(True)
    assert lingua.probe_self_model() is None


async def test_lingua_merges_bus_and_own_situation_facts():
    lingua = Lingua(MagicMock(), chat_client=MagicMock(), intent_log=MagicMock())
    assert await lingua.add_situation_fact("fact A") is True
    assert await lingua.add_situation_fact("x") is True

    lingua._bus_self_model = {
        "values": ["v"],
        "behavioral_norms": [],
        "situation_facts": ["x"],
    }
    sm = lingua.probe_self_model()
    assert sm is not None
    assert sm["situation_facts"] == ["x", "fact A"]


async def test_lingua_rejects_empty_situation_fact():
    lingua = Lingua(MagicMock(), chat_client=MagicMock(), intent_log=MagicMock())
    with pytest.raises(ValueError):
        await lingua.add_situation_fact("   ")


async def test_probe_sampler_without_eidolon():
    lingua = Lingua(MagicMock(), chat_client=MagicMock(), intent_log=MagicMock())
    lingua.chat_client.complete = AsyncMock(
        return_value=ChatResponse(
            text="ok",
            model="probe",
            raw={},
            from_content=True,
            lora_applied=False,
            finish_reason="stop",
            completion_tokens=3,
        )
    )

    sampler = build_probe_sampler(lingua=lingua, required_fact="fact A")

    lingua.set_expects_self_model(False)
    assert await lingua.add_situation_fact("fact A") is True

    result = await sampler("prompt", seed=1)
    assert isinstance(result, ProbeSample)
    assert result.text == "ok"

    # Without the required fact the probe is not ready.
    lingua._own_situation_facts.clear()
    result = await sampler("prompt", seed=2)
    assert isinstance(result, ProbeFailure)
    assert result.reason == "disclosure_not_ready"


def test_individuation_refusal_accepts_lingua_only():
    cfg, reason = _individuation_refusal(
        {"individuation": {"enabled": True}, "modules": {"lingua": True}}
    )
    assert cfg is not None
    assert reason is None


async def test_speech_persona_carries_own_facts_over_a_snapshot():
    lingua = Lingua(MagicMock(), chat_client=MagicMock(), intent_log=MagicMock())
    await lingua.add_situation_fact("fact A")
    lingua._bus_self_model = {"values": ["v"], "behavioral_norms": [], "situation_facts": []}
    assert lingua._self_model()["situation_facts"] == ["fact A"]
