# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Canonical continuous-channel vocabulary for Mundus embodiment.

The clamp ranges for the entity's per-tick continuous motor channels live here,
in a leaf module that both the Mundus core (`module.py`) and the control surface
(`control_surface.py`) import, so neither has to import the other for the shared
vocabulary. `interact` is a single graded-reach trigger, so its range is
non-negative; the locomotion and gaze rates are bidirectional.
"""
from __future__ import annotations

CONTINUOUS_CHANNEL_RANGE: dict[str, tuple[float, float]] = {
    "drive": (-1.0, 1.0),
    "yaw_rate": (-1.0, 1.0),
    "gaze_yaw": (-1.0, 1.0),
    "gaze_pitch": (-1.0, 1.0),
    "interact": (0.0, 1.0),
}
