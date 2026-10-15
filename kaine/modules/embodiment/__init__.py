# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from kaine.modules.embodiment.adapter import (
    EmbodimentAdapter,
    EmbodimentCapabilities,
    FeedFrame,
)
from kaine.modules.embodiment.adapters.stub import StubAdapter
from kaine.modules.embodiment.control_surface import (
    MOTOR_CHANNELS,
    MOTOR_STAGES,
    ContinuousMotorSurface,
    ControlCommand,
    EfferenceLoop,
    MotorCurriculum,
    MotorFeedback,
    MotorPolicy,
    QuiescentMotorPolicy,
    clamp_channel,
)
from kaine.modules.embodiment.module import (
    CONTINUOUS_CHANNEL_RANGE,
    Embodiment,
    operator_approved,
)

__all__ = [
    "Embodiment",
    "operator_approved",
    "CONTINUOUS_CHANNEL_RANGE",
    "EmbodimentAdapter",
    "EmbodimentCapabilities",
    "FeedFrame",
    "StubAdapter",
    # Continuous embodiment control surface (the producer).
    "ContinuousMotorSurface",
    "ControlCommand",
    "MotorFeedback",
    "MotorPolicy",
    "QuiescentMotorPolicy",
    "MotorCurriculum",
    "EfferenceLoop",
    "MOTOR_CHANNELS",
    "MOTOR_STAGES",
    "clamp_channel",
]
