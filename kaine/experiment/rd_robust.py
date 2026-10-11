# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Sharp regression-discontinuity estimation with robust bias correction.

Calonico, Cattaneo and Titiunik (2014), "Robust nonparametric confidence intervals for
regression-discontinuity designs", Econometrica 82(6), 2295-2326, and its Supplemental
Material. The module is written from the published formulas; no external RD software is
used.

Only numpy and the Python standard library are required.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np


class RDError(ValueError):
    """Exception raised for invalid input or an unidentified RD fit."""


@dataclass(frozen=True, slots=True)
class RDEstimate:
    tau_conventional: float
    tau_bias_corrected: float
    se_conventional: float
    se_robust: float
    ci_robust: tuple[float, float]
    n_left: int
    n_right: int
    h: float
    b: float


@dataclass(frozen=True, slots=True)
class RDWeights:
    w_conventional: np.ndarray
    w_bias_corrected: np.ndarray
    residuals_conventional: np.ndarray
    residuals_robust: np.ndarray


@dataclass(frozen=True, slots=True)
class BandwidthSelection:
    h: float
    b: float
    v: float
    c: float
    n: int


def _validate_x_y(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.ndim != 1 or y.ndim != 1:
        raise RDError("x and y must be one-dimensional")
    if x.size != y.size:
        raise RDError("x and y must have the same length")
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
        raise RDError("x and y must contain only finite values")
    return x, y


def _check_positive_finite(value, name):
    if not (math.isfinite(value) and value > 0):
        raise RDError(f"{name} is not positive and finite")


def kernel_constants(p, r):
    """Return Gamma, vartheta and Psi for the triangular kernel on [0, 1].

    CCT Supplement S.1.1.1.
    """
    p = int(p)
    size = p + 1
    Gamma = np.empty((size, size), dtype=float)
    vartheta = np.empty(size, dtype=float)
    Psi = np.empty((size, size), dtype=float)
    for i in range(size):
        for j in range(size):
            s = i + j
            Gamma[i, j] = 1.0 / ((s + 1) * (s + 2))
            Psi[i, j] = 2.0 / ((s + 1) * (s + 2) * (s + 3))
        vartheta[i] = 1.0 / ((i + r + 1) * (i + r + 2))
    return Gamma, vartheta, Psi


def bias_constant(nu, p):
    """nu! * (Gamma_p^{-1} vartheta_{p, p+1})[nu]. CCT's B_{nu, p}."""
    if not (0 <= nu <= p):
        raise RDError("nu must be between 0 and p")
    Gamma, vartheta, _ = kernel_constants(p, p + 1)
    try:
        c = np.linalg.solve(Gamma, vartheta)
    except np.linalg.LinAlgError as exc:
        raise RDError("kernel constant matrix is singular") from exc
    return float(math.factorial(int(nu)) * c[int(nu)])


def _local_poly(x_side, y_side, h, m):
    """Weighted local polynomial fit of order m at bandwidth h on one side.

    Returns beta and L such that beta = L y_side. Columns outside the bandwidth are
    zero. Raises RDError when the fit is not identified.
    """
    if h <= 0 or not math.isfinite(h):
        raise RDError("bandwidth must be positive and finite")
    inside = np.abs(x_side) < h
    x_in = x_side[inside]
    y_in = y_side[inside]
    if x_in.size < m + 1:
        raise RDError(f"side has fewer than {m + 1} units with positive weight")
    if np.unique(x_in).size < m + 1:
        raise RDError(f"side has fewer than {m + 1} distinct x values with positive weight")
    u = x_in / h
    w = (1.0 - np.abs(u)) / h
    R = np.vander(x_in, N=m + 1, increasing=True)
    Rw = R.T * w
    RWR = Rw @ R
    try:
        beta = np.linalg.solve(RWR, Rw @ y_in)
        L = np.linalg.solve(RWR, Rw)
    except np.linalg.LinAlgError as exc:
        raise RDError("local polynomial fit is numerically singular") from exc
    n_side = x_side.size
    L_full = np.zeros((m + 1, n_side), dtype=float)
    L_full[:, inside] = L
    return beta, L_full


def _D_scalar(x_side, h, p):
    """D_s(h) = e_0' (R_p' W_h R_p)^{-1} R_p' W_h x^{p+1}. CCT Appendix A.2."""
    _, L = _local_poly(x_side, np.zeros_like(x_side), h, p)
    # L is zero outside the bandwidth, so the whole side can be used.
    return float(L[0] @ (x_side ** (p + 1)))


def _residuals(x_side, y_side, beta, m):
    """Residuals from an order-m fit with coefficients beta. CCT Supplement S.2.4."""
    R = np.vander(x_side, N=m + 1, increasing=True)
    return y_side - R @ beta


def _eq_distance(a, b):
    if a == b:
        return True
    scale = max(abs(a), abs(b), 1.0)
    return abs(a - b) <= 1e-9 * scale


def _leq_distance(a, b):
    return a <= b or _eq_distance(a, b)


def _nearest_neighbor_sigma_side(x, y, side_mask, j, nn_window=None):
    """Nearest-neighbor variance estimates for one side. CCT Section 5.

    Abadie and Imbens (2006) with J = j neighbors. Ties at the J-th distance are all
    included.

    Loops in Python over the side's units (O(n J) work, a few seconds per side for
    about a hundred thousand units), which is acceptable for calibration runs over
    pooled pilot data and is the cost to watch if it is ever called per tick.
    """
    if j < 1:
        raise RDError("j must be a positive integer")
    n = x.size
    sigma2 = np.zeros(n, dtype=float)
    if nn_window is None:
        mask = side_mask
    else:
        mask = side_mask & (np.abs(x) <= nn_window)
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return sigma2
    xs = x[idx]
    ys = y[idx]
    order = np.argsort(xs, kind="mergesort")
    sx = xs[order]
    sy = ys[order]
    m = sx.size
    sorted_sigma2 = np.empty(m, dtype=float)
    for pos in range(m):
        lo = max(0, pos - j - 1)
        hi = min(m - 1, pos + j + 1)
        dists = []
        vals = []
        for k in range(lo, hi + 1):
            if k == pos:
                continue
            dists.append(abs(sx[k] - sx[pos]))
            vals.append(sy[k])
        total = len(dists)
        if total == 0:
            sorted_sigma2[pos] = 0.0
            continue
        dists_arr = np.asarray(dists)
        vals_arr = np.asarray(vals)
        if total <= j:
            mean_val = float(np.mean(vals_arr))
            count = total
        else:
            jth_index = j - 1
            jth = np.partition(dists_arr, jth_index)[jth_index]
            selected = np.array([_leq_distance(d, jth) for d in dists_arr])
            matched_vals = vals_arr[selected].tolist()
            k = lo - 1
            while k >= 0 and _eq_distance(abs(sx[k] - sx[pos]), jth):
                matched_vals.append(sy[k])
                k -= 1
            k = hi + 1
            while k < m and _eq_distance(abs(sx[k] - sx[pos]), jth):
                matched_vals.append(sy[k])
                k += 1
            count = len(matched_vals)
            mean_val = sum(matched_vals) / count
        sorted_sigma2[pos] = (count / (count + 1.0)) * (sy[pos] - mean_val) ** 2
    inv_order = np.empty_like(order)
    inv_order[order] = np.arange(m)
    sigma2[idx] = sorted_sigma2[inv_order]
    return sigma2


def _linear_variance(w, var_i):
    """Variance of w' y with independent errors var_i = sigma_i^2."""
    return float(np.sum(w ** 2 * var_i))


def _cluster_variance(w, e, cluster, active, k):
    """Liang-Zeger cluster sandwich with the CR1 small-sample adjustment.

    var_CR1 = G/(G-1) * (N-1)/(N-k) * sum_g (sum_i w_i e_i)^2, with N the units of
    positive weight, G their distinct clusters and k the parameters of the two
    side fits (Cameron and Miller 2015, "A Practitioner's Guide to Cluster-Robust
    Inference", Journal of Human Resources 50(2), 317-372, doi:10.3368/jhr.50.2.317).
    Without the adjustment the sandwich understates the variance when there are
    few clusters. The per-bin intervals of the contrast at threshold use it; they
    are reported and do not enter a test.
    """
    labels, inv = np.unique(cluster, return_inverse=True)
    # bincount accumulates repeated labels; fancy-index += would not.
    sums = np.bincount(inv, weights=w * e, minlength=labels.size)
    sandwich = float(np.sum(sums ** 2))
    active_labels = np.unique(cluster[active])
    n_active = int(np.sum(active))
    g = active_labels.size
    if g < 2:
        raise RDError("cluster variance needs at least two active clusters")
    if n_active <= k:
        raise RDError("cluster variance needs more active units than parameters")
    factor = (g / (g - 1)) * ((n_active - 1) / (n_active - k))
    return factor * sandwich


def rd_weights(x, y, h, b, *, p=1, q=2) -> RDWeights:
    """Return the weight vectors and residuals for RD estimation.

    The bias-corrected coefficient is ``w_bias_corrected @ y``. Residuals are
    local-linear at h for the conventional variance and local-quadratic at b
    for the robust variance.
    """
    x, y = _validate_x_y(x, y)
    n = x.size
    _check_positive_finite(h, "h")
    _check_positive_finite(b, "b")
    if p < 0 or p != int(p):
        raise RDError("p must be a non-negative integer")
    if q <= p or q != int(q):
        raise RDError("q must be an integer greater than p")
    p = int(p)
    q = int(q)

    left = x < 0
    right = ~left

    beta_p_r, L_p_r = _local_poly(x[right], y[right], h, p)
    beta_p_l, L_p_l = _local_poly(x[left], y[left], h, p)
    beta_q_r, L_q_r = _local_poly(x[right], y[right], b, q)
    beta_q_l, L_q_l = _local_poly(x[left], y[left], b, q)

    D_r = _D_scalar(x[right], h, p)
    D_l = _D_scalar(x[left], h, p)

    w_conv = np.zeros(n)
    w_bc = np.zeros(n)
    w_conv[right] = L_p_r[0]
    w_bc[right] = L_p_r[0] - D_r * L_q_r[p + 1]
    w_conv[left] = -L_p_l[0]
    w_bc[left] = -L_p_l[0] + D_l * L_q_l[p + 1]

    e_conv = np.zeros(n)
    e_robust = np.zeros(n)
    e_conv[right] = _residuals(x[right], y[right], beta_p_r, p)
    e_conv[left] = _residuals(x[left], y[left], beta_p_l, p)
    e_robust[right] = _residuals(x[right], y[right], beta_q_r, q)
    e_robust[left] = _residuals(x[left], y[left], beta_q_l, q)

    return RDWeights(
        w_conventional=w_conv,
        w_bias_corrected=w_bc,
        residuals_conventional=e_conv,
        residuals_robust=e_robust,
    )


def rd_estimate(
    x,
    y,
    h,
    b,
    *,
    p=1,
    q=2,
    vce="nn",
    cluster=None,
    j=3,
    level=0.95,
    nn_window=None,
):
    """Sharp RD estimate with conventional and bias-corrected coefficients.

    CCT Section 2.1, Appendix A.2, Theorem A.1(V) and Section 5.
    With ``cluster`` the variances are the run-clustered sandwich with the CR1
    adjustment of Cameron and Miller (2015), doi:10.3368/jhr.50.2.317.
    """
    x, y = _validate_x_y(x, y)
    n = x.size
    if not (math.isfinite(h) and h > 0):
        raise RDError("h must be positive and finite")
    if not (math.isfinite(b) and b > 0):
        raise RDError("b must be positive and finite")
    if p < 0 or p != int(p):
        raise RDError("p must be a non-negative integer")
    if q <= p or q != int(q):
        raise RDError("q must be an integer greater than p")
    if vce not in ("nn", "hc0"):
        raise RDError('vce must be "nn" or "hc0"')
    if cluster is not None:
        cluster = np.asarray(cluster)
        if cluster.ndim != 1 or cluster.size != n:
            raise RDError("cluster must be one-dimensional and the same length as x")
        if vce != "hc0":
            raise RDError("cluster is only allowed with vce='hc0'")
    if not (0.0 < level < 1.0):
        raise RDError("level must be between 0 and 1")
    p = int(p)
    q = int(q)

    left = x < 0
    right = ~left

    weights = rd_weights(x, y, h, b, p=p, q=q)
    w_conv = weights.w_conventional
    w_bc = weights.w_bias_corrected
    e_conv = weights.residuals_conventional
    e_robust = weights.residuals_robust

    tau_conv = float(w_conv @ y)
    tau_bc = float(w_bc @ y)

    if vce == "nn":
        left_sigma2 = _nearest_neighbor_sigma_side(x, y, left, j, nn_window)
        right_sigma2 = _nearest_neighbor_sigma_side(x, y, right, j, nn_window)
        sigma2 = left_sigma2 + right_sigma2
        var_conv = _linear_variance(w_conv, sigma2)
        var_robust = _linear_variance(w_bc, sigma2)
    else:
        if cluster is None:
            var_conv = float(np.sum(w_conv ** 2 * e_conv ** 2))
            var_robust = float(np.sum(w_bc ** 2 * e_robust ** 2))
        else:
            active_conv = np.abs(x) < h
            active_robust = np.abs(x) < max(h, b)
            var_conv = _cluster_variance(
                w_conv, e_conv, cluster, active_conv, 2 * (p + 1)
            )
            var_robust = _cluster_variance(
                w_bc, e_robust, cluster, active_robust, 2 * (q + 1)
            )

    se_conv = math.sqrt(max(var_conv, 0.0))
    se_robust = math.sqrt(max(var_robust, 0.0))
    z = NormalDist().inv_cdf(1.0 - (1.0 - level) / 2.0)
    ci = (tau_bc - z * se_robust, tau_bc + z * se_robust)

    cutoff = max(h, b)
    n_left = int(np.sum(left & (x > -cutoff)))
    n_right = int(np.sum(right & (x < cutoff)))

    return RDEstimate(
        tau_conventional=tau_conv,
        tau_bias_corrected=tau_bc,
        se_conventional=se_conv,
        se_robust=se_robust,
        ci_robust=ci,
        n_left=n_left,
        n_right=n_right,
        h=float(h),
        b=float(b),
    )


def wls_condition(x_side, g, m) -> float:
    """Condition number of the weighted local-polynomial design matrix.

    Paper A.8: rows (1, u_i, ..., u_i^m) with u_i = x_i / g and weights
    1 - |u_i| over units with |x_i| < g. Returns infinity when fewer than
    m + 1 distinct x values have positive weight.
    """
    x_side = np.asarray(x_side, dtype=float)
    if x_side.ndim != 1:
        raise RDError("x_side must be one-dimensional")
    _check_positive_finite(g, "g")
    if m < 0 or m != int(m):
        raise RDError("m must be a non-negative integer")
    m = int(m)
    inside = np.abs(x_side) < g
    x_in = x_side[inside]
    if x_in.size < m + 1:
        return math.inf
    if np.unique(x_in).size < m + 1:
        return math.inf
    u = x_in / g
    w = 1.0 - np.abs(u)
    R = np.vander(u, N=m + 1, increasing=True)
    Rw = R.T * w
    return float(np.linalg.cond(Rw @ R))


def _global_poly_coeffs(x_side, y_side, degree):
    """Unweighted OLS polynomial coefficients on one side."""
    if np.unique(x_side).size < degree + 1:
        raise RDError(f"side has fewer than {degree + 1} distinct x values")
    R = np.vander(x_side, N=degree + 1, increasing=True)
    try:
        beta = np.linalg.solve(R.T @ R, R.T @ y_side)
    except np.linalg.LinAlgError as exc:
        raise RDError("global polynomial fit is numerically singular") from exc
    return beta


def _rule_of_thumb_bandwidth(x, n):
    """Silverman-style pilot bandwidth. CCT Supplement S.2.6, Step 0."""
    sx = float(np.std(x, ddof=1))
    iqr = float(np.percentile(x, 75) - np.percentile(x, 25))
    return 2.58 * min(sx, iqr / 1.349) * (n ** (-1.0 / 5.0))


def _varsum_coefficient(k, g, m, x, y, side_mask, sigma2):
    """Var_s(k; g, m) = sum_i L[k, i]^2 sigma_i^2 for one side."""
    _, L = _local_poly(x[side_mask], y[side_mask], g, m)
    return float(np.sum(L[k] ** 2 * sigma2[side_mask]))


def _V_hat(nu_deriv, p_order, g, x, y, left, right, sigma2):
    """nu_deriv!^2 * VarSum(nu_deriv; g, p_order)."""
    varsum = _varsum_coefficient(nu_deriv, g, p_order, x, y, left, sigma2)
    varsum += _varsum_coefficient(nu_deriv, g, p_order, x, y, right, sigma2)
    return float(math.factorial(int(nu_deriv)) ** 2 * varsum)


def mse_bandwidths(x, y, *, p=1, q=2, nu=0, j=3):
    """MSE-optimal bandwidth selector. CCT Supplement S.2.6, Steps 0-2.

    Returns selected h and b together with the pilot bandwidths v and c and the sample
    size n.
    """
    x, y = _validate_x_y(x, y)
    n = x.size
    if n < 2:
        raise RDError("sample size must be at least 2")
    if p < 0 or p != int(p):
        raise RDError("p must be a non-negative integer")
    if q <= p or q != int(q):
        raise RDError("q must be an integer greater than p")
    if nu < 0 or nu > p or nu != int(nu):
        raise RDError("nu must be an integer between 0 and p")
    p = int(p)
    q = int(q)
    nu = int(nu)

    left = x < 0
    right = ~left
    # The nearest-neighbor variances do not depend on the bandwidth, so they are
    # computed once, over the whole side (CCT Section 5).
    sigma2 = _nearest_neighbor_sigma_side(x, y, left, j) + _nearest_neighbor_sigma_side(
        x, y, right, j
    )

    try:
        v = _rule_of_thumb_bandwidth(x, n)
        _check_positive_finite(v, "Step 0 pilot bandwidth")

        # Step 0
        gamma_r = _global_poly_coeffs(x[right], y[right], q + 2)
        gamma_l = _global_poly_coeffs(x[left], y[left], q + 2)
        dg = gamma_r[q + 2] - ((-1) ** (nu + q)) * gamma_l[q + 2]
        V_q1 = _V_hat(q + 1, q + 1, v, x, y, left, right, sigma2)
        bias_c = bias_constant(q + 1, q + 1)
        denom_c = 2.0 * (bias_c ** 2) * (dg ** 2)
        _check_positive_finite(denom_c, "Step 0 denominator")
        C_c = ((2 * q + 3) * n * (v ** (2 * q + 3)) * V_q1) / denom_c
        _check_positive_finite(C_c, "Step 0 constant")
        c = (C_c ** (1.0 / (2 * q + 5))) * (n ** (-1.0 / (2 * q + 5)))

        # Step 1
        beta_r_q1, _ = _local_poly(x[right], y[right], c, q + 1)
        beta_l_q1, _ = _local_poly(x[left], y[left], c, q + 1)
        d1 = beta_r_q1[q + 1] - ((-1) ** (nu + q + 1)) * beta_l_q1[q + 1]
        R1 = _varsum_coefficient(q + 1, c, q + 1, x, y, left, sigma2)
        R1 += _varsum_coefficient(q + 1, c, q + 1, x, y, right, sigma2)
        V_p1q = _V_hat(p + 1, q, v, x, y, left, right, sigma2)
        bias_b = bias_constant(p + 1, q)
        # CCT write V_hat in the regularization terms, but R1 is on the coefficient
        # variance scale. Using VarSum reproduces the Monte Carlo averages in
        # CCT Supplement Table S.A.II.
        denom_b = 2.0 * (q - p) * (bias_b ** 2) * (d1 ** 2 + 3.0 * R1)
        _check_positive_finite(denom_b, "Step 1 denominator")
        C_b = ((2 * p + 3) * n * (v ** (2 * p + 3)) * V_p1q) / denom_b
        _check_positive_finite(C_b, "Step 1 constant")
        b = (C_b ** (1.0 / (2 * q + 3))) * (n ** (-1.0 / (2 * q + 3)))

        # Step 2
        beta_r_q, _ = _local_poly(x[right], y[right], b, q)
        beta_l_q, _ = _local_poly(x[left], y[left], b, q)
        d2 = beta_r_q[p + 1] - ((-1) ** (nu + p + 1)) * beta_l_q[p + 1]
        R2 = _varsum_coefficient(p + 1, b, q, x, y, left, sigma2)
        R2 += _varsum_coefficient(p + 1, b, q, x, y, right, sigma2)
        V_nup = _V_hat(nu, p, v, x, y, left, right, sigma2)
        bias_h = bias_constant(nu, p)
        denom_h = 2.0 * (p + 1 - nu) * (bias_h ** 2) * (d2 ** 2 + 3.0 * R2)
        _check_positive_finite(denom_h, "Step 2 denominator")
        C_h = ((2 * nu + 1) * n * (v ** (1 + 2 * nu)) * V_nup) / denom_h
        _check_positive_finite(C_h, "Step 2 constant")
        h = (C_h ** (1.0 / (2 * p + 3))) * (n ** (-1.0 / (2 * p + 3)))
    except RDError:
        raise
    except Exception as exc:
        raise RDError(f"bandwidth selection failed: {exc}") from exc

    return BandwidthSelection(h=float(h), b=float(b), v=float(v), c=float(c), n=n)


__all__ = [
    "RDError",
    "RDEstimate",
    "RDWeights",
    "BandwidthSelection",
    "kernel_constants",
    "bias_constant",
    "rd_estimate",
    "rd_weights",
    "wls_condition",
    "mse_bandwidths",
]
