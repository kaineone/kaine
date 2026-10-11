# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""A predictive processor's report intensity.

The alert level on a categorical alert, otherwise graded by the error
ratio, the error over the running mean of the module's recent errors,
a stand-in for scaling the error by its precision; it reaches the
alert level when the error is twice its running mean.
"""

from __future__ import annotations

import math


def graded_intensity(baseline: float, alert_level: float, ratio: float) -> float:
    """Return intensity interpolated from baseline toward alert by the ratio."""
    if not math.isfinite(ratio) or ratio < 0:
        ratio = 0.0
    return baseline + (alert_level - baseline) * min(1.0, ratio / 2.0)
