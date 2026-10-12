# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from pathlib import Path


def source(pkg_root: Path) -> str:
    return (pkg_root / "nexus_record.py").read_text()
