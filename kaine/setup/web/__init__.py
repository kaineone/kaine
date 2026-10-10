# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Browser front-end for the KAINE first-run wizard (KAINE setup server)."""
from __future__ import annotations

from kaine.setup.web.app import create_setup_app, serve

__all__ = ["create_setup_app", "serve"]
