# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json
import math
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from kaine.experiment.rd_robust import (
    RDError,
    bias_constant,
    kernel_constants,
    mse_bandwidths,
    rd_estimate,
)

PHI = (math.sqrt(5) - 1) / 2

_REF_PATH = Path(__file__).parent / "data" / "rd_robust_reference.json"
with _REF_PATH.open() as f:
    _REFERENCE = json.load(f)


def dataset(n, jump, shape, noise, shift=0.0):
    i = np.arange(1, n + 1, dtype=float)
    u = (i * PHI + shift) % 1.0
    x = 2.0 * u - 1.0
    e = noise * np.sin(i * 12.9898 + 78.233 * u)
    if shape == "lee":
        m = np.where(x >= 0, 0.52 + 0.84*x - 3.00*x**2 + 7.99*x**3 - 9.01*x**4 + 3.56*x**5,
                     0.48 + 1.27*x + 7.18*x**2 + 20.21*x**3 + 21.54*x**4 + 7.33*x**5)
    elif shape == "linear":
        m = 0.3 + 0.8 * x
    elif shape == "curved":
        m = np.sin(2.5 * x) + 0.6 * x**2
    y = m + jump * (x >= 0) + e
    return x, y


@pytest.mark.parametrize("case", _REFERENCE["cases"])
@pytest.mark.parametrize("vce", ["nn", "hc0"])
def test_reference_coefficients(case, vce):
    x, y = dataset(case["n"], case["jump"], case["shape"], case["noise"],
                   case.get("shift", 0.0))
    h = case["h"]
    b = case["b"]
    est = rd_estimate(x, y, h, b, vce=vce)
    ref = case[vce]
    assert est.tau_conventional == pytest.approx(ref["coef_conventional"],
                                                 rel=1e-10, abs=1e-12)
    assert est.tau_bias_corrected == pytest.approx(ref["coef_bias_corrected"],
                                                  rel=1e-10, abs=1e-12)


@pytest.mark.parametrize("case", _REFERENCE["cases"])
def test_hc0_standard_errors_match_reference(case):
    x, y = dataset(case["n"], case["jump"], case["shape"], case["noise"],
                   case.get("shift", 0.0))
    h = case["h"]
    b = case["b"]
    est = rd_estimate(x, y, h, b, vce="hc0")
    ref = case["hc0"]
    assert est.se_conventional == pytest.approx(ref["se_conventional"], rel=1e-9)
    assert est.se_robust == pytest.approx(ref["se_robust"], rel=1e-9)
    assert est.ci_robust[0] == pytest.approx(ref["ci_robust"][0], rel=1e-9)
    assert est.ci_robust[1] == pytest.approx(ref["ci_robust"][1], rel=1e-9)


@pytest.mark.parametrize("case", _REFERENCE["cases"])
def test_nn_window_standard_errors_match_reference(case):
    x, y = dataset(case["n"], case["jump"], case["shape"], case["noise"],
                   case.get("shift", 0.0))
    h = case["h"]
    b = case["b"]
    est_window = rd_estimate(x, y, h, b, vce="nn", nn_window=max(h, b))
    ref = case["nn"]
    assert est_window.se_conventional == pytest.approx(ref["se_conventional"], rel=1e-9)
    assert est_window.se_robust == pytest.approx(ref["se_robust"], rel=1e-9)

    est_default = rd_estimate(x, y, h, b, vce="nn")
    assert (abs(est_default.se_conventional - ref["se_conventional"])
            / max(ref["se_conventional"], 1e-12) < 0.001)
    assert (abs(est_default.se_robust - ref["se_robust"])
            / max(ref["se_robust"], 1e-12) < 0.001)


def test_exact_linear_jump():
    x, y = dataset(400, 0.5, "linear", 0.0)
    est = rd_estimate(x, y, 0.3, 0.45)
    assert est.tau_conventional == pytest.approx(0.5, abs=1e-12)
    assert est.tau_bias_corrected == pytest.approx(0.5, abs=1e-12)


def test_exact_quadratic_equal_bandwidth():
    n = 500
    x = dataset(n, 0.0, "linear", 0.0)[0]
    y = np.where(
        x >= 0,
        1.0 + 2.0 * x + 0.5 * x ** 2,
        -0.5 + 1.5 * x - 0.3 * x ** 2,
    )
    y += 0.75 * (x >= 0)
    est = rd_estimate(x, y, 0.4, 0.4)
    # The jump is the difference of the intercepts: (1.0 + 0.75) - (-0.5).
    assert est.tau_bias_corrected == pytest.approx(2.25, abs=1e-10)


def test_cluster_singleton_matches_hc0():
    case = _REFERENCE["cases"][0]
    x, y = dataset(case["n"], case["jump"], case["shape"], case["noise"],
                   case.get("shift", 0.0))
    h, b = case["h"], case["b"]
    est_hc0 = rd_estimate(x, y, h, b, vce="hc0")
    est_cl = rd_estimate(x, y, h, b, vce="hc0",
                         cluster=np.arange(x.size))
    assert est_cl.se_robust == pytest.approx(est_hc0.se_robust, abs=1e-12)
    assert est_cl.se_conventional == pytest.approx(est_hc0.se_conventional, abs=1e-12)


def _direct_wls(x_side, y_side, bw, m):
    inside = np.abs(x_side) < bw
    xs = x_side[inside]
    ys = y_side[inside]
    w = (1.0 - np.abs(xs / bw)) / bw
    R = np.vander(xs, N=m + 1, increasing=True)
    Rw = R.T * w
    return np.linalg.solve(Rw @ R, Rw @ ys)


def _direct_Lrow(x_side, bw, m, k):
    """Row k of the weight matrix over the whole side, zero outside the bandwidth."""
    inside = np.abs(x_side) < bw
    xs = x_side[inside]
    w = (1.0 - np.abs(xs / bw)) / bw
    R = np.vander(xs, N=m + 1, increasing=True)
    Rw = R.T * w
    L = np.linalg.solve(Rw @ R, Rw)
    row = np.zeros(x_side.size, dtype=float)
    row[inside] = L[k]
    return row


def _direct_D(x_side, h, p):
    return float(_direct_Lrow(x_side, h, p, 0) @ (x_side ** (p + 1)))


def _direct_clustered_robust_se(x, y, h, b, cluster):
    n = x.size
    left = x < 0
    right = ~left
    w = np.zeros(n, dtype=float)
    e = np.zeros(n, dtype=float)

    beta_q_r = _direct_wls(x[right], y[right], b, 2)
    beta_q_l = _direct_wls(x[left], y[left], b, 2)

    D_r = _direct_D(x[right], h, 1)
    D_l = _direct_D(x[left], h, 1)

    xr = x[right]
    w[right] = _direct_Lrow(xr, h, 1, 0) - D_r * _direct_Lrow(xr, b, 2, 2)
    e[right] = y[right] - np.vander(xr, N=3, increasing=True) @ beta_q_r

    xl = x[left]
    w[left] = -_direct_Lrow(xl, h, 1, 0) + D_l * _direct_Lrow(xl, b, 2, 2)
    e[left] = y[left] - np.vander(xl, N=3, increasing=True) @ beta_q_l

    totals: dict = {}
    for label, contribution in zip(cluster.tolist(), (w * e).tolist()):
        totals[label] = totals.get(label, 0.0) + contribution
    return math.sqrt(sum(v * v for v in totals.values()))


def test_cluster_groups_match_direct():
    x, y = dataset(300, 0.2, "curved", 0.15, shift=0.2)
    h, b = 0.25, 0.4
    cluster = (x * 10.0).astype(int)
    est = rd_estimate(x, y, h, b, vce="hc0", cluster=cluster)
    direct = _direct_clustered_robust_se(x, y, h, b, cluster)
    assert est.se_robust == pytest.approx(direct, abs=1e-10)


def test_bias_constant_p1():
    assert bias_constant(0, 1) == pytest.approx(-0.1)


def _solve_fraction(A, b):
    n = len(A)
    M = [row[:] + [bi] for row, bi in zip(A, b)]
    for col in range(n):
        pivot = col
        while pivot < n and M[pivot][col] == 0:
            pivot += 1
        assert pivot < n
        M[col], M[pivot] = M[pivot], M[col]
        piv = M[col][col]
        M[col] = [val / piv for val in M[col]]
        for r in range(n):
            if r != col and M[r][col] != 0:
                factor = M[r][col]
                M[r] = [M[r][c] - factor * M[col][c] for c in range(n + 1)]
    return [M[i][n] for i in range(n)]


def _closed_bias(nu, p):
    size = p + 1
    Gamma = [[Fraction(1, (i + j + 1) * (i + j + 2))
              for j in range(size)] for i in range(size)]
    vartheta = [Fraction(1, (i + p + 2) * (i + p + 3)) for i in range(size)]
    c = _solve_fraction(Gamma, vartheta)
    return float(math.factorial(nu) * c[nu])


def test_bias_constant_closed_forms():
    assert bias_constant(2, 2) == pytest.approx(_closed_bias(2, 2))
    assert bias_constant(3, 3) == pytest.approx(_closed_bias(3, 3))


def test_infeasible_bandwidth_model1():
    n = 500
    f = 0.625
    sigma = 0.1295

    Gamma1, _, Psi1 = kernel_constants(1, 2)
    inv1 = np.linalg.inv(Gamma1)
    V = 2.0 * sigma ** 2 * (inv1 @ Psi1 @ inv1)[0, 0] / f
    mu_pp_r = 2.0 * (-3.00)
    mu_pp_l = 2.0 * 7.18
    B = ((mu_pp_r - mu_pp_l) / 2.0) * bias_constant(0, 1)
    h_mse = (V / (4.0 * B ** 2)) ** (1.0 / 5.0) * n ** (-1.0 / 5.0)

    Gamma2, _, Psi2 = kernel_constants(2, 3)
    inv2 = np.linalg.inv(Gamma2)
    V2 = (2.0 * sigma ** 2 * math.factorial(2) ** 2
          * (inv2 @ Psi2 @ inv2)[2, 2] / f)
    mu_ppp_r = 6.0 * 7.99
    mu_ppp_l = 6.0 * 20.21
    B2 = ((mu_ppp_r + mu_ppp_l) / math.factorial(3)) * bias_constant(2, 2)
    b_mse = (5.0 * V2 / (2.0 * B2 ** 2)) ** (1.0 / 7.0) * n ** (-1.0 / 7.0)

    assert h_mse == pytest.approx(0.166, abs=5e-4)
    assert b_mse == pytest.approx(0.251, abs=5e-4)


def test_infeasible_bandwidth_model2():
    n = 500
    f = 0.625
    sigma = 0.1295

    mu_pp_r = 2.0 * (-54.81)
    mu_pp_l = 2.0 * 3.28
    mu_ppp_r = 6.0 * 74.30
    mu_ppp_l = 6.0 * 1.45

    Gamma1, _, Psi1 = kernel_constants(1, 2)
    inv1 = np.linalg.inv(Gamma1)
    V = 2.0 * sigma ** 2 * (inv1 @ Psi1 @ inv1)[0, 0] / f
    B = ((mu_pp_r - mu_pp_l) / 2.0) * bias_constant(0, 1)
    h_mse = (V / (4.0 * B ** 2)) ** (1.0 / 5.0) * n ** (-1.0 / 5.0)

    Gamma2, _, Psi2 = kernel_constants(2, 3)
    inv2 = np.linalg.inv(Gamma2)
    V2 = (2.0 * sigma ** 2 * math.factorial(2) ** 2
          * (inv2 @ Psi2 @ inv2)[2, 2] / f)
    B2 = ((mu_ppp_r + mu_ppp_l) / math.factorial(3)) * bias_constant(2, 2)
    b_mse = (5.0 * V2 / (2.0 * B2 ** 2)) ** (1.0 / 7.0) * n ** (-1.0 / 7.0)

    assert h_mse == pytest.approx(0.082, abs=5e-4)
    assert b_mse == pytest.approx(0.189, abs=5e-4)


def _lee_mu(x):
    return np.where(
        x >= 0,
        0.52 + 0.84*x - 3.00*x**2 + 7.99*x**3 - 9.01*x**4 + 3.56*x**5,
        0.48 + 1.27*x + 7.18*x**2 + 20.21*x**3 + 21.54*x**4 + 7.33*x**5,
    )


def _model2_mu(x):
    return np.where(
        x >= 0,
        0.26 + 18.49*x - 54.81*x**2 + 74.30*x**3 - 45.02*x**4 + 9.83*x**5,
        3.71 + 2.30*x + 3.28*x**2 + 1.45*x**3 + 0.23*x**4 + 0.03*x**5,
    )


def _run_bandwidth_monte_carlo(mu, n, reps):
    rng = np.random.default_rng(20140101)
    hs = []
    bs = []
    for _ in range(reps):
        x = 2.0 * rng.beta(2, 4, n) - 1.0
        eps = rng.normal(0, 0.1295, n)
        y = mu(x) + eps
        sel = mse_bandwidths(x, y)
        hs.append(sel.h)
        bs.append(sel.b)
    return np.asarray(hs), np.asarray(bs)


@pytest.mark.parametrize("mu, h_target, b_target", [
    (_lee_mu, 0.204, 0.332),
    (_model2_mu, 0.097, 0.223),
])
def test_mse_bandwidths_reproduce_published_averages(mu, h_target, b_target):
    """CCT Supplement Table S.A.II averages (5000 replications), within 3 Monte Carlo SE."""
    reps = 400
    hs, bs = _run_bandwidth_monte_carlo(mu, 500, reps)
    h_se = np.std(hs, ddof=1) / math.sqrt(reps)
    b_se = np.std(bs, ddof=1) / math.sqrt(reps)
    assert np.mean(hs) == pytest.approx(h_target, abs=3 * h_se)
    assert np.mean(bs) == pytest.approx(b_target, abs=3 * b_se)


def test_validation_errors():
    x = np.array([-0.5, -0.1, 0.1, 0.5])
    y = np.array([1.0, 2.0, 3.0, 4.0])
    with pytest.raises(RDError):
        rd_estimate(x[:-1], y, 0.2, 0.3)
    with pytest.raises(RDError):
        rd_estimate(x, y, 0.0, 0.3)
    with pytest.raises(RDError):
        rd_estimate(x, y, 0.2, 0.3, p=1, q=1)
    x_bad = np.array([-0.5, -0.5, 0.5, 0.5])
    y_bad = np.array([1.0, 2.0, 3.0, 4.0])
    with pytest.raises(RDError):
        rd_estimate(x_bad, y_bad, 0.2, 0.3)
    with pytest.raises(RDError):
        rd_estimate(x, y, 0.2, 0.3, vce="nn",
                     cluster=np.array([1, 1, 2, 2]))
    with pytest.raises(RDError):
        rd_estimate(x, y, 0.2, 0.3, level=1.2)
