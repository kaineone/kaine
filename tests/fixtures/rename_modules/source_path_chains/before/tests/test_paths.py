# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "kaine" / "modules" / "soma" / "reader.py"
STATE = Path("state") / "soma" / "health.json"
