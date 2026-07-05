# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Async JSONL sink — re-exported from the shared persistence layer.

The implementation lives in :mod:`kaine.persistence.jsonl_sink` so that core
runtime code (e.g. the cycle's Spot incident log) can reuse it without importing
``kaine.evaluation`` and violating the sidecar boundary. Evaluation observers
keep importing it from here unchanged.
"""
from __future__ import annotations

from kaine.persistence.jsonl_sink import AsyncJsonlSink, _utc_date_str

__all__ = ["AsyncJsonlSink", "_utc_date_str"]
