# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Learned expected prediction error per interoceptive channel.

A predictive-processing agent does not treat irreducible noise as surprise:
it weights each prediction error by its expected precision, the inverse of
its expected variance (Feldman & Friston 2010, "Attention, uncertainty, and
free-energy", *Front. Hum. Neurosci.* 4:215; Seth 2013, "Interoceptive
inference, emotion, and the embodied self", *Trends Cogn. Sci.* 17:565).
Soma learns that expected precision separately for each interoceptive
channel from the channel's own history of absolute residuals. It is not a
fixed, hardwired sensitivity.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Mapping, Sequence

log = logging.getLogger(__name__)


class ExpectedErrorModel:
    """Running expected absolute error and spread per interoceptive channel."""

    def __init__(self, *, tau_s: float = 600.0, band: float = 2.0) -> None:
        if not (math.isfinite(tau_s) and tau_s > 0):
            raise ValueError("tau_s must be finite and positive")
        if not (math.isfinite(band) and band >= 0):
            raise ValueError("band must be finite and non-negative")
        self._tau_s = float(tau_s)
        self._band = float(band)
        self._expected: list[float] = []
        self._spread: list[float] = []

    @property
    def tau_s(self) -> float:
        return self._tau_s

    @property
    def band(self) -> float:
        return self._band

    @property
    def expected(self) -> tuple[float, ...]:
        return tuple(self._expected)

    @property
    def spread(self) -> tuple[float, ...]:
        return tuple(self._spread)

    def unexpected(
        self, residuals: Sequence[float], dt: float, *, learn: bool = True
    ) -> float:
        """Return the L2 unexpected error across channels and optionally learn.

        The band for each channel is taken from *before* this tick's update,
        so a residual that is large only because the model has just started
        learning still counts as unexpected.
        """
        if len(residuals) != len(self._expected):
            old_width = len(self._expected)
            new_width = len(residuals)
            self._expected = [0.0] * new_width
            self._spread = [0.0] * new_width
            log.info(
                "soma expected error: channel count %d -> %d; estimates start fresh",
                old_width,
                new_width,
            )

        if not math.isfinite(dt) or dt < 0.0:
            dt = 0.0

        alpha = 0.0 if dt == 0.0 else 1.0 - math.exp(-dt / self._tau_s)

        squared = 0.0
        for i, r in enumerate(residuals):
            if math.isfinite(r):
                x = abs(r)
                do_learn = learn
            else:
                x = 0.0
                do_learn = False

            bound = self._expected[i] + self._band * self._spread[i]
            u = max(0.0, x - bound)
            squared += u * u

            if do_learn:
                dev = abs(x - self._expected[i])
                self._expected[i] += alpha * (x - self._expected[i])
                self._spread[i] += alpha * (dev - self._spread[i])

        return math.sqrt(squared)

    def state_dict(self) -> dict[str, list[float]]:
        return {"expected": list(self._expected), "spread": list(self._spread)}

    def load_state_dict(self, state: Any) -> None:
        """Restore estimates from a mapping of equal-length finite non-negative lists."""
        if not isinstance(state, Mapping):
            log.warning(
                "expected_error state is not a mapping; resetting to fresh estimates"
            )
            self._expected = []
            self._spread = []
            return

        expected = state.get("expected")
        spread = state.get("spread")
        if (
            not isinstance(expected, list)
            or not isinstance(spread, list)
            or len(expected) != len(spread)
        ):
            log.warning(
                "expected_error state has mismatched or missing lists; resetting to fresh estimates"
            )
            self._expected = []
            self._spread = []
            return

        try:
            parsed_expected = [float(v) for v in expected]
            parsed_spread = [float(v) for v in spread]
        except Exception:
            log.warning(
                "expected_error state contains non-numeric values; resetting to fresh estimates"
            )
            self._expected = []
            self._spread = []
            return

        if any(
            not math.isfinite(v) or v < 0.0 for v in parsed_expected + parsed_spread
        ):
            log.warning(
                "expected_error state contains non-finite or negative values; resetting to fresh estimates"
            )
            self._expected = []
            self._spread = []
            return

        self._expected = parsed_expected
        self._spread = parsed_spread
