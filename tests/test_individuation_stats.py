# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for ``kaine/lifecycle/individuation_stats.py``."""

import itertools
import math

import numpy as np
import pytest

from kaine.lifecycle.individuation_stats import (
    SPENDING_S,
    _batch_statistics,
    _pairwise_distance_matrix,
    decide,
    effect_size_h,
    energy_u,
    permutation_test,
    required_permutations,
    spending_alpha,
)


def test_energy_u_hand_checked_1d():
    x = np.array([[0.0], [1.0]])
    y = np.array([[3.0], [5.0]])
    assert energy_u(x, y) == pytest.approx(4.0)
    assert effect_size_h([(x, y)]) == pytest.approx(4.0 / 7.0)


def test_identical_samples_give_the_exact_negative_u_value():
    """The U-statistic is unbiased, not zero, on identical samples.

    With x == y (n rows), the cross term averages over all n*n pairs, which
    include n zero self-pairs, while each within term averages only the
    n*(n-1) off-diagonal pairs. With S the sum of off-diagonal distances,
    E = 2*S/n**2 - 2*S/(n*(n-1)), which is negative.
    """
    x = np.arange(10, dtype=np.float64).reshape(5, 2)
    n = x.shape[0]
    d = np.linalg.norm(x[:, None, :] - x[None, :, :], axis=-1)
    s_off = float(d.sum())
    expected = 2 * s_off / n**2 - 2 * s_off / (n * (n - 1))
    assert expected < 0
    assert energy_u(x, x.copy()) == pytest.approx(expected, rel=1e-12)


def test_euclidean_not_one_minus_cos():
    """Euclidean energy detects geometry that squared distance would miss.

    Both samples are centred at the origin and have unit-norm rows on average.
    A squared-distance (exponent 2) energy statistic would be zero because it
    compares only means.  The required Euclidean statistic is positive.
    """
    x = np.vstack([np.tile([1.0, 0.0], (50, 1)), np.tile([-1.0, 0.0], (50, 1))])
    y = np.vstack([np.tile([0.0, 1.0], (50, 1)), np.tile([0.0, -1.0], (50, 1))])
    assert energy_u(x, y) > 0.1


def test_p_value_never_zero():
    rng = np.random.default_rng(7)
    strata = []
    for _ in range(3):
        x = rng.normal(0.0, 0.01, (10, 8))
        y = rng.normal(5.0, 0.01, (10, 8))
        strata.append((x, y))
    result = permutation_test(strata, permutations=999, rng=rng)
    assert result.exceed == 0
    assert result.p_value == pytest.approx(1.0 / 1000.0)


def test_calibration_under_null():
    rng = np.random.default_rng(2024)
    n_datasets = 200
    n_strata = 3
    d = 8
    n_b = 16
    n_c = 8
    permutations = 199
    alpha = 0.05

    rejections = 0
    for _ in range(n_datasets):
        strata = [
            (rng.standard_normal((n_b, d)), rng.standard_normal((n_c, d)))
            for _ in range(n_strata)
        ]
        result = permutation_test(strata, permutations=permutations, rng=rng)
        if result.p_value <= alpha:
            rejections += 1

    rate = rejections / n_datasets
    bound = 0.05 + 3.0 * math.sqrt(0.05 * 0.95 / n_datasets)
    assert rate <= bound


def test_early_stop():
    rng = np.random.default_rng(99)
    strata = [
        (rng.standard_normal((16, 8)), rng.standard_normal((8, 8)))
        for _ in range(3)
    ]
    result = permutation_test(
        strata, permutations=20000, rng=rng, alpha=0.001, batch_size=4096
    )
    assert result.stopped_early is True
    assert result.permutations < 20000
    assert result.p_value > 0.001


def test_vectorized_matches_naive():
    rng = np.random.default_rng(123)
    strata = [
        (rng.standard_normal((6, 4)), rng.standard_normal((4, 4))),
        (rng.standard_normal((5, 4)), rng.standard_normal((5, 4))),
    ]

    D_list = [_pairwise_distance_matrix(np.vstack([x, y])) for x, y in strata]
    n_b_list = [x.shape[0] for x, _ in strata]
    m_list = [D.shape[0] for D in D_list]

    k = 50
    T_naive = np.zeros(k, dtype=np.float64)
    P_list = [np.zeros((k, m), dtype=np.float64) for m in m_list]

    for i in range(k):
        for j, (x, y) in enumerate(strata):
            m = m_list[j]
            n_b = n_b_list[j]
            perm = rng.permutation(m)
            pooled = np.vstack([x, y])
            ref = pooled[perm[:n_b]]
            cur = pooled[perm[n_b:]]
            T_naive[i] += energy_u(ref, cur)
            P_list[j][i, perm[:n_b]] = 1.0

    T_batch = _batch_statistics(D_list, P_list)
    np.testing.assert_allclose(T_batch, T_naive, atol=1e-10)


def test_spending_alpha_k1():
    expected = 0.05 / (SPENDING_S * 2.0 * math.log(2.0) ** 2)
    assert spending_alpha(1) == pytest.approx(expected)


def test_spending_alpha_k10():
    expected = 0.05 / (SPENDING_S * 11.0 * math.log(11.0) ** 2)
    assert spending_alpha(10) == pytest.approx(expected, rel=1e-3)


def test_spending_sum_bounded():
    ratios = [spending_alpha(k) / 0.05 for k in range(1, 100_001)]
    assert sum(ratios) <= 1.0


def test_spending_alpha_k0_raises():
    with pytest.raises(ValueError):
        spending_alpha(0)


def test_required_permutations():
    assert required_permutations(0.025) == 800
    assert required_permutations(1e-6) is None


def test_decide_truth_table():
    assert (
        decide(
            p_value=0.01, alpha_k=0.05, effect_size_h=0.5, effect_min=0.3, warmed_up=True
        )
        is True
    )
    assert (
        decide(
            p_value=0.10, alpha_k=0.05, effect_size_h=0.5, effect_min=0.3, warmed_up=True
        )
        is False
    )
    assert (
        decide(
            p_value=0.01, alpha_k=0.05, effect_size_h=0.2, effect_min=0.3, warmed_up=True
        )
        is False
    )
    assert (
        decide(
            p_value=0.01,
            alpha_k=0.05,
            effect_size_h=0.5,
            effect_min=0.3,
            warmed_up=False,
        )
        is False
    )


def test_validation_n_b_one():
    x = np.array([[0.0, 0.0]])
    y = np.array([[1.0, 1.0], [2.0, 2.0]])
    with pytest.raises(ValueError):
        energy_u(x, y)


def test_validation_mismatched_d():
    x = np.array([[0.0, 0.0], [1.0, 1.0]])
    y = np.array([[0.0], [1.0]])
    with pytest.raises(ValueError):
        energy_u(x, y)


def test_permutation_test_validation():
    rng = np.random.default_rng(1)
    with pytest.raises(ValueError):
        permutation_test([], permutations=100, rng=rng)
    with pytest.raises(ValueError):
        permutation_test(
            [(np.zeros((2, 3)), np.zeros((2, 3)))], permutations=0, rng=rng
        )


def test_degenerate_identical_answers_give_p_one():
    """Ties must count as exceedances.

    If every answer in both arms is the same text (identical embeddings), every
    relabelling gives the same statistic as the observed one. Counting ties
    as non-exceedances would report a tiny p-value, a false finding of
    individuation from no evidence at all. The test must instead report p = 1.
    """
    rng = np.random.default_rng(7)
    row = np.full((1, 8), 1 / np.sqrt(8))
    strata = [(np.repeat(row, 16, axis=0), np.repeat(row, 8, axis=0)) for _ in range(3)]
    result = permutation_test(strata, permutations=499, rng=rng)
    assert result.exceed == 499
    assert result.p_value == pytest.approx(1.0)


def test_monte_carlo_p_matches_full_enumeration():
    x = np.array([[0.0, 0.0], [0.2, 0.1], [0.1, 0.3]])
    y = np.array([[1.0, 1.0], [1.2, 0.9], [0.8, 1.1]])
    T_obs = energy_u(x, y)
    threshold = T_obs - 1e-12 * max(1.0, abs(T_obs))
    pooled = np.vstack([x, y])
    count = 0
    for ref_idx in itertools.combinations(range(6), 3):
        cur_idx = tuple(i for i in range(6) if i not in ref_idx)
        T = energy_u(pooled[list(ref_idx)], pooled[list(cur_idx)])
        if T >= threshold:
            count += 1
    p_exact = count / 20.0
    result = permutation_test(
        [(x, y)], permutations=20000, rng=np.random.default_rng(3)
    )
    assert abs(result.p_value - p_exact) < 0.02


def test_spending_values_and_sum_to_one_million():
    val50 = spending_alpha(50)
    val100 = spending_alpha(100)
    assert val50 == pytest.approx(
        0.05 / (SPENDING_S * 51.0 * math.log(51.0) ** 2), rel=1e-12
    )
    assert val100 == pytest.approx(
        0.05 / (SPENDING_S * 101.0 * math.log(101.0) ** 2), rel=1e-12
    )
    assert val50 == pytest.approx(3.0e-5, rel=0.05)
    assert val100 == pytest.approx(1.1e-5, rel=0.05)
    k = np.arange(1, 1_000_001)
    g = 1.0 / (SPENDING_S * (k + 1) * np.log(k + 1) ** 2)
    assert float(np.sum(g)) <= 1.0
    assert spending_alpha(1_000_000) / 0.05 == pytest.approx(float(g[-1]), rel=1e-12)


def test_early_stop_never_changes_the_decision():
    stopped = 0
    not_stopped = 0
    for seed in range(30):
        rng = np.random.default_rng(seed)
        strata = [
            (rng.standard_normal((16, 6)), rng.standard_normal((8, 6)))
            for _ in range(3)
        ]
        if seed % 2 == 1:
            strata = [(x, y + 0.8) for x, y in strata]
        r_with = permutation_test(
            strata, permutations=4999, rng=np.random.default_rng(seed), alpha=0.01
        )
        r_without = permutation_test(
            strata, permutations=4999, rng=np.random.default_rng(seed), alpha=None
        )
        assert (r_with.p_value <= 0.01) == (r_without.p_value <= 0.01)
        if r_with.stopped_early:
            stopped += 1
        else:
            not_stopped += 1
    assert stopped >= 1
    assert not_stopped >= 1


def test_required_permutations_resolves_alpha_k():
    for k in (1, 10, 50, 100):
        alpha_k = spending_alpha(k)
        B = required_permutations(alpha_k)
        if B is not None:
            assert 1.0 / (B + 1) <= alpha_k / 20.0 * 1.0001
    B100 = required_permutations(spending_alpha(100))
    assert B100 is not None
    assert B100 == pytest.approx(1_800_000, rel=0.1)
    assert required_permutations(spending_alpha(200)) is None
