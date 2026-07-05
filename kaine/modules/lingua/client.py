# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatRequest:
    prompt: str
    model: str
    system: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 512
    stop: Optional[list[str]] = None
    # Hybrid-thinking models (e.g. Qwen3.5) emit a chain-of-thought unless told
    # not to — and then the visible `content` comes back EMPTY: the answer is
    # routed to the separate reasoning channel, or only arrives after a long
    # reasoning detour (and is lost entirely if generation is bounded). Lingua is
    # a voice, not a reasoner (reasoning lives in Nous), so the organ DEFAULTS to
    # thinking off. This client-side flag is the load-bearing suppression: the
    # server's `--reasoning-budget 0` launch flag does NOT reliably suppress CoT
    # on the served abliterated template. `False` → send enable_thinking=false;
    # `True` → allow CoT; `None` → send nothing (genuinely non-thinking servers).
    think: Optional[bool] = False


@dataclass(frozen=True)
class ChatResponse:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ChatClient(Protocol):
    @property
    def base_url(self) -> str: ...

    async def complete(self, request: ChatRequest) -> ChatResponse: ...

    async def aclose(self) -> None: ...


# Chat-template kwarg the llama.cpp / Unsloth Studio server forwards to the
# model's chat template to turn off hybrid-thinking generation (Qwen3.5 et al.).
# This is the OpenAI-compatible, backend-portable replacement for Ollama's native
# top-level `think` flag — see openspec capability `inference-backend`.
_ENABLE_THINKING_KWARG = "enable_thinking"


class OpenAIChatClient:
    """Thin async client for the OpenAI-compatible chat-completions endpoint
    exposed by the local model server (Unsloth Studio on CUDA, or any conforming
    ``llama.cpp``/vLLM server) at e.g. http://127.0.0.1:11434/v1.

    Chain-of-thought suppression travels via ``chat_template_kwargs`` (the
    portable llama.cpp mechanism), NOT Ollama's native ``think`` flag: Lingua is a
    *voice*, not a reasoner — reasoning lives in Nous — so a hybrid-thinking model
    (e.g. Qwen3.5) runs with thinking off. If the served model/server rejects the
    kwarg, the request is retried without it so non-thinking models still work.

    No streaming for v1 — single-shot completion. Streaming can land in a
    follow-up change.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434/v1",
        *,
        api_key: Optional[str] = None,
        timeout_s: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        # infrastructural: real time, not subjective — a request timeout bounds
        # how long we wait on an external service in real wall seconds and must
        # not dilate with the entity's time_scale.
        self._timeout_s = float(timeout_s)
        self._client: Any = None

    @property
    def base_url(self) -> str:
        return self._base_url

    def _ensure_client(self) -> Any:
        if self._client is None:
            import httpx

            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=headers,
                timeout=self._timeout_s,
            )
        return self._client

    def _body(self, request: ChatRequest, *, think: Optional[bool]) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})
        body: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.stop:
            body["stop"] = list(request.stop)
        if think is not None:
            # `think=False` → don't generate a chain-of-thought (the organ case);
            # `think=True` → allow it. Forwarded to the model's chat template.
            body["chat_template_kwargs"] = {_ENABLE_THINKING_KWARG: think}
        return body

    @staticmethod
    def _kwarg_rejected(resp: Any) -> bool:
        # A server/model that doesn't understand the thinking kwarg 400s on it;
        # detect that so we can retry without (a non-thinking model needs none).
        if resp.status_code != 400:
            return False
        text = resp.text.lower()
        return _ENABLE_THINKING_KWARG in text or "chat_template_kwargs" in text or "template" in text

    async def complete(self, request: ChatRequest) -> ChatResponse:
        import time as _time

        # Organ-absent graceful degradation: during the sleep-cycle voice-
        # alignment training window the served organ is unloaded to free the GPU
        # (kaine.modules.hypnos.organ_window). The window falls inside SLEEP, when
        # the entity is not expected to speak, so a generation request DEFERS to a
        # resting no-op rather than hammering the dead endpoint and raising.
        # Consumers resume automatically on reload (the state file flips to idle).
        from kaine.organ_window_state import organ_unloaded

        if organ_unloaded():
            log.debug("lingua: organ resting (voice-alignment window); deferring generation")
            return ChatResponse(
                text="",
                model=request.model,
                raw={"organ_resting": True},
            )

        client = self._ensure_client()
        start = _time.monotonic()
        resp = await client.post(
            "/chat/completions", json=self._body(request, think=request.think)
        )
        if request.think is not None and self._kwarg_rejected(resp):
            resp = await client.post(
                "/chat/completions", json=self._body(request, think=None)
            )
        resp.raise_for_status()
        data = resp.json()
        elapsed_ms = (_time.monotonic() - start) * 1000.0
        # `content` is the visible answer. If thinking slipped through and content
        # came back empty (model truncated mid-reasoning), fall back to the
        # chain-of-thought field so the caller still gets text. llama.cpp / Unsloth
        # Studio name it `reasoning_content`; some servers use `reasoning` — both.
        message = data["choices"][0]["message"]
        text = (
            message.get("content")
            or message.get("reasoning_content")
            or message.get("reasoning")
            or ""
        )
        usage = data.get("usage") or {}
        return ChatResponse(
            text=text,
            model=data.get("model", request.model),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            latency_ms=elapsed_ms,
            raw=data,
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class FakeChatClient:
    """Scriptable stand-in for tests.

    Append (prompt → response) pairs to `responses` and the client will
    return them in order. If `responses` is empty, returns a deterministic
    echo of the prompt.
    """

    def __init__(
        self,
        base_url: str = "http://fake/v1",
        responses: Optional[list[str]] = None,
        latency_ms: float = 5.0,
    ) -> None:
        self._base_url = base_url
        self.responses: list[str] = list(responses or [])
        self.requests: list[ChatRequest] = []
        self._latency_ms = float(latency_ms)
        self.closed = False

    @property
    def base_url(self) -> str:
        return self._base_url

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        if self.responses:
            text = self.responses.pop(0)
        else:
            text = f"[echo:{request.model}] {request.prompt}"
        return ChatResponse(
            text=text,
            model=request.model,
            prompt_tokens=len(request.prompt.split()),
            completion_tokens=len(text.split()),
            latency_ms=self._latency_ms,
            raw={"fake": True},
        )

    async def aclose(self) -> None:
        self.closed = True
