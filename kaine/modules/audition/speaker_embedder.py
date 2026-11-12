# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Local speaker embedding extractor using sherpa-onnx (WeSpeaker CAM++)."""

from __future__ import annotations

import asyncio
import gc
import io
import logging
import math
import wave
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from kaine.residency.router import ResidencyRouter

from kaine.residency.inflight import InflightGate, InflightTicket

logger = logging.getLogger(__name__)

_FULL_CONFIDENCE_S = 1.5


@dataclass(frozen=True)
class SpeakerEmbeddingResult:
    embedding: list[float] | None
    confidence: float
    degraded: bool
    dim: int


def _degraded() -> SpeakerEmbeddingResult:
    return SpeakerEmbeddingResult(embedding=None, confidence=0.0, degraded=True, dim=0)


class SpeakerEmbedder:
    """Speaker embedding client backed by a sherpa-onnx extractor, loaded lazily."""

    _CLOSE_TIMEOUT_S: float = 10.0

    def __init__(
        self,
        model_path: Path | str,
        *,
        num_threads: int = 1,
        sample_rate: int = 16000,
        sherpa_module: Any | None = None,
        router: ResidencyRouter | None = None,
    ) -> None:
        self._path = Path(model_path)
        self._num_threads = int(num_threads)
        self._sample_rate = int(sample_rate)

        so = sherpa_module
        if so is None:
            try:
                import sherpa_onnx as so  # type: ignore[import]
            except ImportError as exc:
                raise ImportError(
                    "sherpa_onnx is required for speaker embedding. "
                    "Install it with: pip install 'kaine[speech-edge]'"
                ) from exc

        self._sherpa_module = so
        self._extractor: Any | None = None
        self._dim = 0
        self._executor: ThreadPoolExecutor | None = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="speaker-embed"
        )

        self._closed = False
        self._state_lock: asyncio.Lock | None = None
        self._gate = InflightGate()
        self._router = router
        self._residency_name = "speaker_embedder"

    @property
    def loaded(self) -> bool:
        return not self._closed and self._extractor is not None

    @property
    def dim(self) -> int:
        if self._extractor is None:
            return self._dim
        return int(self._extractor.dim)

    def _ensure_state_lock(self) -> asyncio.Lock:
        if self._state_lock is None:
            self._state_lock = asyncio.Lock()
        return self._state_lock

    def _build(self) -> Any:
        so = self._sherpa_module
        config = so.SpeakerEmbeddingExtractorConfig(
            model=str(self._path),
            num_threads=self._num_threads,
            provider="cpu",
        )
        return so.SpeakerEmbeddingExtractor(config)

    async def _ensure_loaded_locked(self) -> None:
        if self._extractor is not None:
            return
        if self._closed or self._executor is None:
            raise RuntimeError("speaker embedder is closed")
        if self._router:
            admitted = await self._router.before_load(self._residency_name)
            if not admitted:
                return
        loop = asyncio.get_running_loop()
        extractor = await loop.run_in_executor(self._executor, self._build)
        if self._closed:
            raise RuntimeError("speaker embedder is closed")
        self._extractor = extractor
        self._dim = int(extractor.dim)
        if self._router:
            self._router.after_load(self._residency_name)

    async def warm_up(self) -> None:
        """Load the extractor in the worker thread; idempotent, raises on load error."""
        if self._closed or self._executor is None:
            raise RuntimeError("speaker embedder is closed")
        async with self._ensure_state_lock():
            if self._closed or self._executor is None:
                raise RuntimeError("speaker embedder is closed")
            await self._ensure_loaded_locked()

    async def _use_model(self) -> tuple[Any, InflightTicket]:
        if self._closed or self._executor is None:
            raise RuntimeError("speaker embedder is closed")
        async with self._ensure_state_lock():
            if self._closed or self._executor is None:
                raise RuntimeError("speaker embedder is closed")
            try:
                await self._ensure_loaded_locked()
            except Exception:
                if self._closed:
                    raise RuntimeError("speaker embedder is closed") from None
                raise
            extractor = self._extractor
            ticket = self._gate.admit()
        if self._router:
            self._router.record_use(self._residency_name)
        return (extractor, ticket)

    async def extract(
        self, audio_bytes: bytes, *, sample_rate: int = 16000
    ) -> SpeakerEmbeddingResult:
        """Embed a 16-bit PCM WAV; returns a degraded result on load or compute failure."""
        if self._executor is None:
            raise RuntimeError("speaker embedder is closed")

        try:
            extractor, ticket = await self._use_model()
        except RuntimeError:
            if self._closed:
                raise
            logger.warning("speaker embedder failed to load", exc_info=True)
            return _degraded()
        except Exception:
            logger.warning("speaker embedder failed to load", exc_info=True)
            return _degraded()

        handed = False
        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                if wf.getsampwidth() != 2:
                    raise ValueError(
                        f"unsupported sample width {wf.getsampwidth()}; "
                        "only 16-bit PCM WAV is supported"
                    )
                nchannels = wf.getnchannels()
                nframes = wf.getnframes()
                if nframes == 0:
                    ticket.release()
                    return _degraded()
                pcm = wf.readframes(nframes)

            arr = np.frombuffer(pcm, dtype=np.int16)
            if nchannels > 1:
                arr = arr[0::nchannels]
            samples = (arr.astype(np.float32) / 32768.0).tolist()
            n = len(samples)

            def _compute() -> list[float] | None:
                stream = extractor.create_stream()
                stream.accept_waveform(sample_rate, samples)
                stream.input_finished()
                if not extractor.is_ready(stream):
                    return None
                return list(extractor.compute(stream))

            handed = True
            embedding = await self._gate.run(ticket, self._executor, _compute)
        except BaseException:
            if not handed:
                ticket.release()
            raise

        if embedding is None or not all(math.isfinite(v) for v in embedding):
            return _degraded()

        confidence = min(1.0, n / (sample_rate * _FULL_CONFIDENCE_S))
        return SpeakerEmbeddingResult(
            embedding=[float(v) for v in embedding],
            confidence=confidence,
            degraded=False,
            dim=self.dim,
        )

    async def unload(self) -> None:
        """Release the model while keeping the client usable."""
        if self._closed or self._executor is None or self._extractor is None:
            return
        if self._router:
            self._router.before_unload(self._residency_name)
        try:
            async with self._ensure_state_lock():
                if self._closed or self._executor is None or self._extractor is None:
                    return
                await self._gate.wait_idle()
                self._extractor = None
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(self._executor, gc.collect)
        finally:
            if self._router:
                self._router.after_unload(self._residency_name)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True

        async def _drop() -> None:
            if self._state_lock is None:
                return
            async with self._state_lock:
                await self._gate.wait_idle()
                self._extractor = None

        timed_out = False
        try:
            await asyncio.wait_for(_drop(), timeout=self._CLOSE_TIMEOUT_S)
        except asyncio.TimeoutError:
            timed_out = True
            logger.warning(
                "speaker embedder: timeout waiting for in-flight inference "
                "during close; proceeding"
            )
            self._extractor = None

        if self._executor is not None:
            if not timed_out:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(self._executor, gc.collect)
            self._executor.shutdown(wait=False)
            self._executor = None
