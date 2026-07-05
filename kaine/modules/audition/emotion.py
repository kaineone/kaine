# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Speech emotion classification for AudioInput.

The default `Emotion2vecClassifier` lazy-imports `funasr` (an optional
dep listed under the `audio` extra in pyproject.toml). If funasr isn't
installed, the classifier degrades to neutral with a one-time warning
so AudioInput as a whole still produces transcriptions.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

log = logging.getLogger(__name__)


# Per build prompt §5.1: the categorical emotion set emotion2vec+ uses.
CATEGORIES: tuple[str, ...] = (
    "neutral",
    "happy",
    "sad",
    "angry",
    "surprised",
    "fearful",
    "disgusted",
)


@dataclass(frozen=True)
class EmotionResult:
    category: str
    confidence: float
    scores: dict[str, float]
    model: str
    latency_ms: float
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class EmotionClassifier(Protocol):
    @property
    def model_id(self) -> str: ...

    async def classify(
        self,
        audio_bytes: bytes,
        *,
        sample_rate: int,
    ) -> EmotionResult: ...

    async def shutdown(self) -> None: ...


DEFAULT_EMOTION_MODEL_ID = "emotion2vec/emotion2vec_plus_base"


class Emotion2vecClassifier:
    """Wrapper around emotion2vec+ via funasr.

    funasr is heavy and listed as an optional [audio] extra. If it
    isn't importable, this classifier degrades to a neutral result
    with confidence 0.0 and logs a single warning.
    """

    def __init__(
        self,
        model_id: str = DEFAULT_EMOTION_MODEL_ID,
        *,
        device: str = "cpu",
        hub: str = "hf",
    ) -> None:
        self._model_id = model_id
        self._device = device
        # funasr defaults to the ModelScope hub, where the HF-style id
        # `emotion2vec/emotion2vec_plus_base` 404s (it lives under the
        # `iic/` namespace there). Pin to HuggingFace so the configured
        # model_id resolves. Weights cache after first download; runtime
        # load is local.
        self._hub = hub
        self._model: Any = None
        self._funasr: Any = None
        self._funasr_available: Optional[bool] = None
        self._warned_missing = False

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def device(self) -> str:
        return self._device

    @property
    def funasr_available(self) -> Optional[bool]:
        return self._funasr_available

    async def load(self) -> None:
        if self._funasr_available is not None:
            return
        try:
            import funasr  # type: ignore[import-untyped]
        except Exception as exc:
            self._funasr_available = False
            if not self._warned_missing:
                log.warning(
                    "funasr not installed; emotion classifier degrades to "
                    "neutral. Install with `pip install -e .[audio]` to "
                    "enable emotion2vec+ recognition. (%s)",
                    exc,
                )
                self._warned_missing = True
            return
        import asyncio

        def _load_sync():
            return funasr.AutoModel(
                model=self._model_id,
                device=self._device,
                hub=self._hub,
                disable_update=True,
            )

        try:
            self._model = await asyncio.to_thread(_load_sync)
            self._funasr = funasr
            self._funasr_available = True
            log.info("emotion2vec+ loaded: %s on %s", self._model_id, self._device)
        except Exception:
            log.exception("emotion2vec+ load failed; degrading to neutral")
            self._funasr_available = False

    async def classify(
        self,
        audio_bytes: bytes,
        *,
        sample_rate: int,
    ) -> EmotionResult:
        await self.load()
        start = time.monotonic()
        if not self._funasr_available or self._model is None:
            return EmotionResult(
                category="neutral",
                confidence=0.0,
                scores={c: (1.0 if c == "neutral" else 0.0) for c in CATEGORIES},
                model=self._model_id,
                latency_ms=(time.monotonic() - start) * 1000.0,
                raw={"degraded": True},
            )
        import asyncio
        import io

        def _infer_sync() -> dict[str, Any]:
            # funasr's AutoModel.generate accepts an audio file path or
            # raw audio. The signature varies across funasr versions;
            # we pass bytes via an io.BytesIO. If the model does not
            # support BytesIO, we try a numpy array decoded in-memory —
            # we NEVER write raw audio to disk (zero-persistence invariant).
            import numpy as np

            try:
                result = self._model.generate(
                    input=io.BytesIO(audio_bytes),
                    granularity="utterance",
                    extract_embedding=False,
                )
            except Exception:
                # Fall back to a float32 numpy array decoded in memory.
                # Raw int16 PCM assumed when the WAV header decode fails;
                # the array is released as soon as generate() returns.
                try:
                    import wave
                    with wave.open(io.BytesIO(audio_bytes), "rb") as _wf:
                        _pcm = _wf.readframes(_wf.getnframes())
                    _samples = np.frombuffer(_pcm, dtype=np.int16).astype(np.float32) / 32768.0
                except Exception:
                    _samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                result = self._model.generate(
                    input=_samples,
                    granularity="utterance",
                    extract_embedding=False,
                )
            # Normalize funasr's output into our shape. The exact format
            # is `[{"key": ..., "labels": [...], "scores": [...]}]`.
            return result

        try:
            raw = await asyncio.to_thread(_infer_sync)
        except Exception as exc:
            log.warning("emotion2vec inference failed: %s; returning neutral", exc)
            return EmotionResult(
                category="neutral",
                confidence=0.0,
                scores={c: (1.0 if c == "neutral" else 0.0) for c in CATEGORIES},
                model=self._model_id,
                latency_ms=(time.monotonic() - start) * 1000.0,
                raw={"inference_failed": True, "error": str(exc)},
            )
        item = raw[0] if isinstance(raw, list) and raw else {}
        labels = item.get("labels", []) or []
        scores_list = item.get("scores", []) or []
        scores: dict[str, float] = {}
        for label, score in zip(labels, scores_list):
            normalized = _normalize_label(str(label))
            if normalized in CATEGORIES:
                scores[normalized] = float(score)
        # Fill any missing categories with 0.
        for c in CATEGORIES:
            scores.setdefault(c, 0.0)
        category = max(scores.items(), key=lambda t: t[1])[0]
        confidence = scores[category]
        return EmotionResult(
            category=category,
            confidence=confidence,
            scores=scores,
            model=self._model_id,
            latency_ms=(time.monotonic() - start) * 1000.0,
            raw={"funasr": item},
        )

    async def shutdown(self) -> None:
        self._model = None


def _normalize_label(label: str) -> str:
    """funasr returns labels like '/happy/' or 'Happy'; normalize to our set."""
    s = label.strip().strip("/").lower()
    aliases = {
        "happy": "happy",
        "joy": "happy",
        "sad": "sad",
        "sadness": "sad",
        "angry": "angry",
        "anger": "angry",
        "surprised": "surprised",
        "surprise": "surprised",
        "fearful": "fearful",
        "fear": "fearful",
        "disgusted": "disgusted",
        "disgust": "disgusted",
        "neutral": "neutral",
        "calm": "neutral",
        "other": "neutral",
        "unk": "neutral",
    }
    return aliases.get(s, s if s in CATEGORIES else "neutral")


class FakeEmotionClassifier:
    """Scriptable stand-in for tests."""

    def __init__(
        self,
        model_id: str = "fake/emotion",
        results: Optional[list[EmotionResult]] = None,
        latency_ms: float = 2.0,
    ) -> None:
        self._model_id = model_id
        self.results: list[EmotionResult] = list(results or [])
        self.calls = 0
        self._latency_ms = float(latency_ms)
        self.shutdown_called = False

    @property
    def model_id(self) -> str:
        return self._model_id

    async def classify(
        self,
        audio_bytes: bytes,
        *,
        sample_rate: int,
    ) -> EmotionResult:
        self.calls += 1
        if self.results:
            return self.results.pop(0)
        return EmotionResult(
            category="neutral",
            confidence=1.0,
            scores={c: (1.0 if c == "neutral" else 0.0) for c in CATEGORIES},
            model=self._model_id,
            latency_ms=self._latency_ms,
            raw={"fake": True},
        )

    async def shutdown(self) -> None:
        self.shutdown_called = True
