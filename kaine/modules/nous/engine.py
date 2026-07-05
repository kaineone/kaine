# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Active-inference engine for Nous (pymdp 1.0, JAX).

The engine is the seam between KAINE's workspace and pymdp. Each broadcast it:

1. encodes the :class:`WorkspaceSnapshot` to observation indices
   (:func:`generative_model.encode_snapshot`),
2. updates the posterior over hidden states (``Agent.infer_states``),
3. selects a policy by EFE minimisation (``Agent.infer_policies`` →
   negative expected free energy per policy),
4. reads off the preferred action from the lowest-EFE policy.

It is reached behind the :class:`ActiveInferenceEngine` protocol so a
:class:`FakeEngine` (scripted, no pymdp / no JAX) can substitute in module-level
tests — and so a green build never requires pymdp *or* the retired ONA binary.

Timeout guard
-------------
EFE must not run unbounded inside the ~300 ms cognitive-cycle budget. The pymdp
engine wraps the infer step in a :class:`~concurrent.futures.ThreadPoolExecutor`
with an ``efe_timeout_ms`` deadline (default 250). On overrun it returns the
**last computed posterior** and signals a timeout (via ``last_result.timed_out``
plus a ``nous.timeout`` diagnostic published by the module) so the cycle is
never blocked.
"""
from __future__ import annotations

import logging
import math
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, Sequence, runtime_checkable

from kaine.modules.nous.generative_model import (
    ACTION_FACTOR,
    GenerativeModel,
    build_generative_model,
    encode_snapshot,
)

log = logging.getLogger(__name__)


@dataclass
class EngineResult:
    """Outcome of one engine step.

    ``posterior`` is a list (per hidden-state factor) of 1-D probability
    vectors. ``policy_efe`` is the expected free energy per policy (lower is
    better) aligned to ``actions``. ``action_index`` / ``action`` name the
    selected action (the lowest-EFE policy's first step). ``timed_out`` is True
    when the EFE computation overran the deadline and the *previous* posterior
    was returned instead.

    ``error`` is True when a non-timeout exception aborted inference. In that
    case ``posterior`` / ``policy_efe`` / ``action`` reflect stale priors from
    the last successful step and MUST NOT be published as a fresh computation.
    ``error_reason`` carries a short human-readable summary of the exception.
    (``timed_out=True`` and ``error=True`` are mutually exclusive: timeouts are
    a planned degradation; errors are unexpected.)
    """

    posterior: list[list[float]]
    policy_efe: list[float]
    action_index: int
    action: str
    timed_out: bool = False
    error: bool = False
    error_reason: str = ""
    elapsed_ms: float = 0.0
    obs: list[int] = field(default_factory=list)

    def dominant_factor(self) -> tuple[int, int, float]:
        """Return (factor_idx, state_idx, expectation) of the most-confident
        non-trivial perceptual factor — used to fill ``nous.belief``.

        "Most confident" = lowest normalised entropy among the perceptual
        factors (every factor except the action latent). Ties break toward the
        earlier factor. ``expectation`` is the max posterior mass in that
        factor.
        """
        best: Optional[tuple[float, int, int, float]] = None
        for f, dist in enumerate(self.posterior):
            if f == ACTION_FACTOR:
                continue
            if not dist:
                continue
            ent = normalised_entropy(dist)
            state_idx = int(max(range(len(dist)), key=lambda i: dist[i]))
            expectation = float(dist[state_idx])
            key = (ent, f, state_idx, expectation)
            if best is None or key[0] < best[0]:
                best = key
        if best is None:
            return (ACTION_FACTOR, 0, 1.0)
        _ent, f, state_idx, expectation = best
        return (f, state_idx, expectation)


def normalised_entropy(dist: Sequence[float]) -> float:
    """Shannon entropy of a discrete distribution normalised to [0, 1].

    A point mass → 0.0; a uniform distribution → 1.0. Robust to unnormalised or
    degenerate (length 0/1) inputs.
    """
    n = len(dist)
    if n <= 1:
        return 0.0
    total = float(sum(dist))
    if total <= 0.0:
        return 1.0
    ent = 0.0
    for p in dist:
        q = float(p) / total
        if q > 0.0:
            ent -= q * math.log(q)
    return ent / math.log(n)


@runtime_checkable
class ActiveInferenceEngine(Protocol):
    """The seam Nous drives each broadcast.

    Implementations MUST be safe to call from an async module (they may block
    briefly; the pymdp impl bounds itself with a timeout). ``step`` returns an
    :class:`EngineResult`; it never raises for ordinary inference failures —
    it degrades to the last posterior.
    """

    @property
    def actions(self) -> tuple[str, ...]:
        ...

    def step(self, snapshot: Any) -> EngineResult:
        ...


class PymdpEngine:
    """pymdp 1.0 (JAX) implementation of :class:`ActiveInferenceEngine`.

    Constructs a :class:`pymdp.agent.Agent` from a :class:`GenerativeModel` and
    runs belief updating + EFE policy selection per broadcast, bounded by
    ``efe_timeout_ms``.
    """

    def __init__(
        self,
        model: Optional[GenerativeModel] = None,
        *,
        efe_timeout_ms: float = 250.0,
        policy_len: int = 1,
        num_iter: int = 8,
    ) -> None:
        if efe_timeout_ms <= 0:
            raise ValueError("efe_timeout_ms must be > 0")
        self._model = model or build_generative_model()
        self._efe_timeout_s = float(efe_timeout_ms) / 1000.0
        self._policy_len = int(policy_len)
        self._num_iter = int(num_iter)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nous-efe")
        self._agent = self._build_agent()
        self._jit_cycle = self._build_jit_cycle()
        # Last good posterior, used when a step times out.
        self._last_posterior: list[list[float]] = [
            self._uniform(n) for n in self._model.num_states
        ]
        self._last_efe: list[float] = [0.0] * self._model.num_actions
        # Warm up JAX tracing so the first live step is not the slow one.
        try:
            self._infer(encode_snapshot_default(self._model))
        except Exception:
            log.debug("pymdp warm-up step failed (non-fatal)", exc_info=True)

    @property
    def model(self) -> GenerativeModel:
        return self._model

    @property
    def actions(self) -> tuple[str, ...]:
        return self._model.actions

    def _build_agent(self) -> Any:
        import jax.numpy as jnp
        from pymdp.agent import Agent

        A = [jnp.array(a) for a in self._model.A]
        B = [jnp.array(b) for b in self._model.B]
        C = [jnp.array(c) for c in self._model.C]
        D = [jnp.array(d) for d in self._model.D]
        # The Agent constructor emits a benign equinox "JAX array set as static"
        # warning from its static policy/dependency fields — expected on CPU.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return Agent(
                A=A,
                B=B,
                C=C,
                D=D,
                A_dependencies=self._model.A_dependencies,
                policy_len=self._policy_len,
                num_iter=self._num_iter,
            )

    def _build_jit_cycle(self) -> Any:
        """JIT-compile infer_states + infer_policies into one traced function.

        Plain Python dispatch of the pymdp Agent methods costs ~130 ms/call;
        jitting the whole cycle drops it to well under 1 ms (KAINE is CPU-only,
        ~300 ms cycle budget). The traced function takes batched obs arrays and
        returns (qs, neg_efe) as JAX arrays; we convert to Python lists only
        after `block_until_ready`.
        """
        import jax

        agent = self._agent

        def _cycle(obs_batched: list[Any]) -> tuple[Any, Any]:
            qs = agent.infer_states(obs_batched, empirical_prior=agent.D)
            _q_pi, neg_efe = agent.infer_policies(qs)
            return qs, neg_efe

        return jax.jit(_cycle)

    @staticmethod
    def _uniform(n: int) -> list[float]:
        if n <= 0:
            return []
        return [1.0 / n] * n

    def _infer(self, obs: list[int]) -> tuple[list[list[float]], list[float], int]:
        """Run infer_states + infer_policies; return (posterior, efe, best_idx).

        Pure compute (no timeout). Raises on genuine failure; the caller wraps
        it with the deadline + degradation.
        """
        import jax
        import jax.numpy as jnp
        import numpy as np

        obs_batched = [jnp.array([int(o)]) for o in obs]
        qs, neg_efe = self._jit_cycle(obs_batched)
        jax.block_until_ready((qs, neg_efe))
        posterior: list[list[float]] = []
        for q in qs:
            arr = np.asarray(q).reshape(-1)
            s = float(arr.sum())
            if s > 0:
                arr = arr / s
            posterior.append([float(x) for x in arr])
        neg = np.asarray(neg_efe).reshape(-1)
        # EFE = -neg_efe (lower EFE is better); align to action order. The
        # control factor's policies are one-per-action in action order.
        efe = [float(-x) for x in neg]
        # Pad/trim to action count defensively.
        n_actions = self._model.num_actions
        if len(efe) < n_actions:
            efe = efe + [float("inf")] * (n_actions - len(efe))
        elif len(efe) > n_actions:
            efe = efe[:n_actions]
        best_idx = int(min(range(n_actions), key=lambda i: efe[i]))
        return posterior, efe, best_idx

    def infer(self, obs: Sequence[int]) -> EngineResult:
        """Run one belief-update + EFE policy-selection step on raw obs indices.

        This is the engine core shared by the live cognitive loop and any
        offline driver (e.g. the AIF-vs-RL benchmark): given one observation
        index per modality it runs the *real* pymdp ``infer_states`` +
        ``infer_policies`` (bounded by ``efe_timeout_ms``) and returns the
        :class:`EngineResult`. :meth:`step` is the live entry-point — it merely
        encodes a :class:`WorkspaceSnapshot` to obs and delegates here, so the
        live module's behaviour is exactly this method's behaviour.
        """
        obs = [int(o) for o in obs]
        start = time.perf_counter()
        future = self._executor.submit(self._infer, obs)
        try:
            posterior, efe, best_idx = future.result(timeout=self._efe_timeout_s)
        except FuturesTimeout:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            log.warning(
                "EFE planning overran %.0f ms; returning last posterior",
                self._efe_timeout_s * 1000.0,
            )
            # Let the orphaned compute finish in the background; we move on.
            return EngineResult(
                posterior=[list(p) for p in self._last_posterior],
                policy_efe=list(self._last_efe),
                action_index=0,
                action=self._model.actions[0],
                timed_out=True,
                elapsed_ms=elapsed_ms,
                obs=obs,
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            log.error(
                "EFE planning crashed (non-timeout); stale posterior retained — "
                "belief/policy from this cycle are NOT fresh: %s",
                exc,
                exc_info=True,
            )
            return EngineResult(
                posterior=[list(p) for p in self._last_posterior],
                policy_efe=list(self._last_efe),
                action_index=0,
                action=self._model.actions[0],
                timed_out=False,
                error=True,
                error_reason=f"{type(exc).__name__}: {exc}",
                elapsed_ms=elapsed_ms,
                obs=obs,
            )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        self._last_posterior = [list(p) for p in posterior]
        self._last_efe = list(efe)
        return EngineResult(
            posterior=posterior,
            policy_efe=efe,
            action_index=best_idx,
            action=self._model.actions[best_idx],
            timed_out=False,
            elapsed_ms=elapsed_ms,
            obs=obs,
        )

    def step(self, snapshot: Any) -> EngineResult:
        """Live entry-point: encode the snapshot to obs and run one inference.

        Pure delegation to :meth:`infer` — encoding the workspace snapshot to
        per-modality observation indices is the only Nous-specific step; the
        belief-update + EFE policy selection it then runs is the shared engine
        core the benchmark also drives.
        """
        return self.infer(encode_snapshot(snapshot, self._model))

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def encode_snapshot_default(model: GenerativeModel) -> list[int]:
    """Observation indices for an empty snapshot (warm-up / no coalition)."""

    class _Empty:
        selected_events: list[Any] = []

    return encode_snapshot(_Empty(), model)


class FakeEngine:
    """Scripted :class:`ActiveInferenceEngine` for tests — no pymdp, no JAX.

    Feed it ``posteriors`` (a list of per-factor distributions to return in
    sequence) and ``policy_efe`` (expected free energy per action). It selects
    the lowest-EFE action and never imports pymdp, so module-level tests run
    without the reasoning extra.

    Set ``timeout_on`` to a step index to simulate a deadline overrun on that
    step: it returns the *previous* posterior and ``timed_out=True``.

    Set ``error_on`` to a step index to simulate a non-timeout inference crash
    on that step: it returns the *previous* posterior with ``error=True`` and
    an ``error_reason`` string.
    """

    def __init__(
        self,
        *,
        actions: tuple[str, ...] = ("no_op", "request_think", "request_speak", "request_maintenance"),
        posteriors: Optional[list[list[list[float]]]] = None,
        policy_efe: Optional[list[float]] = None,
        timeout_on: Optional[int] = None,
        error_on: Optional[int] = None,
    ) -> None:
        self._actions = tuple(actions)
        # Default: 4 factors, action latent + 3 perceptual, uniform-ish.
        self._posteriors = posteriors or [
            [
                [1.0, 0.0, 0.0, 0.0],
                [0.1, 0.1, 0.8],
                [0.25, 0.25, 0.25, 0.25],
                [0.25, 0.25, 0.25, 0.25],
            ]
        ]
        self._policy_efe = policy_efe or [0.5, 0.1, 0.4, 0.6]
        self._timeout_on = timeout_on
        self._error_on = error_on
        self._step_index = 0
        self._last_posterior = [list(p) for p in self._posteriors[0]]
        self.steps_called = 0

    @property
    def actions(self) -> tuple[str, ...]:
        return self._actions

    def step(self, snapshot: Any) -> EngineResult:
        idx = self._step_index
        self.steps_called += 1
        self._step_index += 1
        if self._timeout_on is not None and idx == self._timeout_on:
            return EngineResult(
                posterior=[list(p) for p in self._last_posterior],
                policy_efe=list(self._policy_efe),
                action_index=0,
                action=self._actions[0],
                timed_out=True,
                elapsed_ms=999.0,
            )
        if self._error_on is not None and idx == self._error_on:
            return EngineResult(
                posterior=[list(p) for p in self._last_posterior],
                policy_efe=list(self._policy_efe),
                action_index=0,
                action=self._actions[0],
                timed_out=False,
                error=True,
                error_reason="RuntimeError: scripted test error",
                elapsed_ms=1.0,
            )
        posterior = self._posteriors[min(idx, len(self._posteriors) - 1)]
        posterior = [list(p) for p in posterior]
        self._last_posterior = posterior
        best_idx = int(min(range(len(self._policy_efe)), key=lambda i: self._policy_efe[i]))
        return EngineResult(
            posterior=posterior,
            policy_efe=list(self._policy_efe),
            action_index=best_idx,
            action=self._actions[best_idx],
            timed_out=False,
            elapsed_ms=1.0,
        )


__all__ = [
    "ActiveInferenceEngine",
    "EngineResult",
    "PymdpEngine",
    "FakeEngine",
    "normalised_entropy",
]
