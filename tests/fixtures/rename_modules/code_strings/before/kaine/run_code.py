# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

CHILD = (
    "import sys\n"
    "from kaine.modules.topos.feed import WombClock\n"
)

SCRIPT = """
from kaine.modules.topos.feed import WombClock
print(WombClock)
"""

LABEL = "Show the topos view"
