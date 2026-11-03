# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Local TTS backend using Qwen3-TTS (qwen-tts package, CustomVoice model).

Like the sherpa backend, the client supports reversible unload: unload()
releases the model (and its GPU memory) without destroying the client, and
ensure_loaded() loads it again on demand.
"""

from __future__ import annotations

import asyncio
import gc
import io
import logging
import math
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

from kaine.modules.vocal.client import SynthesisResult, TTSRequest
from kaine.residency.inflight import InflightGate, InflightTicket

APPLIED_PROSODY = ("instruct", "speed_factor", "language")

DEFAULT_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"

logger = logging.getLogger(__name__)


class Qwen3TTS:
    """Qwen3-TTS CustomVoice client with reversible unload."""

    _CLOSE_TIMEOUT_S: float = 10.0

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        *,
        device: str = "cuda:1",
        dtype: str = "bfloat16",
        speaker: str = "",
    ) -> None:
        self._model_id = model_id
        self._device = device
        self._dtype = dtype
        self._speaker = speaker or ""
        self._model: Any | None = None
        self._executor: ThreadPoolExecutor | None = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="qwen3-tts"
        )
        self._closed = False
        self._state_lock: asyncio.Lock | None = None
        self._gate = InflightGate()

    @property
    def base_url(self) -> str:
        return "local://qwen3-tts"

    @property
    def loaded(self) -> bool:
        return not self._closed and self._model is not None

    @property
    def speaker(self) -> str:
        return self._speaker

    def _ensure_state_lock(self) -> asyncio.Lock:
        if self._state_lock is None:
            self._state_lock = asyncio.Lock()
        return self._state_lock

    @staticmethod
    def _resolve_speed(speed_factor: float | int | None) -> float:
        if (
            not isinstance(speed_factor, (int, float))
            or not math.isfinite(float(speed_factor))
            or speed_factor <= 0
        ):
            return 1.0
        return max(0.5, min(2.0, float(speed_factor)))

    def _build(self) -> Any:
        try:
            import torch
            from qwen_tts import Qwen3TTSModel  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "qwen-tts and torch are required for the qwen3_tts vocal backend. "
                "Install them with: pip install 'kaine[speech-qwen]'"
            ) from exc

        torch_dtype = getattr(torch, self._dtype, None)
        if torch_dtype is None:
            raise ValueError(f"unknown torch dtype {self._dtype!r}")
        model = Qwen3TTSModel.from_pretrained(
            self._model_id, device_map=self._device, torch_dtype=torch_dtype
        )
        if not self._speaker:
            speakers = list(model.get_supported_speakers() or [])
            if not speakers:
                raise RuntimeError("qwen3-tts model reports no supported speakers")
            self._speaker = str(speakers[0])
        return model

    async def _ensure_loaded_locked(self) -> None:
        if self._model is not None:
            return
        if self._closed or self._executor is None:
            raise RuntimeError("qwen3-tts client is closed")
        loop = asyncio.get_running_loop()
        model = await loop.run_in_executor(self._executor, self._build)
        # The load finished after close: drop it, never keep it on a closed client.
        if self._closed:
            raise RuntimeError("qwen3-tts client is closed")
        self._model = model

    async def ensure_loaded(self) -> None:
        """Load the model when it is not loaded. Idempotent."""
        if self._closed or self._executor is None:
            raise RuntimeError("qwen3-tts client is closed")
        async with self._ensure_state_lock():
            if self._closed or self._executor is None:
                raise RuntimeError("qwen3-tts client is closed")
            await self._ensure_loaded_locked()

    async def warm_up(self) -> None:
        await self.ensure_loaded()

    async def _use_model(self) -> tuple[Any, InflightTicket]:
        if self._closed or self._executor is None:
            raise RuntimeError("qwen3-tts client is closed")
        async with self._ensure_state_lock():
            if self._closed or self._executor is None:
                raise RuntimeError("qwen3-tts client is closed")
            await self._ensure_loaded_locked()
            model = self._model
            ticket = self._gate.admit()
        return (model, ticket)

    async def synthesize(self, request: TTSRequest) -> SynthesisResult:
        """Synthesize ``request.text`` to a mono 16-bit WAV."""
        if self._executor is None:
            raise RuntimeError("qwen3-tts client is closed")

        model, ticket = await self._use_model()
        handed = False
        try:
            text = request.text
            if text is None or text.strip() == "":
                raise ValueError("empty text")

            language = request.language or "Auto"
            instruct = request.instruct or None
            speaker = self._speaker
            speed = self._resolve_speed(request.speed_factor)

            def _generate() -> tuple[Any, int]:
                wavs, sample_rate = model.generate_custom_voice(
                    text=text,
                    language=language,
                    speaker=speaker,
                    instruct=instruct,
                )
                return wavs, int(sample_rate)

            start = time.monotonic()
            # From here on the gate owns the release.
            handed = True
            wavs, sample_rate = await self._gate.run(ticket, self._executor, _generate)
            latency_ms = (time.monotonic() - start) * 1000.0

            first = wavs[0] if isinstance(wavs, (list, tuple)) else wavs
            if hasattr(first, "detach"):
                first = first.detach().cpu().numpy()
            samples = np.asarray(first, dtype=np.float32).reshape(-1)
            if samples.size == 0:
                raise RuntimeError("synthesis produced no audio")

            if speed != 1.0:
                # The model has no rate control; resampling shifts pitch slightly,
                # which is acceptable inside the narrow affect speed band.
                n_out = max(1, int(round(samples.size / speed)))
                samples = np.interp(
                    np.linspace(0, samples.size - 1, n_out),
                    np.arange(samples.size),
                    samples,
                ).astype(np.float32)

            int_samples = np.round(np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(int_samples.tobytes())
            wav_bytes = buf.getvalue()
        except BaseException:
            if not handed:
                ticket.release()
            raise

        return SynthesisResult(
            audio=wav_bytes,
            content_type="audio/wav",
            latency_ms=latency_ms,
            output_format="wav",
            bytes_produced=len(wav_bytes),
        )

    @staticmethod
    def _release_gpu() -> None:
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            logger.debug("qwen3-tts: cuda cache release skipped", exc_info=True)

    async def unload(self) -> None:
        """Release the model while keeping the client usable.

        Waits for in-flight synthesis, drops the model and frees GPU memory.
        Idempotent and a no-op after close.
        """
        if self._closed or self._executor is None or self._model is None:
            return
        async with self._ensure_state_lock():
            if self._closed or self._executor is None or self._model is None:
                return
            await self._gate.wait_idle()
            self._model = None
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self._executor, self._release_gpu)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True

        async def _drop() -> None:
            if self._state_lock is None:
                return
            async with self._state_lock:
                await self._gate.wait_idle()
                self._model = None

        timed_out = False
        try:
            await asyncio.wait_for(_drop(), timeout=self._CLOSE_TIMEOUT_S)
        except asyncio.TimeoutError:
            timed_out = True
            logger.warning(
                "qwen3-tts client: timeout waiting for in-flight synthesis "
                "during close; proceeding"
            )
            self._model = None

        if self._executor is not None:
            if not timed_out:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(self._executor, self._release_gpu)
            self._executor.shutdown(wait=False)
            self._executor = None
