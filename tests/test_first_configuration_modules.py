# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The first_configuration profile is the single definition of the first-configuration module set."""

FIRST_CONFIGURATION = {"interoception", "sequence", "vision", "audition", "language", "affect", "sleep"}


def test_wizard_preset_reads_the_profile():
    from kaine.setup.wizard import first_configuration_modules

    preset = first_configuration_modules()
    assert {name for name, on in preset.items() if on} == FIRST_CONFIGURATION
