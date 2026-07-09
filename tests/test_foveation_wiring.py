# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Composition-root wiring of the fovea-size arousal seam (topos-foveation).

The cognitive cycle holds the ``AffectStateProvider`` it refreshes each tick from
``thymos.state``; ``_wire_topos_arousal`` hands Topos a read-only accessor to its
arousal so the fovea size tracks affect (Easterbrook narrowing) without Topos
importing the workspace or Thymos.
"""

from __future__ import annotations

from datetime import datetime, timezone

from kaine.bus.schema import Event
from kaine.cycle.__main__ import _wire_topos_arousal
from kaine.cycle.affect_state import AffectStateProvider


class _FakeTopos:
    name = "topos"

    def __init__(self, foveation_enabled: bool) -> None:
        self.foveation_enabled = foveation_enabled
        self.arousal_provider = None

    def set_arousal_provider(self, provider) -> None:
        self.arousal_provider = provider


class _FakeRegistry:
    def __init__(self, **modules) -> None:
        self._modules = modules

    def __contains__(self, name: object) -> bool:
        return name in self._modules

    def get(self, name: str):
        return self._modules[name]


def _thymos_state_event(arousal: float) -> tuple[str, Event]:
    return (
        "1-0",
        Event(
            source="thymos",
            type="thymos.state",
            payload={"state": {"valence": 0.0, "arousal": arousal, "dominance": 0.0}},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        ),
    )


def test_no_topos_is_a_noop():
    provider = AffectStateProvider()
    assert _wire_topos_arousal(_FakeRegistry(), provider) is False


def test_foveation_off_does_not_wire():
    topos = _FakeTopos(foveation_enabled=False)
    provider = AffectStateProvider()
    assert _wire_topos_arousal(_FakeRegistry(topos=topos), provider) is False
    assert topos.arousal_provider is None


def test_foveation_on_wires_live_arousal():
    topos = _FakeTopos(foveation_enabled=True)
    provider = AffectStateProvider()
    wired = _wire_topos_arousal(_FakeRegistry(topos=topos), provider)
    assert wired is True
    assert topos.arousal_provider is not None
    # Before any thymos.state, the accessor reports the Thymos baseline (0.3).
    assert topos.arousal_provider() == 0.3
    # After a state update, the accessor reflects the live arousal.
    provider.observe([_thymos_state_event(0.82)])
    assert topos.arousal_provider() == 0.82
