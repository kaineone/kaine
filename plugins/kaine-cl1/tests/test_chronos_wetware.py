# SPDX-License-Identifier: LicenseRef-CAL-0.2
"""Chronos wetware backend against the simulator.

The acceptance criterion from `chronos-on-wetware`: on a temporally *structured*
stimulus the prediction error is lower than on a *scrambled* one, i.e. the
biological forward model does real predictive work, not noise.

`_LinearHead` mirrors `kaine.modules.chronos.network.ForwardPredictionHead`
(a single-layer linear map, online-adapted) so this stays sim-only; the live
integration injects the same `WetwareTimingModel` into the real
`Chronos(bus, network=...)` seam.
"""
from __future__ import annotations

import os

import numpy as np

os.environ.setdefault("CL_SDK_ACCELERATED_TIME", "1")
os.environ.setdefault("CL_SDK_VISUALISATION", "0")

import cl.sim as clsim  # noqa: E402
from kaine_cl1.backends.chronos import WetwareTimingModel  # noqa: E402
from kaine_cl1.substrate.broker import SubstrateBroker  # noqa: E402
from kaine_cl1.substrate.session import SubstrateConfig, SubstrateSession  # noqa: E402

_SOURCE = "kaine_cl1.substrate.sources:make_reference_culture"
_CONFIG = {"seed": 7, "baseline_hz": 2.0, "evoked_spikes": 16, "response_ms": 20.0}


def _open():
    clsim.set_simulator_data_source(_SOURCE, config=_CONFIG)  # resets timeline to t=0
    s = SubstrateSession(SubstrateConfig(accelerated_time=True, ticks_per_second=100))
    s.open()
    b = SubstrateBroker(channel_count=64, ticks_per_second=100, nesting_factor=6)
    territory = b.allocate("chronos", 8)
    b.open(s.neurons)
    return s, b, WetwareTimingModel(b, territory)


class _LinearHead:
    """Faithful minimal stand-in for Chronos' ForwardPredictionHead."""

    def __init__(self, units: int, feat: int, lr: float = 0.15):
        self._W = np.zeros((feat, units))
        self._lr = lr

    def predict(self, hidden):
        return self._W @ np.asarray(hidden)

    def adapt(self, hidden, target):
        h = np.asarray(hidden)
        err = self.predict(h) - np.asarray(target)
        self._W -= self._lr * np.outer(err, h)

    @staticmethod
    def error(pred, actual):
        return float(np.mean(np.abs(np.asarray(pred) - np.asarray(actual))))


def _run_sequence(features):
    """Feed a feature sequence through tick()→hidden→linear head; return the mean
    prediction error over the second half (after the head has adapted)."""
    s, b, model = _open()
    try:
        head = _LinearHead(units=model.units, feat=len(features[0]))
        last_hidden = None
        errors = []
        for t, feat in enumerate(features):
            hidden = model.tick(feat)
            if last_hidden is not None:
                pred = head.predict(last_hidden)
                errors.append(_LinearHead.error(pred, feat))
                head.adapt(last_hidden, feat)
            last_hidden = hidden
        return float(np.mean(errors[len(errors) // 2:]))
    finally:
        s.close()
        clsim.clear_simulator_data_source()


def test_interface_matches_cfc_network():
    s, b, model = _open()
    try:
        assert model.units == 8 and model.input_size == 8
        hidden = model.tick([0.5] * 8)
        assert isinstance(hidden, list) and len(hidden) == 8
    finally:
        s.close()
        clsim.clear_simulator_data_source()


def test_hidden_reflects_input():
    """Different feature amplitudes produce different hidden states: the encoded
    input actually reaches and modulates the substrate."""
    s, b, model = _open()
    try:
        low = np.array(model.tick([-3.0] * 8))
        high = np.array(model.tick([3.0] * 8))
        assert high.sum() > low.sum() + 1.0
    finally:
        s.close()
        clsim.clear_simulator_data_source()


def test_predictive_work_structured_vs_scrambled():
    rng = np.random.default_rng(0)
    vocab = rng.uniform(-3, 3, size=(4, 8))  # four distinct temporal patterns
    steps = 48
    structured = [vocab[t % 4] for t in range(steps)]        # periodic: predictable
    order = rng.integers(0, 4, size=steps)
    scrambled = [vocab[i] for i in order]                    # i.i.d.: unpredictable

    err_structured = _run_sequence(structured)
    err_scrambled = _run_sequence(scrambled)
    # The biological forward model does measurable predictive work: a structured
    # stimulus is predicted better than a scrambled one.
    assert err_structured < err_scrambled
