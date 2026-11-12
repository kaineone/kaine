# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Face detection, expression classification, and gaze estimation tests.

Fully offline: cv2 models are replaced by fake objects.
"""

from __future__ import annotations

import numpy as np
import pytest

from kaine.modules.vision.face_detector import (
    FACE_EMBEDDING_DIM,
    DetectedFace,
    FaceDetectionResult,
    FaceDetector,
)
from kaine.modules.vision.face_expression import (
    EXPRESSION_CATEGORIES,
    ExpressionResult,
    FaceExpressionClassifier,
)
from kaine.modules.vision.gaze_estimator import (
    GazeResult,
    LandmarkGazeEstimator,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_frame(h: int = 480, w: int = 640) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def _fake_face_row() -> np.ndarray:
    """A single face row matching YuNet's 15-column output."""
    return np.array(
        [
            100, 100, 80, 80,  # bbox: x, y, w, h
            120, 115,  # right eye
            160, 115,  # left eye
            140, 135,  # nose
            125, 155,  # right mouth
            155, 155,  # left mouth
            0.95,  # confidence
        ],
        dtype=np.float32,
    )


def _fake_faces_matrix(n: int = 1) -> np.ndarray:
    return np.stack([_fake_face_row() for _ in range(n)])


# ---------------------------------------------------------------------------
# FaceDetector
# ---------------------------------------------------------------------------


class _FakeYuNet:
    """Stands in for cv2.FaceDetectorYN."""

    def __init__(self, faces: np.ndarray | None = None) -> None:
        self._faces = faces
        self.input_size_set: tuple[int, int] | None = None

    def setInputSize(self, size):  # noqa: N802
        self.input_size_set = size

    def detect(self, _image):
        if self._faces is None:
            return 1, None
        return 1, self._faces


class _FakeSFace:
    """Stands in for cv2.FaceRecognizerSF."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail

    def alignCrop(self, src_img, face_box):  # noqa: N802
        if self._fail:
            raise RuntimeError("SFace align failed")
        return np.zeros((112, 112, 3), dtype=np.uint8)

    def feature(self, aligned_img):
        if self._fail:
            raise RuntimeError("SFace feature failed")
        return np.random.randn(1, FACE_EMBEDDING_DIM).astype(np.float32)


def _patch_detector(
    monkeypatch: pytest.MonkeyPatch,
    faces: np.ndarray | None = None,
    *,
    sface_fail: bool = False,
    no_recognizer: bool = False,
) -> FaceDetector:
    """Create a FaceDetector with mocked cv2 models."""
    yunet = _FakeYuNet(faces)
    sface = None if no_recognizer else _FakeSFace(fail=sface_fail)
    det = FaceDetector("/fake/yunet.onnx", "/fake/sface.onnx" if not no_recognizer else None)
    det._detector = yunet
    det._recognizer = sface
    return det


async def test_detect_single_face(monkeypatch: pytest.MonkeyPatch):
    det = _patch_detector(monkeypatch, _fake_faces_matrix(1))
    try:
        result = await det.detect(_fake_frame())
        assert isinstance(result, FaceDetectionResult)
        assert not result.degraded
        assert len(result.faces) == 1
        face = result.faces[0]
        assert isinstance(face, DetectedFace)
        assert face.embedding is not None
        assert len(face.embedding) == FACE_EMBEDDING_DIM
        assert face.confidence == pytest.approx(0.95)
        assert face.crop is not None
        assert face.landmarks.shape == (5, 2)
    finally:
        await det.aclose()


async def test_detect_multiple_faces(monkeypatch: pytest.MonkeyPatch):
    det = _patch_detector(monkeypatch, _fake_faces_matrix(3))
    try:
        result = await det.detect(_fake_frame())
        assert len(result.faces) == 3
        for face in result.faces:
            assert face.embedding is not None
    finally:
        await det.aclose()


async def test_detect_no_faces(monkeypatch: pytest.MonkeyPatch):
    det = _patch_detector(monkeypatch, None)
    try:
        result = await det.detect(_fake_frame())
        assert not result.degraded
        assert result.faces == []
    finally:
        await det.aclose()


async def test_detect_empty_frame(monkeypatch: pytest.MonkeyPatch):
    det = _patch_detector(monkeypatch, _fake_faces_matrix(1))
    try:
        result = await det.detect(np.zeros((0, 0, 3), dtype=np.uint8))
        assert result.faces == []
    finally:
        await det.aclose()


async def test_detect_sface_failure(monkeypatch: pytest.MonkeyPatch):
    det = _patch_detector(monkeypatch, _fake_faces_matrix(1), sface_fail=True)
    try:
        result = await det.detect(_fake_frame())
        assert len(result.faces) == 1
        assert result.faces[0].embedding is None
        assert result.faces[0].crop is None
    finally:
        await det.aclose()


async def test_detect_without_recognizer(monkeypatch: pytest.MonkeyPatch):
    det = _patch_detector(monkeypatch, _fake_faces_matrix(1), no_recognizer=True)
    try:
        result = await det.detect(_fake_frame())
        assert len(result.faces) == 1
        assert result.faces[0].embedding is None
        assert result.faces[0].crop is None
    finally:
        await det.aclose()


async def test_warm_up_loads():
    det = FaceDetector("/fake/yunet.onnx")
    det._detector = _FakeYuNet()
    det._recognizer = None
    assert det.loaded
    await det.aclose()


async def test_closed_raises():
    det = FaceDetector("/fake/yunet.onnx")
    await det.aclose()
    with pytest.raises(RuntimeError):
        await det.detect(_fake_frame())


# ---------------------------------------------------------------------------
# FaceExpressionClassifier
# ---------------------------------------------------------------------------


class _FakeExpressionNet:
    """Stands in for cv2.dnn ONNX net for FER."""

    def __init__(self, logits: np.ndarray | None = None) -> None:
        self._logits = logits if logits is not None else np.array(
            [0.1, 0.05, 0.05, 0.6, 0.1, 0.05, 0.05], dtype=np.float32
        ).reshape(1, -1)

    def setInput(self, blob):  # noqa: N802
        pass

    def forward(self):
        return self._logits


def _patch_expression_classifier(
    logits: np.ndarray | None = None,
) -> FaceExpressionClassifier:
    cls = FaceExpressionClassifier("/fake/fer.onnx")
    cls._net = _FakeExpressionNet(logits)
    return cls


async def test_expression_classify():
    cls = _patch_expression_classifier()
    try:
        crop = np.zeros((112, 112, 3), dtype=np.uint8)
        result = await cls.classify(crop)
        assert isinstance(result, ExpressionResult)
        assert result.label in EXPRESSION_CATEGORIES
        assert len(result.scores) == len(EXPRESSION_CATEGORIES)
        assert sum(result.scores.values()) == pytest.approx(1.0, abs=1e-5)
        assert result.confidence > 0
    finally:
        await cls.aclose()


async def test_expression_happy_dominant():
    logits = np.array([0.0, 0.0, 0.0, 5.0, 0.0, 0.0, 0.0], dtype=np.float32).reshape(1, -1)
    cls = _patch_expression_classifier(logits)
    try:
        result = await cls.classify(np.zeros((112, 112, 3), dtype=np.uint8))
        assert result is not None
        assert result.label == "happy"
        assert result.confidence > 0.9
    finally:
        await cls.aclose()


async def test_expression_empty_crop():
    cls = _patch_expression_classifier()
    try:
        result = await cls.classify(np.zeros((0, 0, 3), dtype=np.uint8))
        assert result is None
    finally:
        await cls.aclose()


async def test_expression_none_crop():
    cls = _patch_expression_classifier()
    try:
        result = await cls.classify(None)
        assert result is None
    finally:
        await cls.aclose()


async def test_expression_closed_raises():
    cls = FaceExpressionClassifier("/fake/fer.onnx")
    await cls.aclose()
    with pytest.raises(RuntimeError):
        await cls.classify(np.zeros((112, 112, 3), dtype=np.uint8))


# ---------------------------------------------------------------------------
# GazeEstimator (landmark-based)
# ---------------------------------------------------------------------------


async def test_landmark_gaze_estimate():
    estimator = LandmarkGazeEstimator()
    landmarks = np.array(
        [
            [120.0, 115.0],
            [160.0, 115.0],
            [140.0, 135.0],
            [125.0, 155.0],
            [155.0, 155.0],
        ],
        dtype=np.float32,
    )
    result = await estimator.estimate(landmarks, (480, 640, 3))
    assert result is not None
    assert isinstance(result, GazeResult)
    assert isinstance(result.yaw, float)
    assert isinstance(result.pitch, float)
    assert isinstance(result.mutual_gaze, bool)


async def test_landmark_gaze_frontal_is_mutual():
    estimator = LandmarkGazeEstimator()
    landmarks = np.array(
        [
            [280.0, 200.0],
            [360.0, 200.0],
            [320.0, 250.0],
            [295.0, 290.0],
            [345.0, 290.0],
        ],
        dtype=np.float32,
    )
    result = await estimator.estimate(landmarks, (480, 640, 3))
    assert result is not None
    assert result.mutual_gaze is True


async def test_landmark_gaze_invalid_landmarks():
    estimator = LandmarkGazeEstimator()
    result = await estimator.estimate(np.zeros((3, 2), dtype=np.float32), (480, 640))
    assert result is None


async def test_landmark_gaze_none_landmarks():
    estimator = LandmarkGazeEstimator()
    result = await estimator.estimate(None, (480, 640))
    assert result is None


# ---------------------------------------------------------------------------
# unload() — reversible model release
# ---------------------------------------------------------------------------


async def test_face_detector_unload(monkeypatch: pytest.MonkeyPatch):
    det = _patch_detector(monkeypatch, _fake_faces_matrix(1))
    assert det.loaded
    await det.unload()
    assert not det.loaded
    assert not det._closed
    assert det._executor is not None
    await det.aclose()


async def test_face_detector_unload_then_reload(monkeypatch: pytest.MonkeyPatch):
    det = _patch_detector(monkeypatch, _fake_faces_matrix(1))
    result_before = await det.detect(_fake_frame())
    assert len(result_before.faces) == 1
    await det.unload()
    assert not det.loaded
    det._detector = _FakeYuNet(_fake_faces_matrix(2))
    det._recognizer = _FakeSFace()
    result_after = await det.detect(_fake_frame())
    assert len(result_after.faces) == 2
    await det.aclose()


async def test_expression_classifier_unload():
    cls = _patch_expression_classifier()
    assert cls.loaded
    await cls.unload()
    assert not cls.loaded
    assert not cls._closed
    assert cls._executor is not None
    await cls.aclose()


async def test_expression_classifier_unload_then_reload():
    cls = _patch_expression_classifier()
    crop = np.zeros((112, 112, 3), dtype=np.uint8)
    result_before = await cls.classify(crop)
    assert result_before is not None
    await cls.unload()
    assert not cls.loaded
    cls._net = _FakeExpressionNet()
    result_after = await cls.classify(crop)
    assert result_after is not None
    assert result_after.label in EXPRESSION_CATEGORIES
    await cls.aclose()


async def test_landmark_gaze_unload():
    estimator = LandmarkGazeEstimator()
    await estimator.unload()
    landmarks = np.array(
        [[280.0, 200.0], [360.0, 200.0], [320.0, 250.0],
         [295.0, 290.0], [345.0, 290.0]], dtype=np.float32,
    )
    result = await estimator.estimate(landmarks, (480, 640, 3))
    assert result is not None
