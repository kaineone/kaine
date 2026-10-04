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
import collections
import logging
import math
import uuid
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
from kaine.workspace.volition import VOLITION_FEEDBACK_STREAM

log = logging.getLogger(__name__)
HYPNOS_OUT_STREAM = "hypnos.out"

# Map an engine action name → a proposal kind for the Volition/proposal path.
# `request_think` is epistemic (internal elaboration) → a `think` proposal.
# `request_speak` → a `speak` proposal. `request_maintenance` → a `rest`
# proposal realized by Volition and Hypnos. `no_op` produces no proposal.
_ACTION_TO_PROPOSAL_KIND: dict[str, str] = {
    "request_think": "think",
    "request_speak": "speak",
    "request_maintenance": "rest",
}


class Nous(BaseModule):
    name: ClassVar[str] = "nous"
    relieves_drives: ClassVar[frozenset[str]] = frozenset({"boredom"})

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
        drive_actions: bool = True,
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
        # `is None`, not truthiness: an injected engine that happens to be falsy
        # (e.g. defines __len__) must never be silently replaced by the default.
        self._engine: ActiveInferenceEngine = engine if engine is not None else PymdpEngine()
        self._baseline_salience = float(baseline_salience)
        self._alert_salience = float(alert_salience)
        self._timeout_salience = float(timeout_salience)
        self._drive_actions = bool(drive_actions)
        self._tick_lock = asyncio.Lock()
        self._last_action: Optional[str] = None
        self._last_posterior: list[list[float]] = []
        self._step_counter: int = 0
        self._feedback_cursor: Optional[str] = None
        self._hypnos_cursor: Optional[str] = None
        self._recent_proposals: collections.OrderedDict[str, int] = collections.OrderedDict()
        self._unknown_outcomes: int = 0
        self._pending_taken: Optional[int] = None
        self._feedback_read_failed: bool = False

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
            await self._apply_taken_action_feedback()
            try:
                result = await asyncio.to_thread(self._engine.step, snapshot)
            except Exception:
                log.exception("active-inference step failed; skipping tick")
                return
            self._step_counter += 1
            if result.error:
                # Non-timeout crash: stale priors must NOT be re-published as a
                # fresh computation. Surface a nous.error diagnostic instead so
                # downstream (Eidolon, Mnemos, Syneidesis) see the gap rather
                # than acting on fabricated belief/policy.
                await self._publish_error(result)
                return
            if result.timed_out:
                await self._publish_timeout(result)
            else:
                # Step committed successfully. The pending realized action,
                # if any, has now been learned by the engine.
                self._pending_taken = None
            await self._publish_belief(result)
            await self._publish_policy(result)
            await self._emit_proposal(result)
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
                "horizon": getattr(self._engine, "policy_len", 1),
                "param_info_gain": getattr(self._engine, "uses_param_info_gain", False),
            },
            salience=self._baseline_salience,
        )

    @property
    def _no_op_index(self) -> int:
        return self._engine.actions.index("no_op")

    def _proposal_preference(self, result: EngineResult) -> float:
        """Softmax probability of the selected action under -EFE (unit precision)."""
        efe = result.policy_efe
        if not efe:
            return 0.0
        values = [float(x) for x in efe]
        finite = [x for x in values if math.isfinite(x)]
        if not finite:
            return 0.0
        min_efe = min(finite)
        exps = [math.exp(-(x - min_efe)) if math.isfinite(x) else 0.0 for x in values]
        total = sum(exps)
        chosen = values[result.action_index]
        if total <= 0.0 or not math.isfinite(chosen):
            return 0.0
        return math.exp(-(chosen - min_efe)) / total

    async def _emit_proposal(self, result: EngineResult) -> None:
        kind = _ACTION_TO_PROPOSAL_KIND.get(result.action)
        if kind is None:
            # no_op: no proposal this cycle.
            return
        preference = self._proposal_preference(result)
        proposal_id = uuid.uuid4().hex
        salience = (
            self._baseline_salience
            + preference * (self._alert_salience - self._baseline_salience)
        )
        await self.publish(
            "nous.proposal",
            {
                "proposal_id": proposal_id,
                "action": result.action,
                "kind": kind,
                "step": self._step_counter,
                "preference": float(preference),
            },
            salience=salience,
        )
        self._recent_proposals[proposal_id] = result.action_index
        if len(self._recent_proposals) > 32:
            self._recent_proposals.popitem(last=False)

    async def _apply_taken_action_feedback(self) -> None:
        """Read volition.proposal_outcome and hypnos.rest_request, then record the taken action.

        Called at the start of every workspace tick, before the engine step.
        """
        if not self._drive_actions:
            self._record_taken_action(self._no_op_index)
            return

        if self._feedback_cursor is None:
            self._feedback_cursor = await self._seed_cursor(VOLITION_FEEDBACK_STREAM)
        if self._hypnos_cursor is None:
            self._hypnos_cursor = await self._seed_cursor(HYPNOS_OUT_STREAM)

        feedback_entries: list[tuple[str, Any]] = []
        if self._feedback_cursor is not None:
            feedback_entries = await self._read_stream(
                VOLITION_FEEDBACK_STREAM, self._feedback_cursor
            )
            if feedback_entries:
                self._feedback_cursor = feedback_entries[-1][0]

        hypnos_entries: list[tuple[str, Any]] = []
        if self._hypnos_cursor is not None:
            hypnos_entries = await self._read_stream(HYPNOS_OUT_STREAM, self._hypnos_cursor)
            if hypnos_entries:
                self._hypnos_cursor = hypnos_entries[-1][0]

        for _eid, event in feedback_entries:
            if event.type != "volition.proposal_outcome":
                continue
            payload = event.payload
            pid = payload.get("proposal_id")
            if payload.get("reason") == "forwarded":
                # Rest proposal forwarded to Hypnos; never changes _recent_proposals
                # and never counts as unknown, because Hypnos will decide.
                continue
            action_index = self._recent_proposals.get(pid)
            if action_index is None:
                self._unknown_outcomes += 1
                continue
            self._recent_proposals.pop(pid, None)
            if bool(payload.get("realized")):
                self._pending_taken = action_index

        for _eid, event in hypnos_entries:
            if event.type != "hypnos.rest_request":
                continue
            payload = event.payload
            pid = payload.get("proposal_id")
            if pid not in self._recent_proposals:
                continue
            action_index = self._recent_proposals.pop(pid)
            if bool(payload.get("accepted")):
                self._pending_taken = action_index
            # accepted: false is a decline; the id is already removed.

        taken_index = self._pending_taken if self._pending_taken is not None else self._no_op_index
        self._record_taken_action(taken_index)

    async def _seed_cursor(self, stream: str) -> Optional[str]:
        """Seed a read cursor at the latest event on ``stream``.

        An empty stream starts at "0". A failed seed returns None so the next
        tick retries, rather than replaying the stream's whole history.
        """
        try:
            latest = await self._bus.latest(stream)
        except Exception:
            if not self._feedback_read_failed:
                log.warning(
                    "failed to seed cursor for %s; treating as no outcome",
                    stream,
                    exc_info=True,
                )
                self._feedback_read_failed = True
            return None
        if latest:
            return latest[0]
        return "0"

    async def _read_stream(self, stream: str, cursor: str) -> list[tuple[str, Any]]:
        try:
            entries = await self._bus.read(stream, last_id=cursor, count=64)
            self._feedback_read_failed = False
        except Exception:
            if not self._feedback_read_failed:
                log.warning(
                    "failed to read %s; treating as no outcome",
                    stream,
                    exc_info=True,
                )
                self._feedback_read_failed = True
            entries = []
        return entries

    def _record_taken_action(self, action_index: int) -> None:
        try:
            self._engine.record_taken_action(action_index)
        except Exception:
            log.warning("record_taken_action(%s) failed", action_index, exc_info=True)

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
        # A state without a label (for example one added by online growth)
        # falls back to a positional name rather than failing the tick.
        model = getattr(self._engine, "model", None)
        labels = getattr(model, "state_labels", None)
        if labels is not None and 0 <= factor_idx < len(labels):
            factor_labels = labels[factor_idx]
            if 0 <= state_idx < len(factor_labels):
                return factor_labels[state_idx]
        return f"factor{factor_idx}_state{state_idx}"

    def serialize(self) -> dict[str, Any]:
        # Zero raw-sense-data persistence: only numeric posteriors + the action
        # label. `posterior` lets NousMergeStrategy pick the lower-entropy
        # (more certain) fork on merge.
        out: dict[str, Any] = {
            "last_action": self._last_action,
            "posterior": [list(p) for p in self._last_posterior],
            "unknown_outcomes": self._unknown_outcomes,
            "step_counter": self._step_counter,
        }
        learned = getattr(self._engine, "learned_state", None)
        if callable(learned):
            out["learned"] = learned()
        return out

    def deserialize(self, state: dict[str, Any]) -> None:
        if "last_action" in state:
            self._last_action = state["last_action"]
        if "posterior" in state and isinstance(state["posterior"], list):
            self._last_posterior = [list(p) for p in state["posterior"]]
            seed = getattr(self._engine, "seed_posterior", None)
            if self._last_posterior and not callable(seed):
                # A wrapping or third-party engine that does not take a seed
                # keeps its own fallback; say so rather than drop it silently.
                log.info(
                    "nous: engine %s cannot take the restored posterior; "
                    "its timeout fallback is not seeded",
                    type(self._engine).__name__,
                )
            elif callable(seed) and self._last_posterior:
                if not seed(self._last_posterior):
                    log.warning(
                        "nous: restored posterior does not match the model; "
                        "engine fallback unchanged"
                    )
        if "unknown_outcomes" in state:
            self._unknown_outcomes = int(state["unknown_outcomes"])
        if "step_counter" in state:
            self._step_counter = int(state["step_counter"])
        if "learned" in state:
            load = getattr(self._engine, "load_learned_state", None)
            if callable(load):
                if not load(state["learned"]):
                    log.warning("nous: could not restore learned model of actions")
            else:
                log.info(
                    "nous: engine %s cannot restore a learned model of actions",
                    type(self._engine).__name__,
                )
        else:
            log.info(
                "nous: snapshot has no learned model of its actions; starting from the prior"
            )
