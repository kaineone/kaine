# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Offline validation simulation for the individuation instrument.

This script generates synthetic beings and uses only
``kaine/lifecycle/individuation_stats.py`` to exercise the statistics core
before any real organ data exists.
"""

import argparse
import concurrent.futures
import dataclasses
import importlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

import numpy as np

# Make the repo root importable so that ``kaine.lifecycle.individuation_stats``
# can be loaded.
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

stats = importlib.import_module("kaine.lifecycle.individuation_stats")

DIM: int = 384
N_PROMPTS: int = 12
CLUSTER_SIZES: Sequence[int] = (2, 3, 4)
DEFAULT_SEED: int = 20261003
DEFAULT_SIGMA: float = 1.0


@dataclasses.dataclass
class PromptModel:
    """A single prompt's embedding distribution: unit centres + weights."""

    centres: np.ndarray
    weights: np.ndarray

    @property
    def k(self) -> int:
        return self.centres.shape[0]

    @property
    def d(self) -> int:
        return self.centres.shape[1]


@dataclasses.dataclass
class PowerCondition:
    """One cell of the power / MMD design."""

    n_b: int
    n_c: int
    drift: tuple
    looks: list[int]


def _json_default(o):
    """Convert numpy scalars and arrays for json.dumps."""
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def _normalize_rows(a: np.ndarray) -> np.ndarray:
    """Row-wise L2 normalisation, guarding against zero rows."""
    norms = np.linalg.norm(a, axis=-1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return a / norms


def _spawn_seeds(rng: np.random.Generator, n: int) -> list[int]:
    """Spawn ``n`` child generators and return stable integer seeds."""
    children = rng.spawn(n)
    return [int(child.integers(0, 1 << 63)) for child in children]


def _progress(i: int, n: int, label: str) -> None:
    """Print progress to stderr every ~10%."""
    step = max(1, n // 10)
    if (i + 1) % step == 0 or i == n - 1:
        print(f"{label}: {i + 1}/{n}", file=sys.stderr)


def make_prompt_model(rng: np.random.Generator, d: int = DIM) -> PromptModel:
    """Draw K centres and a Dirichlet(2,...,2) weight vector."""
    k = int(rng.choice(CLUSTER_SIZES))
    centres = _normalize_rows(rng.standard_normal((k, d)))
    weights = rng.dirichlet(np.full(k, 2.0))
    return PromptModel(centres=centres, weights=weights)


def make_being(rng: np.random.Generator, n_prompts: int = N_PROMPTS) -> list[PromptModel]:
    """Create a synthetic being: one mixture model per prompt."""
    return [make_prompt_model(rng) for _ in range(n_prompts)]


def sample_prompt_vectors(
    model: PromptModel, n: int, sigma: float, rng: np.random.Generator
) -> np.ndarray:
    """Draw n unit vectors from a prompt's Gaussian-mixture."""
    # Pick a cluster for each draw.
    idx = rng.choice(model.k, size=n, p=model.weights)
    centres = model.centres[idx]  # (n, d)
    noise = rng.standard_normal((n, model.d))
    # sigma / sqrt(d) keeps the angular dispersion roughly stable with d.
    raw = centres + sigma * noise / math.sqrt(model.d)
    return _normalize_rows(raw)


def being_samples(
    being: list[PromptModel], n: int, sigma: float, rng: np.random.Generator
) -> list[np.ndarray]:
    """Sample the whole being, returning one array per prompt."""
    return [sample_prompt_vectors(model, n, sigma, rng) for model in being]


def reference_vector(birth_samples: list[np.ndarray]) -> np.ndarray:
    """Birth reference used by the old percentile rule.

    Mean of the birth sample over prompts, normalised.
    """
    per_prompt = np.stack([s.mean(axis=0) for s in birth_samples])
    return _normalize_rows(per_prompt.mean(axis=0).reshape(1, -1))[0]


def mean_within_prompt_cosine(samples: list[np.ndarray]) -> float:
    """Average pairwise cosine similarity inside each prompt."""
    values = []
    for a in samples:
        a = np.asarray(a, dtype=np.float64)
        norms = np.linalg.norm(a, axis=1)
        denom = np.outer(norms, norms)
        cos = (a @ a.T) / np.where(denom == 0, 1.0, denom)
        m = cos.shape[0]
        # Exclude the unit diagonal.
        total = cos.sum() - m
        values.append(total / (m * (m - 1)))
    return float(np.mean(values))


def estimate_dispersion(
    being: list[PromptModel],
    sigma: float,
    rng: np.random.Generator,
    n: int = 200,
) -> float:
    """Mean within-prompt cosine for a given dispersion level."""
    samples = being_samples(being, n, sigma, rng)
    return mean_within_prompt_cosine(samples)


def apply_cluster_drift(
    model: PromptModel, pi: float, rng: np.random.Generator
) -> PromptModel:
    """Add a new cluster with weight ``pi`` and rescale the old weights."""
    new_centre = _normalize_rows(rng.standard_normal((1, model.d)))
    centres = np.concatenate([model.centres, new_centre], axis=0)
    weights = model.weights * (1.0 - pi)
    weights = np.append(weights, pi)
    return PromptModel(centres=centres, weights=weights)


def apply_shift_drift(
    model: PromptModel, delta: float, rng: np.random.Generator
) -> PromptModel:
    """Shift every centre by ``delta * u`` with one random unit ``u``."""
    u = _normalize_rows(rng.standard_normal((1, model.d)))[0]
    shifted = _normalize_rows(model.centres + delta * u)
    return PromptModel(centres=shifted, weights=model.weights.copy())


def apply_partial_drift(
    being: list[PromptModel],
    m: int,
    pi: float,
    rng: np.random.Generator,
) -> list[PromptModel]:
    """Apply cluster drift to only ``m`` of the 12 prompts."""
    models = list(being)
    idx = rng.choice(len(models), size=m, replace=False)
    for i in idx:
        models[i] = apply_cluster_drift(models[i], pi, rng)
    return models


def apply_drift(
    being: list[PromptModel], drift: tuple, rng: np.random.Generator
) -> list[PromptModel]:
    """Dispatch drift construction."""
    kind = drift[0]
    if kind == "cluster":
        pi = drift[1]
        return [apply_cluster_drift(model, pi, rng) for model in being]
    if kind == "shift":
        delta = drift[1]
        return [apply_shift_drift(model, delta, rng) for model in being]
    if kind == "partial":
        m = drift[1]
        pi = drift[2]
        return apply_partial_drift(being, m, pi, rng)
    raise ValueError(f"Unknown drift {drift!r}")


def drift_label(drift: tuple) -> str:
    """Human-readable drift label for tables."""
    kind = drift[0]
    if kind == "cluster":
        return f"cluster-pi{drift[1]}"
    if kind == "shift":
        return f"shift-d{drift[1]}"
    if kind == "partial":
        return f"partial-m{drift[1]}-pi{drift[2]}"
    return str(drift)


def run_energy_test(
    birth: list[np.ndarray],
    current: list[np.ndarray],
    permutations: int,
    rng: np.random.Generator,
    alpha: float | None = None,
) -> stats.PermutationResult:
    """Convenience wrapper around the core stratified energy test."""
    strata = [(birth[i], current[i]) for i in range(len(birth))]
    return stats.permutation_test(
        strata,
        permutations=permutations,
        rng=rng,
        alpha=alpha,
        batch_size=4096,
    )


def old_percentile_reject(
    being: list[PromptModel],
    ref: np.ndarray,
    sigma: float,
    n_nulls: int,
    rng: np.random.Generator,
) -> bool:
    """Simulate the legacy single-transcript percentile rule."""
    # Draw n_nulls + 1 transcripts; each transcript = normalised mean over
    # prompts of one draw per prompt.
    per_prompt = np.stack(
        [sample_prompt_vectors(model, n_nulls + 1, sigma, rng) for model in being],
        axis=0,
    )  # (12, n_nulls+1, d)
    transcripts = _normalize_rows(per_prompt.mean(axis=0))  # (n_nulls+1, d)
    nulls = transcripts[:-1]
    fork = transcripts[-1]
    null_div = 1.0 - nulls @ ref
    fork_div = 1.0 - fork @ ref
    pct = np.percentile(null_div, 95)
    return bool(fork_div > pct)


# --------------------------------------------------------------------------- #
# MMD helpers (experiment 4)
# --------------------------------------------------------------------------- #


def _squared_distance_matrix(a: np.ndarray) -> np.ndarray:
    """Pairwise squared Euclidean distance matrix."""
    a = np.asarray(a, dtype=np.float64)
    sum_sq = np.sum(a * a, axis=1)
    cross = a @ a.T
    sq = sum_sq[:, None] + sum_sq[None, :] - 2.0 * cross
    np.maximum(sq, 0.0, out=sq)
    return sq


def _median_bandwidth(pooled: np.ndarray) -> float:
    """Median heuristic: median of off-diagonal squared distances."""
    D2 = _squared_distance_matrix(pooled)
    mask = ~np.eye(D2.shape[0], dtype=bool)
    med = float(np.median(D2[mask]))
    if med <= 0.0:
        med = 1e-12
    return med


def _mmd_statistic_from_kernel(
    K: np.ndarray, labels: np.ndarray, n_b: int, n_c: int
) -> np.ndarray:
    """Batch MMD^2_u from a kernel matrix with zeroed diagonal.

    MMD^2_u = sum_xx/(n_b(n_b-1)) + sum_yy/(n_c(n_c-1))
              - 2 sum_xy/(n_b n_c).
    """
    P = labels.astype(np.float64)
    Q = 1.0 - P
    sum_xx = np.einsum("km,mn,kn->k", P, K, P)
    sum_yy = np.einsum("km,mn,kn->k", Q, K, Q)
    sum_xy = np.einsum("km,mn,kn->k", P, K, Q)
    return (
        sum_xx / (n_b * (n_b - 1))
        + sum_yy / (n_c * (n_c - 1))
        - 2.0 * sum_xy / (n_b * n_c)
    )


def mmd_permutation_test(
    strata: Sequence[tuple[np.ndarray, np.ndarray]],
    *,
    permutations: int,
    rng: np.random.Generator,
    alpha: float | None = None,
    batch_size: int = 4096,
) -> dict:
    """Stratified Gaussian-kernel MMD two-sample permutation test."""
    if permutations < 1:
        raise ValueError("permutations must be at least 1")

    K_list: list[np.ndarray] = []
    n_b_list: list[int] = []
    m_list: list[int] = []

    for x, y in strata:
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        pooled = np.concatenate([x, y], axis=0)
        bw2 = _median_bandwidth(pooled)
        D2 = _squared_distance_matrix(pooled)
        K = np.exp(-D2 / (2.0 * bw2))
        np.fill_diagonal(K, 0.0)
        K_list.append(K)
        n_b_list.append(x.shape[0])
        m_list.append(pooled.shape[0])

    # Observed statistic.
    T_obs = 0.0
    for K, n_b in zip(K_list, n_b_list):
        n_c = K.shape[0] - n_b
        labels = np.zeros((1, K.shape[0]))
        labels[0, :n_b] = 1.0
        T_obs += float(_mmd_statistic_from_kernel(K, labels, n_b, n_c)[0])

    B = permutations
    exceed = 0
    evaluated = 0
    stopped_early = False
    threshold = T_obs - 1e-12 * max(1.0, abs(T_obs))

    while evaluated < B:
        k = min(batch_size, B - evaluated)
        P_list = [
            stats._random_label_matrix(k, m, n_b, rng)
            for m, n_b in zip(m_list, n_b_list)
        ]
        T_batch = np.zeros(k, dtype=np.float64)
        for K, P, n_b in zip(K_list, P_list, n_b_list):
            n_c = K.shape[0] - n_b
            T_batch += _mmd_statistic_from_kernel(K, P, n_b, n_c)
        exceed += int(np.sum(T_batch >= threshold))
        evaluated += k
        if alpha is not None and (exceed + 1) / (B + 1) > alpha:
            stopped_early = True
            break

    p_value = (exceed + 1) / (B + 1)
    return {
        "p_value": float(p_value),
        "statistic": float(T_obs),
        "permutations": evaluated,
        "exceed": exceed,
        "planned": B,
        "stopped_early": stopped_early,
    }


# --------------------------------------------------------------------------- #
# Experiment 1: size
# --------------------------------------------------------------------------- #


def _size_worker(seed_sigma: tuple[int, float]) -> float:
    seed, sigma = seed_sigma
    rng = np.random.default_rng(seed)
    being = make_being(rng)
    birth = being_samples(being, 16, sigma, rng)
    current = being_samples(being, 8, sigma, rng)
    res = run_energy_test(birth, current, 999, rng)
    return float(res.p_value)


def run_size(
    N: int = 5000,
    quick: bool = False,
    seed: int = DEFAULT_SEED,
    workers: int = 1,
    sigma: float = DEFAULT_SIGMA,
    out: Path | None = None,
) -> dict:
    """Type-I error calibration under the null (birth == current model)."""
    n = 500 if quick else N
    rng = np.random.default_rng(seed)
    seeds = _spawn_seeds(rng, n)

    start = time.perf_counter()
    pvals: list[float] = []

    if workers > 1:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(_size_worker, (s, sigma)) for s in seeds]
            for i, fut in enumerate(concurrent.futures.as_completed(futures)):
                pvals.append(fut.result())
                _progress(i, n, "size")
    else:
        for i, s in enumerate(seeds):
            pvals.append(_size_worker((s, sigma)))
            _progress(i, n, "size")

    pvals_arr = np.asarray(pvals)

    def rate_at(alpha: float) -> dict:
        rate = float(np.mean(pvals_arr <= alpha))
        se = math.sqrt(alpha * (1.0 - alpha) / n)
        bound = alpha + 2.0 * se
        return {
            "alpha": alpha,
            "rate": rate,
            "se": se,
            "ci_low": max(0.0, rate - 2.0 * se),
            "ci_high": min(1.0, rate + 2.0 * se),
            "bound": bound,
            "pass": rate <= bound,
        }

    alpha05 = rate_at(0.05)
    alpha01 = rate_at(0.01)

    # One-sided Kolmogorov-Smirnov check that p-values are uniform or
    # conservative: D+ = sup_t (F_n(t) - t) over t in [1/(B+1), 1), compared
    # with the simultaneous DKW band eps = sqrt(ln(1/0.05) / (2n)), which holds
    # for all t at once with probability >= 0.95 (Dvoretzky-Kiefer-Wolfowitz,
    # Massart's constant). A per-threshold 2*SE band tested at 99 thresholds
    # would fail by chance alone even for an exactly calibrated test.
    ts = np.arange(1, 1000) / 1000.0
    worst_val = -1.0
    worst_t = 0.0
    for t in ts:
        diff = float(np.mean(pvals_arr <= t)) - t
        if diff > worst_val:
            worst_val = diff
            worst_t = float(t)
    worst_bound = math.sqrt(math.log(1.0 / 0.05) / (2.0 * n))
    ks_pass = worst_val <= worst_bound

    wall = time.perf_counter() - start

    # Independent dispersion estimate.
    disp_rng = np.random.default_rng(seed + 1)
    disp_being = make_being(disp_rng)
    cosine = estimate_dispersion(disp_being, sigma, disp_rng)

    result = {
        "experiment": "size",
        "parameters": {
            "N": n,
            "n_b": 16,
            "n_c": 8,
            "permutations": 999,
            "sigma": sigma,
            "seed": seed,
            "quick": quick,
        },
        "mean_within_prompt_cosine": cosine,
        "alpha05": alpha05,
        "alpha01": alpha01,
        "ks_check": {
            "worst_t": worst_t,
            "worst_value": worst_val,
            "worst_bound": worst_bound,
            "pass": ks_pass,
        },
        "p_values": pvals,
        "wall_seconds": wall,
    }

    if out is not None:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, default=_json_default), encoding="utf-8")

    print("\n=== size ===")
    print(f"N={n}, sigma={sigma}, mean within-prompt cosine={cosine:.4f}")
    print(
        f"alpha=0.05: rate={alpha05['rate']:.4f} "
        f"(2SE=[{alpha05['ci_low']:.4f},{alpha05['ci_high']:.4f}], "
        f"bound={alpha05['bound']:.4f}) {'PASS' if alpha05['pass'] else 'FAIL'}"
    )
    print(
        f"alpha=0.01: rate={alpha01['rate']:.4f} "
        f"(2SE=[{alpha01['ci_low']:.4f},{alpha01['ci_high']:.4f}], "
        f"bound={alpha01['bound']:.4f}) {'PASS' if alpha01['pass'] else 'FAIL'}"
    )
    print(
        f"KS uniformity: worst t={worst_t:.2f}, value={worst_val:.4f}, "
        f"DKW bound={worst_bound:.4f} {'PASS' if ks_pass else 'FAIL'}"
    )
    print(f"wall time: {wall:.1f}s")

    return result


# --------------------------------------------------------------------------- #
# Experiment 2: lifetime
# --------------------------------------------------------------------------- #


def _lifetime_worker(args: tuple[int, float, int]) -> dict:
    seed, sigma, looks = args
    rng = np.random.default_rng(seed)
    being = make_being(rng)
    birth = being_samples(being, 16, sigma, rng)
    ref = reference_vector(birth)

    instrument_first: int | None = None
    naive_first: int | None = None
    old_first: int | None = None
    total_perms = 0

    for k in range(1, looks + 1):
        current = being_samples(being, 8, sigma, rng)

        # (i) Spending-alpha instrument rule.
        alpha_k = stats.spending_alpha(k)
        B = stats.required_permutations(alpha_k)
        if B is not None:
            res = run_energy_test(birth, current, B, rng, alpha=alpha_k)
            total_perms += res.permutations
            if res.p_value <= alpha_k and instrument_first is None:
                instrument_first = k

        # (ii) Naive 5% rule.
        if naive_first is None:
            res_naive = run_energy_test(birth, current, 999, rng)
            if res_naive.p_value <= 0.05:
                naive_first = k

        # (iii) Old percentile rule.
        if old_first is None:
            if old_percentile_reject(being, ref, sigma, 50, rng):
                old_first = k

    return {
        "instrument_first": instrument_first,
        "naive_first": naive_first,
        "old_first": old_first,
        "total_perms": total_perms,
    }


def _summarise_lifetime_runs(
    runs: list[dict], looks_of_interest: Sequence[int], L: int, rule_name: str
) -> dict:
    """Compute share of lives with any rejection by selected looks."""
    by_look: dict[str, dict] = {}
    for look in looks_of_interest:
        if rule_name == "instrument":
            n_reject = sum(1 for r in runs if r["instrument_first"] is not None and r["instrument_first"] <= look)
        elif rule_name == "naive":
            n_reject = sum(1 for r in runs if r["naive_first"] is not None and r["naive_first"] <= look)
        else:  # old_percentile
            n_reject = sum(1 for r in runs if r["old_first"] is not None and r["old_first"] <= look)
        rate = n_reject / L
        se = math.sqrt(rate * (1.0 - rate) / L)
        by_look[str(look)] = {
            "rate": rate,
            "se": se,
            "ci_low": max(0.0, rate - 2.0 * se),
            "ci_high": min(1.0, rate + 2.0 * se),
            "n_reject": n_reject,
        }
    return by_look


def run_lifetime(
    L: int = 2000,
    looks: int = 100,
    quick: bool = False,
    seed: int = DEFAULT_SEED,
    workers: int = 1,
    sigma: float = DEFAULT_SIGMA,
    out: Path | None = None,
) -> dict:
    """Familywise error over many sequential looks under H0."""
    n_lives = 200 if quick else L
    rng = np.random.default_rng(seed)
    seeds = _spawn_seeds(rng, n_lives)

    start = time.perf_counter()
    runs: list[dict] = []

    if workers > 1:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(_lifetime_worker, (s, sigma, looks)) for s in seeds]
            for i, fut in enumerate(concurrent.futures.as_completed(futures)):
                runs.append(fut.result())
                _progress(i, n_lives, "lifetime")
    else:
        for i, s in enumerate(seeds):
            runs.append(_lifetime_worker((s, sigma, looks)))
            _progress(i, n_lives, "lifetime")

    looks_of_interest = [10, 50, 100]
    instrument = _summarise_lifetime_runs(runs, looks_of_interest, n_lives, "instrument")
    naive = _summarise_lifetime_runs(runs, looks_of_interest, n_lives, "naive")
    old = _summarise_lifetime_runs(runs, looks_of_interest, n_lives, "old_percentile")

    mean_perms = float(np.mean([r["total_perms"] / looks for r in runs]))

    se100 = math.sqrt(0.05 * 0.95 / n_lives)
    bound100 = 0.05 + 2.0 * se100
    pass_instrument = instrument["100"]["rate"] <= bound100

    wall = time.perf_counter() - start

    disp_rng = np.random.default_rng(seed + 2)
    disp_being = make_being(disp_rng)
    cosine = estimate_dispersion(disp_being, sigma, disp_rng)

    result = {
        "experiment": "lifetime",
        "parameters": {
            "L": n_lives,
            "looks": looks,
            "n_b": 16,
            "n_c": 8,
            "sigma": sigma,
            "seed": seed,
            "quick": quick,
        },
        "mean_within_prompt_cosine": cosine,
        "instrument": {
            "mean_permutations_per_look": mean_perms,
            "by_look": instrument,
            "pass": pass_instrument,
        },
        "naive": {"by_look": naive},
        "old_percentile": {"by_look": old},
        "wall_seconds": wall,
    }

    if out is not None:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, default=_json_default), encoding="utf-8")

    print("\n=== lifetime ===")
    print(f"L={n_lives}, looks={looks}, sigma={sigma}, cosine={cosine:.4f}")
    print(f"instrument mean permutations/look = {mean_perms:.0f}")
    print(f"{'look':>6} {'instrument':>18} {'naive':>18} {'old_pct':>18}")
    for look in looks_of_interest:
        i = instrument[str(look)]
        n = naive[str(look)]
        o = old[str(look)]
        print(
            f"{look:>6} "
            f"{i['rate']:.3f} (±{2*i['se']:.3f}) "
            f"{n['rate']:.3f} (±{2*n['se']:.3f}) "
            f"{o['rate']:.3f} (±{2*o['se']:.3f})"
        )
    print(
        f"instrument look-100 bound={bound100:.4f} "
        f"{'PASS' if pass_instrument else 'FAIL'}"
    )
    print(f"wall time: {wall:.1f}s")

    return result


# --------------------------------------------------------------------------- #
# Experiment 3: power
# --------------------------------------------------------------------------- #


def _build_power_conditions() -> list[PowerCondition]:
    conditions: list[PowerCondition] = []
    for nb, nc in ((12, 6), (16, 8), (24, 12)):
        for pi in (0.25, 0.5):
            looks = [1, 10, 50] if (nb, nc) == (16, 8) and pi == 0.5 else [1, 10]
            conditions.append(PowerCondition(nb, nc, ("cluster", pi), looks))
        for delta in (0.25, 0.5):
            conditions.append(PowerCondition(nb, nc, ("shift", delta), [1, 10]))
        for m in (3, 6):
            looks = [1, 10, 50] if (nb, nc) == (16, 8) and m == 6 else [1, 10]
            conditions.append(PowerCondition(nb, nc, ("partial", m, 0.5), looks))
    return conditions


def _power_worker(args: tuple[int, float, list[PowerCondition]]) -> dict:
    seed, sigma, conditions = args
    rng = np.random.default_rng(seed)
    base = make_being(rng)

    # Maximum sample sizes for this design.
    birth24 = being_samples(base, 24, sigma, rng)

    results: dict = {}
    for cond in conditions:
        drifted = apply_drift(base, cond.drift, rng)
        current12 = being_samples(drifted, 12, sigma, rng)
        birth = [s[: cond.n_b] for s in birth24]
        current = [s[: cond.n_c] for s in current12]

        key = f"{cond.n_b}x{cond.n_c}_{drift_label(cond.drift)}"
        for look in cond.looks:
            alpha_k = stats.spending_alpha(look)
            B = stats.required_permutations(alpha_k)
            if B is None:
                results[(key, look)] = None
                continue
            res = run_energy_test(birth, current, B, rng, alpha=alpha_k)
            results[(key, look)] = int(res.p_value <= alpha_k)
    return results


def _aggregate_counts(results: list[dict], R: int) -> list[dict]:
    totals: dict[tuple[str, int], int] = {}
    for res in results:
        for key, val in res.items():
            if val is None:
                continue
            totals[key] = totals.get(key, 0) + int(val)

    rows = []
    for (key, look), count in sorted(totals.items()):
        power = count / R
        se = math.sqrt(power * (1.0 - power) / R)
        rows.append(
            {
                "key": key,
                "look": look,
                "n_reject": count,
                "power": power,
                "se": se,
                "ci_low": max(0.0, power - 2.0 * se),
                "ci_high": min(1.0, power + 2.0 * se),
            }
        )
    return rows


def run_power(
    R: int = 200,
    quick: bool = False,
    seed: int = DEFAULT_SEED,
    workers: int = 1,
    sigma: float = DEFAULT_SIGMA,
    out: Path | None = None,
) -> dict:
    """Power against the three drift families at sequential looks."""
    n_runs = 40 if quick else R
    conditions = _build_power_conditions()
    rng = np.random.default_rng(seed)
    seeds = _spawn_seeds(rng, n_runs)

    start = time.perf_counter()
    runs: list[dict] = []

    if workers > 1:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as ex:
            futures = [
                ex.submit(_power_worker, (s, sigma, conditions)) for s in seeds
            ]
            for i, fut in enumerate(concurrent.futures.as_completed(futures)):
                runs.append(fut.result())
                _progress(i, n_runs, "power")
    else:
        for i, s in enumerate(seeds):
            runs.append(_power_worker((s, sigma, conditions)))
            _progress(i, n_runs, "power")

    rows = _aggregate_counts(runs, n_runs)

    # Pre-registered acceptance.
    pre_key = "16x8_cluster-pi0.5"
    pre_row = next((r for r in rows if r["key"] == pre_key and r["look"] == 10), None)
    pre_power = pre_row["power"] if pre_row else 0.0
    pre_registered = {
        "look": 10,
        "n_b": 16,
        "n_c": 8,
        "drift": "cluster-pi0.5",
        "power": pre_power,
        "threshold": 0.8,
        "pass": pre_power >= 0.8,
    }

    wall = time.perf_counter() - start

    disp_rng = np.random.default_rng(seed + 3)
    disp_being = make_being(disp_rng)
    cosine = estimate_dispersion(disp_being, sigma, disp_rng)

    result = {
        "experiment": "power",
        "parameters": {
            "R": n_runs,
            "sigma": sigma,
            "seed": seed,
            "quick": quick,
        },
        "mean_within_prompt_cosine": cosine,
        "results": rows,
        "pre_registered": pre_registered,
        "wall_seconds": wall,
    }

    if out is not None:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, default=_json_default), encoding="utf-8")

    print("\n=== power ===")
    print(f"R={n_runs}, sigma={sigma}, cosine={cosine:.4f}")
    print(f"pre-registered (look=10, 16x8, cluster-pi0.5): power={pre_power:.3f} {'PASS' if pre_registered['pass'] else 'FAIL'}")
    print(f"{'condition':>24} {'look':>6} {'power':>8} {'±2SE':>8}")
    for r in rows:
        print(
            f"{r['key']:>24} {r['look']:>6} {r['power']:>8.3f} {2*r['se']:>8.3f}"
        )
    print(f"wall time: {wall:.1f}s")

    return result


# --------------------------------------------------------------------------- #
# Experiment 4: MMD comparison
# --------------------------------------------------------------------------- #


def _build_mmd_conditions() -> list[PowerCondition]:
    conditions: list[PowerCondition] = []
    nb, nc = 16, 8
    for pi in (0.25, 0.5):
        conditions.append(PowerCondition(nb, nc, ("cluster", pi), [1, 10]))
    for delta in (0.25, 0.5):
        conditions.append(PowerCondition(nb, nc, ("shift", delta), [1, 10]))
    for m in (3, 6):
        conditions.append(PowerCondition(nb, nc, ("partial", m, 0.5), [1, 10]))
    return conditions


def _mmd_worker(args: tuple[int, float, list[PowerCondition]]) -> tuple[dict, dict]:
    seed, sigma, conditions = args
    rng = np.random.default_rng(seed)
    base = make_being(rng)
    birth24 = being_samples(base, 24, sigma, rng)

    energy_results: dict = {}
    mmd_results: dict = {}
    for cond in conditions:
        drifted = apply_drift(base, cond.drift, rng)
        current12 = being_samples(drifted, 12, sigma, rng)
        birth = [s[: cond.n_b] for s in birth24]
        current = [s[: cond.n_c] for s in current12]
        strata = [(birth[i], current[i]) for i in range(len(birth))]
        key = drift_label(cond.drift)

        for look in cond.looks:
            alpha_k = stats.spending_alpha(look)
            B = stats.required_permutations(alpha_k)
            if B is None:
                energy_results[(key, look)] = None
                mmd_results[(key, look)] = None
                continue

            re = run_energy_test(birth, current, B, rng, alpha=alpha_k)
            energy_results[(key, look)] = int(re.p_value <= alpha_k)

            rm = mmd_permutation_test(strata, permutations=B, rng=rng, alpha=alpha_k)
            mmd_results[(key, look)] = int(rm["p_value"] <= alpha_k)

    return energy_results, mmd_results


def run_mmd(
    R: int = 100,
    quick: bool = False,
    seed: int = DEFAULT_SEED,
    workers: int = 1,
    sigma: float = DEFAULT_SIGMA,
    out: Path | None = None,
) -> dict:
    """Head-to-head power of the energy statistic vs. Gaussian MMD."""
    n_runs = 30 if quick else R
    conditions = _build_mmd_conditions()
    rng = np.random.default_rng(seed)
    seeds = _spawn_seeds(rng, n_runs)

    start = time.perf_counter()
    energy_runs: list[dict] = []
    mmd_runs: list[dict] = []

    if workers > 1:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(_mmd_worker, (s, sigma, conditions)) for s in seeds]
            for i, fut in enumerate(concurrent.futures.as_completed(futures)):
                e, m = fut.result()
                energy_runs.append(e)
                mmd_runs.append(m)
                _progress(i, n_runs, "mmd")
    else:
        for i, s in enumerate(seeds):
            e, m = _mmd_worker((s, sigma, conditions))
            energy_runs.append(e)
            mmd_runs.append(m)
            _progress(i, n_runs, "mmd")

    energy_rows = _aggregate_counts(energy_runs, n_runs)
    mmd_rows = _aggregate_counts(mmd_runs, n_runs)

    wall = time.perf_counter() - start

    disp_rng = np.random.default_rng(seed + 4)
    disp_being = make_being(disp_rng)
    cosine = estimate_dispersion(disp_being, sigma, disp_rng)

    result = {
        "experiment": "mmd",
        "parameters": {
            "R": n_runs,
            "sigma": sigma,
            "seed": seed,
            "quick": quick,
        },
        "mean_within_prompt_cosine": cosine,
        "energy_results": energy_rows,
        "mmd_results": mmd_rows,
        "wall_seconds": wall,
    }

    if out is not None:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, default=_json_default), encoding="utf-8")

    print("\n=== mmd ===")
    print(f"R={n_runs}, sigma={sigma}, cosine={cosine:.4f}")
    print(f"{'condition':>18} {'look':>6} {'energy':>8} {'mmd':>8}")
    # Show side by side, keyed by (key, look).
    emap = {(r["key"], r["look"]): r for r in energy_rows}
    mmap = {(r["key"], r["look"]): r for r in mmd_rows}
    for key, look in sorted(emap.keys()):
        print(
            f"{key:>18} {look:>6} "
            f"{emap[(key,look)]['power']:>8.3f} "
            f"{mmap[(key,look)]['power']:>8.3f}"
        )
    print(f"wall time: {wall:.1f}s")

    return result


# --------------------------------------------------------------------------- #
# Combined report
# --------------------------------------------------------------------------- #


def _git_commit(repo_root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def run_all(
    quick: bool = False,
    seed: int = DEFAULT_SEED,
    workers: int = 1,
    sigma: float = DEFAULT_SIGMA,
    looks: int = 100,
    report_path: Path | None = None,
) -> dict:
    """Run experiments 1-4 and write a combined markdown report."""
    runs_dir = Path(__file__).resolve().parent / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    size_res = run_size(
        quick=quick, seed=seed, workers=workers, sigma=sigma, out=runs_dir / "size.json"
    )
    lifetime_res = run_lifetime(
        looks=looks,
        quick=quick,
        seed=seed,
        workers=workers,
        sigma=sigma,
        out=runs_dir / "lifetime.json",
    )
    power_res = run_power(
        quick=quick, seed=seed, workers=workers, sigma=sigma, out=runs_dir / "power.json"
    )
    mmd_res = run_mmd(
        quick=quick, seed=seed, workers=workers, sigma=sigma, out=runs_dir / "mmd.json"
    )

    commit = _git_commit(_REPO_ROOT)
    report_path = Path(report_path) if report_path else Path(__file__).resolve().parent / "report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append("# Individuation instrument offline validation report\n")
    lines.append(f"- seed: {seed}")
    lines.append(f"- git commit: {commit}")
    lines.append(f"- sigma: {sigma}")
    lines.append(f"- quick mode: {quick}")
    lines.append(f"- mean within-prompt cosine (baseline): {size_res['mean_within_prompt_cosine']:.4f}\n")

    # Size
    lines.append("## 1. Size (type-I error)\n")
    lines.append(
        f"N={size_res['parameters']['N']}, n_b=16, n_c=8, permutations=999.\n"
    )
    lines.append("| alpha | rate | 2SE bound | pass |")
    lines.append("|-------|------|-----------|------|")
    for entry in (size_res["alpha05"], size_res["alpha01"]):
        lines.append(
            f"| {entry['alpha']:.2f} | {entry['rate']:.4f} | {entry['bound']:.4f} | "
            f"{'PASS' if entry['pass'] else 'FAIL'} |"
        )
    ks = size_res["ks_check"]
    lines.append(
        f"\nKS uniformity: worst t={ks['worst_t']:.2f}, value={ks['worst_value']:.4f}, "
        f"bound={ks['worst_bound']:.4f} -> {'PASS' if ks['pass'] else 'FAIL'}.\n"
    )

    # Lifetime
    lines.append("## 2. Lifetime (familywise error under H0)\n")
    lines.append(
        f"L={lifetime_res['parameters']['L']}, looks={lifetime_res['parameters']['looks']}, "
        f"mean permutations/look={lifetime_res['instrument']['mean_permutations_per_look']:.0f}.\n"
    )
    lines.append("| look | instrument | naive | old_percentile |")
    lines.append("|------|------------|-------|----------------|")
    for look in ("10", "50", "100"):
        i = lifetime_res["instrument"]["by_look"][look]
        n = lifetime_res["naive"]["by_look"][look]
        o = lifetime_res["old_percentile"]["by_look"][look]
        lines.append(
            f"| {look} | {i['rate']:.3f} (±{2*i['se']:.3f}) | "
            f"{n['rate']:.3f} (±{2*n['se']:.3f}) | "
            f"{o['rate']:.3f} (±{2*o['se']:.3f}) |"
        )
    lines.append(
        f"\nInstrument look-100 bound={0.05 + 2*math.sqrt(0.05*0.95/lifetime_res['parameters']['L']):.4f} "
        f"-> {'PASS' if lifetime_res['instrument']['pass'] else 'FAIL'}.\n"
    )

    # Power
    lines.append("## 3. Power\n")
    lines.append(f"R={power_res['parameters']['R']}, sigma={sigma}.\n")
    lines.append("| condition | look | power | ±2SE |")
    lines.append("|-----------|------|-------|------|")
    for r in power_res["results"]:
        lines.append(
            f"| {r['key']} | {r['look']} | {r['power']:.3f} | {2*r['se']:.3f} |"
        )
    pre = power_res["pre_registered"]
    lines.append(
        f"\nPre-registered acceptance (look=10, 16x8, cluster-pi0.5): "
        f"power={pre['power']:.3f}, threshold={pre['threshold']} "
        f"-> {'PASS' if pre['pass'] else 'FAIL'}.\n"
    )

    # MMD
    lines.append("## 4. Energy vs. MMD (16x8 only)\n")
    lines.append(f"R={mmd_res['parameters']['R']}.\n")
    lines.append("| condition | look | energy | mmd |")
    lines.append("|-----------|------|--------|-----|")
    emap = {(r["key"], r["look"]): r for r in mmd_res["energy_results"]}
    mmap = {(r["key"], r["look"]): r for r in mmd_res["mmd_results"]}
    for key, look in sorted(emap.keys()):
        lines.append(
            f"| {key} | {look} | {emap[(key, look)]['power']:.3f} | "
            f"{mmap[(key, look)]['power']:.3f} |"
        )
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nCombined report written to {report_path}")

    return {
        "size": size_res,
        "lifetime": lifetime_res,
        "power": power_res,
        "mmd": mmd_res,
        "report": str(report_path),
        "commit": commit,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _default_out(experiment: str) -> Path:
    return Path(__file__).resolve().parent / "runs" / f"{experiment}.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Offline validation simulation for the individuation instrument."
    )
    parser.add_argument(
        "--quick", action="store_true", help="Use reduced replication counts."
    )
    parser.add_argument(
        "--seed", type=int, default=DEFAULT_SEED, help="Random seed."
    )
    parser.add_argument(
        "--workers", type=int, default=1, help="Parallel workers."
    )
    parser.add_argument(
        "--sigma", type=float, default=DEFAULT_SIGMA, help="Within-prompt dispersion."
    )

    sub = parser.add_subparsers(dest="experiment", required=True)

    size_p = sub.add_parser("size", help="Type-I error calibration.")
    size_p.add_argument(
        "--out", type=Path, default=None, help="Output JSON path."
    )

    life_p = sub.add_parser("lifetime", help="Familywise error over sequential looks.")
    life_p.add_argument("--looks", type=int, default=100, help="Number of looks.")
    life_p.add_argument("--out", type=Path, default=None, help="Output JSON path.")

    pow_p = sub.add_parser("power", help="Power against drift.")
    pow_p.add_argument("--out", type=Path, default=None, help="Output JSON path.")

    mmd_p = sub.add_parser("mmd", help="Energy vs. MMD comparison.")
    mmd_p.add_argument("--out", type=Path, default=None, help="Output JSON path.")

    all_p = sub.add_parser("all", help="Run all experiments and write report.")
    all_p.add_argument("--looks", type=int, default=100, help="Number of looks.")
    all_p.add_argument(
        "--out", type=Path, default=None, help="Report markdown path."
    )

    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.experiment == "size":
        out = args.out if args.out else _default_out("size")
        run_size(quick=args.quick, seed=args.seed, workers=args.workers, sigma=args.sigma, out=out)
    elif args.experiment == "lifetime":
        out = args.out if args.out else _default_out("lifetime")
        run_lifetime(
            looks=args.looks,
            quick=args.quick,
            seed=args.seed,
            workers=args.workers,
            sigma=args.sigma,
            out=out,
        )
    elif args.experiment == "power":
        out = args.out if args.out else _default_out("power")
        run_power(quick=args.quick, seed=args.seed, workers=args.workers, sigma=args.sigma, out=out)
    elif args.experiment == "mmd":
        out = args.out if args.out else _default_out("mmd")
        run_mmd(quick=args.quick, seed=args.seed, workers=args.workers, sigma=args.sigma, out=out)
    elif args.experiment == "all":
        run_all(
            quick=args.quick,
            seed=args.seed,
            workers=args.workers,
            sigma=args.sigma,
            looks=args.looks,
            report_path=args.out,
        )


if __name__ == "__main__":
    main()
