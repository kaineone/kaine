#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Offline, entity-free cross-modal decodability measurement.

Question: does the film programme carry learnable cross-modal structure
(video <-> audio) for a future content code, or does that code need a
different stimulus or live feeds? This is design input, not a go/no-go gate.

No entity, no KAINE service and no bus is involved. The script decodes the
programme films (read-only) the way the perception feed does (OpenCV for
video, PyAV resampled to 16 kHz mono s16 for audio), embeds them with KAINE's
own frozen encoders (the vendored InternVideo-Next clip encoder for video, the
configured acoustic encoder for audio), aligns the two embedding streams on a
common time grid and fits video->audio and audio->video ridge regression and a
regularised CCA under leakage-safe cross-validation. Every lag-0 result is
set against time-shifted and shuffled controls.

Stages (each can be run alone; embeddings are cached):

    extract   decode + embed + cache  (needs a free GPU 0 for the video encoder)
    analyse   CPU only: ridge / CCA, controls, bootstrap CIs, results.json
    report    write the tables into the markdown report

Only numbers are written. The embedding cache lives under the scratch dir and
is the only derived data kept; no media, frame or waveform is stored.

Typical run (see the report for the exact command used):

    systemd-run --user --scope -p MemoryMax=16G nice -n 19 \\
        .venv/bin/python tools/research/crossmodal_decodability.py all
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

# --------------------------------------------------------------------------
# Constants (mirroring the perception feed / shipped config)
# --------------------------------------------------------------------------

DEFAULT_MANIFEST = Path(
    "/var/mnt/675bf75f-6d4f-4738-bdb0-22bfb7a93a69/kaine/media/ignition-programme/programme.toml"
)
DEFAULT_SCRATCH = Path("/var/mnt/675bf75f-6d4f-4738-bdb0-22bfb7a93a69/kaine/scratch/crossmodal")
DEFAULT_MODELS_DIR = Path(
    "/var/mnt/675bf75f-6d4f-4738-bdb0-22bfb7a93a69/kaine/os-drive-state-copy-2026-10-06/models"
)
DEFAULT_REPORT = Path(
    "/var/home/erik/Projects/kaineone/kaine-research/crossmodal-decodability-2026-10-31.md"
)

SAMPLE_RATE = 16000  # [perception_feed.audio].sample_rate / capture_sample_rate
VISION_HZ = 10.0  # [vision].vision_sample_hz
CLIP_LEN = 16  # [vision].clip_len (a 1.6 s clip at 10 Hz)
AUDIO_CONTEXT_S = 2.0  # context of the self-supervised acoustic encoders
WINDOW_S = 0.5  # the common time grid: one pair per window


# --------------------------------------------------------------------------
# Alignment (pure functions; no model needed)
# --------------------------------------------------------------------------


def valid_window_ends(
    duration_s: float,
    window_s: float = WINDOW_S,
    context_s: float = AUDIO_CONTEXT_S,
    stride: int = 1,
) -> np.ndarray:
    """Window END times (s) on the common grid for a film of ``duration_s``.

    A window ends at ``(i + 1) * window_s``. Both streams are causal on the
    window end: the video clip and the audio context both END there. A window
    is valid when its full context fits inside the film, so the first valid
    end is ``ceil(context_s)`` on the grid and the last is at most the
    duration. ``stride`` keeps every stride-th valid window (even subsampling).
    """
    if stride < 1:
        raise ValueError("stride must be >= 1")
    first = int(math.ceil(context_s / window_s - 1e-9))
    last = int(math.floor(duration_s / window_s + 1e-9))
    if last < first:
        return np.zeros(0, dtype=np.float64)
    ends = (np.arange(first, last + 1, dtype=np.float64)) * window_s
    return ends[::stride]


def clip_frame_indices(
    t_end: np.ndarray,
    frame_times: np.ndarray,
    clip_len: int = CLIP_LEN,
    hz: float = VISION_HZ,
) -> np.ndarray:
    """Frame indices (W, clip_len) of the 10 Hz sampled clip ending at ``t_end``.

    The clip's last sample is at the window end, the earlier ones step back by
    ``1/hz``. Each index is the decoded frame whose presentation timestamp is at
    or before the sample time, found from the file's real per-frame timestamps
    (``frame_times``): the programme films are variable-frame-rate, so dividing a
    frame index by the nominal 25 fps drifts from the audio by up to 190 s.
    Indices are clipped into ``[0, len(frame_times) - 1]``.
    """
    t_end = np.asarray(t_end, dtype=np.float64)
    frame_times = np.asarray(frame_times, dtype=np.float64)
    offsets = (np.arange(clip_len, dtype=np.float64) - (clip_len - 1)) / hz  # -1.5 .. 0
    times = t_end[:, None] + offsets[None, :]
    idx = np.searchsorted(frame_times, times + 1e-6, side="right") - 1
    return np.clip(idx, 0, max(0, len(frame_times) - 1)).astype(np.int64)


def audio_sample_span(
    t_end: float, context_s: float = AUDIO_CONTEXT_S, sr: int = SAMPLE_RATE
) -> tuple[int, int]:
    """Half-open sample range ``[start, stop)`` of the audio context ending at ``t_end``."""
    stop = int(round(t_end * sr))
    return max(0, stop - int(round(context_s * sr))), stop


# --------------------------------------------------------------------------
# Pairing, controls and leakage-safe splits (pure functions)
# --------------------------------------------------------------------------


def shift_pairs(n: int, shift: int) -> tuple[np.ndarray, np.ndarray]:
    """Pairs (video index v, audio index a = v + shift) inside one film of n windows."""
    lo = max(0, -shift)
    hi = min(n, n - shift)
    if hi <= lo:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    v = np.arange(lo, hi, dtype=np.int64)
    return v, v + shift


def window_shuffle_pairs(n: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Pair every video window with a randomly permuted audio window of the same span."""
    v = np.arange(n, dtype=np.int64)
    return v, rng.permutation(n).astype(np.int64)


def block_shuffle_pairs(
    n: int, block: int, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray]:
    """Permute whole contiguous audio blocks of ``block`` windows (order kept inside a block).

    The trailing partial block stays in place. Local audio structure is intact;
    only its alignment to the video is destroyed.
    """
    if block < 1:
        raise ValueError("block must be >= 1")
    v = np.arange(n, dtype=np.int64)
    n_full = n // block
    if n_full < 2:  # cannot move a block: fall back so alignment is still destroyed
        return window_shuffle_pairs(n, rng)
    order = rng.permutation(n_full)
    a = v.copy()
    for dst, src in enumerate(order):
        a[dst * block : (dst + 1) * block] = np.arange(src * block, (src + 1) * block)
    return v, a


@dataclass
class Pairs:
    """Flat pair table over all films: which video and audio window each row uses."""

    film: np.ndarray  # (P,) film index
    v: np.ndarray  # (P,) video window index within the film
    a: np.ndarray  # (P,) audio window index within the film

    def __len__(self) -> int:
        return int(self.film.shape[0])

    def take(self, idx: np.ndarray) -> "Pairs":
        return Pairs(self.film[idx], self.v[idx], self.a[idx])


def segment_bounds(n: int, scheme: str, n_blocks: int = 8) -> list[tuple[int, int]]:
    """The contiguous spans of one film that the outer folds hold out as units."""
    if scheme == "film":
        return [(0, n)]
    return [((n * b) // n_blocks, (n * (b + 1)) // n_blocks) for b in range(n_blocks)]


def build_pairs(
    film_sizes: Sequence[int],
    mode: str,
    shift: int = 0,
    seed: int = 0,
    block: int = 60,
    scheme: str = "film",
    n_blocks: int = 8,
) -> Pairs:
    """Pair table for ``mode`` in {"shift", "shuffle_window", "shuffle_block"}.

    The shuffled controls permute audio only WITHIN each outer-fold span (a whole
    film for the film scheme, one block for the block scheme), so a pair's video
    and audio windows always sit in the same span. That keeps the leakage purge
    local: purging a held-out span never has to purge the rest of the film.
    """
    rng = np.random.default_rng(seed)
    films, vs, as_ = [], [], []
    for f, n in enumerate(film_sizes):
        if mode == "shift":
            v, a = shift_pairs(n, shift)
        elif mode in ("shuffle_window", "shuffle_block"):
            vparts, aparts = [], []
            for lo, hi in segment_bounds(n, scheme, n_blocks):
                if hi <= lo:
                    continue
                if mode == "shuffle_window":
                    sv, sa = window_shuffle_pairs(hi - lo, rng)
                else:
                    sv, sa = block_shuffle_pairs(hi - lo, block, rng)
                vparts.append(sv + lo)
                aparts.append(sa + lo)
            v, a = np.concatenate(vparts), np.concatenate(aparts)
        else:
            raise ValueError(f"unknown pairing mode {mode!r}")
        films.append(np.full(v.shape, f, dtype=np.int64))
        vs.append(v)
        as_.append(a)
    return Pairs(np.concatenate(films), np.concatenate(vs), np.concatenate(as_))


def _dilate(mask: np.ndarray, k: int) -> np.ndarray:
    """Boolean dilation of a 1-D mask by ``k`` positions either side."""
    if k <= 0:
        return mask.copy()
    c = np.convolve(mask.astype(np.int32), np.ones(2 * k + 1, dtype=np.int32), mode="same")
    return c > 0


def purged_train_mask(
    test_mask: np.ndarray, pairs: Pairs, film_sizes: Sequence[int], gap: int
) -> np.ndarray:
    """Training rows for a held-out set, with a purge gap against leakage.

    The windows a test pair touches (its video and its audio index) are
    dilated by ``gap`` windows in their film. A candidate training row is
    dropped when its video OR audio window falls inside that footprint. With a
    gap at least the embedding context (video 1.6 s, audio 2 s), no training
    row shares any raw signal with any test row, even for shifted or shuffled
    pairings. The test rows themselves are always excluded.
    """
    footprint = [np.zeros(n, dtype=bool) for n in film_sizes]
    for f in np.unique(pairs.film[test_mask]):
        sel = test_mask & (pairs.film == f)
        footprint[int(f)][pairs.v[sel]] = True
        footprint[int(f)][pairs.a[sel]] = True
    footprint = [_dilate(m, gap) for m in footprint]
    keep = ~test_mask
    for f, fp in enumerate(footprint):
        m = pairs.film == f
        if not m.any():
            continue
        keep[m] &= ~fp[pairs.v[m]] & ~fp[pairs.a[m]]
    return keep


def make_folds(
    film_sizes: Sequence[int], scheme: str, n_blocks: int = 8
) -> list[list[tuple[int, int, int]]]:
    """Outer folds as lists of (film, v_start, v_stop) held-out video ranges.

    ``film``: leave one whole film out (cross-film generalisation).
    ``block``: ``n_blocks`` contiguous blocks per film; fold b holds out block b
    of every film (within-programme generalisation; contiguous, never interleaved).
    """
    if scheme == "film":
        return [[(f, 0, n)] for f, n in enumerate(film_sizes)]
    if scheme == "block":
        folds = []
        for b in range(n_blocks):
            fold = []
            for f, n in enumerate(film_sizes):
                lo = (n * b) // n_blocks
                hi = (n * (b + 1)) // n_blocks
                if hi > lo:
                    fold.append((f, lo, hi))
            folds.append(fold)
        return folds
    raise ValueError(f"unknown scheme {scheme!r}")


def fold_test_mask(pairs: Pairs, fold: Sequence[tuple[int, int, int]]) -> np.ndarray:
    """Rows whose VIDEO window lies in the fold's held-out ranges."""
    m = np.zeros(len(pairs), dtype=bool)
    for f, lo, hi in fold:
        m |= (pairs.film == f) & (pairs.v >= lo) & (pairs.v < hi)
    return m


def inner_blocks(n_rows: int, k: int) -> list[np.ndarray]:
    """Boolean masks of ``k`` contiguous equal chunks over ``n_rows`` ordered rows."""
    out = []
    for b in range(k):
        m = np.zeros(n_rows, dtype=bool)
        m[(n_rows * b) // k : (n_rows * (b + 1)) // k] = True
        out.append(m)
    return out


# --------------------------------------------------------------------------
# Models: ridge and regularised CCA (numpy, float64 solves)
# --------------------------------------------------------------------------

ALPHAS = np.array([0.1, 1.0, 10.0, 100.0, 1e3, 1e4, 1e5])
CCA_DIM = 32  # PCA dimensions kept per side before CCA
CCA_REG = 0.1  # ridge on the whitening, as a fraction of the mean PCA variance
CCA_TOP = 10  # canonical components scored


def _zstats(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mu = x.mean(axis=0)
    sd = x.std(axis=0)
    sd = np.where(sd < 1e-8, 1.0, sd)
    return mu, sd


def _gram(a: np.ndarray, b: np.ndarray | None = None) -> np.ndarray:
    """a.T @ (b or a), float32 matmul accumulated into float64."""
    a32 = np.asarray(a, dtype=np.float32)
    b32 = a32 if b is None else np.asarray(b, dtype=np.float32)
    return (a32.T @ b32).astype(np.float64)


class RidgeModel:
    """Multi-output ridge on z-scored features and targets (train statistics only).

    ``alpha`` is dimensionless: relative to the mean eigenvalue of the z-scored
    Gram matrix, so the same grid suits any feature dimension.
    """

    def __init__(self, alpha: float) -> None:
        self.alpha = float(alpha)

    def fit(self, x: np.ndarray, y: np.ndarray) -> "RidgeModel":
        self.xmu, self.xsd = _zstats(x)
        self.ymu, self.ysd = _zstats(y)
        xz = ((x - self.xmu) / self.xsd).astype(np.float32)
        yz = ((y - self.ymu) / self.ysd).astype(np.float32)
        n = xz.shape[0]
        gram = _gram(xz) / n
        xty = _gram(xz, yz) / n
        p = gram.shape[0]
        self.w = np.linalg.solve(gram + self.alpha * (np.trace(gram) / p) * np.eye(p), xty)
        return self

    def predict_z(self, x: np.ndarray) -> np.ndarray:
        return (((x - self.xmu) / self.xsd) @ self.w).astype(np.float32)

    def target_z(self, y: np.ndarray) -> np.ndarray:
        return ((y - self.ymu) / self.ysd).astype(np.float32)


def select_alpha(
    x: np.ndarray, y: np.ndarray, pairs: Pairs, film_sizes: Sequence[int], gap: int, k: int = 4
) -> float:
    """Pick the ridge alpha by contiguous, purged inner CV on the training rows only.

    The inner held-out error of every alpha is computed from Gram matrices
    (SSE = yy - 2<W,B> + <W,GW>) so each inner fold needs one eigendecomposition,
    not one fit per alpha. Features and targets are z-scored with the outer
    training statistics.
    """
    xmu, xsd = _zstats(x)
    ymu, ysd = _zstats(y)
    xz = ((x - xmu) / xsd).astype(np.float32)
    yz = ((y - ymu) / ysd).astype(np.float32)
    p = xz.shape[1]
    g_tot = _gram(xz)
    b_tot = _gram(xz, yz)
    order = np.lexsort((pairs.v, pairs.film))  # film, then time
    sse = np.zeros(len(ALPHAS))
    used = 0
    for tmask_ordered in inner_blocks(len(order), k):
        tmask = np.zeros(len(pairs), dtype=bool)
        tmask[order[tmask_ordered]] = True
        keep = purged_train_mask(tmask, pairs, film_sizes, gap)
        n_tr = int(keep.sum())
        if n_tr < 50 or tmask.sum() < 10:
            continue
        rem = ~keep
        g_tr = (g_tot - _gram(xz[rem])) / n_tr
        b_tr = (b_tot - _gram(xz[rem], yz[rem])) / n_tr
        g_te = _gram(xz[tmask])
        b_te = _gram(xz[tmask], yz[tmask])
        yy_te = float((yz[tmask].astype(np.float64) ** 2).sum())
        lam, vec = np.linalg.eigh(g_tr)
        lam = np.maximum(lam, 0.0)
        vb = vec.T @ b_tr
        scale = float(np.trace(g_tr)) / p
        for i, a in enumerate(ALPHAS):
            w = vec @ (vb / (lam + a * scale)[:, None])
            sse[i] += yy_te - 2.0 * float((w * b_te).sum()) + float((w * (g_te @ w)).sum())
        used += 1
    if used == 0:
        return float(ALPHAS[len(ALPHAS) // 2])
    return float(ALPHAS[int(np.argmin(sse))])


class CCAModel:
    """Regularised CCA on PCA-reduced, z-scored views (train statistics only)."""

    def __init__(self, dim: int = CCA_DIM, reg: float = CCA_REG) -> None:
        self.dim = dim
        self.reg = reg

    @staticmethod
    def _pca(z: np.ndarray, dim: int) -> tuple[np.ndarray, np.ndarray]:
        cov = _gram(z) / z.shape[0]
        w, v = np.linalg.eigh(cov)
        k = min(dim, v.shape[1])
        return v[:, ::-1][:, :k], np.maximum(w[::-1][:k], 0.0)

    @staticmethod
    def _inv_sqrt(c: np.ndarray) -> np.ndarray:
        w, v = np.linalg.eigh(c)
        w = np.maximum(w, 1e-12)
        return (v / np.sqrt(w)) @ v.T

    def fit(self, x: np.ndarray, y: np.ndarray) -> "CCAModel":
        self.xmu, self.xsd = _zstats(x)
        self.ymu, self.ysd = _zstats(y)
        xz = ((x - self.xmu) / self.xsd).astype(np.float32)
        yz = ((y - self.ymu) / self.ysd).astype(np.float32)
        self.px, vx = self._pca(xz, self.dim)
        self.py, vy = self._pca(yz, self.dim)
        a = (xz @ self.px.astype(np.float32)).astype(np.float64)
        b = (yz @ self.py.astype(np.float32)).astype(np.float64)
        n = a.shape[0]
        cxx = a.T @ a / n + self.reg * vx.mean() * np.eye(a.shape[1])
        cyy = b.T @ b / n + self.reg * vy.mean() * np.eye(b.shape[1])
        cxy = a.T @ b / n
        wx = self._inv_sqrt(cxx)
        wy = self._inv_sqrt(cyy)
        u, s, vt = np.linalg.svd(wx @ cxy @ wy, full_matrices=False)
        k = min(CCA_TOP, u.shape[1], vt.shape[0])
        self.ax = self.px @ (wx @ u[:, :k])
        self.ay = self.py @ (wy @ vt[:k].T)
        self.train_corr = s[:k]
        return self

    def project(self, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        xz = (x - self.xmu) / self.xsd
        yz = (y - self.ymu) / self.ysd
        return (xz @ self.ax).astype(np.float32), (yz @ self.ay).astype(np.float32)


# --------------------------------------------------------------------------
# Per-unit sufficient statistics and block bootstrap
# --------------------------------------------------------------------------

UNIT_S = 20.0  # bootstrap unit: contiguous held-out span of this many seconds


@dataclass
class UnitStats:
    """Sufficient statistics of held-out rows, grouped into contiguous bootstrap units."""

    keys: list[tuple[int, int, int]]  # (film, unit index, fold)
    n: np.ndarray  # (U,)
    stats: np.ndarray  # (U, channels, q)


def _unit_ids(pairs: Pairs, unit_len: int, fold: int) -> list[tuple[int, int, int]]:
    return [(int(f), int(v) // unit_len, fold) for f, v in zip(pairs.film, pairs.v)]


def accumulate_units(
    keys_per_row: list[tuple[int, int, int]], channels: Sequence[np.ndarray]
) -> UnitStats:
    """Sum row-level channels (each (m, q)) into per-unit statistics."""
    uniq: dict[tuple[int, int, int], int] = {}
    row_unit = np.empty(len(keys_per_row), dtype=np.int64)
    for i, k in enumerate(keys_per_row):
        row_unit[i] = uniq.setdefault(k, len(uniq))
    u = len(uniq)
    starts = np.concatenate([[0], np.flatnonzero(np.diff(row_unit)) + 1])
    if len(starts) != u:
        raise ValueError("rows of one unit must be contiguous")
    q = channels[0].shape[1]
    stats = np.zeros((u, len(channels), q), dtype=np.float64)
    for c, ch in enumerate(channels):
        stats[:, c, :] = np.add.reduceat(ch.astype(np.float64), starts, axis=0)
    n = np.diff(np.concatenate([starts, [len(row_unit)]])).astype(np.float64)
    return UnitStats(list(uniq.keys()), n, stats)


def ridge_row_channels(yz: np.ndarray, pz: np.ndarray) -> list[np.ndarray]:
    """[y, p, y*y, p*p, y*p, (y-p)^2] rows for a z-space held-out set."""
    return [yz, pz, yz * yz, pz * pz, yz * pz, (yz - pz) ** 2]


def cca_row_channels(u: np.ndarray, v: np.ndarray) -> list[np.ndarray]:
    return [u, v, u * u, v * v, u * v]


def _pearson_from_sums(
    n: np.ndarray, sa: np.ndarray, sb: np.ndarray, saa: np.ndarray, sbb: np.ndarray, sab: np.ndarray
) -> np.ndarray:
    """Pearson r per column from sums; n broadcasts over the trailing axis."""
    cov = sab - sa * sb / n
    va = saa - sa * sa / n
    vb = sbb - sb * sb / n
    den = np.sqrt(np.maximum(va, 0.0) * np.maximum(vb, 0.0))
    return np.where(den > 1e-12, cov / np.where(den > 1e-12, den, 1.0), 0.0)


def fold_metrics(method: str, sums: np.ndarray, n: np.ndarray) -> dict[str, np.ndarray]:
    """Metrics for one fold from summed stats. ``sums`` is (B, channels, q), ``n`` (B,)."""
    nn = np.maximum(n, 1.0)[:, None]
    if method == "ridge":
        sy, sp, syy, spp, syp, sse = (sums[:, i, :] for i in range(6))
        r2 = 1.0 - sse / np.where(syy > 1e-12, syy, 1.0)  # baseline = train mean (0 in z space)
        corr = _pearson_from_sums(nn, sy, sp, syy, spp, syp)
        return {"r2": r2.mean(axis=1), "corr": corr.mean(axis=1)}
    if method == "cca":
        su, sv, suu, svv, suv = (sums[:, i, :] for i in range(5))
        corr = _pearson_from_sums(nn, su, sv, suu, svv, suv)
        return {"corr1": corr[:, 0], "corr5": corr[:, :5].mean(axis=1)}
    raise ValueError(method)


def stratified_counts(
    keys: Sequence[tuple[int, int, int]], n_boot: int, rng: np.random.Generator
) -> np.ndarray:
    """Bootstrap count matrix (1 + n_boot, U); row 0 is all ones (the point estimate).

    Units are resampled with replacement within their (film, fold) group, so every
    draw keeps the original number of units per film and fold.
    """
    u = len(keys)
    counts = np.ones((1 + n_boot, u), dtype=np.float64)
    groups: dict[tuple[int, int], list[int]] = {}
    for i, (f, _unit, fold) in enumerate(keys):
        groups.setdefault((f, fold), []).append(i)
    for idx in groups.values():
        k = len(idx)
        counts[1:, idx] = rng.multinomial(k, np.full(k, 1.0 / k), size=n_boot)
    return counts


def aggregate(
    method: str,
    unit_stats: UnitStats,
    counts: np.ndarray,
    films: Iterable[int] | None = None,
) -> dict[str, np.ndarray]:
    """n-weighted mean over folds of the per-fold metrics, for each count row.

    ``counts`` is (R, U) aligned to ``unit_stats.keys``. ``films`` restricts the
    units to those films (None = all).
    """
    films_set = None if films is None else set(int(f) for f in films)
    folds = sorted({k[2] for k in unit_stats.keys})
    acc: dict[str, np.ndarray] = {}
    wsum = np.zeros(counts.shape[0])
    for fold in folds:
        idx = [
            i
            for i, k in enumerate(unit_stats.keys)
            if k[2] == fold and (films_set is None or k[0] in films_set)
        ]
        if not idx:
            continue
        cnt = counts[:, idx]
        n_f = cnt @ unit_stats.n[idx]
        sub = unit_stats.stats[idx]
        sums = (cnt @ sub.reshape(len(idx), -1)).reshape(
            counts.shape[0], sub.shape[1], sub.shape[2]
        )
        mets = fold_metrics(method, sums, n_f)
        for name, val in mets.items():
            acc[name] = acc.get(name, 0.0) + val * n_f
        wsum += n_f
    return {k: v / np.maximum(wsum, 1.0) for k, v in acc.items()}


def summarise(draws: np.ndarray) -> dict[str, float]:
    """Point estimate (row 0) and 95% percentile interval over the bootstrap rows."""
    boot = draws[1:]
    if boot.size == 0:
        return {"est": float(draws[0]), "lo": float("nan"), "hi": float("nan")}
    return {
        "est": float(draws[0]),
        "lo": float(np.percentile(boot, 2.5)),
        "hi": float(np.percentile(boot, 97.5)),
    }


def paired_delta(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    """Summary of a - b over the SAME bootstrap draws (paired)."""
    return summarise(a - b)


# --------------------------------------------------------------------------
# Embedding data
# --------------------------------------------------------------------------


@dataclass
class FilmEmbeddings:
    name: str
    t_end: np.ndarray  # (n,) window end times
    video: np.ndarray  # (n, dv) float32
    audio: np.ndarray  # (n, da) float32


# --------------------------------------------------------------------------
# One configuration: (scheme, direction, pairing) -> unit statistics
# --------------------------------------------------------------------------


@dataclass
class Config:
    scheme: str
    direction: str  # "v2a" or "a2v"
    method: str  # "ridge" or "cca"
    control: str  # "lag" | "shuffle_window" | "shuffle_block"
    shift: int = 0  # grid steps (lag only)
    seed: int = 0
    shift_s: float = 0.0  # the same shift in seconds (label only)

    def label(self) -> str:
        if self.control == "lag":
            return f"lag{self.shift_s:+.0f}s"
        return f"{self.control}_s{self.seed}"


def _gather(
    films: Sequence[FilmEmbeddings], pairs: Pairs, direction: str
) -> tuple[np.ndarray, np.ndarray]:
    dv = films[0].video.shape[1]
    da = films[0].audio.shape[1]
    v = np.empty((len(pairs), dv), dtype=np.float32)
    a = np.empty((len(pairs), da), dtype=np.float32)
    for f, fe in enumerate(films):
        m = pairs.film == f
        if m.any():
            v[m] = fe.video[pairs.v[m]]
            a[m] = fe.audio[pairs.a[m]]
    return (v, a) if direction == "v2a" else (a, v)


def run_config(
    films: Sequence[FilmEmbeddings],
    cfg: Config,
    folds: list[list[tuple[int, int, int]]],
    *,
    gap: int,
    unit_len: int,
    block_windows: int,
    n_blocks: int = 8,
) -> UnitStats | None:
    """Fit every outer fold of ``cfg`` and return per-unit held-out statistics."""
    sizes = [len(f.t_end) for f in films]
    if cfg.control == "lag":
        pairs = build_pairs(sizes, "shift", shift=cfg.shift)
    else:
        pairs = build_pairs(
            sizes,
            cfg.control,
            seed=cfg.seed,
            block=block_windows,
            scheme=cfg.scheme,
            n_blocks=n_blocks,
        )
    x_all, y_all = _gather(films, pairs, cfg.direction)
    all_keys: list[tuple[int, int, int]] = []
    all_channels: list[list[np.ndarray]] = []
    for fold_i, fold in enumerate(folds):
        test = fold_test_mask(pairs, fold)
        train = purged_train_mask(test, pairs, sizes, gap)
        if test.sum() < 10 or train.sum() < 100:
            continue
        xtr, ytr = x_all[train], y_all[train]
        if cfg.method == "ridge":
            alpha = select_alpha(xtr, ytr, pairs.take(np.flatnonzero(train)), sizes, gap)
            m = RidgeModel(alpha).fit(xtr, ytr)
            yz = m.target_z(y_all[test])
            pz = m.predict_z(x_all[test])
            chans = ridge_row_channels(yz, pz)
        else:
            m = CCAModel().fit(xtr, ytr)
            u, v = m.project(x_all[test], y_all[test])
            chans = cca_row_channels(u, v)
        all_keys.extend(_unit_ids(pairs.take(np.flatnonzero(test)), unit_len, fold_i))
        all_channels.append(chans)
    if not all_keys:
        return None
    channels = [
        np.concatenate([c[i] for c in all_channels], axis=0) for i in range(len(all_channels[0]))
    ]
    return accumulate_units(all_keys, channels)


def universe_keys(
    film_sizes: Sequence[int], folds: list[list[tuple[int, int, int]]], unit_len: int
) -> list[tuple[int, int, int]]:
    """Every (film, unit, fold) unit the lag-0 pairing can produce for these folds."""
    keys: dict[tuple[int, int, int], None] = {}
    for fold_i, fold in enumerate(folds):
        for f, lo, hi in fold:
            for v in range(lo, hi):
                keys[(f, v // unit_len, fold_i)] = None
    return list(keys)


def counts_for(
    units: UnitStats, universe: Sequence[tuple[int, int, int]], universe_counts: np.ndarray
) -> np.ndarray:
    """Select the universe bootstrap columns for this config's units (paired draws)."""
    col = {k: i for i, k in enumerate(universe)}
    return universe_counts[:, [col[k] for k in units.keys]]


# --------------------------------------------------------------------------
# Extraction (decode + embed). Heavy imports are local.
# --------------------------------------------------------------------------


def gpu0_busy_mb() -> int:
    """Largest memory use (MiB) of any compute process on GPU 0, via nvidia-smi."""
    try:
        idx = (
            subprocess.run(
                ["nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                check=True,
            )
            .stdout.strip()
            .splitlines()
        )
        uuid0 = next(
            line.split(",")[1].strip() for line in idx if line.split(",")[0].strip() == "0"
        )
        apps = (
            subprocess.run(
                [
                    "nvidia-smi",
                    "--query-compute-apps=gpu_uuid,used_memory",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            .stdout.strip()
            .splitlines()
        )
    except (OSError, subprocess.CalledProcessError, StopIteration):
        return 10**9  # unknown: treat as busy
    used = [int(line.split(",")[1]) for line in apps if line.split(",")[0].strip() == uuid0]
    return max(used) if used else 0


def decode_audio(path: str) -> np.ndarray:
    """Whole-film mono 16 kHz int16, resampled with the audition feed's PyAV settings.

    Only the ``rframe.samples`` real samples of each resampled frame are kept
    (``to_ndarray``). The audition feed (``kaine/modules/audition/feed.py``)
    appends ``bytes(rframe.planes[0])`` instead, and that buffer is padded: on
    the installed PyAV a 193-sample frame is a 512-byte plane. Taking the padded
    plane would stretch the film's audio by 27 to 40 percent with silent gaps, so
    this tool does not copy that step; see the report.
    """
    import av  # type: ignore

    parts: list[np.ndarray] = []
    container = av.open(path)
    try:
        resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        stream = container.streams.audio[0]
        for frame in container.decode(stream):
            for rframe in resampler.resample(frame):
                parts.append(rframe.to_ndarray().reshape(-1).astype("<i2", copy=False))
        for rframe in resampler.resample(None) or []:
            parts.append(rframe.to_ndarray().reshape(-1).astype("<i2", copy=False))
    finally:
        container.close()
    return np.concatenate(parts) if parts else np.zeros(0, dtype="<i2")


def video_frame_times(path: str) -> np.ndarray:
    """Presentation time (s) of every video frame, in decode order, from the packets.

    VP8 here has no reordering, so decode order equals presentation order and
    index ``i`` is the ``i``-th frame OpenCV returns (checked against its count).
    """
    import av  # type: ignore

    c = av.open(path)
    try:
        stream = c.streams.video[0]
        times = [float(pk.pts * pk.time_base) for pk in c.demux(stream) if pk.pts is not None]
    finally:
        c.close()
    out = np.asarray(times, dtype=np.float64)
    if out.size and (np.diff(out) < 0).any():
        raise ValueError("video packet timestamps are not monotonic; reordering unsupported")
    return out


def embed_audio(pcm: np.ndarray, t_end: np.ndarray, encoder_name: str, device: str) -> np.ndarray:
    """Acoustic embeddings of the trailing context ending at each window end.

    Uses KAINE's own ``build_acoustic_encoder``. For the self-supervised encoders
    the rolling buffer is reset before each window and fed the full context, so
    every embedding is a pure function of its own 2 s window (also under subsampling).
    """
    from kaine.modules.audition.acoustic import build_acoustic_encoder

    kwargs: dict[str, Any] = {}
    if encoder_name in ("dasheng", "wavjepa"):
        kwargs = {"device": device, "context_s": AUDIO_CONTEXT_S}
    enc = build_acoustic_encoder(encoder_name, **kwargs)
    out = np.empty((len(t_end), enc.embedding_dim), dtype=np.float32)
    for i, t in enumerate(t_end):
        lo, hi = audio_sample_span(float(t))
        chunk = pcm[lo:hi].astype("<i2").tobytes()
        if hasattr(enc, "_buffer"):
            enc._buffer.clear()
            enc._buffer_samples = 0
        out[i] = np.asarray(enc.embed(chunk, SAMPLE_RATE), dtype=np.float32)
    return out


def embed_video(
    path: str, t_end: np.ndarray, frame_times: np.ndarray, device: str, batch: int = 4
) -> tuple[np.ndarray, str]:
    """InternVideo-Next clip embeddings (768-d, native attention pool) per window.

    Frames are decoded with OpenCV, converted BGR->RGB->PIL and preprocessed by
    the vendored VideoMAE processor (resize 224, centre crop, ImageNet norm),
    exactly the non-foveated path of the vision module; the frozen model is the
    one KAINE loads. Returns (embeddings, model note). May return fewer rows
    than windows if the file ends early; the caller trims.
    """
    import cv2
    import torch
    from PIL import Image

    from kaine.hardware import resolve_dtype
    from kaine.modules.vision.encoder import _load_videomae_processor
    from kaine.modules.vision.internvideo_next_loader import load_internvideo_next

    processor = _load_videomae_processor()
    model = load_internvideo_next(device=device, torch_dtype=resolve_dtype(device))
    param_dtype = next(model.parameters()).dtype

    idx_mat = clip_frame_indices(t_end, frame_times)
    wanted = set(int(i) for i in np.unique(idx_mat))
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {path}")
    cache: dict[int, Any] = {}
    cursor = 0
    exhausted = False
    out: list[np.ndarray] = []
    pending: list[Any] = []

    def flush() -> None:
        if not pending:
            return
        x = torch.stack(pending).to(device=device, dtype=param_dtype)  # (B, 3, T, H, W)
        with torch.no_grad():
            emb = model(x)
        out.append(emb.float().cpu().numpy())
        pending.clear()

    n_done = 0
    for w in range(len(t_end)):
        need = idx_mat[w]
        hi = int(need.max())
        while cursor <= hi and not exhausted:
            if cursor in wanted:
                ok, frame = cap.read()
                if not ok:
                    exhausted = True
                    break
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                px = processor(Image.fromarray(rgb), return_tensors="pt")["pixel_values"]
                cache[cursor] = px.reshape(3, 224, 224).to(torch.float16)
            else:
                if not cap.grab():
                    exhausted = True
                    break
            cursor += 1
        if any(int(i) not in cache for i in need):
            break  # file ended before this window's clip: stop here
        clip = torch.stack([cache[int(i)] for i in need], dim=1)  # (3, T, H, W)
        pending.append(clip)
        n_done += 1
        if len(pending) >= batch:
            flush()
        if w + 1 < len(t_end):
            lo_next = int(idx_mat[w + 1].min())
            for k in [k for k in cache if k < lo_next]:
                del cache[k]
        if n_done % 500 == 0:
            print(f"    video windows {n_done}/{len(t_end)}", flush=True)
    flush()
    cap.release()
    model = None  # drop the weights before emptying the CUDA cache
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
    emb = np.concatenate(out, axis=0) if out else np.zeros((0, 768), dtype=np.float32)
    return emb, "InternVideo-Next base p14 res224 f16, attention pool, non-foveated full frame"


def cache_paths(
    scratch: Path, film_stem: str, kind: str, name: str, stride: int, limit: int | None
) -> Path:
    tag = f"w{WINDOW_S}_c{AUDIO_CONTEXT_S}_s{stride}" + (f"_lim{limit}" if limit else "")
    return scratch / "cache" / f"{film_stem}.{kind}.{name}.{tag}.npy"


def stage_extract(args: argparse.Namespace) -> None:
    from kaine.modules.vision.feed import load_playlist_manifest

    manifest = load_playlist_manifest(args.manifest)
    if not args.skip_verify:
        print("verifying manifest sha256 (read-only) ...", flush=True)
        manifest.verify_against(Path(args.manifest).parent)
    scratch = Path(args.scratch)
    (scratch / "cache").mkdir(parents=True, exist_ok=True)
    if args.video_device.startswith("cuda") or args.audio_device.startswith("cuda"):
        busy = gpu0_busy_mb()
        if busy > args.gpu_free_mb and not args.force_gpu:
            raise SystemExit(
                f"GPU 0 has a process using {busy} MiB (> {args.gpu_free_mb}); refusing to run. "
                "Wait for it to finish (or pass --video-device cpu --audio-device cpu)."
            )
    for item in sorted(manifest.items, key=lambda i: i.order):
        stem = Path(item.path).stem
        if args.films and not any(s.lower() in stem.lower() for s in args.films):
            continue
        meta_path = scratch / "cache" / f"{stem}.meta.json"
        print(f"[{stem}]", flush=True)
        t0 = time.time()
        pcm = decode_audio(str(item.path))
        audio_dur = len(pcm) / SAMPLE_RATE
        ftimes = video_frame_times(str(item.path))
        video_dur = float(ftimes[-1]) + float(np.median(np.diff(ftimes)))
        duration = min(audio_dur, video_dur)
        t_end = valid_window_ends(duration - 0.05, stride=args.stride)
        if args.limit:
            t_end = t_end[: args.limit]
        timing = {
            "nominal_fps": float(item.fps),
            "frames": int(len(ftimes)),
            "mean_fps": float(len(ftimes) / video_dur),
            "last_frame_pts_s": float(ftimes[-1]),
            "audio_s": audio_dur,
            "video_s": video_dur,
            "drift_at_end_s_if_nominal_fps": float(len(ftimes) / item.fps - video_dur),
        }
        print(f"  {timing} -> {len(t_end)} windows", flush=True)

        vpath = cache_paths(scratch, stem, "video", "internvideo_next_pts", args.stride, args.limit)
        if vpath.exists() and not args.recompute:
            v_emb = np.load(vpath)
        else:
            v_emb, note = embed_video(str(item.path), t_end, ftimes, args.video_device)
            np.save(vpath, v_emb)
        n_ok = min(len(t_end), len(v_emb))
        for enc_name in args.audio_encoders:
            apath = cache_paths(scratch, stem, "audio", enc_name, args.stride, args.limit)
            if (
                apath.exists()
                and not (args.recompute or args.recompute_audio)
                and len(np.load(apath, mmap_mode="r")) >= n_ok
            ):
                continue
            a_emb = embed_audio(pcm, t_end[:n_ok], enc_name, args.audio_device)
            np.save(apath, a_emb)
        meta_path.write_text(
            json.dumps(
                {
                    "film": stem,
                    "duration_s": duration,
                    "timing": timing,
                    "n_windows": int(n_ok),
                    "window_s": WINDOW_S,
                    "stride": args.stride,
                    "audio_context_s": AUDIO_CONTEXT_S,
                    "t_end": t_end[:n_ok].tolist(),
                }
            )
        )
        print(f"  done in {time.time() - t0:.0f}s", flush=True)


def load_films(args: argparse.Namespace, audio_encoder: str) -> list[FilmEmbeddings]:
    scratch = Path(args.scratch)
    films: list[FilmEmbeddings] = []
    for meta_path in sorted((scratch / "cache").glob("*.meta.json")):
        meta = json.loads(meta_path.read_text())
        stem = meta["film"]
        if args.films and not any(s.lower() in stem.lower() for s in args.films):
            continue
        if meta["stride"] != args.stride:
            continue
        v = np.load(
            cache_paths(scratch, stem, "video", "internvideo_next_pts", args.stride, args.limit)
        )
        a = np.load(cache_paths(scratch, stem, "audio", audio_encoder, args.stride, args.limit))
        n = min(len(v), len(a), len(meta["t_end"]))
        films.append(FilmEmbeddings(stem, np.asarray(meta["t_end"][:n]), v[:n], a[:n]))
    if not films:
        raise SystemExit("no cached embeddings found; run the extract stage first")
    return films


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------

SHIFTS_S = (-120.0, -30.0, -5.0, 0.0, 5.0, 30.0, 120.0)


def stage_analyse(args: argparse.Namespace) -> dict[str, Any]:
    scratch = Path(args.scratch)
    results: dict[str, Any] = {
        "params": {
            "window_s": WINDOW_S,
            "audio_context_s": AUDIO_CONTEXT_S,
            "clip_len": CLIP_LEN,
            "vision_hz": VISION_HZ,
            "unit_s": UNIT_S,
            "n_boot": args.n_boot,
            "block_folds": args.n_blocks,
            "purge_s": args.purge_s,
            "ridge_alphas": ALPHAS.tolist(),
            "cca_dim": CCA_DIM,
            "cca_reg": CCA_REG,
            "stride": args.stride,
        },
        "encoders": {},
    }
    for enc_name in args.audio_encoders:
        films = load_films(args, enc_name)
        grid_s = WINDOW_S * args.stride
        sizes = [len(f.t_end) for f in films]
        unit_len = max(1, int(round(UNIT_S / grid_s)))
        gap = int(math.ceil(args.purge_s / grid_s))
        block_windows = max(1, int(round(30.0 / grid_s)))
        enc_res: dict[str, Any] = {
            "films": [f.name for f in films],
            "windows_per_film": sizes,
            "video_dim": int(films[0].video.shape[1]),
            "audio_dim": int(films[0].audio.shape[1]),
            "schemes": {},
        }
        for scheme in args.schemes:
            folds = make_folds(sizes, scheme, args.n_blocks)
            uni = universe_keys(sizes, folds, unit_len)
            rng = np.random.default_rng(args.seed)
            uni_counts = stratified_counts(uni, args.n_boot, rng)
            controls: list[Config] = []
            for s in SHIFTS_S:
                controls.append(
                    Config(scheme, "v2a", "ridge", "lag", shift=int(round(s / grid_s)), shift_s=s)
                )
            for seed in range(args.n_shuffle_seeds):
                controls.append(Config(scheme, "v2a", "ridge", "shuffle_window", seed=seed))
                controls.append(Config(scheme, "v2a", "ridge", "shuffle_block", seed=seed))
            sch_res: dict[str, Any] = {}
            for direction in ("v2a", "a2v"):
                for method in ("ridge", "cca"):
                    if method == "cca" and direction == "a2v":
                        continue  # CCA is symmetric in the two views
                    for base in controls:
                        cfg = Config(
                            scheme,
                            direction,
                            method,
                            base.control,
                            base.shift,
                            base.seed,
                            base.shift_s,
                        )
                        t0 = time.time()
                        units = run_config(
                            films,
                            cfg,
                            folds,
                            gap=gap,
                            unit_len=unit_len,
                            block_windows=block_windows,
                            n_blocks=args.n_blocks,
                        )
                        if units is None:
                            continue
                        cnt = counts_for(units, uni, uni_counts)
                        entry: dict[str, Any] = {"all": {}, "per_film": {}}
                        for name, draws in aggregate(method, units, cnt).items():
                            entry["all"][name] = summarise(draws)
                            entry.setdefault("_draws", {})[f"all/{name}"] = draws
                        for fi, fe in enumerate(films):
                            pf = aggregate(method, units, cnt, films=[fi])
                            for name, draws in pf.items():
                                entry["per_film"].setdefault(fe.name, {})[name] = summarise(draws)
                                entry["_draws"][f"{fe.name}/{name}"] = draws
                        key = f"{direction}/{method}/{cfg.label()}"
                        sch_res[key] = entry
                        print(
                            f"  [{enc_name}/{scheme}] {key}: "
                            + ", ".join(f"{k}={v['est']:+.4f}" for k, v in entry["all"].items())
                            + f" ({time.time() - t0:.0f}s)",
                            flush=True,
                        )
            # paired contrasts lag 0 vs each control, from the shared bootstrap draws
            contrasts: dict[str, Any] = {}
            for direction in ("v2a", "a2v"):
                for method in ("ridge", "cca"):
                    if method == "cca" and direction == "a2v":
                        continue
                    base = sch_res.get(f"{direction}/{method}/lag+0s")
                    if base is None:
                        continue
                    for key, entry in sch_res.items():
                        if not key.startswith(f"{direction}/{method}/") or key.endswith("lag+0s"):
                            continue
                        for dname in list(base["_draws"]):
                            if dname in entry["_draws"] and dname.startswith("all/"):
                                contrasts.setdefault(f"{direction}/{method}", {}).setdefault(
                                    key.split("/")[-1], {}
                                )[dname[4:]] = paired_delta(
                                    base["_draws"][dname], entry["_draws"][dname]
                                )
            for entry in sch_res.values():
                entry.pop("_draws", None)
            enc_res["schemes"][scheme] = {
                "configs": sch_res,
                "contrasts_lag0_minus_control": contrasts,
            }
        results["encoders"][enc_name] = enc_res
    out = scratch / "results.json"
    out.write_text(json.dumps(results, indent=1))
    print(f"wrote {out}")
    return results


# --------------------------------------------------------------------------
# Report tables
# --------------------------------------------------------------------------


def _fmt(s: dict[str, float]) -> str:
    return f"{s['est']:+.3f} [{s['lo']:+.3f}, {s['hi']:+.3f}]"


def headline(results: dict[str, Any]) -> str:
    """One compact table per encoder and scheme: lag 0 against its controls."""
    rows: list[str] = []
    for enc, er in results["encoders"].items():
        for scheme, sr in er["schemes"].items():
            cfgs = sr["configs"]
            for dm in sorted({k.rsplit("/", 1)[0] for k in cfgs}):
                direction, method = dm.split("/")
                metrics = ["r2", "corr"] if method == "ridge" else ["corr5", "corr1"]
                for m in metrics:
                    lag0 = cfgs.get(f"{dm}/lag+0s")
                    if lag0 is None:
                        continue

                    def mean_of(labels: list[str]) -> float:
                        vals = [
                            cfgs[f"{dm}/{x}"]["all"][m]["est"]
                            for x in labels
                            if f"{dm}/{x}" in cfgs
                        ]
                        return float(np.mean(vals)) if vals else float("nan")

                    shuf = [k.split("/")[-1] for k in cfgs if k.startswith(dm + "/shuffle")]
                    con = sr["contrasts_lag0_minus_control"].get(dm, {})
                    sw = [x for x in shuf if x.startswith("shuffle_window")]
                    sb = [x for x in shuf if x.startswith("shuffle_block")]
                    dw = np.mean([con[x][m]["est"] for x in sw]) if sw else float("nan")
                    db = np.mean([con[x][m]["est"] for x in sb]) if sb else float("nan")
                    rows.append(
                        f"| {enc} | {scheme} | {direction} {method} | {m} | {_fmt(lag0['all'][m])} "
                        f"| {mean_of(['lag-5s', 'lag+5s']):+.3f} | {mean_of(['lag-30s', 'lag+30s']):+.3f} "
                        f"| {mean_of(['lag-120s', 'lag+120s']):+.3f} | {mean_of(shuf):+.3f} "
                        f"| {dw:+.3f} | {db:+.3f} |"
                    )
    head = (
        "| audio encoder | split | model | metric | lag 0 [95% CI] | mean of +-5 s | mean of +-30 s "
        "| mean of +-120 s | mean of shuffles | lag 0 minus window-shuffle | lag 0 minus block-shuffle |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|"
    )
    return head + "\n" + "\n".join(rows) + "\n"


def stage_report(args: argparse.Namespace, results: dict[str, Any] | None = None) -> str:
    if results is None:
        results = json.loads((Path(args.scratch) / "results.json").read_text())
    lines: list[str] = ["### Headline (pooled over held-out folds)\n", headline(results), ""]
    for enc, er in results["encoders"].items():
        lines.append(f"### Audio encoder: {enc}\n")
        lines.append(
            f"Films: {', '.join(er['films'])}; windows per film: {er['windows_per_film']}; "
            f"video dim {er['video_dim']}, audio dim {er['audio_dim']}.\n"
        )
        for scheme, sr in er["schemes"].items():
            lines.append(f"#### Split scheme: {scheme}\n")
            cfgs = sr["configs"]
            for dm in sorted({k.rsplit("/", 1)[0] for k in cfgs}):
                direction, method = dm.split("/")
                metrics = ["r2", "corr"] if method == "ridge" else ["corr1", "corr5"]
                lines.append(f"**{direction} {method}** (pooled over folds; estimate [95% CI])\n")
                lines.append("| pairing | " + " | ".join(metrics) + " |")
                lines.append("|---|" + "---|" * len(metrics))
                for k, e in cfgs.items():
                    if not k.startswith(dm + "/"):
                        continue
                    lines.append(
                        f"| {k.split('/')[-1]} | "
                        + " | ".join(_fmt(e["all"][m]) for m in metrics)
                        + " |"
                    )
                lines.append("")
                lines.append(
                    f"Per film, lag +0 vs the shuffled and ±30 s controls ({metrics[0]}):\n"
                )
                films = er["films"]
                lines.append("| pairing | " + " | ".join(films) + " |")
                lines.append("|---|" + "---|" * len(films))
                for k, e in cfgs.items():
                    if not k.startswith(dm + "/"):
                        continue
                    lab = k.split("/")[-1]
                    if lab in ("lag+0s", "lag-30s", "lag+30s") or lab.startswith("shuffle"):
                        lines.append(
                            f"| {lab} | "
                            + " | ".join(
                                _fmt(e["per_film"][f][metrics[0]]) if f in e["per_film"] else "n/a"
                                for f in films
                            )
                            + " |"
                        )
                lines.append("")
                con = sr["contrasts_lag0_minus_control"].get(dm, {})
                if con:
                    lines.append(f"Lag 0 minus control ({metrics[0]}, paired bootstrap):\n")
                    lines.append("| control | delta |")
                    lines.append("|---|---|")
                    for lab, d in con.items():
                        lines.append(f"| {lab} | {_fmt(d[metrics[0]])} |")
                    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("stage", choices=["extract", "analyse", "report", "all"])
    p.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    p.add_argument("--scratch", default=str(DEFAULT_SCRATCH))
    p.add_argument("--report-path", default=str(DEFAULT_REPORT))
    p.add_argument("--films", nargs="*", default=None, help="substring filter on film names")
    p.add_argument("--audio-encoders", nargs="+", default=["spectral", "dasheng"])
    p.add_argument("--video-device", default="cuda:0")
    p.add_argument("--audio-device", default="cuda:0")
    p.add_argument("--gpu-free-mb", type=int, default=1024)
    p.add_argument("--force-gpu", action="store_true")
    p.add_argument("--skip-verify", action="store_true")
    p.add_argument("--recompute", action="store_true")
    p.add_argument(
        "--recompute-audio",
        action="store_true",
        help="redo the audio embeddings, keep cached video",
    )
    p.add_argument(
        "--stride", type=int, default=1, help="keep every n-th window (even subsampling)"
    )
    p.add_argument("--limit", type=int, default=None, help="first N windows per film (smoke runs)")
    p.add_argument("--schemes", nargs="+", default=["film", "block"])
    p.add_argument("--n-blocks", type=int, default=8)
    p.add_argument("--purge-s", type=float, default=4.0)
    p.add_argument("--n-boot", type=int, default=300)
    p.add_argument("--n-shuffle-seeds", type=int, default=2)
    p.add_argument("--seed", type=int, default=0)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    # Match nvidia-smi's GPU numbering and expose ONLY the 4070 (GPU 0).
    os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("KAINE_MODELS_DIR", str(DEFAULT_MODELS_DIR))
    args = build_parser().parse_args(argv)
    if args.stage in ("extract", "all"):
        stage_extract(args)
    results = None
    if args.stage in ("analyse", "all"):
        results = stage_analyse(args)
    if args.stage in ("report", "all"):
        text = stage_report(args, results)
        path = Path(args.report_path).with_suffix(".tables.md")
        path.write_text(text)
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
