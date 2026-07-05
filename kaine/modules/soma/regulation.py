# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Homeostatic regulation detector for Soma.

When prediction error remains above ``regulation_threshold`` for
``sustain_window_s`` seconds, emits a ``soma.regulation`` advisory
event.  Soma NEVER actuates directly; it publishes intents and the
cycle engine acts on them (separation of perception from control).

Advisory action ladder
-----------------------
- ``reduce_rate``         : sustained mild stress
- ``shed_module``         : sustained moderate stress
- ``request_maintenance`` : sustained severe stress

The detector steps up through these in order as sustain time
accumulates.  It resets on any tick where error drops below the
threshold, preventing indefinite escalation.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

log = logging.getLogger(__name__)

# Advisory action escalation levels (in order of severity).
_ACTIONS = ("reduce_rate", "shed_module", "request_maintenance")

# Severities paired with each action tier (1 = mild, 3 = critical).
_SEVERITIES = (1, 2, 3)


class RegulationDetector:
    """Sustained-error detector that triggers homeostatic regulation.

    Each tick call ``update(error, now)``; the detector tracks how long
    error has been continuously above the threshold.  When the sustain
    window is exceeded it returns a regulation advisory dict; otherwise
    it returns None.

    Multiple regulation events may fire on subsequent ticks (the detector
    does not suppress repeats — the caller may debounce if desired).  The
    escalation tier advances once per full sustain window:

        - First window expired  → reduce_rate
        - Second window expired → shed_module
        - Third+ window expired → request_maintenance
    """

    def __init__(
        self,
        *,
        threshold: float = 0.5,
        sustain_window_s: float = 30.0,
    ) -> None:
        if threshold < 0:
            raise ValueError("threshold must be >= 0")
        if sustain_window_s <= 0:
            raise ValueError("sustain_window_s must be positive")

        self._threshold = float(threshold)
        self._sustain_window_s = float(sustain_window_s)

        # Monotonic timestamp when this stress episode began.
        self._stress_start: Optional[float] = None
        # Number of complete windows that have expired during this episode.
        self._windows_expired: int = 0
        # Last emission time — prevents flooding on successive ticks.
        self._last_emitted_window: int = -1

    @property
    def threshold(self) -> float:
        return self._threshold

    @property
    def sustain_window_s(self) -> float:
        return self._sustain_window_s

    @property
    def is_stressed(self) -> bool:
        """True while error is continuously above threshold."""
        return self._stress_start is not None

    def sustain_elapsed_s(self, now: Optional[float] = None) -> float:
        """Seconds the current stress episode has been sustained (0 if none).

        Exposed so the Soma warm-up can record how long an advisory would have
        been sustaining when it withholds it (the ``sustain_elapsed_s`` field on
        ``soma.regulation.withheld``), without re-parsing the advisory reason.
        """
        if self._stress_start is None:
            return 0.0
        if now is None:
            now = time.monotonic()
        return max(0.0, now - self._stress_start)

    def update(
        self,
        prediction_error: float,
        *,
        now: Optional[float] = None,
    ) -> Optional[dict]:
        """Process one tick's prediction error.

        Parameters
        ----------
        prediction_error:
            Current tick's L2 prediction error.
        now:
            Current monotonic time (seconds).  Defaults to
            ``time.monotonic()``.  Exposed for testing.

        Returns
        -------
        dict or None
            If a regulation advisory should be published:
            ``{"action": str, "reason": str, "severity": int}``
            Otherwise returns None.
        """
        if now is None:
            now = time.monotonic()

        if prediction_error < self._threshold:
            # Error dropped — reset episode.
            if self._stress_start is not None:
                log.debug(
                    "RegulationDetector: stress episode cleared (error=%.4f < threshold=%.4f)",
                    prediction_error,
                    self._threshold,
                )
            self._stress_start = None
            self._windows_expired = 0
            self._last_emitted_window = -1
            return None

        # Error is above threshold — track stress episode.
        if self._stress_start is None:
            self._stress_start = now
            log.debug(
                "RegulationDetector: stress episode started (error=%.4f >= threshold=%.4f)",
                prediction_error,
                self._threshold,
            )

        elapsed = now - self._stress_start
        windows_expired = int(elapsed / self._sustain_window_s)

        if windows_expired > 0 and windows_expired > self._last_emitted_window:
            # New window has elapsed — emit advisory.
            self._windows_expired = windows_expired
            self._last_emitted_window = windows_expired

            tier = min(windows_expired - 1, len(_ACTIONS) - 1)
            action = _ACTIONS[tier]
            severity = _SEVERITIES[tier]

            advisory = {
                "action": action,
                "reason": (
                    f"prediction error {prediction_error:.4f} sustained above "
                    f"threshold {self._threshold:.4f} for "
                    f"{elapsed:.1f}s"
                ),
                "severity": severity,
            }
            log.info(
                "RegulationDetector: advisory %r (severity=%d, elapsed=%.1fs)",
                action,
                severity,
                elapsed,
            )
            return advisory

        return None

    def reset(self) -> None:
        """Reset the detector state (e.g. after Hypnos maintenance)."""
        self._stress_start = None
        self._windows_expired = 0
        self._last_emitted_window = -1
