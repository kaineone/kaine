# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

import pytest

from kaine.bus.schema import Event
from kaine.modules.thymos.modulator import StateModulator
from kaine.modules.thymos.state import DimensionalState
from kaine.workspace.strategies import ThymosModulator


def _event() -> Event:
    return Event(
        source="soma",
        type="t",
        payload={},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


def test_satisfies_thymos_modulator_protocol():
    mod = StateModulator(lambda: DimensionalState())
    assert isinstance(mod, ThymosModulator)


@pytest.mark.asyncio
async def test_higher_arousal_strictly_larger():
    states = {"a": DimensionalState(arousal=0.2), "b": DimensionalState(arousal=0.8)}
    current = "a"

    def getter():
        return states[current]

    mod = StateModulator(getter)
    a = await mod.modulate(_event())
    current = "b"
    b = await mod.modulate(_event())
    assert b > a


@pytest.mark.asyncio
async def test_in_range():
    mod = StateModulator(lambda: DimensionalState(arousal=0.5))
    val = await mod.modulate(_event())
    assert 0.0 <= val <= 1.0


@pytest.mark.asyncio
async def test_floor_at_zero_arousal():
    mod = StateModulator(lambda: DimensionalState(arousal=0.0), floor=0.3, ceiling=0.9)
    val = await mod.modulate(_event())
    assert val == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_ceiling_at_full_arousal():
    mod = StateModulator(lambda: DimensionalState(arousal=1.0), floor=0.2, ceiling=0.8)
    val = await mod.modulate(_event())
    assert val == pytest.approx(0.8)


def test_invalid_floor_ceiling_rejected():
    with pytest.raises(ValueError):
        StateModulator(lambda: DimensionalState(), floor=0.5, ceiling=0.3)
    with pytest.raises(ValueError):
        StateModulator(lambda: DimensionalState(), floor=-0.1)
    with pytest.raises(ValueError):
        StateModulator(lambda: DimensionalState(), ceiling=1.5)
