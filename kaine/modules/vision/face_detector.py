# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Face detection and identity-embedding extraction (YuNet + SFace).

YuNet detects faces and returns bounding boxes with 5-point landmarks
(MIT).  SFace extracts a 128-dim identity embedding from each aligned
face crop (Apache 2.0).

The face crop is also used downstream by the expression classifier and
gaze estimator, so ``detect()`` returns it alongside the embedding.
"""

from __future__ import annotations

import asyncio
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

FACE_EMBEDDING_DIM = 128


@dataclass(frozen=True)
class DetectedFace:
    """One detected face with its identity embedding and crop."""

    bbox: tuple[float, float, float, float]  # x, y, w, h
    landmarks: np.ndarray  # shape (5, 2): right_eye, left_eye, nose, right_mouth, left_mouth
    confidence: float
    embedding: list[float] | None  # 128-dim SFace embedding, None on failure
    crop: np.ndarray | None  # aligned face crop (BGR), for expression/gaze


@dataclass(frozen=True)
class FaceDetectionResult:
    """Result of face detection on a single frame."""

    faces: list[DetectedFace]
    degraded: bool


def _empty_result() -> FaceDetectionResult:
    return FaceDetectionResult(faces=[], degraded=False)


def _degraded_result() -> FaceDetectionResult:
    return FaceDetectionResult(faces=[], degraded=True)


class FaceDetector:
    """Face detector backed by YuNet + SFace, loaded lazily."""

    _CLOSE_TIMEOUT_S: float = 5.0

    def __init__(
        self,
        detector_path: Path | str,
        recognizer_path: Path | str | None = None,
        *,
        input_size: tuple[int, int] = (320, 320),
        score_threshold: float = 0.7,
        nms_threshold: float = 0.3,
        top_k: int = 5000,
    ) -> None:
        self._detector_path = Path(detector_path)
        self._recognizer_path = Path(recognizer_path) if recognizer_path else None
        self._input_size = input_size
        self._score_threshold = score_threshold
        self._nms_threshold = nms_threshold
        self._top_k = top_k

        self._detector: Any = None
        self._recognizer: Any = None
        self._executor: ThreadPoolExecutor | None = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="face-detect"
        )
        self._closed = False
        self._state_lock: asyncio.Lock | None = None

    @property
    def loaded(self) -> bool:
        return not self._closed and self._detector is not None

    def _ensure_state_lock(self) -> asyncio.Lock:
        if self._state_lock is None:
            self._state_lock = asyncio.Lock()
        return self._state_lock

    def _build(self) -> tuple[Any, Any]:
        import cv2

        detector = cv2.FaceDetectorYN.create(
            str(self._detector_path),
            "",
            self._input_size,
            self._score_threshold,
            self._nms_threshold,
            self._top_k,
        )
        recognizer = None
        if self._recognizer_path is not None:
            recognizer = cv2.FaceRecognizerSF.create(
                str(self._recognizer_path), ""
            )
        return detector, recognizer

    async def _ensure_loaded(self) -> None:
        if self._detector is not None:
            return
        if self._closed or self._executor is None:
            raise RuntimeError("face detector is closed")
        loop = asyncio.get_running_loop()
        detector, recognizer = await loop.run_in_executor(
            self._executor, self._build
        )
        if self._closed:
            raise RuntimeError("face detector is closed")
        self._detector = detector
        self._recognizer = recognizer

    async def warm_up(self) -> None:
        if self._closed or self._executor is None:
            raise RuntimeError("face detector is closed")
        async with self._ensure_state_lock():
            if self._closed or self._executor is None:
                raise RuntimeError("face detector is closed")
            await self._ensure_loaded()

    async def unload(self) -> None:
        """Release loaded models. Next detect() call will reload."""
        async with self._ensure_state_lock():
            self._detector = None
            self._recognizer = None
        logger.info("Face detector unloaded")

    async def detect(
        self, frame: np.ndarray
    ) -> FaceDetectionResult:
        if self._closed or self._executor is None:
            raise RuntimeError("face detector is closed")

        try:
            async with self._ensure_state_lock():
                if self._closed or self._executor is None:
                    raise RuntimeError("face detector is closed")
                await self._ensure_loaded()
                detector = self._detector
                recognizer = self._recognizer
        except Exception:
            logger.warning("face detector failed to load", exc_info=True)
            return _degraded_result()

        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                self._executor,
                lambda: self._detect_sync(frame, detector, recognizer),
            )
        except Exception:
            logger.warning("face detection failed", exc_info=True)
            return _degraded_result()
        return result

    @staticmethod
    def _detect_sync(
        frame: np.ndarray,
        detector: Any,
        recognizer: Any,
    ) -> FaceDetectionResult:
        if frame.size == 0:
            return _empty_result()

        h, w = frame.shape[:2]
        detector.setInputSize((w, h))
        _, raw_faces = detector.detect(frame)

        if raw_faces is None or len(raw_faces) == 0:
            return _empty_result()

        faces: list[DetectedFace] = []
        for face_row in raw_faces:
            x, y, fw, fh = float(face_row[0]), float(face_row[1]), float(face_row[2]), float(face_row[3])
            landmarks = np.array([
                [float(face_row[4]), float(face_row[5])],    # right eye
                [float(face_row[6]), float(face_row[7])],    # left eye
                [float(face_row[8]), float(face_row[9])],    # nose
                [float(face_row[10]), float(face_row[11])],  # right mouth
                [float(face_row[12]), float(face_row[13])],  # left mouth
            ], dtype=np.float32)
            confidence = float(face_row[14])

            crop = None
            embedding = None
            if recognizer is not None:
                try:
                    crop = recognizer.alignCrop(frame, face_row)
                    raw_feat = recognizer.feature(crop)
                    feat_list = raw_feat.flatten().tolist()
                    if len(feat_list) > 0 and all(math.isfinite(v) for v in feat_list):
                        embedding = feat_list
                except Exception:
                    logger.debug("SFace embedding failed for one face", exc_info=True)

            faces.append(DetectedFace(
                bbox=(x, y, fw, fh),
                landmarks=landmarks,
                confidence=confidence,
                embedding=embedding,
                crop=crop,
            ))

        return FaceDetectionResult(faces=faces, degraded=False)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._detector = None
        self._recognizer = None
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None
