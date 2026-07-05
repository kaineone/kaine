# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Nous — the active-inference engine (KAINE Paper §3.3.2).

Nous performs belief updating + policy selection by expected-free-energy
minimisation over a compact discrete generative model (pymdp 1.0, JAX). It
replaces the retired NARS/ONA symbolic reasoner (archived under
``external/archive/`` for a future complementary symbolic module).

Each global broadcast Nous:

- drives the :class:`ActiveInferenceEngine` (snapshot → posterior + EFE policy),
- publishes ``nous.belief`` (PRESERVED contract shape so Mnemos / Eidolon /
  Syneidesis consumers keep working) with redefined semantics: ``statement`` =
  the dominant latent-factor label, ``frequency`` = posterior expectation,
  ``confidence`` = 1 − normalised entropy, ``kind`` = ``"belief"``,
- publishes ``nous.policy`` (selected policy + expected free energy + horizon),
- emits the chosen epistemic / communicative action as an ``intent.act`` event
  through the Volition/intent path — NEVER a direct effector call. Syneidesis
  inhibition + Praxis whitelists remain in control of all outward action; Nous
  proposes, the executive disposes.

On an EFE timeout the engine returns the last posterior; Nous publishes a
``nous.timeout`` diagnostic (salience 0.3) and does not block the cycle.

On a non-timeout inference crash the engine returns stale priors and sets
``EngineResult.error=True``; Nous publishes a ``nous.error`` diagnostic and
skips publishing ``nous.belief`` / ``nous.policy`` for that cycle — stale
priors are never re-broadcast as a fresh computation.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar, Optional

from kaine.bus.client import AsyncBus
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.base import BaseModule
from kaine.modules.nous.engine import (
    ActiveInferenceEngine,
    EngineResult,
    PymdpEngine,
    normalised_entropy,
)

log = logging.getLogger(__name__)

# Map an engine action name → an intent kind on the Volition/intent path.
# `request_think` is epistemic (internal elaboration) → a `think` intent, which
# does not require a Praxis whitelist. `request_speak` → a `speak` intent.
# `no_op` and `request_maintenance` do not produce an intent.act (maintenance is
# signalled to Hypnos via the soma/regulation path, not an effector intent).
_ACTION_TO_INTENT_KIND: dict[str, str] = {
    "request_think": "think",
    "request_speak": "speak",
}
_INTENT_TYPE_FOR_KIND: dict[str, str] = {
    "think": "intent.act",
    "speak": "intent.act",
}


class Nous(BaseModule):
    name: ClassVar[str] = "nous"

    def holds_external_resources(self) -> bool:
        return True

    def __init__(
        self,
        bus: AsyncBus,
        *,
        engine: Optional[ActiveInferenceEngine] = None,
        baseline_salience: float = 0.4,
        alert_salience: float = 0.8,
        timeout_salience: float = 0.3,
    ) -> None:
        super().__init__(bus)
        if not 0.0 <= baseline_salience <= 1.0:
            raise ValueError("baseline_salience must be in [0, 1]")
        if not 0.0 <= alert_salience <= 1.0:
            raise ValueError("alert_salience must be in [0, 1]")
        if not 0.0 <= timeout_salience <= 1.0:
            raise ValueError("timeout_salience must be in [0, 1]")
        # The pymdp engine is constructed lazily/eagerly here. Tests inject a
        # FakeEngine so they need neither pymdp nor JAX.
        self._engine: ActiveInferenceEngine = engine or PymdpEngine()
        self._baseline_salience = float(baseline_salience)
        self._alert_salience = float(alert_salience)
        self._timeout_salience = float(timeout_salience)
        self._tick_lock = asyncio.Lock()
        self._last_action: Optional[str] = None
        self._last_posterior: list[list[float]] = []

    @property
    def engine(self) -> ActiveInferenceEngine:
        return self._engine

    async def shutdown(self) -> None:
        await super().shutdown()
        close = getattr(self._engine, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                log.warning("engine close failed", exc_info=True)

    async def on_workspace(self, snapshot: WorkspaceSnapshot) -> None:
        if not snapshot.selected_events:
            return
        async with self._tick_lock:
            try:
                result = await asyncio.to_thread(self._engine.step, snapshot)
            except Exception:
                log.exception("active-inference step failed; skipping tick")
                return
            if result.error:
                # Non-timeout crash: stale priors must NOT be re-published as a
                # fresh computation. Surface a nous.error diagnostic instead so
                # downstream (Eidolon, Mnemos, Syneidesis) see the gap rather
                # than acting on fabricated belief/policy.
                await self._publish_error(result)
                return
            if result.timed_out:
                await self._publish_timeout(result)
            await self._publish_belief(result)
            await self._publish_policy(result)
            await self._emit_action_intent(result)
            self._last_action = result.action
            self._last_posterior = [list(p) for p in result.posterior]

    async def _publish_belief(self, result: EngineResult) -> None:
        factor_idx, state_idx, expectation = result.dominant_factor()
        label = self._state_label(factor_idx, state_idx)
        dist = result.posterior[factor_idx] if factor_idx < len(result.posterior) else []
        confidence = 1.0 - normalised_entropy(dist)
        confidence = max(0.0, min(1.0, confidence))
        salience = (
            self._alert_salience
            if confidence >= 0.75
            else self._baseline_salience
        )
        await self.publish(
            "nous.belief",
            {
                "statement": label,
                "kind": "belief",
                "frequency": float(expectation),
                "confidence": float(confidence),
            },
            salience=salience,
        )

    async def _publish_policy(self, result: EngineResult) -> None:
        try:
            efe = float(result.policy_efe[result.action_index])
        except (IndexError, ValueError):
            efe = 0.0
        await self.publish(
            "nous.policy",
            {
                "policy": result.action,
                "expected_free_energy": efe,
                "horizon": 1,
            },
            salience=self._baseline_salience,
        )

    async def _emit_action_intent(self, result: EngineResult) -> None:
        kind = _ACTION_TO_INTENT_KIND.get(result.action)
        if kind is None:
            # no_op / request_maintenance: no effector intent this cycle.
            return
        intent_type = _INTENT_TYPE_FOR_KIND.get(kind, "intent.act")
        await self.publish(
            intent_type,
            {
                "kind": kind,
                "about": result.action,
            },
            salience=self._baseline_salience,
        )

    async def _publish_error(self, result: EngineResult) -> None:
        """Publish a nous.error diagnostic on an inference crash.

        Belief and policy are NOT published on an error cycle — the stale
        priors held by the engine are returned from step() but they represent
        the PREVIOUS successful computation, not a fresh inference from this
        snapshot. Publishing them as if they were fresh would mislead
        downstream consumers (Eidolon, Mnemos, Syneidesis).
        """
        await self.publish(
            "nous.error",
            {
                "error_reason": result.error_reason,
                "elapsed_ms": float(result.elapsed_ms),
                "num_factors": len(result.posterior),
                "num_actions": len(self._engine.actions),
            },
            salience=self._timeout_salience,
        )

    async def _publish_timeout(self, result: EngineResult) -> None:
        await self.publish(
            "nous.timeout",
            {
                "elapsed_ms": float(result.elapsed_ms),
                "num_factors": len(result.posterior),
                "num_actions": len(self._engine.actions),
            },
            salience=self._timeout_salience,
        )

    def _state_label(self, factor_idx: int, state_idx: int) -> str:
        model = getattr(self._engine, "model", None)
        if model is not None:
            try:
                return model.state_labels[factor_idx][state_idx]
            except (IndexError, AttributeError):
                pass
        return f"factor{factor_idx}_state{state_idx}"

    def serialize(self) -> dict[str, Any]:
        # Zero raw-sense-data persistence: only numeric posteriors + the action
        # label. `posterior` lets NousMergeStrategy pick the lower-entropy
        # (more certain) fork on merge.
        return {
            "last_action": self._last_action,
            "posterior": [list(p) for p in self._last_posterior],
        }

    def deserialize(self, state: dict[str, Any]) -> None:
        if "last_action" in state:
            self._last_action = state["last_action"]
        if "posterior" in state and isinstance(state["posterior"], list):
            self._last_posterior = [list(p) for p in state["posterior"]]
