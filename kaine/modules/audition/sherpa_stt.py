# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Local STT backend using sherpa-onnx Moonshine (offline recognizer)."""

from __future__ import annotations

import asyncio
import io
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from kaine.modules.audition.stt_client import TranscriptionResult


class SherpaMoonshineSTT:
    """Offline Moonshine STT client backed by sherpa-onnx."""

    def __init__(
        self,
        model_dir: Path | str,
        *,
        model_id: str = "moonshine-base-en",
        num_threads: int = 2,
        sherpa_module: Any | None = None,
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

        self._recognizer = so.OfflineRecognizer.from_moonshine_v2(
            encoder=str(self._dir / "encoder_model.ort"),
            decoder=str(self._dir / "decoder_model_merged.ort"),
            tokens=str(self._dir / "tokens.txt"),
            num_threads=self._num_threads,
        )
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="sherpa-stt"
        )

    @property
    def base_url(self) -> str:
        return f"sherpa-onnx://{self._model_id}"

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
            stream = self._recognizer.create_stream()
            stream.accept_waveform(rate, samples)
            self._recognizer.decode_stream(stream)
            return stream.result.text

        loop = asyncio.get_running_loop()
        start = time.monotonic()
        text = await loop.run_in_executor(self._executor, _decode)
        latency_ms = (time.monotonic() - start) * 1000.0

        return TranscriptionResult(
            text=text.strip(),
            model=self._model_id,
            latency_ms=latency_ms,
            raw={"sample_rate": rate, "samples": n},
        )

    async def aclose(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None
