# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Event-type names: the one source (module-core D3).

The names here are recorded exactly as they are used on the bus; no renames.
Comparison code in ``kaine/workspace/`` and ``kaine/cycle/`` imports these
constants instead of repeating the bare string, so a producer that renames a
type breaks readers at import time rather than silently.

The registry of payload models is added later in this module.
"""

from __future__ import annotations

AFFECT_STATE = "affect.state"
AFFECT_REGULATION = "affect.regulation"
INTEROCEPTION_REPORT = "interoception.report"
INTEROCEPTION_REGULATION = "interoception.regulation"
VISION_REPORT = "vision.report"
CYCLE_SET_RATES = "cycle.set_rates"
SLEEP_SLEEP_STARTED = "sleep.sleep.started"
SLEEP_SLEEP_COMPLETED = "sleep.sleep.completed"
SLEEP_REST_REQUEST = "sleep.rest_request"
WELFARE_GRAY_ZONE = "welfare.gray_zone"
EXTERNAL_SPEECH = "external_speech"
AUDITION_TRANSCRIPTION = "audition.transcription"
SOCIAL_COGNITION_SOCIAL_ERROR = "social_cognition.social_error"
