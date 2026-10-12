# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from unittest.mock import AsyncMock, MagicMock

import pytest

from kaine.cycle.__main__ import _individuation_refusal
from kaine.cycle.individuation_probe import ProbeFailure, build_probe_sampler
from kaine.lifecycle.individuation_store import ProbeSample
from kaine.modules.language.client import ChatResponse
from kaine.modules.language.module import Language


async def test_language_holds_and_renders_situation_facts():
    language = Language(MagicMock(), chat_client=MagicMock(), intent_log=MagicMock())

    assert await language.add_situation_fact("fact A") is True
    assert await language.add_situation_fact("fact A") is False
    assert language._self_model()["situation_facts"] == ["fact A"]

    language.set_expects_self_model(False)
    sm = language.probe_self_model()
    assert sm is not None
    assert sm["values"] == []
    assert sm["behavioral_norms"] == []
    assert sm["situation_facts"] == ["fact A"]

    language.set_expects_self_model(True)
    assert language.probe_self_model() is None


async def test_language_merges_bus_and_own_situation_facts():
    language = Language(MagicMock(), chat_client=MagicMock(), intent_log=MagicMock())
    assert await language.add_situation_fact("fact A") is True
    assert await language.add_situation_fact("x") is True

    language._bus_self_model = {
        "values": ["v"],
        "behavioral_norms": [],
        "situation_facts": ["x"],
    }
    sm = language.probe_self_model()
    assert sm is not None
    assert sm["situation_facts"] == ["x", "fact A"]


async def test_language_rejects_empty_situation_fact():
    language = Language(MagicMock(), chat_client=MagicMock(), intent_log=MagicMock())
    with pytest.raises(ValueError):
        await language.add_situation_fact("   ")


async def test_probe_sampler_without_self_model():
    language = Language(MagicMock(), chat_client=MagicMock(), intent_log=MagicMock())
    language.chat_client.complete = AsyncMock(
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

    sampler = build_probe_sampler(language=language, required_fact="fact A")

    language.set_expects_self_model(False)
    assert await language.add_situation_fact("fact A") is True

    result = await sampler("prompt", seed=1)
    assert isinstance(result, ProbeSample)
    assert result.text == "ok"

    # Without the required fact the probe is not ready.
    language._own_situation_facts.clear()
    result = await sampler("prompt", seed=2)
    assert isinstance(result, ProbeFailure)
    assert result.reason == "disclosure_not_ready"


def test_individuation_refusal_accepts_language_only():
    cfg, reason = _individuation_refusal(
        {"individuation": {"enabled": True}, "modules": {"lingua": True}}
    )
    assert cfg is not None
    assert reason is None


async def test_speech_persona_carries_own_facts_over_a_snapshot():
    language = Language(MagicMock(), chat_client=MagicMock(), intent_log=MagicMock())
    await language.add_situation_fact("fact A")
    language._bus_self_model = {"values": ["v"], "behavioral_norms": [], "situation_facts": []}
    assert language._self_model()["situation_facts"] == ["fact A"]
