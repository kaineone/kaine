# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Stimulation safety guards; a non-finite current never reaches the SDK,
and a module can stimulate only its own territory."""

import math

import pytest
from kaine_cl1.substrate.broker import SubstrateBroker
from kaine_cl1.substrate.codec import PopulationEncoder, RateEncoder, StimRequest, _clamp01


def test_clamp01_maps_nan_to_zero():
    assert _clamp01(float("nan")) == 0.0
    assert _clamp01(float("inf")) == 1.0
    assert _clamp01(float("-inf")) == 0.0
    assert _clamp01(0.4) == 0.4


def test_rate_encoder_never_emits_nan():
    req = RateEncoder(3).encode(float("nan"))
    assert math.isfinite(req.amplitude_uA)
    assert req.amplitude_uA == 0.5


def test_population_encoder_never_emits_nan():
    reqs = PopulationEncoder([1, 2, 3]).encode([float("nan"), 0.5, float("inf")])
    assert len(reqs) == 3
    assert all(math.isfinite(r.amplitude_uA) for r in reqs)


def test_to_cl_refuses_non_finite_amplitude():
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="non-finite"):
            StimRequest(5, value).to_cl()


def _make_broker_with_two_modules():
    b = SubstrateBroker(channel_count=64)
    a = b.allocate("a", 4)
    other = b.allocate("b", 4)
    return b, a, other


def test_queue_stim_rejects_channels_outside_the_territory():
    b, a, other = _make_broker_with_two_modules()
    with pytest.raises(ValueError, match="outside its territory"):
        b.queue_stim("a", [StimRequest(other.channels[0], 1.0)])
    assert b._pending == {}


def test_queue_stim_rejects_non_finite_amplitude():
    b, a, _other = _make_broker_with_two_modules()
    with pytest.raises(ValueError, match="non-finite"):
        b.queue_stim(
            "a",
            [
                StimRequest(a.channels[0], 1.0),
                StimRequest(a.channels[1], float("nan")),
            ],
        )
    assert b._pending == {}


def test_queue_stim_accepts_valid_requests():
    b, a, _other = _make_broker_with_two_modules()
    b.queue_stim("a", [StimRequest(c, 1.0) for c in a.channels])
    assert len(b._pending["a"]) == 4


def test_queue_stim_unknown_module_still_keyerror():
    b, a, _other = _make_broker_with_two_modules()
    with pytest.raises(KeyError):
        b.queue_stim("nobody", [StimRequest(a.channels[0], 1.0)])
    assert b._pending == {}

