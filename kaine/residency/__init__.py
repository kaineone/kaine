# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Host-local model residency: one memory budget per domain, the footprint catalogue, and the fit report."""

__all__ = [
    "budget",
    "catalogue",
    "fit",
    "inflight",
]

# No eager imports of heavy modules; submodules are imported on demand.
__version__ = "0.1"
