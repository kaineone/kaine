# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Statistics of the individuation instrument.

A stratified two-sample energy test compares the being's current answer
embeddings against its birth-reference answer embeddings, prompt by prompt.
For each prompt (a stratum) an unbiased U-statistic energy distance is
computed and the stratum statistics are summed to give the overall test
statistic T.

References
----------
- Szekely & Rizzo (2017): the U-statistic form of the energy two-sample test.
- Rizzo & Szekely (2016): the H effect-size coefficient.  Euclidean distance
  is required; an exponent of 2 would reduce the test to a comparison of
  means only.
- Phipson & Smyth (2010): exact permutation p-values via ``p = (b+1)/(B+1)``.
- Lan & DeMets (1983): alpha-spending functions for sequential looks.
"""

import dataclasses
import math
from typing import Sequence

import numpy as np

# Upper bound on sum_{n>=2} 1/(n ln^2 n) (partial sum to 10^6 plus the
# integral tail bound 1/ln(10^6)); therefore the sum over k of gamma_k is
# at most 1.
SPENDING_S: float = 2.1097

Strata = Sequence[tuple[np.ndarray, np.ndarray]]


def _pairwise_distance_matrix(a: np.ndarray) -> np.ndarray:
    """Euclidean distance matrix between rows of ``a``."""
    a = np.asarray(a, dtype=np.float64)
    sum_sq = np.sum(a * a, axis=1)
    cross = a @ a.T
    sq = sum_sq[:, None] + sum_sq[None, :] - 2.0 * cross
    np.maximum(sq, 0.0, out=sq)
    return np.sqrt(sq, out=sq)


def _pairwise_mean_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Mean Euclidean distance between rows of ``a`` and rows of ``b``."""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    a_sq = np.sum(a * a, axis=1)
    b_sq = np.sum(b * b, axis=1)
    cross = a @ b.T
    sq = np.maximum(a_sq[:, None] + b_sq[None, :] - 2.0 * cross, 0.0)
    return float(np.mean(np.sqrt(sq)))


def _within_mean_distance(a: np.ndarray) -> float:
    """Mean Euclidean distance over ordered pairs ``i != i'`` of rows of ``a``."""
    a = np.asarray(a, dtype=np.float64)
    n = a.shape[0]
    distances = _pairwise_distance_matrix(a)
    # Diagonal is zero, so the total sum is already the off-diagonal sum.
    return float(np.sum(distances) / (n * (n - 1)))


def energy_u(x: np.ndarray, y: np.ndarray) -> float:
    """Unbiased U-statistic energy distance between two samples.

    E = 2 * mean_{i,l} ||x_i - y_l|| - mean_{i != i'} ||x_i - x_i'||
        - mean_{l != l'} ||y_l - y_l'||, with Euclidean norms and the
    within-group means over ordered pairs of distinct rows.

    Parameters
    ----------
    x : (n_b, d) reference sample.
    y : (n_c, d) current sample.

    Returns
    -------
    E as a float.  May be slightly negative under the null.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if x.ndim != 2 or y.ndim != 2:
        raise ValueError("x and y must be two-dimensional arrays")
    n_b, d_x = x.shape
    n_c, d_y = y.shape
    if d_x != d_y:
        raise ValueError("x and y must have the same trailing dimension")
    if n_b < 2 or n_c < 2:
        raise ValueError("both samples must contain at least two observations")

    mean_xy = _pairwise_mean_distance(x, y)
    mean_xx = _within_mean_distance(x)
    mean_yy = _within_mean_distance(y)
    return float(2.0 * mean_xy - mean_xx - mean_yy)


def stratified_energy(strata: Strata) -> float:
    """Sum of stratum-level unbiased energy statistics."""
    return float(sum(energy_u(x, y) for x, y in strata))


def effect_size_h(strata: Strata) -> float:
    """Rizzo & Szekely H coefficient across strata.

    H = (sum_j E_j) / (sum_j 2 * mean_{i,l} ||x_i - y_l||) for stratum j.

    Returns ``0.0`` when the denominator is zero.
    """
    numerator = 0.0
    denominator = 0.0
    for x, y in strata:
        E = energy_u(x, y)
        mean_xy = _pairwise_mean_distance(x, y)
        numerator += E
        denominator += 2.0 * mean_xy
    if denominator == 0.0:
        return 0.0
    return float(numerator / denominator)


@dataclasses.dataclass(frozen=True)
class PermutationResult:
    """Result of a stratified permutation energy test."""

    p_value: float
    statistic: float
    permutations: int
    exceed: int
    planned: int
    stopped_early: bool


def _random_label_matrix(k: int, m: int, n_b: int, rng: np.random.Generator) -> np.ndarray:
    """Generate a ``(k, m)`` indicator matrix with exactly ``n_b`` ones per row."""
    idx = np.broadcast_to(np.arange(m, dtype=np.int64), (k, m)).copy()
    perms = rng.permuted(idx, axis=1)
    labels = np.zeros((k, m), dtype=np.float64)
    rows = np.arange(k, dtype=np.int64)[:, None]
    cols = perms[:, :n_b]
    labels[rows, cols] = 1.0
    return labels


def _batch_statistics(
    D_list: Sequence[np.ndarray],
    labels: Sequence[np.ndarray],
) -> np.ndarray:
    """Vectorized stratified energy for a batch of permutations.

    Parameters
    ----------
    D_list : sequence of ``(m_j, m_j)`` pooled Euclidean distance matrices.
    labels : sequence of ``(k, m_j)`` indicator matrices.  Row ``r`` of
        ``labels[j]`` has exactly ``n_b_j`` ones and marks which rows of
        stratum ``j`` are assigned to the reference group in permutation ``r``.

    Returns
    -------
    T : ``(k,)`` array of stratified energy statistics.
    """
    if not D_list or not labels:
        raise ValueError("D_list and labels must be non-empty")
    k = labels[0].shape[0]
    T = np.zeros(k, dtype=np.float64)
    for D, P in zip(D_list, labels):
        m = D.shape[0]
        n_b = int(np.sum(P[0]))
        n_c = m - n_b
        if n_b < 2 or n_c < 2:
            raise ValueError("invalid label matrix: each group needs at least two rows")
        Q = 1.0 - P
        sum_xx = np.einsum("km,mn,kn->k", P, D, P)
        sum_yy = np.einsum("km,mn,kn->k", Q, D, Q)
        sum_xy = np.einsum("km,mn,kn->k", P, D, Q)
        E = (
            2.0 * sum_xy / (n_b * n_c)
            - sum_xx / (n_b * (n_b - 1))
            - sum_yy / (n_c * (n_c - 1))
        )
        T += E
    return T


def permutation_test(
    strata: Strata,
    *,
    permutations: int,
    rng: np.random.Generator,
    alpha: float | None = None,
    batch_size: int = 4096,
) -> PermutationResult:
    """Exact stratified permutation energy test with optional alpha spending.

    For each stratum the pooled rows are randomly relabelled into reference and
    current groups and the stratified statistic T is recomputed.  The p-value
    is ``(b + 1) / (B + 1)`` where ``b`` is the number of permuted statistics
    that meet or exceed the observed statistic.  If ``alpha`` is supplied the
    loop stops at the first batch boundary where this lower-bound p-value
    exceeds ``alpha``.
    """
    if permutations < 1:
        raise ValueError("permutations must be at least 1")
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if not strata:
        raise ValueError("strata must be non-empty")

    prepared: list[tuple[np.ndarray, np.ndarray]] = []
    D_list: list[np.ndarray] = []
    n_b_list: list[int] = []

    for x, y in strata:
        x_arr = np.asarray(x, dtype=np.float64)
        y_arr = np.asarray(y, dtype=np.float64)
        if x_arr.ndim != 2 or y_arr.ndim != 2:
            raise ValueError("each stratum must contain two-dimensional arrays")
        n_b, d_x = x_arr.shape
        n_c, d_y = y_arr.shape
        if d_x != d_y:
            raise ValueError("within each stratum x and y must share the same dimension")
        if n_b < 2 or n_c < 2:
            raise ValueError("each stratum must have at least two rows per sample")

        pooled = np.concatenate([x_arr, y_arr], axis=0)
        D_list.append(_pairwise_distance_matrix(pooled))
        prepared.append((x_arr, y_arr))
        n_b_list.append(n_b)

    T_obs = stratified_energy(prepared)
    B = permutations
    exceed = 0
    evaluated = 0
    stopped_early = False
    threshold = T_obs - 1e-12 * max(1.0, abs(T_obs))

    while evaluated < B:
        k = min(batch_size, B - evaluated)
        P_list = [
            _random_label_matrix(k, D.shape[0], n_b, rng)
            for D, n_b in zip(D_list, n_b_list)
        ]
        T_batch = _batch_statistics(D_list, P_list)
        exceed += int(np.sum(T_batch >= threshold))
        evaluated += k
        if alpha is not None and (exceed + 1) / (B + 1) > alpha:
            stopped_early = True
            break

    p_value = (exceed + 1) / (B + 1)
    return PermutationResult(
        p_value=float(p_value),
        statistic=float(T_obs),
        permutations=evaluated,
        exceed=exceed,
        planned=B,
        stopped_early=stopped_early,
    )


def spending_alpha(k: int, alpha_total: float = 0.05) -> float:
    """Per-look alpha for the k-th look under a Lan-DeMets-style spend.

    Returns ``alpha_total / (SPENDING_S * (k+1) * log(k+1)^2)``.
    """
    if k < 1:
        raise ValueError("k must be at least 1")
    if not (0.0 < alpha_total < 1.0):
        raise ValueError("alpha_total must lie in (0, 1)")
    return alpha_total / (SPENDING_S * (k + 1) * math.log(k + 1) ** 2)


def required_permutations(alpha_k: float, b_max: int = 2_000_000) -> int | None:
    """Minimum B so that the exact p-value can reach ``alpha_k``.

    Returns ``ceil(20 / alpha_k)`` or ``None`` if that exceeds ``b_max``.
    """
    b = math.ceil(20.0 / alpha_k)
    if b > b_max:
        return None
    return b


def decide(
    *,
    p_value: float,
    alpha_k: float,
    effect_size_h: float,
    effect_min: float,
    warmed_up: bool,
) -> bool:
    """Individuation decision: significant, large-enough effect, and warmed up."""
    return warmed_up and p_value <= alpha_k and effect_size_h >= effect_min
