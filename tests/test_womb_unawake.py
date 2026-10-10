# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from kaine.boot.perception_feed import bind_womb_unawake_source


def test_bind_womb_unawake_source_sets_fn():
    cfg = {"perception_feed": {"_womb_unawake": {}}}
    def fn() -> float:
        return 1.0
    bind_womb_unawake_source(cfg, fn)
    assert cfg["perception_feed"]["_womb_unawake"]["fn"] is fn


def test_bind_womb_unawake_source_silently_ignores_missing_holder():
    cfg = {}
    cfg2 = {"perception_feed": {}}
    bind_womb_unawake_source(cfg, lambda: 1.0)
    bind_womb_unawake_source(cfg2, lambda: 1.0)
    bind_womb_unawake_source(None, lambda: 1.0)
    assert cfg == {}
    assert cfg2 == {"perception_feed": {}}
