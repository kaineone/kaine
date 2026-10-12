# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest


@pytest.mark.parametrize("vision_loads", [True, False])
def test_loads(vision_loads):
    assert vision_loads in (True, False)


def read(obj):
    return getattr(obj, "vision_cursor", None)


KEY = "topos"
