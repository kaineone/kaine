# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The vision-model manifest and the integrity check the runtime runs before
loading a model, kept out of ``kaine.setup`` so the runtime never imports
install tooling.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "VisionModel",
    "VISION_MANIFEST",
    "is_installed",
]


@dataclass(frozen=True)
class VisionModel:
    id: str
    title: str
    url: str
    filename: str
    size_bytes: int
    sha256: str
    licence: str


VISION_MANIFEST: dict[str, VisionModel] = {
    "yunet": VisionModel(
        id="yunet",
        title="YuNet face detection (OpenCV Zoo)",
        url="https://huggingface.co/opencv/opencv_zoo/resolve/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        filename="face_detection_yunet_2023mar.onnx",
        size_bytes=232_589,
        sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        licence="MIT",
    ),
    "sface": VisionModel(
        id="sface",
        title="SFace face recognition (OpenCV Zoo)",
        url="https://huggingface.co/opencv/opencv_zoo/resolve/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        filename="face_recognition_sface_2021dec.onnx",
        size_bytes=38_696_353,
        sha256="0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
        licence="Apache-2.0",
    ),
    "fer": VisionModel(
        id="fer",
        title="Facial expression recognition (OpenCV Zoo)",
        url="https://huggingface.co/opencv/opencv_zoo/resolve/main/models/facial_expression_recognition/facial_expression_recognition_mobilefacenet_2022july.onnx",
        filename="facial_expression_recognition_mobilefacenet_2022july.onnx",
        size_bytes=4_791_892,
        sha256="4f61307602fc089ce20488a31d4e4614e3c9753a7d6c41578c854858b183e1a9",
        licence="Apache-2.0",
    ),
    "gaze-mobilenetv2": VisionModel(
        id="gaze-mobilenetv2",
        title="MobileNet V2 gaze estimation",
        url="https://github.com/yakhyo/gaze-estimation/releases/download/weights/mobilenetv2_gaze.onnx",
        filename="mobilenetv2_gaze.onnx",
        size_bytes=9_790_767,
        sha256="b81312df85c7ac1c1b5f78c573620d22c2719cb839650e15f12dc7eecb7744a4",
        licence="MIT",
    ),
}


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_verified_marker(target: Path) -> dict[str, Any] | None:
    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def is_installed(model_id: str, root: Path | str | None = None) -> bool:
    """Check whether a vision model's ONNX file is present and verified."""
    model = VISION_MANIFEST.get(model_id)
    if model is None:
        return False
    from kaine.model_paths import vision_model_path  # lazy: break cycle with model_paths

    onnx_path = vision_model_path(model_id, root)
    if not onnx_path.is_file():
        return False
    marker_path = onnx_path.with_suffix(".verified")
    marker = _read_verified_marker(marker_path)
    if marker is None:
        return False
    if marker.get("sha256") != model.sha256:
        return False
    if marker.get("size_bytes") != model.size_bytes:
        return False
    return True
