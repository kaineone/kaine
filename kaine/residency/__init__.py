# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Residency budgeting, footprint catalogue, and fit reporting for KAINE."""

from kaine.residency.budget import (
    MemoryDomain,
    ResidencyBudget,
    cgroup_available_bytes,
    compute_budget,
    default_reserve_bytes,
    probe_budget,
)
from kaine.residency.catalogue import (
    ALLOWED_KEYS,
    CatalogueError,
    FootprintCatalogue,
    FootprintEntry,
    load_catalogue,
    save_catalogue,
)
from kaine.residency.fit import (
    SPEECH_LADDERS,
    Demand,
    FitReport,
    Placement,
    Rung,
    fit_report,
)

__all__ = [
    "ALLOWED_KEYS",
    "CatalogueError",
    "Demand",
    "FitReport",
    "FootprintCatalogue",
    "FootprintEntry",
    "MemoryDomain",
    "Placement",
    "ResidencyBudget",
    "Rung",
    "SPEECH_LADDERS",
    "cgroup_available_bytes",
    "compute_budget",
    "default_reserve_bytes",
    "fit_report",
    "load_catalogue",
    "probe_budget",
    "save_catalogue",
]
