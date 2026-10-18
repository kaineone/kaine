# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import types

import pytest

from kaine.evaluation.ab_divergence import AssemblerConditionedClient
from kaine.modules.language.client import ChatRequest, ChatResponse
from kaine.modules.language.context import HEARD_SPEECH_GUARD, OWN_TURN_STOP, heard_utterance_line

_fake_clients: list["_FakeOrganClient"] = []


class _FakeOrganClient:
    def __init__(self, base_url=None, timeout_s=None, api_key=None, **kwargs):
        self.base_url = base_url
        self.timeout_s = timeout_s
        self.api_key = api_key
        self.kwargs = kwargs
        self.requests: list[ChatRequest] = []

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(text="fine", model="m", from_content=True)

    async def aclose(self) -> None:
        pass


@pytest.mark.asyncio
async def test_control_client_uses_own_turn_layout(monkeypatch):
    def factory(**kw):
        client = _FakeOrganClient(**kw)
        _fake_clients.append(client)
        return client

    monkeypatch.setattr("kaine.modules.language.client.OpenAIChatClient", factory)
    from kaine.cycle.__main__ import build_ab_divergence_control_client

    eval_cfg = types.SimpleNamespace(
        chat_url="http://fake/v1",
        chat_timeout_s=1.0,
        chat_api_key=None,
        chat_model_id="m",
        chat_think=False,
    )
    ctl = build_ab_divergence_control_client(eval_cfg)
    out = await ctl.complete_conditioned("hello there", "- I feel calm.")

    assert out == "fine"
    assert len(_fake_clients) == 1
    assert len(_fake_clients[0].requests) == 1
    request = _fake_clients[0].requests[0]

    assert request.own_turn is True
    assert request.user_turn == heard_utterance_line("hello there")
    assert "- I feel calm." in request.prompt
    assert "hello there" not in request.prompt
    assert request.stop == list(OWN_TURN_STOP)
    assert request.system.endswith(HEARD_SPEECH_GUARD)


@pytest.mark.asyncio
async def test_two_part_builder_still_works():
    async def complete(system: str, prompt: str) -> str:
        return prompt

    client = AssemblerConditionedClient(
        lambda u, c: ("s", f"{c}|{u}"),
        complete,
    )
    assert await client.complete_conditioned("u", "c") == "c|u"
