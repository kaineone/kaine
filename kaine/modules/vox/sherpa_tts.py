# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Local TTS backend using sherpa-onnx Kokoro.

The client supports reversible unload: call unload() to release model memory
without destroying the client, and ensure_loaded() to load it again on demand.
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
from pathlib import Path
from typing import Any

import numpy as np

from kaine import speech_manifest
from kaine.modules.vox.client import SynthesisResult, TTSRequest

APPLIED_PROSODY = ("speed_factor",)

logger = logging.getLogger(__name__)


class SherpaKokoroTTS:
    """Offline Kokoro TTS client backed by sherpa-onnx.

    Models can be released with unload() and restored with ensure_loaded()
    without rebuilding the client.
    """

    def __init__(
        self,
        model_dir: Path | str,
        *,
        model_id: str = "kokoro-en",
        speaker_id: int = 0,
        num_threads: int = 2,
        sherpa_module: Any | None = None,
        _verify: bool = True,
    ) -> None:
        self._model_id = model_id
        self._speaker_id = int(speaker_id)
        self._dir = Path(model_dir)
        self._num_threads = int(num_threads)

        required = ("model.int8.onnx", "voices.bin", "tokens.txt", "espeak-ng-data")
        missing = [f for f in required if not (self._dir / f).exists()]
        if missing:
            raise FileNotFoundError(
                f"missing model file(s): {missing}. "
                f"Run: python -m kaine.setup.speech_models --tts {model_id}"
            )

        so = sherpa_module
        if so is None:
            try:
                import sherpa_onnx as so  # type: ignore[import]
            except ImportError as exc:
                raise ImportError(
                    "sherpa_onnx is required for the local speech backend. "
                    "Install it with: pip install 'kaine[speech-edge]'"
                ) from exc

        if _verify:
            speech_manifest.verify_model_dir(model_id, self._dir)

        self._sherpa_module = so
        self._tts: Any | None = None
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="sherpa-tts"
        )

        self._closed = False
        self._state_lock: asyncio.Lock | None = None
        self._inflight = 0
        self._inflight_cv = asyncio.Condition()

    @property
    def base_url(self) -> str:
        return f"sherpa-onnx://{self._model_id}"

    @property
    def loaded(self) -> bool:
        return not self._closed and self._tts is not None

    def _ensure_state_lock(self) -> asyncio.Lock:
        if self._state_lock is None:
            self._state_lock = asyncio.Lock()
        return self._state_lock

    def _resolve_speed(self, speed_factor: float | int | None) -> float:
        if (
            not isinstance(speed_factor, (int, float))
            or not math.isfinite(float(speed_factor))
            or speed_factor <= 0
        ):
            return 1.0
        return max(0.5, min(2.0, float(speed_factor)))

    async def _ensure_loaded_locked(self) -> None:
        """Load the TTS object while the state lock is held."""
        if self._tts is not None:
            return
        if self._closed or self._executor is None:
            raise RuntimeError("sherpa-onnx TTS client is closed")
        loop = asyncio.get_running_loop()

        def _build():
            tts = self._sherpa_module.OfflineTts(
                self._sherpa_module.OfflineTtsConfig(
                    model=self._sherpa_module.OfflineTtsModelConfig(
                        kokoro=self._sherpa_module.OfflineTtsKokoroModelConfig(
                            model=str(self._dir / "model.int8.onnx"),
                            voices=str(self._dir / "voices.bin"),
                            tokens=str(self._dir / "tokens.txt"),
                            data_dir=str(self._dir / "espeak-ng-data"),
                        ),
                        num_threads=self._num_threads,
                    ),
                )
            )
            if not (0 <= self._speaker_id < tts.num_speakers):
                raise ValueError(
                    f"speaker_id {self._speaker_id} out of range [0, {tts.num_speakers})"
                )
            return tts

        self._tts = await loop.run_in_executor(self._executor, _build)

    async def ensure_loaded(self) -> None:
        """Load the model when it is not loaded.

        Idempotent: concurrent callers share a single load. Raises if the
        client has been closed.
        """
        if self._closed or self._executor is None:
            raise RuntimeError("sherpa-onnx TTS client is closed")
        async with self._ensure_state_lock():
            if self._closed or self._executor is None:
                raise RuntimeError("sherpa-onnx TTS client is closed")
            await self._ensure_loaded_locked()

    async def warm_up(self) -> None:
        """Build the offline TTS object in the engine's worker thread.

        Idempotent: a second call is a no-op. Validates the speaker id once
        the object exists. Raises on build or validation error.
        """
        if self._closed or self._executor is None:
            return
        await self.ensure_loaded()

    async def _use_model(self) -> None:
        """Load the model if needed and mark one in-flight inference."""
        if self._closed or self._executor is None:
            raise RuntimeError("sherpa-onnx TTS client is closed")
        async with self._ensure_state_lock():
            if self._closed or self._executor is None:
                raise RuntimeError("sherpa-onnx TTS client is closed")
            await self._ensure_loaded_locked()
            async with self._inflight_cv:
                self._inflight += 1

    async def _release_inference(self) -> None:
        async with self._inflight_cv:
            self._inflight -= 1
            self._inflight_cv.notify_all()

    async def synthesize(self, request: TTSRequest) -> SynthesisResult:
        """Synthesize ``request.text`` to a mono 16-bit WAV."""
        if self._executor is None:
            raise RuntimeError("sherpa-onnx TTS client is closed")

        await self._use_model()

        try:
            text = request.text
            if text is None or text.strip() == "":
                raise ValueError("empty text")

            speed = self._resolve_speed(request.speed_factor)

            def _generate():
                assert self._tts is not None
                return self._tts.generate(text, sid=self._speaker_id, speed=speed)

            loop = asyncio.get_running_loop()
            start = time.monotonic()
            audio = await loop.run_in_executor(self._executor, _generate)
            latency_ms = (time.monotonic() - start) * 1000.0

            samples = np.asarray(audio.samples, dtype=np.float32)
            if samples.size == 0:
                raise RuntimeError("synthesis produced no audio")

            clipped = np.clip(samples, -1.0, 1.0)
            int_samples = np.round(clipped * 32767).astype(np.int16)

            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(audio.sample_rate)
                wf.writeframes(int_samples.tobytes())
            wav_bytes = buf.getvalue()
        finally:
            await self._release_inference()

        return SynthesisResult(
            audio=wav_bytes,
            content_type="audio/wav",
            latency_ms=latency_ms,
            output_format="wav",
            bytes_produced=len(wav_bytes),
        )

    async def _wait_inflight(self) -> None:
        async with self._inflight_cv:
            while self._inflight > 0:
                await self._inflight_cv.wait()

    async def unload(self) -> None:
        """Release the model while keeping the client usable.

        Waits for any in-flight inference to finish, drops the TTS object,
        and runs garbage collection in the engine thread. Idempotent and a
        no-op after the client has been closed.
        """
        if self._closed or self._executor is None or self._tts is None:
            return
        async with self._ensure_state_lock():
            if self._closed or self._executor is None or self._tts is None:
                return
            await self._wait_inflight()
            self._tts = None
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
                await self._wait_inflight()
                self._tts = None

        try:
            await asyncio.wait_for(_drop(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning(
                "sherpa-onnx TTS client: timeout waiting for in-flight inference "
                "during close; proceeding"
            )
            self._tts = None

        if self._executor is not None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self._executor, gc.collect)
            self._executor.shutdown(wait=False)
            self._executor = None
