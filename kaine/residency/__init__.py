# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Host-local model residency: one memory budget per domain, the footprint catalogue, and the fit report."""

__all__ = [
    "budget",
    "catalogue",
    "config",
    "events",
    "fit",
    "inflight",
    "ledger",
    "policy",
    "queue",
]

# No eager imports of heavy modules; submodules are imported on demand.
__version__ = "0.1"
