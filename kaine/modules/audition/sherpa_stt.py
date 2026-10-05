# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Local STT backend using sherpa-onnx Moonshine (offline recognizer).

The client supports reversible unload: call unload() to release model memory
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
from pathlib import Path
from typing import Any

import numpy as np

from kaine import speech_manifest
from kaine.modules.audition.stt_client import TranscriptionResult

logger = logging.getLogger(__name__)


class SherpaMoonshineSTT:
    """Offline Moonshine STT client backed by sherpa-onnx.

    Models can be released with unload() and restored with ensure_loaded()
    without rebuilding the client.
    """

    def __init__(
        self,
        model_dir: Path | str,
        *,
        model_id: str = "moonshine-base-en",
        num_threads: int = 2,
        sherpa_module: Any | None = None,
        _verify: bool = True,
    ) -> None:
        self._model_id = model_id
        self._dir = Path(model_dir)
        self._num_threads = int(num_threads)

        required = ("encoder_model.ort", "decoder_model_merged.ort", "tokens.txt")
        missing = [f for f in required if not (self._dir / f).exists()]
        if missing:
            raise FileNotFoundError(
                f"missing model file(s): {missing}. "
                f"Run: python -m kaine.setup.speech_models --stt {model_id}"
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
        self._recognizer: Any | None = None
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="sherpa-stt"
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
        return not self._closed and self._recognizer is not None

    def _ensure_state_lock(self) -> asyncio.Lock:
        if self._state_lock is None:
            self._state_lock = asyncio.Lock()
        return self._state_lock

    async def _ensure_loaded_locked(self) -> None:
        """Load the recognizer while the state lock is held."""
        if self._recognizer is not None:
            return
        if self._closed or self._executor is None:
            raise RuntimeError("sherpa-onnx STT client is closed")
        loop = asyncio.get_running_loop()
        self._recognizer = await loop.run_in_executor(
            self._executor,
            self._sherpa_module.OfflineRecognizer.from_moonshine_v2,
            str(self._dir / "encoder_model.ort"),
            str(self._dir / "decoder_model_merged.ort"),
            str(self._dir / "tokens.txt"),
            self._num_threads,
        )

    async def ensure_loaded(self) -> None:
        """Load the model when it is not loaded.

        Idempotent: concurrent callers share a single load. Raises if the
        client has been closed.
        """
        if self._closed or self._executor is None:
            raise RuntimeError("sherpa-onnx STT client is closed")
        async with self._ensure_state_lock():
            if self._closed or self._executor is None:
                raise RuntimeError("sherpa-onnx STT client is closed")
            await self._ensure_loaded_locked()

    async def warm_up(self) -> None:
        """Build the offline recogniser in the engine's worker thread.

        Idempotent: a second call is a no-op. Raises on build error.
        """
        if self._closed or self._executor is None:
            return
        await self.ensure_loaded()

    async def _use_model(self) -> None:
        """Load the model if needed and mark one in-flight inference.

        This holds the state lock only long enough to load and increment the
        in-flight counter, so unload() can wait for running inference without
        blocking the event loop.
        """
        if self._closed or self._executor is None:
            raise RuntimeError("sherpa-onnx STT client is closed")
        async with self._ensure_state_lock():
            if self._closed or self._executor is None:
                raise RuntimeError("sherpa-onnx STT client is closed")
            await self._ensure_loaded_locked()
            async with self._inflight_cv:
                self._inflight += 1

    async def _release_inference(self) -> None:
        async with self._inflight_cv:
            self._inflight -= 1
            self._inflight_cv.notify_all()

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        sample_rate: int,
        model: str,
        filename: str = "audio.wav",
    ) -> TranscriptionResult:
        """Decode a 16-bit PCM WAV to text using the loaded Moonshine model."""
        if self._executor is None:
            raise RuntimeError("sherpa-onnx STT client is closed")

        await self._use_model()

        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                if wf.getsampwidth() != 2:
                    raise ValueError(
                        f"unsupported sample width {wf.getsampwidth()}; "
                        "only 16-bit PCM WAV is supported"
                    )
                nchannels = wf.getnchannels()
                rate = wf.getframerate()
                nframes = wf.getnframes()
                if nframes == 0:
                    return TranscriptionResult(
                        text="",
                        model=self._model_id,
                        latency_ms=0.0,
                        raw={"sample_rate": rate, "samples": 0},
                    )
                pcm = wf.readframes(nframes)

            arr = np.frombuffer(pcm, dtype=np.int16)
            if nchannels > 1:
                arr = arr[0::nchannels]
            samples = arr.astype(np.float32) / 32768.0
            n = len(samples)

            def _decode() -> str:
                assert self._recognizer is not None
                stream = self._recognizer.create_stream()
                stream.accept_waveform(rate, samples)
                self._recognizer.decode_stream(stream)
                return stream.result.text

            loop = asyncio.get_running_loop()
            start = time.monotonic()
            text = await loop.run_in_executor(self._executor, _decode)
            latency_ms = (time.monotonic() - start) * 1000.0
        finally:
            await self._release_inference()

        return TranscriptionResult(
            text=text.strip(),
            model=self._model_id,
            latency_ms=latency_ms,
            raw={"sample_rate": rate, "samples": n},
        )

    async def _wait_inflight(self) -> None:
        async with self._inflight_cv:
            while self._inflight > 0:
                await self._inflight_cv.wait()

    async def unload(self) -> None:
        """Release the model while keeping the client usable.

        Waits for any in-flight inference to finish, drops the recognizer, and
        runs garbage collection in the engine thread. Idempotent and a no-op
        after the client has been closed.
        """
        if self._closed or self._executor is None or self._recognizer is None:
            return
        async with self._ensure_state_lock():
            if self._closed or self._executor is None or self._recognizer is None:
                return
            await self._wait_inflight()
            self._recognizer = None
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
                self._recognizer = None

        try:
            await asyncio.wait_for(_drop(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning(
                "sherpa-onnx STT client: timeout waiting for in-flight inference "
                "during close; proceeding"
            )
            self._recognizer = None

        if self._executor is not None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self._executor, gc.collect)
            self._executor.shutdown(wait=False)
            self._executor = None
