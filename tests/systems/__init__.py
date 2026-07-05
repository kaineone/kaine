# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Per-subsystem I/O contract tests.

Each file under this package exercises one subsystem against a
fakeredis-backed bus. No full-system boot. No entity state. Use
`SubsystemHarness` from `_harness.py` to set up.

Run only the systems suite with `pytest -m systems`.
"""
