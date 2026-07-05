# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TTSRequest:
    text: str
    voice_mode: str = "predefined"
    predefined_voice_id: Optional[str] = None
    reference_audio_filename: Optional[str] = None
    output_format: str = "wav"
    temperature: Optional[float] = None
    exaggeration: Optional[float] = None
    cfg_weight: Optional[float] = None
    speed_factor: Optional[float] = None
    language: Optional[str] = None
    split_text: bool = True


@dataclass(frozen=True)
class SynthesisResult:
    audio: bytes
    content_type: str
    latency_ms: float
    output_format: str
    bytes_produced: int


@runtime_checkable
class TTSClient(Protocol):
    @property
    def base_url(self) -> str: ...

    async def synthesize(self, request: TTSRequest) -> SynthesisResult: ...

    async def aclose(self) -> None: ...


class ChatterboxClient:
    """Async client for the Chatterbox-TTS-Server `/tts` endpoint."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8883",
        *,
        timeout_s: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        # infrastructural: real time, not subjective (TTS request timeout).
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

    async def synthesize(self, request: TTSRequest) -> SynthesisResult:
        client = self._ensure_client()
        body: dict[str, Any] = {
            "text": request.text,
            "voice_mode": request.voice_mode,
            "output_format": request.output_format,
            "split_text": request.split_text,
        }
        for key in (
            "predefined_voice_id",
            "reference_audio_filename",
            "temperature",
            "exaggeration",
            "cfg_weight",
            "speed_factor",
            "language",
        ):
            value = getattr(request, key)
            if value is not None:
                body[key] = value
        start = time.monotonic()
        resp = await client.post("/tts", json=body)
        resp.raise_for_status()
        audio = resp.content
        elapsed_ms = (time.monotonic() - start) * 1000.0
        content_type = resp.headers.get("content-type", f"audio/{request.output_format}")
        return SynthesisResult(
            audio=audio,
            content_type=content_type,
            latency_ms=elapsed_ms,
            output_format=request.output_format,
            bytes_produced=len(audio),
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class FakeTTSClient:
    """Deterministic scriptable stand-in for tests."""

    def __init__(
        self,
        base_url: str = "http://fake-tts",
        *,
        canned_audio: bytes | None = None,
        latency_ms: float = 5.0,
    ) -> None:
        self._base_url = base_url
        self._canned_audio = canned_audio or b"\x00\x00FAKE_WAV_HEADER\x00\x00"
        self._latency_ms = float(latency_ms)
        self.requests: list[TTSRequest] = []
        self.closed = False

    @property
    def base_url(self) -> str:
        return self._base_url

    async def synthesize(self, request: TTSRequest) -> SynthesisResult:
        self.requests.append(request)
        return SynthesisResult(
            audio=self._canned_audio,
            content_type=f"audio/{request.output_format}",
            latency_ms=self._latency_ms,
            output_format=request.output_format,
            bytes_produced=len(self._canned_audio),
        )

    async def aclose(self) -> None:
        self.closed = True
