# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Nous on wetware as a hybrid. The silicon engine keeps beliefs and expected free energy;
the substrate proposes a policy from per-action channel groups, with DishBrain-style
agreement feedback on two feedback channels. Shadow mode (default) never changes what Nous
does; drive mode acts on the proposal. On Cortical Labs' simulator this proves wiring only,
since the simulator does not learn. See openspec/changes/nous-on-wetware/.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

import numpy as np

from kaine_cl1.substrate.broker import ChannelTerritory, SubstrateBroker
from kaine_cl1.substrate.codec import StimRequest

log = logging.getLogger(__name__)

FEEDBACK_CHANNELS = 2
MIN_CHANNELS_PER_ACTION = 2
FEEDBACK_PULSE_UA = 1.5
LOG_EVERY = 100


class WetwarePolicyEngine:
    """KAINE's Nous engine wrapped with a substrate policy proposal; forwards unknown
    attributes to the inner engine.
    """

    def __init__(
        self,
        inner: Any,
        broker: SubstrateBroker,
        territory: ChannelTerritory,
        *,
        mode: str = "shadow",
        min_uA: float = 0.5,
        max_uA: float = 3.0,
        seed: int = 0,
    ) -> None:
        if mode not in {"shadow", "drive"}:
            raise ValueError(f'mode must be "shadow" or "drive", got {mode!r}')

        n = len(inner.actions)
        channels = tuple(territory.channels)
        need = n * MIN_CHANNELS_PER_ACTION + FEEDBACK_CHANNELS
        if len(channels) < need:
            raise ValueError(
                f"the nous territory has {len(channels)} channels but {n} actions need at "
                f"least {need} (two per action plus two feedback channels)"
            )

        rest = channels[:-FEEDBACK_CHANNELS]
        group_size = len(rest) // n
        groups = tuple(
            tuple(rest[i * group_size : (i + 1) * group_size]) for i in range(n)
        )
        feedback_channels = tuple(channels[-FEEDBACK_CHANNELS:])

        self._inner = inner
        self._broker = broker
        self._module = territory.module
        self._mode = mode
        self._min_uA = min_uA
        self._max_uA = max_uA
        self._rng = np.random.default_rng(seed)
        self._groups = groups
        self._feedback_channels = feedback_channels
        self._n = n
        self._prev_proposal: int | None = None
        self._prev_silicon: int | None = None
        self._proposals = 0
        self._agreements = 0

    @property
    def actions(self) -> tuple[str, ...]:
        return self._inner.actions

    def _encode(self, efe: list[float]) -> list[float]:
        efe_arr = np.asarray(efe, dtype=np.float64)
        finite = np.isfinite(efe_arr)
        if not finite.any():
            return [self._min_uA] * self._n

        logits = np.full_like(efe_arr, -np.inf)
        logits[finite] = -efe_arr[finite]
        max_logit = np.max(logits[finite])
        weights = np.exp(logits - max_logit)
        weights[~finite] = 0.0
        weights = weights / weights.max()
        amplitudes = self._min_uA + weights * (self._max_uA - self._min_uA)
        return amplitudes.tolist()

    def _feedback(self) -> list[StimRequest]:
        if self._prev_proposal is None:
            return []

        if self._prev_proposal == self._prev_silicon:
            return [StimRequest(ch, FEEDBACK_PULSE_UA) for ch in self._feedback_channels]

        requests: list[StimRequest] = []
        for ch in self._feedback_channels:
            amplitude = self._rng.uniform(0.0, self._max_uA)
            if amplitude >= self._min_uA:
                requests.append(StimRequest(ch, amplitude))
        return requests

    def step(self, snapshot: Any) -> Any:
        res = self._inner.step(snapshot)
        if res.timed_out or res.error:
            return res

        amps = self._encode(res.policy_efe)
        requests: list[StimRequest] = [
            StimRequest(ch, amps[i])
            for i, group in enumerate(self._groups)
            for ch in group
        ] + self._feedback()

        obs = self._broker.exchange(self._module, requests)

        counts = np.zeros(self._n, dtype=np.float64)
        for spike in obs.spikes:
            for idx, group in enumerate(self._groups):
                if spike.channel in group:
                    counts[idx] += 1.0
                    break

        sizes = np.array([len(g) for g in self._groups], dtype=np.float64)
        rates = counts / sizes
        max_rate = float(rates.max())
        if max_rate <= 0.0:
            proposal = res.action_index
        else:
            top = np.flatnonzero(rates == max_rate)
            if top.size > 1:
                proposal = res.action_index
            else:
                proposal = int(top[0])

        self._prev_proposal = proposal
        self._prev_silicon = res.action_index
        self._proposals += 1
        if proposal == res.action_index:
            self._agreements += 1

        if self._proposals % LOG_EVERY == 0:
            pct = 100.0 * self._agreements / self._proposals
            log.info(
                "CL1 Nous (%s mode): tissue agreed with the silicon policy on "
                "%d of %d proposals (%.0f%%)",
                self._mode,
                self._agreements,
                self._proposals,
                pct,
            )

        if self._mode == "shadow":
            return res

        return dataclasses.replace(
            res, action_index=proposal, action=self.actions[proposal]
        )

    @property
    def proposal_count(self) -> int:
        return self._proposals

    @property
    def agreement_rate(self) -> float:
        if self._proposals == 0:
            return 0.0
        return self._agreements / self._proposals

    @property
    def last_proposal(self) -> int | None:
        return self._prev_proposal

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._inner, name)

