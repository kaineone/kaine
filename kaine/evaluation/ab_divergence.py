# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""A/B divergence observer: every Lingua external_speech is paired
with a second 'bare LLM' inference and the cosine similarity logged.

The bare output never reaches the user or Mnemos. We use the same
chat endpoint as Lingua via httpx so behavior matches the real one.
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, runtime_checkable

import httpx

from kaine.bus.schema import Event
from kaine.evaluation._base import BusReader, StreamSubscriberObserver
from kaine.evaluation.embeddings import TextEmbedder, cosine_similarity
from kaine.evaluation.proactive_audit import LINGUA_EXTERNAL_STREAM
from kaine.evaluation.sink import AsyncJsonlSink

log = logging.getLogger(__name__)


BARE_SYSTEM_PROMPT = (
    "You are a helpful assistant. Respond to the user's input directly. "
    "You have no memory of past interactions and no other context."
)


@runtime_checkable
class BareInferenceClient(Protocol):
    async def complete(self, user_text: str) -> str: ...
    async def close(self) -> None: ...


# Chat-template kwarg the local OpenAI-compatible server (Unsloth Studio /
# llama.cpp) forwards to turn off hybrid-thinking generation — the portable
# replacement for Ollama's native `think` flag. Mirrors
# kaine.modules.lingua.client so the bare baseline suppresses reasoning exactly
# as the organ does; the eval layer keeps its own copy because it must not import
# kaine.modules.* (the sidecar import boundary).
_ENABLE_THINKING_KWARG = "enable_thinking"


class HTTPBareInferenceClient:
    def __init__(
        self,
        *,
        base_url: str,
        model_id: str,
        timeout_s: float = 60.0,
        think: Optional[bool] = None,
        api_key: Optional[str] = None,
    ) -> None:
        base = base_url.rstrip("/")
        # Target the OpenAI-compatible /v1 surface (same server as the organ).
        # Tolerate a base given without /v1 by appending it.
        if not base.endswith("/v1"):
            base = base + "/v1"
        self._base_url = base
        self._model_id = model_id
        self._think = think
        # Bearer auth for a keyed server (e.g. Unsloth Studio); omitted for a
        # keyless server. Same key the organ uses.
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        self._client = httpx.AsyncClient(timeout=timeout_s, headers=headers)

    def _body(self, user_text: str, *, think: Optional[bool]) -> dict:
        body: dict = {
            "model": self._model_id,
            "messages": [
                {"role": "system", "content": BARE_SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.7,
            "max_tokens": 512,
        }
        if think is not None:
            body["chat_template_kwargs"] = {_ENABLE_THINKING_KWARG: think}
        return body

    def _kwarg_rejected(self, resp) -> bool:
        if resp.status_code != 400:
            return False
        text = resp.text.lower()
        return (
            _ENABLE_THINKING_KWARG in text
            or "chat_template_kwargs" in text
            or "template" in text
        )

    async def complete(self, user_text: str) -> str:
        url = f"{self._base_url}/chat/completions"
        try:
            resp = await self._client.post(url, json=self._body(user_text, think=self._think))
            if self._think is not None and self._kwarg_rejected(resp):
                resp = await self._client.post(url, json=self._body(user_text, think=None))
            resp.raise_for_status()
        except Exception as exc:
            log.warning("bare inference HTTP failed: %s", exc)
            return ""
        data = resp.json()
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        return str(msg.get("content") or msg.get("reasoning") or "")

    async def close(self) -> None:
        await self._client.aclose()


class FakeBareInferenceClient:
    """For tests — returns a deterministic transform of the input."""

    def __init__(self, response: str = "bare response") -> None:
        self._response = response
        self.calls: list[str] = []

    async def complete(self, user_text: str) -> str:
        self.calls.append(user_text)
        return self._response

    async def close(self) -> None:
        return


async def divergence_for(
    conditioned_text: str,
    bare_text: str,
    *,
    embedder: TextEmbedder,
) -> float:
    """Pure A/B divergence between two output texts under one embedder.

    This is the *same* metric the live observer reports — ``1 - cosine`` of
    the two embedded outputs — factored out so controls and the observer share
    one definition (no parallel re-implementation that could drift).

    Both texts are embedded with the SAME embedder. Two identical strings embed
    to the same vector, so cosine is exactly 1.0 and divergence is exactly 0.0
    for ANY embedder (lexical hash or semantic) — that property is what makes the
    negative control embedder-agnostic. An empty arm yields divergence 1.0 (the
    live observer's convention: no comparable output ⇒ maximal divergence).
    """
    if not conditioned_text or not bare_text:
        return 1.0
    a = await embedder.embed(conditioned_text)
    b = await embedder.embed(bare_text)
    if not a or not b:
        return 1.0
    return 1.0 - cosine_similarity(a, b)


@runtime_checkable
class ConditionedInferenceClient(Protocol):
    """A single inference path that takes an utterance plus an explicit
    workspace-conditioning string and returns the model's output.

    The *control* path runs BOTH arms through this one method, varying only the
    ``conditioning`` argument: empty conditioning for the bare arm, injected
    conditioning for the conditioned arm. Because both arms share the same
    client, model, persona scaffolding, and prompt structure, any divergence the
    control reports is attributable to the conditioning ALONE — which is exactly
    what the A/B meter is supposed to measure. The real implementation (wired at
    the cycle entrypoint) reuses Lingua's ``ContextAssembler`` + chat client, so
    the control exercises the production conditioning path, not a parallel fake.
    """

    async def complete_conditioned(self, utterance: str, conditioning: str) -> str: ...


async def divergence_control(
    client: ConditionedInferenceClient,
    utterance: str,
    conditioning: str,
    *,
    embedder: TextEmbedder,
) -> dict[str, Any]:
    """Run the A/B meter as a controlled instrument.

    Produces the conditioned arm (``utterance`` under ``conditioning``) and the
    bare arm (the SAME ``utterance`` under EMPTY conditioning) through the SAME
    inference path, embeds both, and returns the divergence plus the raw arms so
    a caller (or test) can inspect them.

    - Negative control: pass ``conditioning=""`` → both arms run identical input
      → identical output → ``divergence ≈ 0``.
    - Positive control: pass a large, known ``conditioning`` → the conditioned
      arm diverges from the bare arm → ``divergence`` large.

    Returns a dict with ``conditioned_text``, ``bare_text``, ``divergence``,
    ``cosine_similarity``, and ``embedder`` (the kind tag, for disclosure).
    """
    conditioned_text = await client.complete_conditioned(utterance, conditioning)
    bare_text = await client.complete_conditioned(utterance, "")
    divergence = await divergence_for(conditioned_text, bare_text, embedder=embedder)
    return {
        "conditioned_text": conditioned_text,
        "bare_text": bare_text,
        "divergence": divergence,
        "cosine_similarity": 1.0 - divergence,
        "embedder": getattr(embedder, "kind", "unknown"),
    }


class AssemblerConditionedClient:
    """Real conditioned-inference path for the control: Lingua's own
    ``ContextAssembler`` + the language-organ chat client.

    Wired at the cycle entrypoint (the allowed module-coupling point), this
    builds the conditioned prompt the SAME way Lingua does in production, then
    runs it through the SAME chat client. ``conditioning`` is the rendered
    workspace/awareness block: an empty string reproduces the "nothing salient"
    prompt (the bare arm), a populated string injects the workspace contents.

    The evaluation layer never imports this directly into the live observer; it
    is constructed by the entrypoint and handed to ``divergence_control`` so the
    decoupling rule (``kaine.evaluation`` imports no ``kaine.modules.*``) holds —
    the seam is a duck-typed callable, not an import.

    Parameters
    ----------
    build_prompt:
        ``(utterance, conditioning) -> (system, prompt)``. Built from a real
        ``ContextAssembler`` at the entrypoint. Both arms call it with the same
        ``utterance``, differing only in ``conditioning``.
    complete:
        ``(system, prompt) -> str`` — the language-organ chat call. Both arms
        share it, so model/temperature/think are identical across arms.
    """

    def __init__(self, build_prompt, complete) -> None:
        self._build_prompt = build_prompt
        self._complete = complete

    async def complete_conditioned(self, utterance: str, conditioning: str) -> str:
        system, prompt = self._build_prompt(utterance, conditioning)
        return await self._complete(system, prompt)


class ABDivergenceObserver(StreamSubscriberObserver):
    name = "ab_divergence"
    stream = LINGUA_EXTERNAL_STREAM

    def __init__(
        self,
        bus: BusReader,
        sink: AsyncJsonlSink,
        *,
        embedder: TextEmbedder,
        client: BareInferenceClient,
        sample_rate: float = 1.0,
        last_user_input_provider=None,
        rng: random.Random | None = None,
    ) -> None:
        super().__init__(bus, poll_interval_s=0.3)
        self._sink = sink
        self._embedder = embedder
        self._client = client
        self._sample_rate = max(0.0, min(1.0, float(sample_rate)))
        self._last_input = last_user_input_provider
        self._rng = rng or random.Random()
        self._sampled_count = 0

    async def start(self) -> None:
        try:
            await self._embedder.load()
        except Exception:
            log.warning("AB embedder load failed; fallback to lazy load", exc_info=True)
        await super().start()

    async def stop(self) -> None:
        await super().stop()
        try:
            await self._client.close()
        except Exception:
            log.warning("bare inference client close failed", exc_info=True)

    async def handle(self, entry_id: str, event: Event) -> None:
        if event.type != "external_speech":
            return
        # Organ-absent graceful degradation: during the sleep-cycle voice-
        # alignment training window the served organ is unloaded to free the GPU
        # (the bare baseline arm would otherwise POST to a dead endpoint). The
        # window falls inside sleep, so SKIP the sample — logged as skipped, NOT
        # recorded as a divergence failure. The arm resumes on organ reload.
        from kaine.organ_window_state import organ_unloaded

        if organ_unloaded():
            await self._sink.write(
                {
                    "entry_id": entry_id,
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "skipped": "organ_resting_voice_alignment_window",
                }
            )
            return
        if self._sample_rate < 1.0 and self._rng.random() > self._sample_rate:
            return
        payload = event.payload or {}
        real_text = str(payload.get("text") or "")
        user_text = self._resolve_user_text(payload)
        if not real_text or not user_text:
            return
        try:
            bare_text = await self._client.complete(user_text)
        except Exception:
            bare_text = ""
            log.warning("bare inference raised", exc_info=True)
        try:
            real_vec = await self._embedder.embed(real_text)
            bare_vec = await self._embedder.embed(bare_text) if bare_text else []
        except Exception:
            log.warning("AB embedding failed", exc_info=True)
            real_vec, bare_vec = [], []
        sim = cosine_similarity(real_vec, bare_vec) if bare_vec else 0.0
        self._sampled_count += 1
        embedder_kind = getattr(self._embedder, "kind", "unknown")
        await self._sink.write(
            {
                "entry_id": entry_id,
                "ts": datetime.now(timezone.utc).isoformat(),
                "embedder": embedder_kind,
                "user_text_len": len(user_text),
                "real_text_len": len(real_text),
                "bare_text_len": len(bare_text),
                "cosine_similarity": sim,
                "divergence": 1.0 - sim,
                "contributing_modules": payload.get("contributing_modules") or [],
            }
        )

    def _resolve_user_text(self, payload: dict[str, Any]) -> str:
        # Lingua's intent-expression log carries `user_input`; if Lingua
        # publishes that on its event payload (it does via faithful_log),
        # use it. Otherwise, fall back to whatever's available.
        candidate = payload.get("user_input") or payload.get("user_text")
        if candidate:
            return str(candidate)
        # Last resort: callbacks fed by audition.
        if self._last_input is not None:
            try:
                return self._last_input() or ""
            except Exception:
                return ""
        return ""
