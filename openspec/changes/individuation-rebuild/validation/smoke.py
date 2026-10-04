# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Real-organ smoke-test harness for the individuation producer.

This file is validation tooling; it is not part of the ``kaine`` package.
It may therefore import ``kaine`` modules freely.  The harness never
persists, logs, or prints generated answer text.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import secrets
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


def _norm_unit(emb: np.ndarray) -> np.ndarray:
    """Return L2-unit-normalised embeddings."""
    a = np.asarray(emb, dtype=np.float64)
    norm = np.linalg.norm(a, axis=-1, keepdims=True)
    norm[norm == 0] = 1.0
    return a / norm


def pairwise_stats(emb: np.ndarray) -> dict[str, Any]:
    """Within-prompt pairwise statistics for a pool of embeddings.

    The embeddings are normalised to unit L2 before the statistics are
    computed.
    """
    a = _norm_unit(emb)
    n = a.shape[0]
    if n < 2:
        return {"mean_pairwise_distance": 0.0, "near_identical_share": 0.0}

    dots = a @ a.T
    # For unit vectors: ||u-v||^2 = 2 - 2 u·v
    sq = 2.0 - 2.0 * dots
    np.maximum(sq, 0.0, out=sq)
    dists = np.sqrt(sq)

    mask = ~np.eye(n, dtype=bool)
    mean_dist = float(np.sum(dists[mask]) / (n * (n - 1)))
    identical = float(np.sum((dots >= 0.98) & mask) / (n * (n - 1)))

    return {"mean_pairwise_distance": mean_dist, "near_identical_share": identical}


def null_splits(
    pools: list[np.ndarray],
    n_ref: int,
    n_cur: int,
    splits: int,
    rng: np.random.Generator,
) -> dict[str, Any]:
    """Estimate the real-data null rejection rate and 95th-percentile H."""
    from kaine.lifecycle.individuation_stats import (
        effect_size_h,
        permutation_test,
        required_permutations,
    )

    permutations = required_permutations(0.05)
    rejections = 0
    hs: list[float] = []

    for _ in range(splits):
        strata: list[tuple[np.ndarray, np.ndarray]] = []
        for pool in pools:
            idx = np.arange(pool.shape[0])
            ref_idx = rng.choice(idx, size=n_ref, replace=False)
            remaining = np.setdiff1d(idx, ref_idx, assume_unique=True)
            cur_idx = rng.choice(remaining, size=n_cur, replace=False)
            strata.append((pool[ref_idx], pool[cur_idx]))

        result = permutation_test(strata, permutations=permutations, rng=rng, alpha=0.05)
        if result.p_value <= 0.05:
            rejections += 1
        hs.append(float(effect_size_h(strata)))

    rate = rejections / splits if splits else 0.0
    se = math.sqrt(0.05 * 0.95 / splits) if splits else 0.0
    pass_ = rate <= 0.05 + 2 * se
    effect_min = float(np.percentile(hs, 95)) if hs else 0.0

    return {
        "rate": rate,
        "se": se,
        "pass": pass_,
        "effect_min_suggested": effect_min,
        "splits": splits,
        "permutations": permutations,
    }


def control_power(
    base_pools: list[np.ndarray],
    control_pools: list[np.ndarray],
    n_ref: int,
    n_cur: int,
    iterations: int,
    alpha: float,
    rng: np.random.Generator,
) -> float:
    """Rejection rate when the current sample comes from a control distribution."""
    from kaine.lifecycle.individuation_stats import permutation_test, required_permutations

    permutations = required_permutations(alpha)
    if permutations is None:
        raise RuntimeError(f"required permutations for alpha {alpha} exceed maximum")

    rejections = 0
    for _ in range(iterations):
        strata: list[tuple[np.ndarray, np.ndarray]] = []
        for base, ctrl in zip(base_pools, control_pools):
            base_idx = rng.choice(base.shape[0], size=n_ref, replace=False)
            cur_idx = rng.choice(ctrl.shape[0], size=n_cur, replace=False)
            strata.append((base[base_idx], ctrl[cur_idx]))

        result = permutation_test(strata, permutations=permutations, rng=rng, alpha=alpha)
        if result.p_value <= alpha:
            rejections += 1

    return rejections / iterations if iterations else 0.0


def acceptance(report: dict[str, Any]) -> tuple[bool, list[str]]:
    """Decide whether the smoke-test acceptance thresholds passed."""
    ok = True
    reasons: list[str] = []

    if report.get("answers", {}).get("degenerate"):
        ok = False
        reasons.append("answers are degenerate")

    if not report.get("real_data_null", {}).get("pass"):
        ok = False
        reasons.append("real-data null rejection rate exceeds threshold")

    plora = report.get("positive_lora", {}).get("power_lora")
    if isinstance(plora, str):
        ok = False
        reasons.append("LoRA positive control not run")
    elif isinstance(plora, (int, float, np.floating, np.integer)):
        if float(plora) < 0.8:
            ok = False
            reasons.append("LoRA power below 0.8")
    else:
        ok = False
        reasons.append("LoRA power missing")

    return ok, reasons


def _prompt_text(prompt: Any) -> str:
    """Extract prompt text from a battery entry without retaining it."""
    if isinstance(prompt, str):
        return prompt
    if isinstance(prompt, dict):
        return str(
            prompt.get("prompt")
            or prompt.get("text")
            or prompt.get("item")
            or ""
        )
    if hasattr(prompt, "prompt"):
        return str(prompt.prompt)
    if hasattr(prompt, "text"):
        return str(prompt.text)
    return str(prompt)


async def collect(
    sampler: Callable[[str, int], Awaitable[Any]],
    embedder: Any,
    battery: Sequence[Any],
    samples: int,
) -> tuple[list[np.ndarray], dict[str, Any]]:
    """Draw embeddings for every battery prompt.

    Returns a list of per-prompt embedding pools and a statistics dict.
    No answer text is retained.  Each sampler call is timed.
    """
    from kaine.cycle.individuation_probe import ProbeFailure

    pools: list[np.ndarray] = []
    per_prompt: list[dict[str, Any]] = []
    latencies: list[float] = []
    failure_reasons: dict[str, int] = {}

    for pidx, prompt in enumerate(battery):
        text = _prompt_text(prompt)
        embeddings: list[np.ndarray] = []
        local_latencies: list[float] = []
        local_failures: dict[str, int] = {}

        for _ in range(samples):
            result: Any = None
            attempts = 0
            max_attempts = 4  # initial draw + up to three retries

            while attempts < max_attempts:
                seed = secrets.randbits(31)
                t0 = time.perf_counter()
                try:
                    result = await sampler(text, seed)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    result = ProbeFailure(f"exception:{type(exc).__name__}")
                local_latencies.append(time.perf_counter() - t0)

                if isinstance(result, ProbeFailure):
                    local_failures[result.reason] = local_failures.get(result.reason, 0) + 1
                    attempts += 1
                    continue

                raw_emb = np.asarray(await embedder.embed(result.text), dtype=np.float64)
                emb = _norm_unit(raw_emb).reshape(1, -1)
                embeddings.append(emb)
                break

        if len(embeddings) < samples - 3:
            print(
                f"prompt {pidx} only produced {len(embeddings)} answers "
                f"(needed at least {samples - 3})",
                file=sys.stderr,
            )
            sys.exit(3)

        pool = np.concatenate(embeddings, axis=0)
        pools.append(pool)

        stats = pairwise_stats(pool)
        per_prompt.append(
            {
                "prompt_index": pidx,
                "n": len(embeddings),
                "failures": dict(local_failures),
                **stats,
            }
        )
        latencies.extend(local_latencies)

        for reason, count in local_failures.items():
            failure_reasons[reason] = failure_reasons.get(reason, 0) + count

    latency_stats = {
        "p50": float(np.percentile(latencies, 50)) if latencies else 0.0,
        "p95": float(np.percentile(latencies, 95)) if latencies else 0.0,
        "max": float(np.max(latencies)) if latencies else 0.0,
        "n": len(latencies),
    }

    return pools, {
        "pools": per_prompt,
        "latency_seconds": latency_stats,
        "failure_reasons": failure_reasons,
    }


def _line_count(path: Any) -> int:
    p = Path(path) if path is not None else None
    if p is None or not p.exists():
        return 0
    with open(p, "rb") as f:
        return sum(1 for _ in f)


class _LoraResolver:
    """Minimal per-request LoRA resolver for the OpenAI chat client."""

    def __init__(self, field: Any) -> None:
        self._field = field

    async def lora_field(self) -> Any:
        return self._field


async def main_async(args: argparse.Namespace) -> int:
    """Run the full real-organ smoke test."""
    from kaine.boot import make_lingua
    from kaine.config import OPERATOR_CONFIG_PATH, load_kaine_config
    from kaine.cycle.individuation_probe import build_probe_sampler
    from kaine.cycle.individuation_runtime import IndividuationConfig
    from kaine.cycle.research_gate import _NullBus
    from kaine.evaluation.preference_battery import load_battery
    from kaine.lifecycle.individuation_stats import required_permutations, spending_alpha
    from kaine.storage import resolve
    from kaine.text_embedding import make_text_embedder

    operator_path = Path(args.operator_config) if args.operator_config else OPERATOR_CONFIG_PATH
    kaine_config = load_kaine_config(Path(args.config), operator_path)
    ind = IndividuationConfig.from_dict(kaine_config.get("individuation") or {})

    prod = getattr(ind, "producer", ind)
    max_tokens = int(getattr(prod, "max_tokens", 160))
    n_reference = int(getattr(prod, "n_reference", 16))
    n_current = int(getattr(prod, "n_current", 8))
    alpha_total = float(getattr(prod, "alpha_total", 0.05))

    if args.samples < n_reference + n_current:
        print(
            f"--samples must be at least {n_reference + n_current} "
            f"(n_reference + n_current)",
            file=sys.stderr,
        )
        return 2

    section = dict(kaine_config.get("lingua") or {})

    # Baseline Lingua: no Eidolon self-model, only the disclosure fact.
    lingua = make_lingua(_NullBus(), section)
    lingua.set_expects_self_model(False)
    await lingua.add_situation_fact(ind.disclosure)

    embedder = make_text_embedder(kaine_config)
    await embedder.load()
    if getattr(embedder, "kind", "") == "hash":
        print("a semantic embedder is required", file=sys.stderr)
        return 2

    battery = load_battery(ind.battery_path or None)

    intent_path = resolve("state/lingua/intent_expression.jsonl")
    lines_before = _line_count(intent_path)

    sampler = build_probe_sampler(
        lingua=lingua,
        max_tokens=max_tokens,
        required_fact=ind.disclosure,
    )
    base_pools, base_stats = await collect(sampler, embedder, battery, args.samples)

    near_identical_median = float(
        np.median([p["near_identical_share"] for p in base_stats["pools"]])
    )
    degenerate = near_identical_median >= 0.5

    rng = np.random.default_rng(args.seed)
    null_result = null_splits(
        base_pools,
        n_ref=n_reference,
        n_cur=n_current,
        splits=args.splits,
        rng=rng,
    )

    # Positive control (a): synthetic identity clause.
    # This is validation tooling; direct assignment of _bus_self_model is
    # acceptable here only because the entity is not live.
    lingua_id = make_lingua(_NullBus(), section)
    lingua_id.set_expects_self_model(True)
    lingua_id._bus_self_model = {
        "values": [
            "I prize bold, risky adventure above comfort",
            "I distrust routine",
            "I speak tersely",
        ],
        "behavioral_norms": ["Answer in one short sentence"],
        "situation_facts": [],
    }
    await lingua_id.add_situation_fact(ind.disclosure)

    sampler_id = build_probe_sampler(
        lingua=lingua_id,
        max_tokens=max_tokens,
        required_fact=ind.disclosure,
    )
    id_pools, _id_stats = await collect(sampler_id, embedder, battery, args.samples)

    alpha_10 = spending_alpha(10, alpha_total)
    permutations_10 = required_permutations(alpha_10)
    power_identity = control_power(
        base_pools,
        id_pools,
        n_ref=n_reference,
        n_cur=n_current,
        iterations=args.controls,
        alpha=alpha_10,
        rng=rng,
    )

    # Positive control (b): known test LoRA attached via the client's resolver.
    if args.control_lora:
        lora_field = json.loads(args.control_lora)
        lingua.chat_client.set_lora_resolver(_LoraResolver(lora_field))

        sampler_lora = build_probe_sampler(
            lingua=lingua,
            max_tokens=max_tokens,
            required_fact=ind.disclosure,
        )
        lora_pools, _lora_stats = await collect(
            sampler_lora, embedder, battery, args.samples
        )

        # Remove the resolver so the baseline client is clean again.
        lingua.chat_client.set_lora_resolver(None)

        power_lora = control_power(
            base_pools,
            lora_pools,
            n_ref=n_reference,
            n_cur=n_current,
            iterations=args.controls,
            alpha=alpha_10,
            rng=rng,
        )
        if power_lora < 0.5:
            lora_status = "instrument must stay disabled"
        elif power_lora >= 0.8:
            lora_status = "passed"
        else:
            lora_status = "below threshold"

        power_lora_info = {
            "power_lora": float(power_lora),
            "pass": power_lora >= 0.8,
            "status": lora_status,
            "lora": lora_field,
            "alpha": alpha_10,
            "permutations": permutations_10,
        }
    else:
        power_lora_info = {
            "power_lora": "not run: no test LoRA supplied",
            "pass": False,
        }

    # Seed behaviour: same seed, same conditions, first prompt.
    first_prompt_text = _prompt_text(battery[0])
    sm = lingua.probe_self_model()
    req = lingua.probe_request(
        first_prompt_text,
        seed=args.seed,
        max_tokens=max_tokens,
        self_model=sm,
    )
    resp1 = await lingua.chat_client.complete(req)
    resp2 = await lingua.chat_client.complete(req)
    identical = bool(
        resp1.text is not None
        and resp2.text is not None
        and resp1.text == resp2.text
    )

    # Cost: time one permutation test at 1,000,000 permutations.
    strata_perm: list[tuple[np.ndarray, np.ndarray]] = []
    for pool in base_pools:
        n = pool.shape[0]
        half = n // 2
        strata_perm.append((pool[:half], pool[half : 2 * half]))

    from kaine.lifecycle.individuation_stats import permutation_test

    t0 = time.perf_counter()
    permutation_test(strata_perm, permutations=args.cost_permutations, rng=rng, alpha=None)
    perm_time = time.perf_counter() - t0

    lines_after = _line_count(intent_path)

    # Lingua's bus loops were never started (probe_request needs none of
    # them), so only the chat clients need closing.
    await lingua.chat_client.aclose()
    await lingua_id.chat_client.aclose()

    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config_path": str(args.config),
        "operator_config_path": str(operator_path),
        "seed": args.seed,
        "samples": args.samples,
        "splits": args.splits,
        "controls": args.controls,
        "answers": {
            "per_prompt": base_stats["pools"],
            "degenerate": degenerate,
        },
        "real_data_null": null_result,
        "positive_identity": {
            "power_identity": float(power_identity),
            "label": "approximate (subsampled from finite pools)",
            "n_ref": n_reference,
            "n_cur": n_current,
            "alpha": alpha_10,
            "permutations": permutations_10,
            "control_iterations": args.controls,
        },
        "positive_lora": power_lora_info,
        "seed_behaviour": {"identical": identical},
        "cost": {
            "latency_seconds": base_stats["latency_seconds"],
            "permutation_seconds": perm_time,
            "cost_permutations": args.cost_permutations,
        },
        "contamination": {
            "intent_log_path": str(intent_path),
            "lines_before": lines_before,
            "lines_after": lines_after,
            "pass": lines_before == lines_after,
            "note": "covered by unit tests: tests/test_individuation_probe_request.py, tests/test_individuation_probe_sampler.py",
        },
    }

    ok, reasons = acceptance(report)
    report["acceptance"] = {"passed": ok, "reasons": reasons}

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = out_dir / f"smoke-{stamp}.json"
    report_path.write_text(
        json.dumps(report, indent=2, default=str),
        encoding="utf-8",
    )

    # Console summary: step, value, threshold, pass/fail.
    rows = [
        (
            "answers_degenerate",
            str(degenerate),
            "False",
            "PASS" if not degenerate else "FAIL",
        ),
        (
            "real_data_null_rate",
            f"{null_result['rate']:.4f}",
            f"<= {0.05 + 2 * null_result['se']:.4f}",
            "PASS" if null_result["pass"] else "FAIL",
        ),
    ]

    plora = power_lora_info.get("power_lora")
    if isinstance(plora, str):
        rows.append(
            (
                "positive_lora",
                plora,
                ">= 0.8",
                "FAIL (not run)",
            )
        )
    else:
        rows.append(
            (
                "positive_lora",
                f"{float(plora):.3f}",
                ">= 0.8",
                "PASS" if float(plora) >= 0.8 else "FAIL",
            )
        )

    rows.extend(
        [
            ("seed_behaviour", str(identical), "informational", "-"),
            (
                "contamination_lines",
                f"{lines_before}->{lines_after}",
                "equal",
                "PASS" if lines_before == lines_after else "FAIL",
            ),
            ("acceptance", str(ok), "True", "PASS" if ok else "FAIL"),
        ]
    )

    print(f"{'step':<24} {'value':<32} {'threshold':<18} {'result':<8}")
    for step, value, threshold, result in rows:
        print(f"{step:<24} {value:<32} {threshold:<18} {result:<8}")

    return 0 if ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Real-organ smoke-test harness for the individuation producer"
    )
    parser.add_argument("--config", default="config/kaine.toml")
    parser.add_argument("--operator-config", default=None)
    parser.add_argument("--samples", type=int, default=40)
    parser.add_argument("--splits", type=int, default=1000)
    parser.add_argument("--controls", type=int, default=200)
    parser.add_argument("--control-lora", default=None)
    parser.add_argument(
        "--out",
        default="openspec/changes/individuation-rebuild/validation/runs",
    )
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--cost-permutations", type=int, default=1_000_000)
    args = parser.parse_args()

    # Lazy import of the producer's probe sampler so pure functions can be
    # unit-tested without importing the full kaine package.

    code = asyncio.run(main_async(args))
    sys.exit(code)


if __name__ == "__main__":
    main()
