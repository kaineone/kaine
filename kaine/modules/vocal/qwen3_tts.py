# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Local TTS backend using Qwen3-TTS (qwen-tts package).

The client supports reversible unload: call unload() to release GPU memory
without destroying the client, and ensure_loaded() to load it again on demand.
"""
from __future__ import annotations

import asyncio
import gc
import io
import logging
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

import numpy as np

from kaine.modules.vocal.client import SynthesisResult, TTSRequest
from kaine.residency.inflight import InflightGate, InflightTicket

APPLIED_PROSODY = ("instruct", "language")

logger = logging.getLogger(__name__)


class Qwen3TTS:
    """In-process Qwen3-TTS backed by the qwen-tts package.

    Models can be released with unload() and restored with ensure_loaded()
    without rebuilding the client.
    """

    _CLOSE_TIMEOUT_S: float = 30.0

    def __init__(
        self,
        model_id: str = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
        tokenizer_id: str = "Qwen/Qwen3-TTS-Tokenizer-12Hz",
        *,
        device: str = "cuda:1",
        dtype_name: str = "bfloat16",
        speaker: str = "",
        _qwen_tts_module: Any | None = None,
    ) -> None:
        self._model_id = model_id
        self._tokenizer_id = tokenizer_id
        self._device = device
        self._dtype_name = dtype_name
        self._speaker = speaker
        self._resolved_speaker: Optional[str] = None
        self._qwen_tts_module = _qwen_tts_module

        self._model: Any | None = None
        self._tokenizer: Any | None = None

        self._closed = False
        self._state_lock: asyncio.Lock | None = None
        self._gate = InflightGate()
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="qwen3-tts"
        )

    @property
    def base_url(self) -> str:
        short_name = self._model_id.rsplit("/", 1)[-1]
        return f"qwen3-tts://{short_name}"

    @property
    def loaded(self) -> bool:
        return not self._closed and self._model is not None

    def _ensure_state_lock(self) -> asyncio.Lock:
        if self._state_lock is None:
            self._state_lock = asyncio.Lock()
        return self._state_lock

    async def _ensure_loaded_locked(self) -> None:
        """Load the model and tokenizer while the state lock is held."""
        if self._model is not None:
            return
        if self._closed or self._executor is None:
            raise RuntimeError("Qwen3-TTS client is closed")
        loop = asyncio.get_running_loop()

        def _build() -> tuple[Any, Any, str]:
            qwen_mod = self._qwen_tts_module
            if qwen_mod is None:
                try:
                    import qwen_tts as qwen_mod  # type: ignore[import]
                except ImportError as exc:
                    raise ImportError(
                        "qwen-tts is required for the Qwen3-TTS backend. "
                        "Install it with: pip install 'kaine[speech-qwen3]'"
                    ) from exc

            import torch

            dtype_map = {
                "bfloat16": torch.bfloat16,
                "float16": torch.float16,
                "float32": torch.float32,
            }
            dtype = dtype_map.get(self._dtype_name, torch.bfloat16)

            logger.info(
                "loading Qwen3-TTS model %s on %s (%s)",
                self._model_id, self._device, self._dtype_name,
            )

            model = qwen_mod.Qwen3TTSModel.from_pretrained(
                self._model_id,
                device_map=self._device,
                dtype=dtype,
            )
            tokenizer = qwen_mod.Qwen3TTSTokenizer.from_pretrained(
                self._tokenizer_id,
                device_map=self._device,
            )

            speakers = model.get_supported_speakers()
            if speakers is None:
                speakers = []
            speakers = list(speakers)

            if self._speaker:
                resolved = self._speaker
            elif speakers:
                resolved = sorted(speakers, key=str)[0]
            else:
                resolved = ""

            logger.info("Qwen3-TTS speaker: %s", resolved or "(none)")
            return model, tokenizer, resolved

        model, tokenizer, resolved = await loop.run_in_executor(
            self._executor, _build
        )
        if self._closed:
            raise RuntimeError("Qwen3-TTS client is closed")
        self._model = model
        self._tokenizer = tokenizer
        self._resolved_speaker = resolved
        if not self._qwen_tts_module:
            try:
                import qwen_tts

                self._qwen_tts_module = qwen_tts
            except ImportError:
                pass  # deferred: ensure_loaded() will raise if still missing

    async def ensure_loaded(self) -> None:
        """Load the model when it is not loaded.

        Idempotent: concurrent callers share a single load. Raises if the
        client has been closed.
        """
        if self._closed or self._executor is None:
            raise RuntimeError("Qwen3-TTS client is closed")
        async with self._ensure_state_lock():
            if self._closed or self._executor is None:
                raise RuntimeError("Qwen3-TTS client is closed")
            await self._ensure_loaded_locked()

    async def warm_up(self) -> None:
        """Load the model eagerly."""
        await self.ensure_loaded()

    async def _use_model(self) -> tuple[Any, InflightTicket]:
        """Load the model if needed and mark one in-flight inference."""
        if self._closed or self._executor is None:
            raise RuntimeError("Qwen3-TTS client is closed")
        async with self._ensure_state_lock():
            if self._closed or self._executor is None:
                raise RuntimeError("Qwen3-TTS client is closed")
            await self._ensure_loaded_locked()
            model = self._model
            ticket = self._gate.admit()
        return (model, ticket)

    async def synthesize(self, request: TTSRequest) -> SynthesisResult:
        """Synthesize ``request.text`` to a mono 16-bit WAV."""
        if self._executor is None:
            raise RuntimeError("Qwen3-TTS client is closed")

        model, ticket = await self._use_model()
        handed = False

        try:
            text = request.text
            if not text or not text.strip():
                raise ValueError("empty text")

            resolved_speaker = self._resolved_speaker or ""
            language = request.language or "English"
            instruct = request.instruct or ""

            def _generate() -> tuple[list[Any], int]:
                return model.generate_custom_voice(
                    text=text,
                    language=language,
                    speaker=resolved_speaker,
                    instruct=instruct,
                )

            start = time.monotonic()
            handed = True
            wavs, sr = await self._gate.run(
                ticket, self._executor, _generate
            )
            latency_ms = (time.monotonic() - start) * 1000.0

            samples = np.asarray(wavs[0], dtype=np.float32)
            if samples.size == 0:
                raise RuntimeError("synthesis produced no audio")

            clipped = np.clip(samples, -1.0, 1.0)
            int_samples = np.round(clipped * 32767).astype(np.int16)

            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
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

    async def unload(self) -> None:
        """Release the model while keeping the client usable.

        Waits for any in-flight inference to finish, drops the model objects,
        and runs garbage collection in the engine thread.
        """
        if self._closed or self._executor is None or self._model is None:
            return
        async with self._ensure_state_lock():
            if self._closed or self._executor is None or self._model is None:
                return
            await self._gate.wait_idle()
            self._model = None
            self._tokenizer = None
            self._resolved_speaker = None
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self._executor, gc.collect)

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
                self._tokenizer = None
                self._resolved_speaker = None

        timed_out = False
        try:
            await asyncio.wait_for(_drop(), timeout=self._CLOSE_TIMEOUT_S)
        except asyncio.TimeoutError:
            timed_out = True
            logger.warning(
                "Qwen3-TTS client: timeout waiting for in-flight inference "
                "during close; proceeding"
            )
            self._model = None
            self._tokenizer = None
            self._resolved_speaker = None

        if self._executor is not None:
            if not timed_out:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(self._executor, gc.collect)
            self._executor.shutdown(wait=False)
            self._executor = None
