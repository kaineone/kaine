# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Active-inference agent adapter — drives the *live* Nous pymdp engine.

This adapter is the head-to-head subject under test. It does NOT re-implement
active inference: it constructs a :class:`kaine.modules.nous.generative_model.
GenerativeModel` from an env's ``A``/``B``/``C``/``D`` tensors and runs it
through :class:`kaine.modules.nous.engine.PymdpEngine` — the *same* pymdp 1.0
``Agent`` + belief-update + EFE policy-selection core the live cognitive loop
drives (``PymdpEngine.infer``). So the benchmarked engine IS the live engine;
only the observations and the generative model are the task's rather than the
workspace's. No bus, no intents, no entity, no cognitive cycle.

At each env step the adapter:
  1. feeds the env's per-modality observation indices to ``engine.infer`` →
     real ``infer_states`` (belief update) + ``infer_policies`` (EFE per policy);
  2. selects the EFE-minimising policy and emits its **first controllable
     action** (the env's action == the location/choice the policy moves to).

For ``policy_len > 1`` tasks (the epistemic T-maze needs lookahead to value the
cue), the engine's per-action EFE convenience field is insufficient (it assumes
1-step policies), so the adapter reads the agent's policy array and maps the
lowest-EFE *policy* back to its first action — using the engine's own agent and
its own computed EFE. The belief update and EFE computation themselves are
entirely the live engine's.
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np

from kaine.evaluation.benchmarks.active_inference.envs import DiscretePOMDP
from kaine.modules.nous.engine import PymdpEngine
from kaine.modules.nous.generative_model import GenerativeModel


def build_model_for_env(task: DiscretePOMDP) -> GenerativeModel:
    """Wrap an env's generative tensors in Nous's :class:`GenerativeModel`.

    The env already exposes ``A``/``B``/``D`` and ``preference_C()`` in pymdp's
    list-over-modalities / list-over-factors layout, so this is a faithful
    repackaging — the AIF agent is handed exactly the model the env's
    ``reward_matching`` documents. ``state_labels`` are synthesised positionally
    (the benchmark does not need the human-readable Nous belief contract).
    """
    A = [np.asarray(a, dtype=float) for a in task.A]
    B = [np.asarray(b, dtype=float) for b in task.B]
    C = [np.asarray(c, dtype=float) for c in task.preference_C()]
    D = [np.asarray(d, dtype=float) for d in task.D]
    num_states = [int(b.shape[0]) for b in B]
    num_obs = [int(a.shape[0]) for a in A]
    state_labels = [tuple(f"f{f}_s{s}" for s in range(n)) for f, n in enumerate(num_states)]
    # The controllable factor is factor 0 (its B carries one slice per action);
    # its action space is the env's action set.
    actions = tuple(f"action_{i}" for i in range(task.num_actions()))
    return GenerativeModel(
        A=A,
        B=B,
        C=C,
        D=D,
        A_dependencies=[list(dep) for dep in task.A_dependencies],
        num_states=num_states,
        num_obs=num_obs,
        state_labels=state_labels,
        actions=actions,
    )


class AIFAgent:
    """Drives a :class:`PymdpEngine` on a :class:`DiscretePOMDP`.

    Construction builds the env's generative model and the live engine once
    (warming the JAX trace); :meth:`act` runs one real belief-update + EFE
    policy-selection step and returns the first action of the EFE-minimising
    policy. The engine is reused across all episodes/steps of a task (as the
    live module reuses it across cognitive cycles).
    """

    def __init__(
        self,
        task: DiscretePOMDP,
        *,
        efe_timeout_ms: float = 60_000.0,
        num_iter: int = 16,
        gamma: float = 16.0,
    ) -> None:
        self._task = task
        self._model = build_model_for_env(task)
        self._policy_len = int(getattr(task, "policy_len", 1))
        # Reuse the live engine. A generous timeout: this is an offline
        # benchmark, not the ~300 ms cognitive cycle, so EFE must complete
        # rather than degrade to a stale posterior.
        self._engine = PymdpEngine(
            self._model,
            efe_timeout_ms=efe_timeout_ms,
            policy_len=self._policy_len,
            num_iter=num_iter,
        )
        self._gamma = gamma
        # Precompute the map from policy index -> first controllable action.
        self._policy_first_action = self._extract_policy_first_actions()
        self.last_efe: list[float] = []
        self.last_posterior: list[list[float]] = []
        # Sequential belief state: the empirical prior carried between steps. It
        # is the agent's running belief over hidden states, propagated through
        # the chosen action's transition (pymdp ``update_empirical_prior``) so
        # information gathered earlier (e.g. what the cue revealed) persists.
        # Reset to the generative-model prior ``D`` at each episode boundary.
        self._prior: Any = None
        self.reset_belief()

    # -- policy decoding -----------------------------------------------------

    def _extract_policy_first_actions(self) -> np.ndarray:
        """First controllable-factor action for each pymdp policy.

        ``policy_arr`` has shape ``(num_policies, policy_len, num_control_factors)``.
        Factor 0 is the env's controllable factor, so column 0 of timestep 0 is
        the first action. With ``policy_len == 1`` this is the identity over
        actions (and matches the engine's own per-action EFE ordering).
        """
        agent = self._engine._agent  # the live engine's pymdp Agent
        policy_arr = np.asarray(agent.policies.policy_arr)
        # shape (npol, policy_len, n_control_factors)
        return policy_arr[:, 0, 0].astype(int)

    # -- belief state --------------------------------------------------------

    def reset_belief(self) -> None:
        """Reset the carried belief to the generative-model prior ``D``.

        Called at the start of each episode so the hidden context (e.g. the
        T-maze reward condition) is unknown again.
        """
        import jax.numpy as jnp

        # agent.D is the prior over hidden states (list per factor). Carry a
        # batched copy (pymdp uses a leading batch dim of size 1).
        self._prior = [jnp.array(np.asarray(d).reshape(1, -1)) for d in self._model.D]

    # -- one decision --------------------------------------------------------

    def act(self, obs: tuple[int, ...]) -> int:
        """Run one real EFE step on the observation and return the first action.

        Performs the live engine's belief update from the *carried* prior (so
        information gathered earlier persists), selects the EFE-minimising
        policy, returns its first controllable action, and propagates the belief
        through that action's transition for the next step.
        """
        action, neg_efe, posterior, qs = self._infer_policy_efe(obs)
        self.last_efe = [float(-x) for x in neg_efe]
        self.last_posterior = posterior
        # Propagate belief through the chosen action for the next step.
        self._prior = self._propagate(action, qs)
        return action

    def _infer_policy_efe(self, obs: tuple[int, ...]):
        """Belief update + per-policy neg-EFE using the live engine's agent.

        Calls the identical pymdp ``infer_states`` / ``infer_policies`` the
        engine's :meth:`PymdpEngine.infer` uses, from the carried empirical
        prior. The engine's ``_infer`` collapses EFE to per-action (lossy for
        multi-step policies); here we keep the full per-policy vector and decode
        its first action. It runs on the engine's own warmed agent, so it is the
        live engine's computation, read out at policy granularity.
        """
        import jax
        import jax.numpy as jnp

        agent = self._engine._agent
        obs_batched = [jnp.array([int(o)]) for o in obs]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            qs = agent.infer_states(obs_batched, empirical_prior=self._prior)
            _q_pi, neg_efe = agent.infer_policies(qs)
            jax.block_until_ready((qs, neg_efe))
        neg = np.asarray(neg_efe).reshape(-1)
        posterior: list[list[float]] = []
        for q in qs:
            arr = np.asarray(q).reshape(-1)
            s = float(arr.sum())
            if s > 0:
                arr = arr / s
            posterior.append([float(x) for x in arr])
        best_policy = int(np.argmin(-neg))
        action = int(self._policy_first_action[best_policy])
        return action, [float(x) for x in neg], posterior, qs

    def _propagate(self, action: int, qs: Any) -> Any:
        """Next empirical prior = transition applied to the current posterior.

        Uses pymdp ``update_empirical_prior`` with a per-control-factor action
        vector (only factor 0 is controllable; uncontrollable factors take their
        single slice). This is the live engine's transition model carrying the
        belief forward.
        """
        import jax.numpy as jnp

        agent = self._engine._agent
        n_ctrl = len(agent.num_controls) if hasattr(agent, "num_controls") else 1
        # Build the action vector: chosen action on the controllable factor 0,
        # 0 (the only slice) on uncontrollable factors.
        act_vec = [0] * n_ctrl
        act_vec[0] = int(action)
        action_arr = jnp.array(act_vec).reshape(1, -1)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                return agent.update_empirical_prior(action_arr, qs)
            except Exception:
                # Fall back to the static prior D if propagation is unsupported
                # for this model shape — degrades to memoryless (still real).
                return self._prior

    def close(self) -> None:
        self._engine.close()


__all__ = ["AIFAgent", "build_model_for_env"]
