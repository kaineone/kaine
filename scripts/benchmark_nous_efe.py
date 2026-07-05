#!/usr/bin/env python
# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Pre-build EFE latency benchmark for Nous (pymdp 1.0, JAX).

Runs the configured complexity envelope through belief updating + EFE policy
selection 100 times on the target CPU and asserts the **median ≤ 200 ms**. Exits
non-zero on failure so CI can refuse a slow configuration before the main suite.

Usage:
    python scripts/benchmark_nous_efe.py [--iterations N] [--threshold-ms MS]

The envelope is read from ``[nous]`` in ``config/kaine.toml`` when present
(``factors``, ``max_states_per_factor``, ``planning_horizon``); otherwise the
default compact model is used. KAINE is CPU-only — JAX logs a one-line
GPU-fallback notice, which is expected and correct.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path
from typing import Any


def _load_nous_config() -> dict[str, Any]:
    toml_path = Path("config/kaine.toml")
    if not toml_path.exists():
        return {}
    try:
        import tomllib

        cfg = tomllib.loads(toml_path.read_text())
        return dict(cfg.get("nous") or {})
    except Exception:
        return {}


class _Event:
    def __init__(self, source: str, payload: dict[str, Any], salience: float) -> None:
        self.source = source
        self.payload = payload
        self.salience = salience


class _Snapshot:
    def __init__(self, events: list[_Event]) -> None:
        self.selected_events = [(str(i), e) for i, e in enumerate(events)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--threshold-ms", type=float, default=200.0)
    args = parser.parse_args()

    try:
        from kaine.modules.nous.engine import PymdpEngine
        from kaine.modules.nous.generative_model import build_generative_model
    except Exception as exc:  # pragma: no cover - import guard
        print(f"FAIL: could not import Nous engine ({exc})", file=sys.stderr)
        return 2

    cfg = _load_nous_config()
    horizon = int(cfg.get("planning_horizon", 1))
    max_states = cfg.get("max_states_per_factor")
    model = build_generative_model(
        max_states_per_factor=int(max_states) if max_states is not None else None,
    )
    # Use a generous timeout for the benchmark so we measure raw compute, not
    # the guard.
    engine = PymdpEngine(model, efe_timeout_ms=10_000.0, policy_len=horizon)

    snapshot = _Snapshot(
        [
            _Event("soma", {}, 0.9),
            _Event("thymos", {"state": {"valence": 0.4, "arousal": 0.7}}, 0.5),
        ]
    )

    # Warm-up (JAX tracing) — not counted.
    for _ in range(3):
        engine.step(snapshot)

    samples_ms: list[float] = []
    for _ in range(max(1, args.iterations)):
        start = time.perf_counter()
        engine.step(snapshot)
        samples_ms.append((time.perf_counter() - start) * 1000.0)

    engine.close()

    median = statistics.median(samples_ms)
    p95 = sorted(samples_ms)[min(len(samples_ms) - 1, int(len(samples_ms) * 0.95))]
    print(
        f"Nous EFE benchmark: iterations={len(samples_ms)} "
        f"median={median:.2f}ms p95={p95:.2f}ms threshold={args.threshold_ms:.0f}ms"
    )
    print(
        "envelope: "
        f"factors={model.num_factors} actions={model.num_actions} "
        f"max_states={max(model.num_states)} horizon={horizon}"
    )
    if median > args.threshold_ms:
        print(
            f"FAIL: median {median:.2f}ms exceeds threshold {args.threshold_ms:.0f}ms",
            file=sys.stderr,
        )
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
