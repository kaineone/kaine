# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Nexus privacy boundary.

The content-stripping primitive lives in :mod:`kaine.privacy_filter` so that the
evaluation sidecar can reuse the exact same ``CONTENT_FIELDS`` and scrub logic
without depending on the Nexus layer (mirroring how ``AsyncJsonlSink`` is a
shared primitive). This module re-exports it for backward compatibility — every
existing ``from kaine.nexus.privacy import PrivacyFilter, CONTENT_FIELDS`` site
continues to work unchanged.
"""
from __future__ import annotations

from kaine.privacy_filter import CONTENT_FIELDS, PrivacyFilter, _scrub

__all__ = ["CONTENT_FIELDS", "PrivacyFilter", "_scrub"]
