# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Facial expression classification (OpenCV Zoo FER model).

Classifies an aligned face crop (from YuNet/SFace) into 7 expression
categories: angry, disgust, fearful, happy, neutral, sad, surprised.
This is the pSTS analogue: changeable facial features feeding the
emotion system, not the identity system.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from kaine.residency.router import ResidencyRouter

logger = logging.getLogger(__name__)

EXPRESSION_CATEGORIES: tuple[str, ...] = (
    "angry",
    "disgust",
    "fearful",
    "happy",
    "neutral",
    "sad",
    "surprised",
)


@dataclass(frozen=True)
class ExpressionResult:
    """Expression classification for one face."""

    label: str
    scores: dict[str, float]
    confidence: float


class FaceExpressionClassifier:
    """Expression classifier backed by the OpenCV Zoo FER ONNX model."""

    def __init__(
        self,
        model_path: Path | str,
        *,
        input_size: tuple[int, int] = (112, 112),
        router: ResidencyRouter | None = None,
    ) -> None:
        self._model_path = Path(model_path)
        self._input_size = input_size
        self._net: Any = None
        self._executor: ThreadPoolExecutor | None = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="face-expr"
        )
        self._closed = False
        self._state_lock: asyncio.Lock | None = None
        self._router = router
        self._residency_name = "face_expression"

    @property
    def loaded(self) -> bool:
        return not self._closed and self._net is not None

    def _ensure_state_lock(self) -> asyncio.Lock:
        if self._state_lock is None:
            self._state_lock = asyncio.Lock()
        return self._state_lock

    def _build(self) -> Any:
        import cv2

        net = cv2.dnn.readNetFromONNX(str(self._model_path))
        return net

    async def _ensure_loaded(self) -> None:
        if self._net is not None:
            return
        if self._closed or self._executor is None:
            raise RuntimeError("expression classifier is closed")
        if self._router:
            await self._router.before_load(self._residency_name)
        loop = asyncio.get_running_loop()
        net = await loop.run_in_executor(self._executor, self._build)
        if self._closed:
            raise RuntimeError("expression classifier is closed")
        self._net = net
        if self._router:
            self._router.after_load(self._residency_name)

    async def warm_up(self) -> None:
        if self._closed or self._executor is None:
            raise RuntimeError("expression classifier is closed")
        async with self._ensure_state_lock():
            if self._closed or self._executor is None:
                raise RuntimeError("expression classifier is closed")
            await self._ensure_loaded()

    async def unload(self) -> None:
        """Release loaded model. Next classify() call will reload."""
        if self._router:
            self._router.before_unload(self._residency_name)
        async with self._ensure_state_lock():
            self._net = None
        if self._router:
            self._router.after_unload(self._residency_name)
        logger.info("Expression classifier unloaded")

    async def classify(self, face_crop: np.ndarray) -> ExpressionResult | None:
        """Classify the expression in an aligned face crop.

        Returns None if the crop is empty or classification fails.
        """
        if self._closed or self._executor is None:
            raise RuntimeError("expression classifier is closed")
        if face_crop is None or face_crop.size == 0:
            return None

        try:
            async with self._ensure_state_lock():
                if self._closed or self._executor is None:
                    raise RuntimeError("expression classifier is closed")
                await self._ensure_loaded()
                net = self._net
        except Exception:
            logger.warning("expression classifier failed to load", exc_info=True)
            return None

        if self._router:
            self._router.record_use(self._residency_name)
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                self._executor,
                lambda: self._classify_sync(face_crop, net),
            )
        except Exception:
            logger.warning("expression classification failed", exc_info=True)
            return None
        return result

    def _classify_sync(
        self, face_crop: np.ndarray, net: Any
    ) -> ExpressionResult | None:
        import cv2

        w, h = self._input_size
        blob = cv2.dnn.blobFromImage(
            face_crop, 1.0 / 255.0, (w, h), (0, 0, 0), swapRB=True
        )
        # OpenCV Zoo FER expects (x/255 - 0.5) / 0.5 per channel.
        blob = (blob - 0.5) / 0.5
        net.setInput(blob)
        output = net.forward()

        if output is None or output.size == 0:
            return None

        logits = output.flatten()
        if len(logits) != len(EXPRESSION_CATEGORIES):
            logger.warning(
                "FER model returned %d outputs, expected %d",
                len(logits),
                len(EXPRESSION_CATEGORIES),
            )
            return None

        exp = np.exp(logits - np.max(logits))
        probs = exp / exp.sum()

        scores = {
            cat: float(probs[i]) for i, cat in enumerate(EXPRESSION_CATEGORIES)
        }
        best_idx = int(np.argmax(probs))
        label = EXPRESSION_CATEGORIES[best_idx]
        confidence = float(probs[best_idx])

        return ExpressionResult(label=label, scores=scores, confidence=confidence)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._net = None
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None
