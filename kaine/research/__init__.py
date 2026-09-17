# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""kaine.research — opt-in, operator-initiated research submission.

Default tier: numeric metrics only. See kaine/research/submission.py.
"""

from kaine.research.submission import (
    DENY_PATTERNS,
    METRICS_ONLY_GLOBS,
    Bundle,
    build_research_bundle,
    preview,
)

__all__ = [
    "Bundle",
    "METRICS_ONLY_GLOBS",
    "DENY_PATTERNS",
    "build_research_bundle",
    "preview",
]
