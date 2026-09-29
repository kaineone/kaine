# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Active-inference engine for Nous.

The engine is the seam between KAINE's workspace and a backend active-inference
implementation. Today there are two backends:

- :class:`PymdpEngine`: pymdp 1.0 / JAX (the historical backend).
- :class:`NumpyActiveInferenceEngine` (in
  :mod:`kaine.modules.nous.numpy_engine`): a pure-NumPy backend that reproduces
  the same model contract and golden fixtures.

Both share the same timeout guard, action-factor restore, evidence cap,
learned-state interchange format and :class:`ActiveInferenceEngine` protocol.
Only the backend math differs, through the abstract hooks on
:class:`_EngineBase`.

Timeout guard
-------------
EFE must not run unbounded inside the ~300 ms cognitive-cycle budget. The engine
wraps the infer step in a :class:`~concurrent.futures.ThreadPoolExecutor` with
an ``efe_timeout_ms`` deadline (default 250). On overrun it returns the **last
computed posterior** and signals a timeout (via ``last_result.timed_out`` plus a
``nous.timeout`` diagnostic published by the module) so the cycle is never
blocked.
"""
from __future__ import annotations

import logging
import math
import time
import warnings
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, Sequence, runtime_checkable

import numpy as np

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
        """The ordered action names the engine selects among."""

    def step(self, snapshot: Any) -> EngineResult:
        """Run one inference step over ``snapshot`` and return the result."""


class _EngineBase(ABC, ActiveInferenceEngine):
    """Backend-agnostic Nous engine logic.

    Concrete backends implement the abstract hooks for constructing an agent,
    running one inference/planning cycle, converting posterior/prior objects to
    and from plain lists, learning one transition, propagating a prior, and
    reading/replacing the agent's transition arrays.
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

        # Fixed action-factor transition slices (factor 0). The engine restores
        # these after every learning update so the action latent can never be
        # learned away from the model's deterministic control dynamics.
        self._orig_B0 = np.asarray(self._model.B[ACTION_FACTOR]).copy()
        self._orig_pB0: Optional[np.ndarray] = None
        if self._model.pB is not None:
            self._orig_pB0 = np.asarray(self._model.pB[ACTION_FACTOR]).copy()

        # Build the backend agent. Subclasses decide what "native" form means.
        self._agent = self._make_agent(None)
        self._policies = self._policy_array(self._agent)
        self._prior = self._initial_prior(self._agent)

        # Carried prior bookkeeping.
        self._prev_qs: Optional[list[Any]] = None
        self._prev_action: Optional[int] = None
        self._prev_qs_committed: Optional[list[Any]] = None
        self._generation = 0

        # Last committed posterior / EFE, used when a step times out.
        self._last_posterior: list[list[float]] = [
            self._uniform(n) for n in self._model.num_states
        ]
        self._last_efe: list[float] = [0.0] * self._model.num_actions

        self._warm_up()

    # ------------------------------------------------------------------ #
    # Shared protocol surface
    # ------------------------------------------------------------------ #

    @property
    def model(self) -> GenerativeModel:
        return self._model

    @property
    def actions(self) -> tuple[str, ...]:
        return self._model.actions

    @property
    def policy_len(self) -> int:
        return self._policy_len

    @property
    def uses_param_info_gain(self) -> bool:
        """Most real backends exploit the pB parameter information gain."""
        return True

    # ------------------------------------------------------------------ #
    # Backend hooks (abstract)
    # ------------------------------------------------------------------ #

    @abstractmethod
    def _make_agent(self, pB: Optional[list[np.ndarray]]) -> Any:
        """Build a backend agent from the engine model.

        ``pB`` is an optional unbatched Dirichlet prior over transitions. When
        ``None`` the agent should be built from the model's own pB (if the
        model learns) or from the model's fixed B matrices.
        """

    @abstractmethod
    def _cycle(
        self, agent: Any, obs: list[int], prior: Any
    ) -> tuple[Any, np.ndarray]:
        """Run one infer_states + infer_policies cycle.

        Returns ``(qs, neg_efe)`` where ``qs`` is in the backend's native form
        and ``neg_efe`` is a flat 1-D numpy array of negative expected free
        energies per policy.
        """

    @abstractmethod
    def _posterior_lists(self, qs: Any) -> list[list[float]]:
        """Convert backend qs to a list of normalised 1-D probability lists."""

    @abstractmethod
    def _learn(
        self, agent: Any, prev_qs: Any, qs: Any, row: np.ndarray, obs: list[int]
    ) -> Any:
        """One-step B learning for the taken action; returns a new agent."""

    @abstractmethod
    def _propagate(self, agent: Any, row: np.ndarray, qs: Any) -> Any:
        """Propagate a posterior through B under the given action row."""

    @abstractmethod
    def _get_pB(self, agent: Any) -> list[np.ndarray]:
        """Return unbatched numpy pB arrays (one per factor), or [] if none."""

    @abstractmethod
    def _get_B(self, agent: Any) -> list[np.ndarray]:
        """Return unbatched numpy B arrays (one per factor)."""

    @abstractmethod
    def _with_pB_B(
        self, agent: Any, pB: list[np.ndarray], B: list[np.ndarray]
    ) -> Any:
        """Return an agent whose pB/B arrays are replaced with the given ones."""

    @abstractmethod
    def _initial_prior(self, agent: Any) -> Any:
        """Return the backend-native form of the initial carried prior."""

    @abstractmethod
    def _prior_lists(self, prior: Any) -> list[list[float]]:
        """Convert a backend-native prior to plain lists."""

    @abstractmethod
    def _prior_from_lists(self, lists: list[list[float]]) -> Any:
        """Convert plain lists to a backend-native prior."""

    @abstractmethod
    def _policy_array(self, agent: Any) -> Optional[np.ndarray]:
        """Return the agent's policy array as a numpy ndarray (or None)."""

    @abstractmethod
    def _warm_up(self) -> None:
        """Backend-specific compile / warm-up. No-op for the NumPy backend."""

    # ------------------------------------------------------------------ #
    # Shared internals
    # ------------------------------------------------------------------ #

    @staticmethod
    def _uniform(n: int) -> list[float]:
        if n <= 0:
            return []
        return [1.0 / n] * n

    def _first_step_row(self, action_index: int) -> np.ndarray:
        """The first-step control row of a policy that begins with ``action_index``."""
        if self._policies is None:
            raise RuntimeError("policy array unavailable")
        first = self._policies[:, 0, ACTION_FACTOR]
        matches = np.flatnonzero(first == action_index)
        if matches.size == 0:
            raise RuntimeError(f"no policy begins with action {action_index}")
        k = int(matches[0])
        return self._policies[k : k + 1, 0, :]

    def _infer(
        self, obs: list[int]
    ) -> tuple[list[list[float]], list[float], int, Any, Any, Any]:
        """Run infer + EFE and prepare the post-step update.

        Pure compute (no timeout, no side effects on ``self``). Returns the
        posterior, per-action EFE, chosen action, the raw qs, the agent that
        results from learning the previous transition (or the current agent if
        there is no previous step), and the next carried prior.
        """
        qs, neg_efe = self._cycle(self._agent, obs, self._prior)
        posterior = self._posterior_lists(qs)
        neg = np.asarray(neg_efe).reshape(-1)
        efe = [float(-x) for x in neg]
        n_actions = self._model.num_actions

        if self._policies is None or self._policies.ndim != 3:
            if self._policy_len == 1:
                # Fallback: with horizon 1 the policy vector is one-per-action.
                if len(efe) < n_actions:
                    efe = efe + [float("inf")] * (n_actions - len(efe))
                elif len(efe) > n_actions:
                    efe = efe[:n_actions]
                best_idx = int(min(range(n_actions), key=lambda i: efe[i]))
            else:
                shape_info = "unavailable" if self._policies is None else f"ndim={self._policies.ndim}"
                raise RuntimeError(
                    f"Policy array {shape_info} but policy_len={self._policy_len}; "
                    f"cannot compute per-action EFE at horizon > 1"
                )
            return posterior, efe, best_idx, qs, self._agent, self._prior

        first = self._policies[:, 0, ACTION_FACTOR]
        if len(efe) != len(first):
            raise RuntimeError(
                f"EFE vector length ({len(efe)}) does not match policy count ({len(first)})"
            )

        per_action_efe = [float("inf")] * n_actions
        for p_idx, action_first in enumerate(first):
            a = int(action_first)
            if 0 <= a < n_actions and efe[p_idx] < per_action_efe[a]:
                per_action_efe[a] = efe[p_idx]
        best_idx = int(min(range(n_actions), key=lambda i: per_action_efe[i]))

        # Learn the previous transition, then propagate the posterior under the
        # chosen action to become the next carried prior.
        agent = self._agent
        if (
            self._model.pB is not None
            and self._prev_qs is not None
            and self._prev_action is not None
        ):
            row = self._first_step_row(self._prev_action)
            agent = self._learn(agent, self._prev_qs, qs, row, obs)
            agent = self._restore_action_factor(agent)
            agent = self._cap_perceptual_transitions(agent)

        row_a = self._first_step_row(best_idx)
        prior = self._propagate(agent, row_a, qs)
        return posterior, per_action_efe, best_idx, qs, agent, prior

    def _restore_action_factor(self, agent: Any) -> Any:
        """Lock factor 0 back to the model's original dynamics."""
        B = self._get_B(agent)
        B[ACTION_FACTOR] = self._orig_B0
        pB = self._get_pB(agent)
        if self._orig_pB0 is not None:
            pB[ACTION_FACTOR] = self._orig_pB0
        return self._with_pB_B(agent, pB, B)

    def _cap_perceptual_transitions(self, agent: Any) -> Any:
        """Bound the evidence Nous holds in perceptual transition counts.

        Rescaling any column whose concentration exceeds
        ``transition_max_concentration`` keeps the Dirichlet posterior sensitive
        to change instead of freezing as counts grow toward float32 infinity.
        The action factor (factor 0) is excluded — it is restored separately.
        """
        cap = self._model.transition_max_concentration
        pB = self._get_pB(agent)
        B = self._get_B(agent)
        perceptual = list(range(1, self._model.num_factors))
        for f in perceptual:
            pb = np.asarray(pB[f])
            col_sums = pb.sum(axis=0, keepdims=True)
            scale = np.where(col_sums > cap, cap / col_sums, 1.0)
            pb_scaled = pb * scale
            b_sums = pb_scaled.sum(axis=0, keepdims=True)
            b_sums = np.where(b_sums == 0.0, 1.0, b_sums)
            pB[f] = pb_scaled
            B[f] = pb_scaled / b_sums
        return self._with_pB_B(agent, pB, B)

    def seed_posterior(self, posterior: list[list[float]]) -> bool:
        if len(posterior) != len(self._model.num_states):
            log.warning(
                "nous: seeded posterior factor count mismatch: %d vs %d",
                len(posterior),
                len(self._model.num_states),
            )
            return False
        for i, (dist, size) in enumerate(zip(posterior, self._model.num_states)):
            if len(dist) != size:
                log.warning(
                    "nous: seeded posterior length mismatch at factor %d: %d vs %d",
                    i,
                    len(dist),
                    size,
                )
                return False
            if not all(
                isinstance(x, (int, float)) and math.isfinite(x) and x >= 0
                for x in dist
            ):
                log.warning(
                    "nous: seeded posterior has non-finite or negative value at factor %d",
                    i,
                )
                return False
        self._last_posterior = [list(p) for p in posterior]
        return True

    def infer(self, obs: Sequence[int]) -> EngineResult:
        """Run one belief-update + EFE policy-selection step on raw obs indices."""
        obs = [int(o) for o in obs]
        start = time.perf_counter()
        captured_generation = self._generation
        future = self._executor.submit(self._infer, obs)
        try:
            posterior, efe, best_idx, qs, agent, prior = future.result(
                timeout=self._efe_timeout_s
            )
        except FuturesTimeout:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            log.warning(
                "EFE planning overran %.0f ms; returning last posterior",
                self._efe_timeout_s * 1000.0,
            )
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
        if captured_generation != self._generation:
            log.debug(
                "nous infer result is stale (generation changed from %d to %d); "
                "dropping without committing",
                captured_generation,
                self._generation,
            )
            return EngineResult(
                posterior=[list(p) for p in self._last_posterior],
                policy_efe=list(self._last_efe),
                action_index=0,
                action=self._model.actions[0],
                timed_out=False,
                elapsed_ms=elapsed_ms,
                obs=obs,
            )
        # Commit the learned transition update and the carried prior only after
        # a successful, non-timeout step.
        self._agent = agent
        self._prior = prior
        self._prev_qs = qs
        self._prev_qs_committed = qs
        self._prev_action = best_idx
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
        """Live entry-point: encode the snapshot to obs and run one inference."""
        obs = encode_snapshot(snapshot, self._model)
        obs[ACTION_FACTOR] = self._prev_action if self._prev_action is not None else 0
        return self.infer(obs)

    def record_taken_action(self, action_index: int) -> None:
        """Tell the engine which action was actually executed.

        Call this when an external wrapper overrides the silicon-selected action.
        The carried prior is re-propagated from the last committed posterior
        under the action that was actually taken.
        """
        if self._prev_qs_committed is None:
            return
        self._prev_action = int(action_index)
        row = self._first_step_row(action_index)
        self._prior = self._propagate(self._agent, row, self._prev_qs_committed)

    def learned_state(self) -> dict[str, Any]:
        """Return the learned transition prior and carried belief.

        Arrays are returned in unbatched numpy form so the serialized shape is
        comparable to the model's pB/D shapes and interchangeable between
        backends.
        """
        if self._model.pB is None:
            return {}
        pB_out = [arr.tolist() for arr in self._get_pB(self._agent)]
        prior_out = self._prior_lists(self._prior)
        return {
            "pB": pB_out,
            "carried_prior": prior_out,
            "last_action_index": self._prev_action,
        }

    def load_learned_state(self, state: dict[str, Any]) -> bool:
        """Validate and restore a serialized learned model.

        Any in-flight inference from before this call is considered stale and
        is dropped at commit time.
        """
        self._generation += 1
        if self._model.pB is None:
            log.warning("nous load_learned_state: this model does not learn its transitions")
            return False

        expected_shapes = [pb.shape for pb in self._model.pB]
        pB_raw = state.get("pB")
        prior_raw = state.get("carried_prior")
        last_action = state.get("last_action_index")

        if not isinstance(pB_raw, list) or len(pB_raw) != len(expected_shapes):
            log.warning("nous load_learned_state: pB factor count mismatch")
            return False

        new_pB: list[np.ndarray] = []
        for f, (raw, expected) in enumerate(zip(pB_raw, expected_shapes)):
            try:
                pb = np.asarray(raw, dtype=np.float64)
            except Exception as exc:
                log.warning(
                    "nous load_learned_state: pB factor %d not array-like: %s", f, exc
                )
                return False
            if pb.shape != expected:
                log.warning(
                    "nous load_learned_state: pB factor %d shape %s != expected %s",
                    f,
                    pb.shape,
                    expected,
                )
                return False
            if not np.all(np.isfinite(pb)):
                log.warning(
                    "nous load_learned_state: pB factor %d contains non-finite values", f
                )
                return False
            if np.any(pb < 0):
                log.warning(
                    "nous load_learned_state: pB factor %d contains negative values", f
                )
                return False
            if np.any(pb.sum(axis=0) <= 0.0):
                log.warning(
                    "nous load_learned_state: pB factor %d has a zero column", f
                )
                return False
            new_pB.append(pb)

        prior_expected = [d.shape for d in self._model.D]
        if not isinstance(prior_raw, list) or len(prior_raw) != len(prior_expected):
            log.warning("nous load_learned_state: carried_prior factor count mismatch")
            return False

        new_prior_lists: list[list[float]] = []
        for f, (raw, expected) in enumerate(zip(prior_raw, prior_expected)):
            try:
                p = np.asarray(raw, dtype=np.float64)
            except Exception as exc:
                log.warning(
                    "nous load_learned_state: carried_prior factor %d not array-like: %s",
                    f,
                    exc,
                )
                return False
            if p.shape == expected:
                new_prior_lists.append(p.tolist())
            elif p.shape == (1,) + expected:
                new_prior_lists.append(p[0].tolist())
            else:
                log.warning(
                    "nous load_learned_state: carried_prior factor %d shape %s "
                    "!= expected %s or %s",
                    f,
                    p.shape,
                    expected,
                    (1,) + expected,
                )
                return False
            if not np.all(np.isfinite(p)) or np.any(p < 0):
                log.warning(
                    "nous load_learned_state: carried_prior factor %d has invalid values", f
                )
                return False

        # All checks passed; commit the learned model.
        self._agent = self._make_agent(new_pB)
        self._policies = self._policy_array(self._agent)
        self._prior = self._prior_from_lists(new_prior_lists)
        self._prev_qs = None
        self._prev_qs_committed = None
        self._prev_action = last_action if isinstance(last_action, int) else None
        return True

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


class PymdpEngine(_EngineBase):
    """pymdp 1.0 (JAX) implementation of :class:`ActiveInferenceEngine`."""

    def __init__(
        self,
        model: Optional[GenerativeModel] = None,
        *,
        efe_timeout_ms: float = 250.0,
        policy_len: int = 1,
        num_iter: int = 8,
    ) -> None:
        # JIT functions are independent of any particular agent instance, so
        # build them before the base class constructs the first agent.
        self._jit_cycle = self._build_jit_cycle()
        self._jit_learn = self._build_jit_learn()
        self._jit_propagate = self._build_jit_propagate()
        super().__init__(
            model=model,
            efe_timeout_ms=efe_timeout_ms,
            policy_len=policy_len,
            num_iter=num_iter,
        )
        # Kept for backward compatibility with tests that inspect batched slices.
        self._orig_pB0_batched: Optional[Any] = None
        self._orig_B0_batched: Optional[Any] = None
        if self._model.pB is not None:
            import jax.numpy as jnp
            self._orig_pB0_batched = jnp.array(self._model.pB[ACTION_FACTOR])[None]
            self._orig_B0_batched = jnp.array(self._model.B[ACTION_FACTOR])[None]

    # ------------------------------------------------------------------ #
    # Backend hooks
    # ------------------------------------------------------------------ #

    def _make_agent(self, pB: Optional[list[np.ndarray]]) -> Any:
        import jax.numpy as jnp
        from pymdp.agent import Agent

        A = [jnp.array(a)[None] for a in self._model.A]
        C = [jnp.array(c)[None] for c in self._model.C]
        D = [jnp.array(d)[None] for d in self._model.D]

        if pB is None and self._model.pB is not None:
            pB = self._model.pB
        learning = pB is not None

        B: list[Any] = []
        if learning:
            for pb in pB:
                pb_arr = jnp.array(pb)
                col_sums = pb_arr.sum(axis=0, keepdims=True)
                col_sums = jnp.where(col_sums == 0.0, 1.0, col_sums)
                B.append((pb_arr / col_sums)[None])
        else:
            B = [jnp.array(b)[None] for b in self._model.B]

        kwargs: dict[str, Any] = {}
        if learning:
            kwargs.update(
                pB=[jnp.array(pb)[None] for pb in pB],
                B_action_dependencies=self._model.B_action_dependencies,
                num_controls=[self._model.num_actions],
                use_param_info_gain=True,
                learn_B=True,
            )

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
                **kwargs,
            )

    def _cycle(self, agent: Any, obs: list[int], prior: Any) -> tuple[Any, np.ndarray]:
        import jax
        import jax.numpy as jnp

        obs_batched = [jnp.array([int(o)]) for o in obs]
        qs, neg_efe = self._jit_cycle(agent, obs_batched, prior)
        jax.block_until_ready((qs, neg_efe))
        return qs, np.asarray(neg_efe).reshape(-1)

    def _posterior_lists(self, qs: Any) -> list[list[float]]:
        posterior: list[list[float]] = []
        for q in qs:
            arr = np.asarray(q).reshape(-1)
            s = float(arr.sum())
            if s > 0:
                arr = arr / s
            posterior.append([float(x) for x in arr])
        return posterior

    def _learn(
        self, agent: Any, prev_qs: Any, qs: Any, row: np.ndarray, obs: list[int]
    ) -> Any:
        import jax
        import jax.numpy as jnp

        beliefs = [jnp.concatenate([pq, q], axis=1) for pq, q in zip(prev_qs, qs)]
        obs_batched = [jnp.array([int(o)]) for o in obs]
        acts = jnp.asarray(row)[:, None, :]
        agent = self._jit_learn(agent, beliefs, obs_batched, acts)
        jax.block_until_ready(agent)
        return agent

    def _propagate(self, agent: Any, row: np.ndarray, qs: Any) -> Any:
        import jax
        import jax.numpy as jnp

        prior = self._jit_propagate(agent, jnp.asarray(row), qs)
        jax.block_until_ready(prior)
        return prior

    @staticmethod
    def _unbatch_array(arr: Any) -> np.ndarray:
        a = np.asarray(arr)
        if a.ndim == 4 and a.shape[0] == 1:
            a = a[0]
        return a

    def _get_pB(self, agent: Any) -> list[np.ndarray]:
        pB = getattr(agent, "pB", None)
        if pB is None:
            return []
        return [self._unbatch_array(pb) for pb in pB]

    def _get_B(self, agent: Any) -> list[np.ndarray]:
        return [self._unbatch_array(b) for b in agent.B]

    def _with_pB_B(
        self, agent: Any, pB: list[np.ndarray], B: list[np.ndarray]
    ) -> Any:
        import equinox as eqx
        import jax.numpy as jnp

        # equinox.tree_at needs a selector that picks the nodes out of the
        # tree it is given (not nodes captured from `agent` beforehand).
        B_batched = [jnp.array(b)[None] for b in B]
        if pB and getattr(agent, "pB", None) is not None:
            pB_batched = [jnp.array(pb)[None] for pb in pB]

            def _select(ag: Any) -> tuple[Any, ...]:
                return tuple(ag.pB) + tuple(ag.B)

            return eqx.tree_at(_select, agent, tuple(pB_batched) + tuple(B_batched))

        def _select_B(ag: Any) -> tuple[Any, ...]:
            return tuple(ag.B)

        return eqx.tree_at(_select_B, agent, tuple(B_batched))

    def _initial_prior(self, agent: Any) -> Any:
        return list(agent.D)

    def _prior_lists(self, prior: Any) -> list[list[float]]:
        return [np.asarray(p).reshape(-1).tolist() for p in prior]

    def _prior_from_lists(self, lists: list[list[float]]) -> Any:
        import jax.numpy as jnp
        return [jnp.array(np.asarray(p, dtype=np.float64)[None]) for p in lists]

    def _policy_array(self, agent: Any) -> Optional[np.ndarray]:
        try:
            policies = agent.policies
            arr = getattr(policies, "policy_arr", None)
            return np.asarray(arr) if arr is not None else None
        except Exception:
            log.debug("pymdp policy array unavailable at construction", exc_info=True)
            return None

    def _warm_up(self) -> None:
        try:
            self._infer(encode_snapshot_default(self._model))
        except Exception:
            log.debug("pymdp warm-up step failed (non-fatal)", exc_info=True)

        if self._model.pB is None:
            return

        try:
            import equinox as eqx
            import jax
            import jax.numpy as jnp

            obs_batched = [jnp.array([o]) for o in encode_snapshot_default(self._model)]
            qs_dummy = [jnp.full((1, n), 1.0 / n) for n in self._model.num_states]
            beliefs = [jnp.concatenate([q, q], axis=1) for q in qs_dummy]
            if self._policies is not None:
                row = jnp.asarray(self._first_step_row(0))
            else:
                row = jnp.zeros((1, len(self._model.num_states)))
            acts = row[:, None, :]
            _agent_tmp = self._jit_learn(self._agent, beliefs, obs_batched, acts)
            if self._orig_pB0_batched is not None and self._orig_B0_batched is not None:
                _agent_tmp = eqx.tree_at(
                    lambda ag: (ag.pB[ACTION_FACTOR], ag.B[ACTION_FACTOR]),
                    _agent_tmp,
                    (self._orig_pB0_batched, self._orig_B0_batched),
                )
            _ = self._jit_propagate(_agent_tmp, row, qs_dummy)
            jax.block_until_ready(_)
        except Exception:
            log.debug("pymdp learning warm-up failed (non-fatal)", exc_info=True)

    # ------------------------------------------------------------------ #
    # pymdp-specific helpers
    # ------------------------------------------------------------------ #

    def _build_jit_cycle(self) -> Any:
        import jax

        def _cycle(agent: Any, obs_batched: list[Any], prior: list[Any]) -> tuple[Any, Any]:
            qs = agent.infer_states(obs_batched, empirical_prior=prior)
            _q_pi, neg_efe = agent.infer_policies(qs)
            return qs, neg_efe

        return jax.jit(_cycle)

    @staticmethod
    def _build_jit_learn() -> Any:
        import jax

        def _learn(agent: Any, beliefs: list[Any], obs: list[Any], acts: Any) -> Any:
            return agent.infer_parameters(beliefs, obs, acts, beliefs_B=beliefs)

        return jax.jit(_learn)

    @staticmethod
    def _build_jit_propagate() -> Any:
        import jax

        def _propagate(agent: Any, act: Any, qs: Any) -> Any:
            return agent.update_empirical_prior(act, qs)

        return jax.jit(_propagate)


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

    @property
    def policy_len(self) -> int:
        return 1

    def seed_posterior(self, posterior: list[list[float]]) -> bool:
        if len(posterior) != len(self._last_posterior):
            log.warning("nous: fake engine seeded posterior factor count mismatch")
            return False
        for i, (dist, expected) in enumerate(zip(posterior, self._last_posterior)):
            if len(dist) != len(expected):
                log.warning(
                    "nous: fake engine seeded posterior length mismatch at factor %d", i
                )
                return False
            if not all(
                isinstance(x, (int, float)) and math.isfinite(x) and x >= 0
                for x in dist
            ):
                log.warning(
                    "nous: fake engine seeded posterior has non-finite or negative value at factor %d",
                    i,
                )
                return False
        self._last_posterior = [list(p) for p in posterior]
        return True

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

    @property
    def uses_param_info_gain(self) -> bool:
        return False

    def record_taken_action(self, action_index: int) -> None:
        """No-op: the fake engine has no learned transitions to re-propagate."""
        return

    def learned_state(self) -> dict[str, Any]:
        return {}

    def load_learned_state(self, state: dict[str, Any]) -> bool:
        return False


__all__ = [
    "ActiveInferenceEngine",
    "EngineResult",
    "PymdpEngine",
    "FakeEngine",
    "normalised_entropy",
]
