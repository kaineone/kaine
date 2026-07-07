# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Topos subsystem: vision encoder contract. Heavy transformers load is
deferred to `initialize`; this test only verifies construction + the
change-detection pure-function pipeline."""
from __future__ import annotations

import pytest

from kaine.modules.topos.change import CosineChangeDetector
from kaine.modules.topos.habituation import RollingMeanHabituator
from kaine.modules.topos.module import Topos

from tests.systems._harness import SubsystemHarness


@pytest.mark.asyncio
async def test_topos_constructs_lazy_encoder():
    async with SubsystemHarness() as h:
        topos = Topos(h.bus, encoder_model_id="facebook/dinov2-small", device_preference="cpu")
        # No initialize() — we don't want to download weights.
        assert topos.name == "topos"
        assert isinstance(topos.serialize(), dict)


def test_change_detector_observes_drop_in_change_for_static_scene():
    cd = CosineChangeDetector()
    s1 = cd.observe([1.0, 0.0, 0.0])
    s2 = cd.observe([1.0, 0.0, 0.0])
    # Repeating the same embedding yields lower change score the second time.
    assert s2 <= s1


def test_habituator_returns_decreasing_novelty_for_static_scene():
    hab = RollingMeanHabituator(window=4)
    n1 = hab.observe([1.0, 0.0])
    hab.observe([1.0, 0.0])
    n3 = hab.observe([1.0, 0.0])
    # Novelty / habituation score should decrease with repeated input.
    assert n3 <= n1
