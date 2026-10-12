# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>


def nous_health_probe() -> str:
    return "nous"


def other_probe() -> str:
    return "other"


__all__ = [
    "other_probe",
    "nous_health_probe",
]
__all__ += ("other_probe", "nous_health_probe")
