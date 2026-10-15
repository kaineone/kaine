# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Deprecated alias package for :mod:`kaine.dashboard`.

Kept so ``python -m kaine.nexus`` keeps working until the operator rename step. The functional-module-names-drop-aliases change removes it.
"""

from kaine.dashboard.config import DashboardConfig as NexusConfig
from kaine.dashboard.config import load_dashboard_config as load_nexus_config
from kaine.dashboard.privacy import PrivacyFilter

__all__ = ["NexusConfig", "PrivacyFilter", "load_nexus_config"]
