# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from kaine.modules.lingua.client import ChatRequest, OpenAIChatClient


def test_body_think_false_sets_reasoning_effort_none():
    client = OpenAIChatClient("http://localhost:11434/v1")
    request = ChatRequest(model="test-model", prompt="hello")
    body = client._body(request, think=False)
    assert body["reasoning_effort"] == "none"


def test_body_think_true_sets_reasoning_effort_high():
    client = OpenAIChatClient("http://localhost:11434/v1")
    request = ChatRequest(model="test-model", prompt="hello")
    body = client._body(request, think=True)
    assert body["reasoning_effort"] == "high"


def test_body_think_none_omits_reasoning_effort():
    client = OpenAIChatClient("http://localhost:11434/v1")
    request = ChatRequest(model="test-model", prompt="hello")
    body = client._body(request, think=None)
    assert "reasoning_effort" not in body


def test_body_think_false_preserves_chat_template_kwargs():
    client = OpenAIChatClient("http://localhost:11434/v1")
    request = ChatRequest(model="test-model", prompt="hello")
    body = client._body(request, think=False)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["reasoning_effort"] == "none"
