# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The thesis_test profile is the single definition of the base-thesis module set."""

BASE_THESIS = {"soma", "chronos", "topos", "audition", "lingua", "thymos", "hypnos"}


def test_wizard_preset_reads_the_profile():
    from kaine.setup.wizard import base_thesis_modules

    preset = base_thesis_modules()
    assert {name for name, on in preset.items() if on} == BASE_THESIS
