# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Speech emotion classification for Audition.

The default `Emotion2vecClassifier` lazy-imports `funasr` (an optional
dep listed under the `audio` extra in pyproject.toml). If funasr isn't
installed, the classifier degrades to neutral with a one-time warning
so Audition as a whole still produces transcriptions.
"""
from __future__ import annotations

import asyncio
import gc
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from kaine.residency.inflight import InflightGate

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


class NullEmotionClassifier:
    """Vocal-emotion disabled — the Tier-0/Tier-1 case (openspec runtime-backends).

    emotion2vec+ (funasr) has no clean edge port, so vocal emotion is a
    Tier-2-only faculty; below it the classifier is *explicitly* disabled rather
    than silently loading a heavy model. Selected by setting
    ``[audition].emotion_model_id = ""``. It satisfies the same
    :class:`EmotionClassifier` protocol and always returns a neutral,
    zero-confidence result tagged ``disabled`` — so Audition still transcribes
    speech; it simply reports no vocal affect, and reports that honestly (a
    removed capability is surfaced, not silently faked as real neutrality).
    """

    MODEL_ID = ""

    @property
    def model_id(self) -> str:
        return self.MODEL_ID

    async def classify(
        self,
        audio_bytes: bytes,
        *,
        sample_rate: int,
    ) -> EmotionResult:
        return EmotionResult(
            category="neutral",
            confidence=0.0,
            scores={c: (1.0 if c == "neutral" else 0.0) for c in CATEGORIES},
            model="disabled",
            latency_ms=0.0,
            raw={"disabled": True},
        )

    async def shutdown(self) -> None:
        return


class Emotion2vecClassifier:
    """Wrapper around emotion2vec+ via funasr.

    funasr is heavy and listed as an optional [audio] extra. If it
    isn't importable, the classifier degrades to a neutral result
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
        self._load_failed: bool = False
        self._warned_missing = False
        self._load_lock: Optional[asyncio.Lock] = None
        self._gate = InflightGate()

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def device(self) -> str:
        return self._device

    @property
    def funasr_available(self) -> Optional[bool]:
        return self._funasr_available

    @property
    def loaded(self) -> bool:
        """True while the emotion2vec model is held."""
        return self._model is not None

    def _lock(self) -> asyncio.Lock:
        if self._load_lock is None:
            self._load_lock = asyncio.Lock()
        assert self._load_lock is not None
        return self._load_lock

    async def _ensure_loaded_locked(self) -> None:
        if self._model is not None:
            return
        if self._funasr_available is False or self._load_failed:
            return
        if self._funasr_available is None:
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
            self._funasr = funasr
            self._funasr_available = True

        def _load_sync():
            kwargs = {"disable_update": True}
            if not self._device.startswith("cuda"):
                kwargs["fp16"] = False
                kwargs["bf16"] = False
            return self._funasr.AutoModel(
                model=self._model_id,
                device=self._device,
                hub=self._hub,
                **kwargs,
            )

        try:
            self._model = await asyncio.to_thread(_load_sync)
            if not self._device.startswith("cuda"):
                import torch

                inner = getattr(self._model, "model", None)
                if inner is None:
                    log.warning(
                        "funasr AutoModel has no .model attribute; "
                        "cannot verify float32 weights on %s",
                        self._device,
                    )
                else:
                    # Unconditionally cast every floating-point parameter and
                    # buffer to float32, then verify no half/bfloat16 state remains.
                    # This closes the default-dtype race with other modules whose
                    # model construction can briefly change the process-wide
                    # default dtype.
                    inner.float()
                    non_float32 = [
                        (name, p.dtype)
                        for name, p in inner.named_parameters()
                        if p.dtype.is_floating_point and p.dtype != torch.float32
                    ] + [
                        (name, b.dtype)
                        for name, b in inner.named_buffers()
                        if b.dtype.is_floating_point and b.dtype != torch.float32
                    ]
                    if non_float32:
                        log.error(
                            "emotion2vec+ model still contains non-float32 tensors "
                            "after .float() on %s: %s; treating load as failed",
                            self._device,
                            non_float32,
                        )
                        self._funasr_available = False
                        self._model = None
                        return
            log.info("emotion2vec+ loaded: %s on %s", self._model_id, self._device)
        except Exception:
            log.exception("emotion2vec+ load failed; degrading to neutral")
            self._load_failed = True
            self._funasr_available = False
            self._model = None

    async def ensure_loaded(self) -> None:
        if self._model is not None:
            return
        if self._funasr_available is False or self._load_failed:
            return
        lock = self._lock()
        async with lock:
            await self._ensure_loaded_locked()

    async def load(self) -> None:
        return await self.ensure_loaded()

    async def unload(self) -> None:
        """Release the underlying model. Idempotent."""
        lock = self._lock()
        async with lock:
            await self._gate.wait_idle()
            self._model = None
        await asyncio.to_thread(gc.collect)
        if self._device.startswith("cuda"):
            import torch

            torch.cuda.empty_cache()

    async def shutdown(self) -> None:
        await self.unload()

    async def classify(
        self,
        audio_bytes: bytes,
        *,
        sample_rate: int,
    ) -> EmotionResult:
        lock = self._lock()

        async with lock:
            await self._ensure_loaded_locked()
            if self._funasr_available is False or self._load_failed or self._model is None:
                return self._degraded_result()
            local_model = self._model
            ticket = self._gate.admit()

        start = time.monotonic()

        def _infer_sync() -> dict[str, Any]:
            # funasr's AutoModel.generate accepts an audio file path or
            # raw audio. The signature varies across funasr versions;
            # we pass bytes via an io.BytesIO. If the model does not
            # support BytesIO, we try a numpy array decoded in-memory —
            # we NEVER write raw audio to disk (zero-persistence invariant).
            import io

            import numpy as np

            try:
                result = local_model.generate(
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
                result = local_model.generate(
                    input=_samples,
                    granularity="utterance",
                    extract_embedding=False,
                )
            # Normalize funasr's output into our shape. The exact format
            # is `[{"key": ..., "labels": [...], "scores": [...]}]`.
            return result

        # run() owns the ticket from here: it releases it however the call ends.
        try:
            raw = await self._gate.run(ticket, None, _infer_sync)
        except Exception as exc:
            log.warning("emotion2vec inference failed: %s; returning neutral", exc)
            return self._inference_failed_result(start, exc)

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

    def _degraded_result(self) -> EmotionResult:
        return EmotionResult(
            category="neutral",
            confidence=0.0,
            scores={c: (1.0 if c == "neutral" else 0.0) for c in CATEGORIES},
            model=self._model_id,
            latency_ms=0.0,
            raw={"degraded": True},
        )

    def _inference_failed_result(self, start: float, exc: Exception) -> EmotionResult:
        return EmotionResult(
            category="neutral",
            confidence=0.0,
            scores={c: (1.0 if c == "neutral" else 0.0) for c in CATEGORIES},
            model=self._model_id,
            latency_ms=(time.monotonic() - start) * 1000.0,
            raw={"inference_failed": True, "error": str(exc)},
        )


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
