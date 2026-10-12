# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest


@pytest.mark.parametrize("topos_loads", [True, False])
def test_loads(topos_loads):
    assert topos_loads in (True, False)


def read(obj):
    return getattr(obj, "topos_cursor", None)


KEY = "topos"
