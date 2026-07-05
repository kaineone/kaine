# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    model: str
    latency_ms: float
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class STTClient(Protocol):
    @property
    def base_url(self) -> str: ...

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        sample_rate: int,
        model: str,
        filename: str = "audio.wav",
    ) -> TranscriptionResult: ...

    async def aclose(self) -> None: ...


class SpeachesClient:
    """Async client for the Speaches OpenAI-compatible STT endpoint.

    POSTs multipart/form-data to /v1/audio/transcriptions with the
    audio file plus a model name. Speaches accepts WAV/MP3/FLAC; the
    caller is responsible for handing in the right encoding.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        *,
        timeout_s: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        # infrastructural: real time, not subjective (STT request timeout).
        self._timeout_s = float(timeout_s)
        self._client: Any = None

    @property
    def base_url(self) -> str:
        return self._base_url

    def _ensure_client(self) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_s,
            )
        return self._client

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        sample_rate: int,
        model: str,
        filename: str = "audio.wav",
    ) -> TranscriptionResult:
        client = self._ensure_client()
        files = {
            "file": (filename, audio_bytes, _content_type_for(filename)),
        }
        data = {"model": model}
        start = time.monotonic()
        resp = await client.post(
            "/v1/audio/transcriptions", files=files, data=data
        )
        resp.raise_for_status()
        body = resp.json()
        elapsed_ms = (time.monotonic() - start) * 1000.0
        text = body.get("text", "")
        return TranscriptionResult(
            text=text,
            model=body.get("model", model),
            latency_ms=elapsed_ms,
            raw=body,
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _content_type_for(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".wav"):
        return "audio/wav"
    if lower.endswith(".mp3"):
        return "audio/mpeg"
    if lower.endswith(".flac"):
        return "audio/flac"
    if lower.endswith(".opus"):
        return "audio/opus"
    return "application/octet-stream"


class FakeSTTClient:
    """Deterministic stand-in for tests.

    Returns scripted texts in order. If exhausted, echoes a placeholder.
    """

    def __init__(
        self,
        base_url: str = "http://fake-stt",
        responses: Optional[list[str]] = None,
        latency_ms: float = 10.0,
    ) -> None:
        self._base_url = base_url
        self.responses: list[str] = list(responses or [])
        self.transcriptions: list[tuple[int, int]] = []  # (sample_rate, len(audio_bytes))
        self._latency_ms = float(latency_ms)
        self.closed = False

    @property
    def base_url(self) -> str:
        return self._base_url

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        sample_rate: int,
        model: str,
        filename: str = "audio.wav",
    ) -> TranscriptionResult:
        self.transcriptions.append((sample_rate, len(audio_bytes)))
        text = self.responses.pop(0) if self.responses else "<fake-transcription>"
        return TranscriptionResult(
            text=text,
            model=model,
            latency_ms=self._latency_ms,
            raw={"fake": True},
        )

    async def aclose(self) -> None:
        self.closed = True
