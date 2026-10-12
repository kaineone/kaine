# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>


class Vox:
    pass


def probes(make):
    return [
        make(role="Vox", title="Vox", label="Vox"),
        make(kind="Vox"),
    ]


__all__ = ["Vox", "probes"]
