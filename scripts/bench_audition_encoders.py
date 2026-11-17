# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Offline bake-off of acoustic encoders: spectral, dasheng, wavjepa.

Never boots an entity. Generates deterministic synthetic audio (pink-ish noise
with a loud 1 kHz chirp injected every ``--surprise-interval`` blocks), runs each
encoder through the audition salience pipeline (embed -> cosine change ->
forward-model prediction error) and reports, per encoder:

  * ROC AUC of salience against the known surprise blocks
  * false alerts per minute (non-surprise blocks above the 95th percentile of
    non-surprise salience)
  * p50 / p95 per-block latency (encode + forward step), ms
  * peak RSS (MB) after loading the encoder

Encoders that cannot load (no torch, no GPU, no weights) are skipped with a
note; nothing is fabricated.

Run: .venv/bin/python scripts/bench_audition_encoders.py
     .venv/bin/python scripts/bench_audition_encoders.py --blocks 600 --device cuda:0
"""

from __future__ import annotations

import argparse
import json
import resource
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np

from kaine.modules.audition.acoustic import ACOUSTIC_ENCODERS, cosine_change
from kaine.modules.audition.forward import AuditoryForwardModel

SAMPLE_RATE = 16000
BLOCK_SAMPLES = 8000  # 500 ms
BLOCK_SECONDS = BLOCK_SAMPLES / SAMPLE_RATE
SEED = 42
ENCODERS = ("spectral", "dasheng", "wavjepa")
OUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "records" / "audition-encoder-bakeoff.json"


def generate_audio(n_blocks: int, surprise_interval: int) -> tuple[list[bytes], list[int]]:
    """Return (PCM int16 LE blocks, labels) with labels[i]=1 for surprise blocks."""
    rng = np.random.default_rng(SEED)
    total = n_blocks * BLOCK_SAMPLES
    white = rng.standard_normal(total)
    # Pink-ish: shape the white spectrum by 1/sqrt(f).
    spec = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(total, d=1.0 / SAMPLE_RATE)
    freqs[0] = freqs[1]
    spec = spec / np.sqrt(freqs)
    noise = np.fft.irfft(spec, n=total)
    noise = 0.1 * noise / (np.std(noise) + 1e-12)

    labels = [0] * n_blocks
    t = np.arange(BLOCK_SAMPLES) / SAMPLE_RATE
    # Short 1 kHz sine chirp (900 -> 1100 Hz) with a fade envelope, 0.8 amplitude.
    burst_len = BLOCK_SAMPLES // 4
    tb = t[:burst_len]
    inst_freq = 900.0 + 200.0 * (tb / tb[-1])
    phase = 2 * np.pi * np.cumsum(inst_freq) / SAMPLE_RATE
    burst = 0.8 * np.sin(phase) * np.hanning(burst_len)

    for i in range(surprise_interval - 1, n_blocks, surprise_interval):
        labels[i] = 1
        start = i * BLOCK_SAMPLES + BLOCK_SAMPLES // 4
        noise[start : start + burst_len] += burst

    samples = np.clip(noise, -1.0, 1.0)
    blocks = [
        (samples[i * BLOCK_SAMPLES : (i + 1) * BLOCK_SAMPLES] * 32767).astype("<i2").tobytes()
        for i in range(n_blocks)
    ]
    return blocks, labels


def roc_auc(labels: list[int], scores: list[float]) -> Optional[float]:
    """ROC AUC via sklearn if present, else the rank-sum (Mann-Whitney) form."""
    if len(set(labels)) < 2:
        return None
    try:
        from sklearn.metrics import roc_auc_score

        return float(roc_auc_score(labels, scores))
    except ImportError:
        pass
    y = np.asarray(labels)
    s = np.asarray(scores, dtype=float)
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), dtype=float)
    sorted_s = s[order]
    i = 0
    while i < len(s):  # average ranks over ties
        j = i
        while j + 1 < len(s) and sorted_s[j + 1] == sorted_s[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    n_pos = int(y.sum())
    n_neg = len(y) - n_pos
    return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def peak_rss_mb() -> float:
    # ru_maxrss is KiB on Linux.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def run_encoder(
    name: str, blocks: list[bytes], labels: list[int], device: str
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {} if name == "spectral" else {"device": device}
    encoder = ACOUSTIC_ENCODERS[name](**kwargs)
    # Force the lazy weight load now so memory and latency exclude it.
    encoder.embed(blocks[0], SAMPLE_RATE)
    rss_mb = peak_rss_mb()
    # Fresh encoder state (rolling buffer) for the measured pass.
    encoder = ACOUSTIC_ENCODERS[name](**kwargs)
    encoder.embed(blocks[0], SAMPLE_RATE)
    encoder = _reset(encoder, name, kwargs)

    forward = AuditoryForwardModel(feature_dim=encoder.embedding_dim, seed=SEED)
    prev: Optional[list[float]] = None
    salience: list[float] = []
    lat_ms: list[float] = []
    for blk in blocks:
        t0 = time.perf_counter()
        emb = encoder.embed(blk, SAMPLE_RATE)
        change = cosine_change(emb, prev)
        err = forward.step(emb)
        lat_ms.append((time.perf_counter() - t0) * 1000.0)
        salience.append(float(change) + float(err))
        prev = emb

    neg = [s for s, y in zip(salience, labels) if y == 0]
    threshold = float(np.percentile(neg, 95))
    false_alerts = sum(1 for s, y in zip(salience, labels) if y == 0 and s > threshold)
    minutes = len(blocks) * BLOCK_SECONDS / 60.0
    return {
        "embedding_dim": int(encoder.embedding_dim),
        "roc_auc": roc_auc(labels, salience),
        "false_alerts_per_min": false_alerts / minutes,
        "p95_threshold": threshold,
        "latency_ms_p50": float(np.percentile(lat_ms, 50)),
        "latency_ms_p95": float(np.percentile(lat_ms, 95)),
        "peak_rss_mb": rss_mb,
    }


def _reset(encoder: Any, name: str, kwargs: dict[str, Any]) -> Any:
    """Return an encoder with an empty rolling buffer (weights already cached on disk)."""
    return encoder if name == "spectral" else ACOUSTIC_ENCODERS[name](**kwargs)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocks", type=int, default=600)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--surprise-interval", type=int, default=150)
    args = parser.parse_args(argv)

    print("KAINE audition encoder bake-off — offline, no entity boot, nothing persisted but the result JSON.\n")
    blocks, labels = generate_audio(args.blocks, args.surprise_interval)
    print(
        f"audio: {args.blocks} blocks x {BLOCK_SAMPLES} samples @ {SAMPLE_RATE} Hz, "
        f"{sum(labels)} surprise blocks (every {args.surprise_interval})\n"
    )

    results: dict[str, Any] = {}
    for name in ENCODERS:
        try:
            results[name] = run_encoder(name, blocks, labels, args.device)
        except Exception as exc:  # noqa: BLE001 - report, never fabricate
            results[name] = {"skipped": f"{type(exc).__name__}: {exc}"}
            print(f"[skip] {name}: couldn't measure because {type(exc).__name__}: {exc}")

    header = f"{'encoder':<10} {'AUC':>7} {'FA/min':>8} {'p50 ms':>9} {'p95 ms':>9} {'RSS MB':>9}"
    print("\n" + header)
    print("-" * len(header))
    for name, r in results.items():
        if "skipped" in r:
            print(f"{name:<10} skipped")
            continue
        auc = "n/a" if r["roc_auc"] is None else f"{r['roc_auc']:.3f}"
        print(
            f"{name:<10} {auc:>7} {r['false_alerts_per_min']:>8.2f} "
            f"{r['latency_ms_p50']:>9.2f} {r['latency_ms_p95']:>9.2f} {r['peak_rss_mb']:>9.0f}"
        )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "config": {
            "blocks": args.blocks,
            "block_samples": BLOCK_SAMPLES,
            "sample_rate": SAMPLE_RATE,
            "surprise_interval": args.surprise_interval,
            "seed": SEED,
            "device": args.device,
        },
        "results": results,
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
