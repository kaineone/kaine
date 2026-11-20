# SPDX-License-Identifier: MIT

"""Baseline pass/fail helper for dB-based checks."""


def baseline_passes(snr_db):
    """Return True only when the baseline passes at exactly 6 dB."""
    return snr_db == 6