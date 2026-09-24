# SPDX-License-Identifier: LicenseRef-CAL-0.2
"""Pure-logic foundation tests: no simulator required."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest
from kaine_cl1.substrate.broker import (
    OversubscribedError,
    SubstrateBroker,
    nesting_factor_for,
)
from kaine_cl1.substrate.codec import (
    FiringRateDecoder,
    PopulationEncoder,
    RateEncoder,
    SurpriseDecoder,
    lempel_ziv_complexity,
)


@dataclass
class FakeSpike:
    channel: int
    timestamp: int


# -- allocation -----------------------------------------------------------------
def test_allocation_is_disjoint():
    b = SubstrateBroker(channel_count=64)
    t1 = b.allocate("chronos", 12)
    t2 = b.allocate("soma", 12)
    assert set(t1.channels).isdisjoint(t2.channels)
    assert len(t1.channels) == 12 and len(t2.channels) == 12


def test_oversubscription_fails_at_allocation():
    b = SubstrateBroker(channel_count=64)
    b.allocate("a", 40)
    b.allocate("b", 20)
    with pytest.raises(OversubscribedError):
        b.allocate("c", 8)  # 40+20+8 = 68 > 64


def test_double_allocation_rejected():
    b = SubstrateBroker(channel_count=64)
    b.allocate("chronos", 8)
    with pytest.raises(ValueError):
        b.allocate("chronos", 8)


# -- routing --------------------------------------------------------------------
def test_route_isolates_by_territory():
    # reserved_channels empty here so channel identities 0..7 are exact for the
    # routing assertion; the channel-0 stim quirk is a sim concern, not routing.
    b = SubstrateBroker(channel_count=64, reserved_channels=frozenset())
    ta = b.allocate("a", 4)  # channels 0..3
    tb = b.allocate("b", 4)  # channels 4..7
    spikes = [FakeSpike(c, 100 + c) for c in (0, 1, 5, 6, 3, 4)]
    routed = b.route(spikes)
    assert {s.channel for s in routed["a"]} <= set(ta.channels)
    assert {s.channel for s in routed["b"]} <= set(tb.channels)
    assert len(routed["a"]) == 3 and len(routed["b"]) == 3


# -- cadence --------------------------------------------------------------------
def test_nesting_factor():
    assert nesting_factor_for(100, 3.33) == 30
    assert nesting_factor_for(100, 100.0) == 1
    with pytest.raises(ValueError):
        nesting_factor_for(100, 7.0)  # 14.28… not an integer nesting


# -- encoder safety -------------------------------------------------------------
@pytest.mark.parametrize("value", [-100.0, -0.1, 0.0, 0.5, 1.0, 5.0, 1e9])
def test_encoder_never_exceeds_limits(value):
    req = RateEncoder(channel=8).encode(value)
    channel_set, design = req.to_cl()  # StimDesign validates on construction
    assert abs(req.amplitude_uA) <= 3.0
    assert design.duration_us % 20 == 0


def test_population_encoder_matches_territory():
    enc = PopulationEncoder(channels=(0, 1, 2, 3))
    reqs = enc.encode([0.0, 0.3, 0.6, 1.0])
    assert [r.channel for r in reqs] == [0, 1, 2, 3]
    with pytest.raises(ValueError):
        enc.encode([0.1, 0.2])  # wrong length


# -- decoders -------------------------------------------------------------------
def test_firing_rate_decoder_counts_per_channel():
    dec = FiringRateDecoder(channels=(10, 11, 12))
    spikes = [FakeSpike(10, 0), FakeSpike(10, 1), FakeSpike(12, 2), FakeSpike(99, 3)]
    vec = dec.decode(spikes)
    assert list(vec) == [2.0, 0.0, 1.0]  # ch99 not in territory, dropped


def test_lempel_ziv_orders_disorder():
    ordered = [0] * 64
    periodic = [0, 1] * 32
    disordered = list(np.random.default_rng(0).integers(0, 2, size=64))
    assert lempel_ziv_complexity(ordered) < lempel_ziv_complexity(disordered)
    assert lempel_ziv_complexity(periodic) < lempel_ziv_complexity(disordered)


def test_surprise_rises_for_disordered_response():
    channels = tuple(range(8))
    dec = SurpriseDecoder(channels=channels, bins=16, baseline_window=16)
    rng = np.random.default_rng(1)
    # Prime the baseline with quiet, ordered responses (few, aligned spikes).
    for _ in range(16):
        ordered = [FakeSpike(channels[0], t) for t in range(0, 40, 10)]
        dec.decode(ordered, from_ts=0, frame_count=250)
    quiet = dec.decode([FakeSpike(channels[0], t) for t in range(0, 40, 10)],
                       from_ts=0, frame_count=250)
    # A dense, scattered response across the whole territory is more disordered.
    noisy = [FakeSpike(int(rng.integers(0, 8)), int(rng.integers(0, 250)))
             for _ in range(120)]
    surprise = dec.decode(noisy, from_ts=0, frame_count=250)
    assert surprise > quiet
