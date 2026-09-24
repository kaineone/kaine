# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Chronos on wetware: the reference conversion.

Chronos is KAINE's interval-timing organ. Upstream it steps a small Closed-form
Continuous-time (CfC) network each tick and feeds the resulting hidden state to a
linear prediction head that anticipates the next temporal feature; the prediction
error becomes salience.

Chronos already exposes the exact seam we need: its constructor takes
``network=`` and only builds the silicon ``CfCNetwork`` when that is ``None``
(``kaine/modules/chronos/module.py``). So the conversion is
pure injection (``Chronos(bus, network=WetwareTimingModel(...))``), with the
module body, its bus subscriptions, and its ``chronos.out`` event shapes unchanged.

``WetwareTimingModel`` matches ``CfCNetwork``'s ``.tick(feature_vec) -> hidden``
interface, but realises the hidden state on the shared biological substrate:
population-code the temporal feature onto the Chronos territory, run one cognitive
tick of the closed loop, and decode the territory's firing into the hidden vector.
Chronos' own prediction head and error machinery then run on that hidden state.

See `openspec/changes/chronos-on-wetware/`.
"""
from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from kaine_cl1.substrate.broker import ChannelTerritory, SubstrateBroker
from kaine_cl1.substrate.codec import FiringRateDecoder, PopulationEncoder


def _project(feature_vec: Sequence[float], size: int) -> np.ndarray:
    """Resize an arbitrary feature vector to `size` components in [0, 1].

    Averages the feature into `size` contiguous bins, then squashes each bin to
    [0, 1] with a fixed logistic so the mapping is stable across ticks (no
    per-call min/max that would destroy cross-time comparability)."""
    vec = np.asarray(list(feature_vec), dtype=float)
    if vec.size == 0:
        return np.zeros(size)
    if vec.size != size:
        idx = np.linspace(0, vec.size, size + 1).astype(int)
        vec = np.array([vec[idx[i]:max(idx[i] + 1, idx[i + 1])].mean() for i in range(size)])
    return 1.0 / (1.0 + np.exp(-vec))  # fixed squash → [0, 1]


class WetwareTimingModel:
    """Drop-in for Chronos' `network=` (the `CfCNetwork.tick` interface).

    The biological substrate replaces the silicon recurrent net; everything
    downstream in Chronos (prediction head, error, salience) is unchanged.
    """

    def __init__(
        self,
        broker: SubstrateBroker,
        territory: ChannelTerritory,
        *,
        min_uA: float = 0.5,
        max_uA: float = 3.0,
        hidden_scale: float = 12.0,
    ) -> None:
        self._broker = broker
        self._module = territory.module
        self._channels = territory.channels
        self._encoder = PopulationEncoder(self._channels, max_uA=max_uA)
        self._min_uA = float(min_uA)
        self._max_uA = float(max_uA)
        self._decoder = FiringRateDecoder(self._channels)
        self._hidden_scale = float(hidden_scale)

    @property
    def units(self) -> int:
        """Hidden-state width: one component per leased electrode."""
        return len(self._channels)

    @property
    def input_size(self) -> int:
        return len(self._channels)

    def tick(self, feature_vec: Sequence[float]) -> list[float]:
        """Encode the feature → stim, run one closed-loop tick, decode → hidden."""
        amps01 = _project(feature_vec, len(self._channels))
        # PopulationEncoder maps each component in [0,1] to an amplitude in
        # [min_uA, max_uA]; the reference culture's evoked response scales with
        # amplitude, so the hidden state carries the encoded feature.
        self._broker.queue_stim(self._module, self._encoder.encode(amps01))
        obs = self._broker.run_cognitive_tick()[self._module]
        hidden = self._decoder.decode(obs.spikes) / self._hidden_scale
        return hidden.tolist()

    def reset(self) -> None:  # matches CfCNetwork.reset()
        pass

    def state_dict(self) -> dict[str, Any]:
        return {"channels": list(self._channels)}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        return
