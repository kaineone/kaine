# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Shared persistence primitives usable by any layer.

These primitives carry no dependency on the evaluation/sidecar subsystem, so
core runtime code (e.g. the cycle's Spot incident log) may use them without
violating the sidecar boundary (only the cycle/nexus entrypoints may import
``kaine.evaluation``).
"""
from kaine.persistence.jsonl_sink import AsyncJsonlSink, _utc_date_str

__all__ = ["AsyncJsonlSink", "_utc_date_str"]
