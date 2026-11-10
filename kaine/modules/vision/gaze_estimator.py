# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Gaze estimation from face landmarks or a learned model.

Two backends, config-selectable:
  1. ``landmark`` — solvePnP on YuNet's 5-point landmarks, producing
     yaw/pitch.  Zero model cost; coarser accuracy.
  2. ``learned`` — MobileNet V2 gaze model (~10 MB ONNX, MIT).  Produces
     per-face yaw, pitch at higher accuracy.

Both produce a ``GazeResult`` with yaw, pitch (radians) and a
``mutual_gaze`` flag (true when the face points roughly at the camera).
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

MUTUAL_GAZE_THRESHOLD_DEG = 15.0

# 3D model points for a generic face (in mm, centred on nose tip).
# These correspond to: right eye, left eye, nose tip, right mouth corner,
# left mouth corner — matching YuNet's landmark order.
_MODEL_POINTS_3D = np.array(
    [
        [-30.0, -30.0, -30.0],  # right eye
        [30.0, -30.0, -30.0],  # left eye
        [0.0, 0.0, 0.0],  # nose tip
        [-20.0, 30.0, -15.0],  # right mouth corner
        [20.0, 30.0, -15.0],  # left mouth corner
    ],
    dtype=np.float64,
)


@dataclass(frozen=True)
class GazeResult:
    """Gaze estimate for one face."""

    yaw: float  # radians, positive = looking right
    pitch: float  # radians, positive = looking down
    mutual_gaze: bool  # face roughly pointing at camera


def _is_mutual(yaw: float, pitch: float) -> bool:
    threshold = math.radians(MUTUAL_GAZE_THRESHOLD_DEG)
    return abs(yaw) < threshold and abs(pitch) < threshold


class LandmarkGazeEstimator:
    """Head-pose gaze from solvePnP on 5-point landmarks.  No model cost."""

    async def estimate(
        self, landmarks: np.ndarray, frame_shape: tuple[int, ...]
    ) -> GazeResult | None:
        """Estimate gaze from 5 face landmarks (shape (5, 2))."""
        if landmarks is None or landmarks.shape != (5, 2):
            return None
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._estimate_sync, landmarks, frame_shape
        )

    @staticmethod
    def _estimate_sync(
        landmarks: np.ndarray, frame_shape: tuple[int, ...]
    ) -> GazeResult | None:
        import cv2

        h, w = frame_shape[:2]
        focal_length = float(w)
        cx, cy = w / 2.0, h / 2.0
        camera_matrix = np.array(
            [[focal_length, 0.0, cx], [0.0, focal_length, cy], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )
        dist_coeffs = np.zeros((4, 1), dtype=np.float64)

        image_points = landmarks.astype(np.float64)
        success, rvec, _tvec = cv2.solvePnP(
            _MODEL_POINTS_3D,
            image_points,
            camera_matrix,
            dist_coeffs,
            flags=cv2.SOLVEPNP_SQPNP,
        )
        if not success:
            return None

        rmat, _ = cv2.Rodrigues(rvec)
        # Decompose rotation matrix to Euler angles.
        sy = math.sqrt(rmat[0, 0] ** 2 + rmat[1, 0] ** 2)
        if sy > 1e-6:
            yaw = math.atan2(rmat[1, 0], rmat[0, 0])
            pitch = math.atan2(-rmat[2, 0], sy)
        else:
            yaw = math.atan2(-rmat[1, 2], rmat[1, 1])
            pitch = math.atan2(-rmat[2, 0], sy)

        return GazeResult(yaw=yaw, pitch=pitch, mutual_gaze=_is_mutual(yaw, pitch))

    async def aclose(self) -> None:
        pass


class LearnedGazeEstimator:
    """Gaze estimation via a MobileNet V2 ONNX model."""

    def __init__(
        self,
        model_path: Path | str,
        *,
        input_size: tuple[int, int] = (448, 448),
    ) -> None:
        self._model_path = Path(model_path)
        self._input_size = input_size
        self._net: Any = None
        self._executor: ThreadPoolExecutor | None = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="gaze-est"
        )
        self._closed = False
        self._state_lock: asyncio.Lock | None = None

    @property
    def loaded(self) -> bool:
        return not self._closed and self._net is not None

    def _ensure_state_lock(self) -> asyncio.Lock:
        if self._state_lock is None:
            self._state_lock = asyncio.Lock()
        return self._state_lock

    def _build(self) -> Any:
        import cv2

        return cv2.dnn.readNetFromONNX(str(self._model_path))

    async def _ensure_loaded(self) -> None:
        if self._net is not None:
            return
        if self._closed or self._executor is None:
            raise RuntimeError("gaze estimator is closed")
        loop = asyncio.get_running_loop()
        net = await loop.run_in_executor(self._executor, self._build)
        if self._closed:
            raise RuntimeError("gaze estimator is closed")
        self._net = net

    async def warm_up(self) -> None:
        if self._closed or self._executor is None:
            raise RuntimeError("gaze estimator is closed")
        async with self._ensure_state_lock():
            if self._closed or self._executor is None:
                raise RuntimeError("gaze estimator is closed")
            await self._ensure_loaded()

    async def estimate(
        self,
        landmarks: np.ndarray,  # unused by learned backend
        frame_shape: tuple[int, ...],  # unused
        *,
        face_crop: np.ndarray | None = None,
    ) -> GazeResult | None:
        """Estimate gaze from a face crop via the learned model."""
        if face_crop is None or face_crop.size == 0:
            return None
        if self._closed or self._executor is None:
            raise RuntimeError("gaze estimator is closed")

        try:
            async with self._ensure_state_lock():
                if self._closed or self._executor is None:
                    raise RuntimeError("gaze estimator is closed")
                await self._ensure_loaded()
                net = self._net
        except Exception:
            logger.warning("gaze estimator failed to load", exc_info=True)
            return None

        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                self._executor,
                lambda: self._estimate_sync(face_crop, net),
            )
        except Exception:
            logger.warning("gaze estimation failed", exc_info=True)
            return None

    @staticmethod
    def _bin_to_angle(logits: np.ndarray) -> float:
        """Convert (1, 90) classification logits to a degree angle.

        Formula: (sum(softmax(logits) * arange(90)) * 4 - 180).
        Result is in degrees; caller converts to radians.
        """
        v = logits.flatten().astype(np.float64)
        exp = np.exp(v - v.max())
        probs = exp / exp.sum()
        idx = np.arange(len(probs), dtype=np.float64)
        return float(np.dot(probs, idx) * 4.0 - 180.0)

    def _estimate_sync(
        self, face_crop: np.ndarray, net: Any
    ) -> GazeResult | None:
        import cv2

        w, h = self._input_size
        blob = cv2.dnn.blobFromImage(
            face_crop, 1.0 / 255.0, (w, h), (0, 0, 0), swapRB=True
        )
        net.setInput(blob)
        outputs = net.forward(["yaw", "pitch"])
        if outputs is None or len(outputs) < 2:
            return None

        yaw_deg = self._bin_to_angle(outputs[0])
        pitch_deg = self._bin_to_angle(outputs[1])

        if not (math.isfinite(yaw_deg) and math.isfinite(pitch_deg)):
            return None

        yaw = math.radians(yaw_deg)
        pitch = math.radians(pitch_deg)
        return GazeResult(yaw=yaw, pitch=pitch, mutual_gaze=_is_mutual(yaw, pitch))

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._net = None
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None
