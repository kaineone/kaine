# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Pure NumPy active-inference engine reproducing pymdp 1.0 for KAINE models."""

from __future__ import annotations

import copy
import itertools

import numpy as np

# pymdp.maths.MINVAL: float64 machine epsilon.
MINVAL = float(np.finfo(np.float64).eps)
GAMMA = 16.0


def log_stable(x: np.ndarray) -> np.ndarray:
    """Stable logarithm with minimum clipping (matches pymdp.maths.log_stable)."""
    return np.log(np.clip(np.asarray(x, dtype=np.float64), min=MINVAL))


def stable_xlogx(x: np.ndarray) -> np.ndarray:
    """``x log(x)`` with non-zero clipping (matches pymdp.maths.stable_xlogx)."""
    x = np.asarray(x, dtype=np.float64)
    return x * np.log(np.clip(x, min=MINVAL))


def stable_entropy(x: np.ndarray) -> np.ndarray:
    """Entropy of a probability-like tensor (matches pymdp.maths.stable_entropy)."""
    return -stable_xlogx(x).sum()


def _digamma(x: np.ndarray) -> np.ndarray:
    """Digamma for positive arguments, in NumPy (no SciPy).

    Shifts each value up to at least 6 with the recurrence
    psi(x) = psi(x + 1) - 1/x, then applies the asymptotic series; the error
    is far below the 1e-4 parity tolerance.
    """
    x = np.asarray(x, dtype=np.float64).copy()
    result = np.zeros_like(x)
    for _ in range(6):
        small = x < 6.0
        if not small.any():
            break
        result[small] -= 1.0 / x[small]
        x[small] += 1.0
    inv = 1.0 / x
    inv2 = inv * inv
    series = inv2 * (
        1.0 / 12.0
        - inv2 * (1.0 / 120.0 - inv2 * (1.0 / 252.0 - inv2 * (1.0 / 240.0 - inv2 * (1.0 / 132.0))))
    )
    return result + np.log(x) - 0.5 * inv - series


def _exact_wnorm(A: np.ndarray) -> np.ndarray:
    """Reproduce pymdp.maths._exact_wnorm: -1 times eq. (D.15) of Da Costa et al. (2020)."""
    A = np.asarray(A, dtype=np.float64)
    safe_A = np.clip(A, MINVAL, None)
    safe_sumA = np.clip(safe_A.sum(axis=0), MINVAL, None)
    wA = (
        np.log(safe_sumA) - np.log(safe_A)
        + 1.0 / safe_A - 1.0 / safe_sumA
        + _digamma(safe_A) - _digamma(safe_sumA)
    )
    return -wA


def spm_wnorm(A: np.ndarray, exact_param_info_gain: bool = True) -> np.ndarray:
    """Weight matrix for parameter information gain (matches pymdp.maths.spm_wnorm)."""
    A = np.asarray(A, dtype=np.float64)
    if exact_param_info_gain:
        return _exact_wnorm(A)
    norm = 1.0 / A.sum(axis=0)
    avg = 1.0 / (A + MINVAL)
    return norm - avg


def construct_policies(
    num_states: list[int],
    num_controls: list[int] | None = None,
    policy_len: int = 1,
    control_fac_idx: list[int] | None = None,
) -> np.ndarray:
    """Reproduce pymdp.control.construct_policies ordering exactly."""
    num_factors = len(num_states)
    if control_fac_idx is None:
        if num_controls is not None:
            control_fac_idx = [f for f, n_c in enumerate(num_controls) if n_c > 1]
        else:
            control_fac_idx = list(range(num_factors))

    if num_controls is None:
        num_controls = [
            num_states[c_idx] if c_idx in control_fac_idx else 1
            for c_idx in range(num_factors)
        ]

    x = num_controls * policy_len
    policies = list(itertools.product(*[list(range(i)) for i in x]))
    result = []
    for pol_tuple in policies:
        arr = np.array(pol_tuple).reshape(policy_len, num_factors)
        result.append(arr)
    return np.stack(result, axis=0).astype(np.int64)


def factor_dot(
    M: np.ndarray,
    xs: list[np.ndarray],
    keep_dims: tuple[int] | None = None,
) -> np.ndarray:
    """Reproduce pymdp.maths.factor_dot using ``numpy.einsum``."""
    M = np.asarray(M, dtype=np.float64)
    xs = [np.asarray(x, dtype=np.float64) for x in xs]
    if keep_dims is None:
        d = 0
        keep_dims = ()
    else:
        d = len(keep_dims)
        keep_dims = tuple(sorted(keep_dims))
    if M.ndim != len(xs) + d:
        raise ValueError(
            f"factor_dot: M.ndim={M.ndim} != len(xs)={len(xs)} + d={d}"
        )

    contract_axes = [i for i in range(M.ndim) if i not in keep_dims]

    # No contraction needed (e.g. single-factor likelihood).
    if len(xs) == 0:
        if len(contract_axes) == 0:
            return M
        return M.sum(axis=tuple(contract_axes))

    letters: dict[int, str] = {}
    next_letter = 0

    def get_letter(idx: int) -> str:
        nonlocal next_letter
        if idx not in letters:
            letters[idx] = chr(ord("a") + next_letter)
            next_letter += 1
        return letters[idx]

    m_sub = "".join(get_letter(i) for i in range(M.ndim))
    x_subs = [get_letter(contract_axes[idx]) for idx in range(len(xs))]
    out_sub = "".join(get_letter(i) for i in range(M.ndim) if i in keep_dims)
    sub = f"{m_sub},{','.join(x_subs)}->{out_sub}"
    return np.einsum(sub, M, *xs, optimize=True)


def compute_log_likelihood(
    obs: list[np.ndarray],
    A: list[np.ndarray],
    distr_obs: bool = True,
) -> np.ndarray:
    """Combined log-likelihood over hidden states."""
    result = [
        compute_log_likelihood_single_modality(o, a, distr_obs=distr_obs)
        for o, a in zip(obs, A)
    ]
    if not result:
        return np.array(0.0)
    total = result[0]
    for r in result[1:]:
        total = total + r
    return total


def compute_log_likelihood_single_modality(
    o_m: np.ndarray,
    A_m: np.ndarray,
    distr_obs: bool = True,
) -> np.ndarray:
    """Observation log-likelihood for a single modality."""
    A_m = np.asarray(A_m, dtype=np.float64)
    if distr_obs:
        o_m = np.asarray(o_m, dtype=np.float64)
        expanded_shape = (1,) * (A_m.ndim - 1)
        expanded_obs = o_m.reshape(o_m.shape + expanded_shape)
        return (expanded_obs * log_stable(A_m)).sum(axis=0)
    else:
        idx = tuple(np.asarray(o_m).reshape(-1))
        return log_stable(A_m[idx])


def _mll_factors(
    qs: list[np.ndarray],
    ll_m: np.ndarray,
    factor_list_m: list[int],
) -> list[np.ndarray]:
    """Map a modality log-likelihood to marginal log-likelihoods for its factors."""
    results = []
    for f in factor_list_m:
        xs = [qs[idx] for idx in factor_list_m if idx != f]
        ax_in_ll = factor_list_m.index(f)
        res = factor_dot(ll_m, xs, keep_dims=(ax_in_ll,))
        results.append(res)
    return results


def _all_marginal_log_likelihood(
    qs: list[np.ndarray],
    log_likelihoods: list[np.ndarray],
    all_factor_lists: list[list[int]],
    num_factors: int,
) -> list[np.ndarray]:
    """Sum modality marginal log-likelihoods into a per-factor vector."""
    qL_marginals = [
        _mll_factors(qs, ll_m, factor_list_m)
        for ll_m, factor_list_m in zip(log_likelihoods, all_factor_lists)
    ]

    qL_all = [np.zeros(1, dtype=np.float64) for _ in range(num_factors)]
    for m, factor_list_m in enumerate(all_factor_lists):
        for dep_idx, f in enumerate(factor_list_m):
            marg = qL_marginals[m][dep_idx]
            target_shape = (np.asarray(qs[f]).shape[0],)
            if marg.shape != target_shape:
                marg = marg.reshape(target_shape)
            qL_all[f] = qL_all[f] + marg
    return qL_all


def softmax(x: np.ndarray) -> np.ndarray:
    """Stable softmax."""
    x = np.asarray(x, dtype=np.float64)
    x = x - x.max()
    e = np.exp(x)
    s = e.sum()
    return e / (s if s > 0 else 1.0)


def run_factorized_fpi(
    A: list[np.ndarray],
    obs: list[np.ndarray],
    prior: list[np.ndarray],
    A_dependencies: list[list[int]],
    num_iter: int = 1,
    distr_obs: bool = True,
) -> list[np.ndarray]:
    """FPI with sparse A_dependencies; matches pymdp.algos.run_factorized_fpi."""
    prior = [np.asarray(p, dtype=np.float64) for p in prior]
    A = [np.asarray(a, dtype=np.float64) for a in A]
    obs = [np.asarray(o, dtype=np.float64) for o in obs]

    if len(prior) == 1:
        log_likelihood = compute_log_likelihood(obs, A, distr_obs=distr_obs)
        log_q = log_likelihood + log_stable(prior[0])
        return [softmax(log_q)]

    log_likelihoods = [
        compute_log_likelihood_single_modality(o, A[m], distr_obs=distr_obs)
        for m, o in enumerate(obs)
    ]

    log_prior = [log_stable(p) for p in prior]
    log_q = [np.zeros_like(p) for p in prior]

    for _ in range(num_iter):
        q = [softmax(lq) for lq in log_q]
        marginal_ll = _all_marginal_log_likelihood(
            q, log_likelihoods, A_dependencies, len(prior)
        )
        log_q = [mll + lp for mll, lp in zip(marginal_ll, log_prior)]

    qs = [softmax(lq) for lq in log_q]
    return qs


def compute_expected_state(
    qs_prior: list[np.ndarray],
    B: list[np.ndarray],
    u_t: np.ndarray,
    B_dependencies: list[list[int]] | None = None,
) -> list[np.ndarray]:
    """Reproduce pymdp.control.compute_expected_state for a single timestep."""
    u_t = np.asarray(u_t, dtype=np.int64).reshape(-1)
    if B_dependencies is None:
        B_dependencies = [[f] for f in range(len(B))]
    qs_next = []
    for f, (B_f, u_f, deps) in enumerate(zip(B, u_t, B_dependencies)):
        B_f = np.asarray(B_f, dtype=np.float64)
        relevant = [np.asarray(qs_prior[idx], dtype=np.float64) for idx in deps]
        B_slice = B_f[..., u_f]
        qs_next.append(factor_dot(B_slice, relevant, keep_dims=(0,)))
    return qs_next


def compute_expected_obs(
    qs: list[np.ndarray],
    A: list[np.ndarray],
    A_dependencies: list[list[int]],
) -> list[np.ndarray]:
    """Reproduce pymdp.control.compute_expected_obs."""
    result = []
    for m, A_m in enumerate(A):
        deps = A_dependencies[m]
        relevant = [np.asarray(qs[idx], dtype=np.float64) for idx in deps]
        A_m = np.asarray(A_m, dtype=np.float64)
        result.append(factor_dot(A_m, relevant, keep_dims=(0,)))
    return result


def compute_info_gain(
    qs: list[np.ndarray],
    qo: list[np.ndarray],
    A: list[np.ndarray],
    A_dependencies: list[list[int]],
) -> float:
    """Reproduce pymdp.control.compute_info_gain."""
    total = 0.0
    for m, (qo_m, A_m) in enumerate(zip(qo, A)):
        H_qo = stable_entropy(qo_m)
        H_A_m = -stable_xlogx(np.asarray(A_m, dtype=np.float64)).sum(axis=0)
        deps = A_dependencies[m]
        relevant = [np.asarray(qs[idx], dtype=np.float64) for idx in deps]
        qs_H_A_m = factor_dot(H_A_m, relevant)
        total += H_qo - qs_H_A_m
    return float(total)


def compute_expected_utility(
    qo: list[np.ndarray],
    C: list[np.ndarray],
    t: int = 0,
) -> float:
    """Reproduce pymdp.control.compute_expected_utility."""
    util = 0.0
    for o_m, C_m in zip(qo, C):
        C_m = np.asarray(C_m, dtype=np.float64)
        if C_m.ndim > 1:
            util += float((np.asarray(o_m, dtype=np.float64) * C_m[t]).sum())
        else:
            util += float((np.asarray(o_m, dtype=np.float64) * C_m).sum())
    return util


def calc_negative_pB_info_gain(
    pB: list[np.ndarray],
    qs_t: list[np.ndarray],
    qs_t_minus_1: list[np.ndarray],
    B_dependencies: list[list[int]],
    u_t_minus_1: np.ndarray,
) -> float:
    """Reproduce pymdp.control.calc_negative_pB_info_gain."""
    neg = 0.0
    u_t_minus_1 = np.asarray(u_t_minus_1, dtype=np.int64).reshape(-1)
    for i, (pb, qs, deps) in enumerate(zip(pB, qs_t, B_dependencies)):
        pb = np.asarray(pb, dtype=np.float64)
        u = int(u_t_minus_1[i])
        pb_u = pb[..., u]
        wB = spm_wnorm(pb_u) * (pb_u > 0.0)
        relevant = [np.asarray(qs_t_minus_1[idx], dtype=np.float64) for idx in deps]
        fd = factor_dot(wB, relevant, keep_dims=(0,))[..., None]
        contribution = float(np.asarray(qs, dtype=np.float64).dot(fd.ravel()))
        neg += contribution
    return neg


def compute_neg_efe_policy(
    qs_init: list[np.ndarray],
    A: list[np.ndarray],
    B: list[np.ndarray],
    C: list[np.ndarray],
    pA: list[np.ndarray] | None,
    pB: list[np.ndarray] | None,
    A_dependencies: list[list[int]],
    B_dependencies: list[list[int]],
    policy: np.ndarray,
    use_utility: bool = True,
    use_states_info_gain: bool = True,
    use_param_info_gain: bool = False,
) -> float:
    """Evaluate negative EFE of a single policy."""
    # Mirrors pymdp's scan: at every step t (including t = 0) the parameter
    # information gain uses the propagated beliefs, the beliefs before the
    # step, and the step's own action.
    qs = [np.asarray(q, dtype=np.float64) for q in qs_init]
    neg_efe = 0.0
    for t, u_t in enumerate(policy):
        qs_next = compute_expected_state(qs, B, u_t, B_dependencies=B_dependencies)
        qo = compute_expected_obs(qs_next, A, A_dependencies)
        if use_utility:
            neg_efe += compute_expected_utility(qo, C, t=t)
        if use_states_info_gain:
            neg_efe += compute_info_gain(qs_next, qo, A, A_dependencies)
        if use_param_info_gain and pB is not None:
            neg_efe -= calc_negative_pB_info_gain(pB, qs_next, qs, B_dependencies, u_t)
        qs = qs_next
    return neg_efe


def update_posterior_policies(
    policy_matrix: np.ndarray,
    qs_init: list[np.ndarray],
    A: list[np.ndarray],
    B: list[np.ndarray],
    C: list[np.ndarray],
    E: np.ndarray,
    pA: list[np.ndarray] | None,
    pB: list[np.ndarray] | None,
    A_dependencies: list[list[int]],
    B_dependencies: list[list[int]],
    gamma: float = GAMMA,
    use_utility: bool = True,
    use_states_info_gain: bool = True,
    use_param_info_gain: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Reproduce pymdp.control.update_posterior_policies for unbatched arrays."""
    neg_efe_all = np.zeros(len(policy_matrix), dtype=np.float64)
    qs_init_arr = [np.asarray(q, dtype=np.float64) for q in qs_init]
    for p_idx, policy in enumerate(policy_matrix):
        neg_efe_all[p_idx] = compute_neg_efe_policy(
            qs_init_arr,
            A,
            B,
            C,
            pA,
            pB,
            A_dependencies,
            B_dependencies,
            policy,
            use_utility=use_utility,
            use_states_info_gain=use_states_info_gain,
            use_param_info_gain=use_param_info_gain,
        )
    q_pi = softmax(gamma * neg_efe_all + log_stable(E))
    return q_pi, neg_efe_all


def dirichlet_expected_value(dir_arr: np.ndarray, event_dim: int = 0) -> np.ndarray:
    """Expected value of Dirichlet parameters (matches pymdp.learning.dirichlet_expected_value)."""
    dir_arr = np.clip(np.asarray(dir_arr, dtype=np.float64), min=MINVAL)
    return dir_arr / dir_arr.sum(axis=event_dim, keepdims=True)


def multidimensional_outer(tensors: list[np.ndarray]) -> np.ndarray:
    """Outer product over a list of 1D tensors."""
    result = np.asarray(tensors[0], dtype=np.float64)
    for t in tensors[1:]:
        t = np.asarray(t, dtype=np.float64)
        result = np.tensordot(result, t, axes=0)
    return result


def update_state_transition_dirichlet(
    pB: list[np.ndarray],
    B: list[np.ndarray],
    joint_beliefs: list[list[np.ndarray]],
    actions: np.ndarray,
    *,
    num_controls: list[int],
    lr: float = 1.0,
    factors_to_update: str | list[int] = "all",
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Reproduce pymdp.learning.update_state_transition_dirichlet for one transition."""
    nf = len(pB)
    if factors_to_update == "all":
        factors_to_update_sorted = list(range(nf))
    else:
        factors_to_update_sorted = [-1] * nf
        for f_i in sorted(factors_to_update):
            factors_to_update_sorted[f_i] = f_i

    actions = np.asarray(actions, dtype=np.int64)
    if actions.ndim == 1:
        actions = actions[None, :]

    qB: list[np.ndarray] = []
    E_qB: list[np.ndarray] = []
    for f, (pb_f, joint_qs_f, flag, na) in enumerate(
        zip(pB, joint_beliefs, factors_to_update_sorted, num_controls)
    ):
        pb_f = np.asarray(pb_f, dtype=np.float64)
        if flag > -1:
            a_f = actions[:, f]
            onehot = np.zeros((a_f.shape[0], na), dtype=np.float64)
            onehot[np.arange(a_f.shape[0]), a_f] = 1.0
            tensors = [np.asarray(q, dtype=np.float64) for q in joint_qs_f]
            tensors.append(onehot[0])
            accum = multidimensional_outer(tensors)
            qB_f = pb_f + lr * accum
        else:
            qB_f = pb_f
        E_qB_f = dirichlet_expected_value(qB_f)
        qB.append(qB_f)
        E_qB.append(E_qB_f)
    return qB, E_qB


class NumpyAgent:
    """Unbatched NumPy active-inference agent reproducing the pymdp subset KAINE uses."""

    def __init__(
        self,
        A: list[np.ndarray],
        B: list[np.ndarray],
        C: list[np.ndarray],
        D: list[np.ndarray],
        *,
        A_dependencies: list[list[int]],
        pB: list[np.ndarray] | None = None,
        B_action_dependencies: list[list[int]] | None = None,
        num_controls: list[int] | None = None,
        policy_len: int = 1,
        num_iter: int = 8,
        use_utility: bool = True,
        use_states_info_gain: bool = True,
        use_param_info_gain: bool = False,
        learn_B: bool = False,
        lr_pB: float = 1.0,
    ):
        if pB is not None and not learn_B:
            raise ValueError("Providing pB without learn_B=True is not supported")

        self.A = [np.asarray(a, dtype=np.float64) for a in A]
        self.B = [np.asarray(b, dtype=np.float64) for b in B]
        self.C = [np.asarray(c, dtype=np.float64) for c in C]
        self.D = [np.asarray(d, dtype=np.float64) for d in D]
        self.A_dependencies = A_dependencies
        self.num_factors = len(B)
        self.num_modalities = len(A)
        self.policy_len = policy_len
        self.num_iter = num_iter
        self.use_utility = use_utility
        self.use_states_info_gain = use_states_info_gain
        self.use_param_info_gain = use_param_info_gain
        self.learn_B = learn_B
        self.lr_pB = lr_pB

        # State-transition dependencies are always factor-local in KAINE models.
        self.B_dependencies = [[f] for f in range(self.num_factors)]

        self.B_action_dependencies = (
            B_action_dependencies
            if B_action_dependencies is not None
            else [[f] for f in range(self.num_factors)]
        )

        if B_action_dependencies is not None:
            if num_controls is None:
                raise ValueError(
                    "num_controls is required when B_action_dependencies is provided"
                )
            self.num_controls_multi = list(num_controls)
            self.action_maps = self._build_action_maps(
                self.num_controls_multi, self.B_action_dependencies
            )
            self.B, self.pB = self._flatten_B_action_dims(
                self.B, pB, self.B_action_dependencies
            )
            self.num_controls = [
                self.B[f].shape[-1] for f in range(self.num_factors)
            ]
        else:
            self.num_controls_multi = None
            self.action_maps = None
            self.pB = (
                [np.asarray(pb, dtype=np.float64) for pb in pB]
                if pB is not None
                else None
            )
            self.num_controls = (
                num_controls
                if num_controls is not None
                else [self.B[f].shape[-1] for f in range(self.num_factors)]
            )

        self.control_fac_idx = [
            f for f, n_c in enumerate(self.num_controls) if n_c > 1
        ]

        if self.action_maps is not None:
            # Policies are built over the *control* factors, then remapped to
            # per-state-factor flat action indices (matching pymdp).
            n_control_factors = len(self.num_controls_multi)
            control_fac_idx = list(range(n_control_factors))
            policies_control = construct_policies(
                [1] * n_control_factors,
                self.num_controls_multi,
                policy_len,
                control_fac_idx,
            )
            self.policies_arr = self._construct_flattend_policies(
                policies_control, self.action_maps
            )
        else:
            self.policies_arr = construct_policies(
                [b.shape[0] for b in self.B],
                self.num_controls,
                policy_len,
                self.control_fac_idx,
            )

        self.E = np.ones(len(self.policies_arr), dtype=np.float64) / len(
            self.policies_arr
        )
        self.gamma = GAMMA
        self._validate()

    def _build_action_maps(
        self,
        num_controls_multi: list[int],
        B_action_dependencies: list[list[int]],
    ) -> list[dict]:
        """Build action-map metadata for each state factor."""
        maps: list[dict] = []
        for f, deps in enumerate(B_action_dependencies):
            if not deps:
                maps.append(
                    {
                        "multi_dependency": [],
                        "multi_dims": [],
                        "flat_dependency": [f],
                        "flat_dims": [1],
                    }
                )
                continue
            dims = [num_controls_multi[d] for d in deps]
            maps.append(
                {
                    "multi_dependency": deps,
                    "multi_dims": dims,
                    "flat_dependency": [f],
                    "flat_dims": [int(np.prod(dims))],
                }
            )
        return maps

    def _flatten_B_action_dims(
        self,
        B: list[np.ndarray],
        pB: list[np.ndarray] | None,
        B_action_dependencies: list[list[int]],
    ) -> tuple[list[np.ndarray], list[np.ndarray] | None]:
        """Flatten trailing action axes of B and pB according to action_maps."""
        new_B: list[np.ndarray] = []
        new_pB: list[np.ndarray] | None = [] if pB is not None else None
        for f, (B_f, deps) in enumerate(zip(B, B_action_dependencies)):
            B_f = np.asarray(B_f, dtype=np.float64)
            if len(deps) == 0:
                B_flat = np.expand_dims(B_f, axis=-1)
                new_B.append(B_flat)
                if pB is not None:
                    pb_f = np.asarray(pB[f], dtype=np.float64)
                    new_pB.append(np.expand_dims(pb_f, axis=-1))
                continue

            dims = [self.num_controls_multi[d] for d in deps]
            flat_size = int(np.prod(dims))
            target_shape = list(B_f.shape)[: -len(deps)] + [flat_size]
            new_B.append(B_f.reshape(target_shape))
            if pB is not None:
                pb_f = np.asarray(pB[f], dtype=np.float64)
                new_pB.append(pb_f.reshape(target_shape))
        if new_pB is not None and len(new_pB) == 0:
            new_pB = None
        return new_B, new_pB

    def _construct_flattend_policies(
        self,
        policies: np.ndarray,
        action_maps: list[dict],
    ) -> np.ndarray:
        """Map control-factor policies to per-state-factor flat action indices."""
        n_policies, policy_len, _ = policies.shape
        n_state_factors = len(action_maps)
        flat = np.zeros(
            (n_policies, policy_len, n_state_factors), dtype=np.int64
        )
        for f, action_map in enumerate(action_maps):
            deps = action_map["multi_dependency"]
            if not deps:
                continue
            dims = tuple(action_map["multi_dims"])
            combos = policies[:, :, deps]
            # pymdp's get_combination_index: C order (last dependency fastest);
            # ravel_multi_index takes one index array per dimension.
            flat[:, :, f] = np.ravel_multi_index(
                tuple(np.moveaxis(combos, -1, 0)), dims, order="C"
            )
        return flat

    def _validate(self) -> None:
        if any(a.ndim == 0 for a in self.A):
            raise ValueError("Empty A modality")
        for m, deps in enumerate(self.A_dependencies):
            expected = [self.B[d].shape[0] for d in deps]
            actual = list(self.A[m].shape[1:])
            if expected != actual:
                raise ValueError(
                    f"A[{m}] shape {self.A[m].shape} incompatible with dependencies {deps}"
                )

    @property
    def policies(self) -> np.ndarray:
        return self.policies_arr

    def infer_states(
        self,
        obs: list[int],
        empirical_prior: list[np.ndarray],
    ) -> list[np.ndarray]:
        """Run factorized FPI state inference for a single observation step."""
        o_vec = []
        for m, o in enumerate(obs):
            o_arr = np.zeros(self.A[m].shape[0], dtype=np.float64)
            o_arr[int(o)] = 1.0
            o_vec.append(o_arr)
        prior = [np.asarray(p, dtype=np.float64) for p in empirical_prior]
        return run_factorized_fpi(
            self.A,
            o_vec,
            prior,
            self.A_dependencies,
            num_iter=self.num_iter,
            distr_obs=True,
        )

    def infer_policies(
        self,
        qs: list[np.ndarray],
    ) -> tuple[np.ndarray, np.ndarray]:
        """Policy posterior and negative EFE per policy."""
        qs_arr = [np.asarray(q, dtype=np.float64) for q in qs]
        return update_posterior_policies(
            self.policies_arr,
            qs_arr,
            self.A,
            self.B,
            self.C,
            self.E,
            None,  # pA
            self.pB,
            self.A_dependencies,
            self.B_dependencies,
            gamma=self.gamma,
            use_utility=self.use_utility,
            use_states_info_gain=self.use_states_info_gain,
            use_param_info_gain=self.use_param_info_gain,
        )

    def infer_parameters(
        self,
        qs_prev: list[np.ndarray],
        qs: list[np.ndarray],
        policy_row: np.ndarray,
    ) -> "NumpyAgent":
        """One-step B learning; returns a new agent with updated pB and B."""
        if not self.learn_B or self.pB is None:
            return self
        joint_beliefs = []
        for f in range(self.num_factors):
            deps = self.B_dependencies[f]
            q_t = np.asarray(qs[f], dtype=np.float64)
            prev_factors = [np.asarray(qs_prev[idx], dtype=np.float64) for idx in deps]
            joint_beliefs.append([q_t] + prev_factors)
        actions = np.asarray(policy_row, dtype=np.int64).reshape(1, -1)
        new_pB, new_B = update_state_transition_dirichlet(
            self.pB,
            self.B,
            joint_beliefs,
            actions,
            num_controls=self.num_controls,
            lr=self.lr_pB,
            factors_to_update="all",
        )
        agent = copy.copy(self)
        agent.pB = new_pB
        agent.B = new_B
        return agent

    def update_empirical_prior(
        self,
        policy_row: np.ndarray,
        qs: list[np.ndarray],
    ) -> list[np.ndarray]:
        """Propagate posterior through B under the given action."""
        return compute_expected_state(
            [np.asarray(q, dtype=np.float64) for q in qs],
            self.B,
            np.asarray(policy_row, dtype=np.int64),
            B_dependencies=self.B_dependencies,
        )

    def with_state(
        self,
        B: list[np.ndarray] | None = None,
        pB: list[np.ndarray] | None = None,
    ) -> "NumpyAgent":
        """Return a new agent with replaced B and/or pB."""
        agent = copy.copy(self)
        if B is not None:
            agent.B = [np.asarray(b, dtype=np.float64) for b in B]
        if pB is not None:
            agent.pB = [np.asarray(pb, dtype=np.float64) for pb in pB]
        return agent
