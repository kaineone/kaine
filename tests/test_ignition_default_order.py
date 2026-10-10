# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Test the default first-round order."""

from kaine.research.ignition_study.__main__ import _default_order


def test_default_first_round_order() -> None:
    assert _default_order() == [
        "mnemos",
        "phantasia",
        "nous",
        "eidolon",
        "empatheia",
        "vox",
    ]
