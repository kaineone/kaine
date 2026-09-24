# SPDX-License-Identifier: LicenseRef-CAL-0.2
"""Smoke tests. The real conversion tests are enumerated in the openspec plan
(each change's tasks.md ends with a simulator-backed acceptance test)."""


def test_package_imports():
    import kaine_cl1

    assert kaine_cl1.__version__


def test_broker_channel_ceiling_is_64():
    # The 64-electrode ceiling is the hard architectural bound on how many
    # modules can share one culture. Guard the constant so the plan's territory
    # budgeting stays honest.
    from kaine_cl1.substrate import broker

    assert broker._CHANNELS_TOTAL == 64
