# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from kaine.modules.vision.change import (
    ChangeDetector,
    CosineChangeDetector,
)
from kaine.modules.vision.encoder import (
    DEFAULT_DINOV2_MODEL_ID,
    DEFAULT_ENCODER_BACKEND,
    DEFAULT_INTERNVIDEO_NEXT_MODEL_ID,
    ENCODER_BACKENDS,
    DINOv2Encoder,
    Encoder,
    InternVideoNextEncoder,
    make_encoder,
)
from kaine.modules.vision.habituation import (
    RollingMeanHabituator,
    SceneHabituator,
)
from kaine.modules.vision.module import Vision

__all__ = [
    "ChangeDetector",
    "CosineChangeDetector",
    "DEFAULT_DINOV2_MODEL_ID",
    "DEFAULT_ENCODER_BACKEND",
    "DEFAULT_INTERNVIDEO_NEXT_MODEL_ID",
    "ENCODER_BACKENDS",
    "DINOv2Encoder",
    "Encoder",
    "InternVideoNextEncoder",
    "make_encoder",
    "RollingMeanHabituator",
    "SceneHabituator",
    "Vision",
]
