# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Process-wide gate for suspending and resuming the study record.

When disk pressure forces the awake floor to suspend the study record,
this gate drops entries and lets the sink emit gap markers around the
dropped span.
"""

from __future__ import annotations

import threading


class StudyRecordGate:
    """Idempotent suspend/resume gate for the study record."""

    def __init__(self) -> None:
        self._suspended = False
        self._lock = threading.Lock()

    @property
    def suspended(self) -> bool:
        with self._lock:
            return self._suspended

    def suspend(self) -> None:
        with self._lock:
            self._suspended = True

    def resume(self) -> None:
        with self._lock:
            self._suspended = False


_GATE = StudyRecordGate()


def study_record_gate() -> StudyRecordGate:
    """Return the process-wide study-record gate.

    The awake floor and all study-record sinks share this single gate so
    suspension is global across every study-record stream.
    """
    return _GATE
