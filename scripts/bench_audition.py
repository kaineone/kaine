# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Host benchmark for general auditory perception (auditory-perception, task 1.7).

General auditory perception adds, per captured window, one acoustic encode plus a
change score and a forward-model step over the embedding — the salience substrate
that lets any sound be heard. Before it may ship enabled, that per-window cost
must be shown to fit inside the window budget on the actual host — this measures
it. Dry probe: no entity boot, no capture device, nothing persisted; audio is a
synthetic tone held in memory.

Real measurement or an explicit "couldn't measure X because Y" — no fabricated
numbers.

Run: .venv/bin/python scripts/bench_audition.py
     .venv/bin/python scripts/bench_audition.py --iters 200 --window-ms 500
"""

from __future__ import annotations

import argparse
import statistics
import time
from typing import Optional

import numpy as np

from kaine.modules.audition.acoustic import (
    SpectralAcousticEncoder,
    cosine_change,
)
from kaine.modules.audition.forward import AuditoryForwardModel


def _tone(freq: float, seconds: float, sr: int) -> bytes:
    t = np.arange(int(seconds * sr)) / sr
    # Sum a couple of partials + noise so the spectral encode does real work.
    x = 0.3 * np.sin(2 * np.pi * freq * t) + 0.1 * np.sin(2 * np.pi * 2 * freq * t)
    x = x + 0.02 * np.random.default_rng(0).standard_normal(t.shape)
    return (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()


def _pct(samples: list[float], q: float) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iters", type=int, default=200)
    parser.add_argument("--window-ms", type=int, default=500)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--n-bands", type=int, default=32)
    args = parser.parse_args(argv)

    print("KAINE general-auditory-perception benchmark (auditory-perception task 1.7)")
    print("Dry probe — no entity boot, no capture, nothing persisted.\n")

    sr = args.sample_rate
    window_s = args.window_ms / 1000.0
    enc = SpectralAcousticEncoder(n_bands=args.n_bands)
    fm = AuditoryForwardModel(feature_dim=enc.embedding_dim)
    # A different tone each iter so change/forward-model do real, varied work.
    windows = [
        _tone(180 + 40 * (i % 8), window_s, sr) for i in range(min(args.iters, 64))
    ]

    prev = None
    for w in windows[:5]:  # warm up (numpy/JIT, forward-model buffer)
        e = enc.embed(w, sr)
        cosine_change(e, prev)
        fm.step(e)
        prev = e

    encode_ms, total_ms = [], []
    prev = None
    for i in range(args.iters):
        w = windows[i % len(windows)]
        t0 = time.perf_counter()
        emb = enc.embed(w, sr)
        encode_ms.append((time.perf_counter() - t0) * 1000.0)
        t1 = time.perf_counter()
        cosine_change(emb, prev)
        fm.step(emb)
        prev = emb
        total_ms.append((time.perf_counter() - t1) * 1000.0 + encode_ms[-1])

    budget_ms = args.window_ms
    enc_p95 = _pct(encode_ms, 0.95)
    tot_p95 = _pct(total_ms, 0.95)
    print(f"encoder:   {enc.model_id} (dim {enc.embedding_dim})")
    print(f"window:    {args.window_ms} ms @ {sr} Hz  ({args.iters} iters)")
    print(
        f"  encode          mean {statistics.mean(encode_ms):6.2f} ms   "
        f"p95 {enc_p95:6.2f} ms"
    )
    print(
        f"  encode+salience mean {statistics.mean(total_ms):6.2f} ms   "
        f"p95 {tot_p95:6.2f} ms"
    )
    print()
    print(f"window budget: {budget_ms} ms")
    if tot_p95 <= budget_ms:
        print(
            f"VERDICT: FITS — per-window perception p95 uses "
            f"{100 * tot_p95 / budget_ms:.1f}% of the window "
            f"({budget_ms - tot_p95:.1f} ms headroom)."
        )
        return 0
    print(
        f"VERDICT: OVER BUDGET by {tot_p95 - budget_ms:.1f} ms — reduce n_bands or "
        "lengthen the window before enabling."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
