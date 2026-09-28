# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""NumPy-only active-inference engine for Nous.

This backend shares all guard/bookkeeping logic with :class:`PymdpEngine`
through :class:`_EngineBase`. It uses :class:`NumpyAgent` for the numerics and
imports no JAX / pymdp code, so Nous can run on hosts without the ``reasoning``
extra.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np

from kaine.modules.nous.engine import _EngineBase
from kaine.modules.nous.generative_model import GenerativeModel


class NumpyActiveInferenceEngine(_EngineBase):
    """Pure-NumPy implementation of :class:`ActiveInferenceEngine`."""

    def __init__(
        self,
        model: Optional[GenerativeModel] = None,
        *,
        efe_timeout_ms: float = 250.0,
        policy_len: int = 1,
        num_iter: int = 8,
    ) -> None:
        super().__init__(
            model=model,
            efe_timeout_ms=efe_timeout_ms,
            policy_len=policy_len,
            num_iter=num_iter,
        )

    # ------------------------------------------------------------------ #
    # Backend hooks
    # ------------------------------------------------------------------ #

    def _make_agent(self, pB: Optional[list[np.ndarray]]) -> Any:
        from kaine.modules.nous.numpy_aif import NumpyAgent, dirichlet_expected_value

        A = [np.asarray(a, dtype=np.float64) for a in self._model.A]
        C = [np.asarray(c, dtype=np.float64) for c in self._model.C]
        D = [np.asarray(d, dtype=np.float64) for d in self._model.D]

        if pB is None and self._model.pB is not None:
            pB = self._model.pB

        if pB is not None:
            B = [dirichlet_expected_value(np.asarray(pb, dtype=np.float64)) for pb in pB]
            agent = NumpyAgent(
                A=A,
                B=B,
                C=C,
                D=D,
                A_dependencies=self._model.A_dependencies,
                pB=[np.asarray(pb, dtype=np.float64) for pb in pB],
                B_action_dependencies=self._model.B_action_dependencies,
                num_controls=[self._model.num_actions],
                policy_len=self._policy_len,
                num_iter=self._num_iter,
                use_param_info_gain=True,
                learn_B=True,
            )
        else:
            B = [np.asarray(b, dtype=np.float64) for b in self._model.B]
            agent = NumpyAgent(
                A=A,
                B=B,
                C=C,
                D=D,
                A_dependencies=self._model.A_dependencies,
                policy_len=self._policy_len,
                num_iter=self._num_iter,
                use_param_info_gain=True,
                learn_B=False,
            )

        return agent

    def _cycle(
        self, agent: Any, obs: list[int], prior: Any
    ) -> tuple[Any, np.ndarray]:
        qs = agent.infer_states(obs, prior)
        _q_pi, neg_efe = agent.infer_policies(qs)
        return qs, np.asarray(neg_efe, dtype=np.float64).reshape(-1)

    def _posterior_lists(self, qs: Any) -> list[list[float]]:
        posterior: list[list[float]] = []
        for q in qs:
            arr = np.asarray(q, dtype=np.float64).reshape(-1)
            s = float(arr.sum())
            if s > 0:
                arr = arr / s
            posterior.append([float(x) for x in arr])
        return posterior

    def _learn(
        self, agent: Any, prev_qs: Any, qs: Any, row: np.ndarray, obs: list[int]
    ) -> Any:
        row_flat = np.asarray(row, dtype=np.int64).reshape(-1)
        return agent.infer_parameters(prev_qs, qs, row_flat)

    def _propagate(self, agent: Any, row: np.ndarray, qs: Any) -> Any:
        row_flat = np.asarray(row, dtype=np.int64).reshape(-1)
        return agent.update_empirical_prior(row_flat, qs)

    def _get_pB(self, agent: Any) -> list[np.ndarray]:
        if agent.pB is None:
            return []
        return [np.asarray(pb, dtype=np.float64).copy() for pb in agent.pB]

    def _get_B(self, agent: Any) -> list[np.ndarray]:
        return [np.asarray(b, dtype=np.float64).copy() for b in agent.B]

    def _with_pB_B(
        self, agent: Any, pB: list[np.ndarray], B: list[np.ndarray]
    ) -> Any:
        pB_out = [np.asarray(pb, dtype=np.float64) for pb in pB] if pB else None
        B_out = [np.asarray(b, dtype=np.float64) for b in B]
        return agent.with_state(B=B_out, pB=pB_out)

    def _initial_prior(self, agent: Any) -> Any:
        return [np.asarray(d, dtype=np.float64) for d in agent.D]

    def _prior_lists(self, prior: Any) -> list[list[float]]:
        return [np.asarray(p, dtype=np.float64).reshape(-1).tolist() for p in prior]

    def _prior_from_lists(self, lists: list[list[float]]) -> Any:
        return [np.asarray(p, dtype=np.float64) for p in lists]

    def _policy_array(self, agent: Any) -> Optional[np.ndarray]:
        return np.asarray(agent.policies, dtype=np.int64)

    def _warm_up(self) -> None:
        """NumPy needs no compile step."""
        return
