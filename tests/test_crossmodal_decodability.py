# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the offline cross-modal decodability tool: alignment, the
leakage-safe splits and the statistics, on synthetic data (no model, no media)."""

import importlib.util
import sys
from pathlib import Path

import numpy as np

_PATH = Path(__file__).resolve().parents[1] / "tools" / "research" / "crossmodal_decodability.py"
_spec = importlib.util.spec_from_file_location("crossmodal_decodability", _PATH)
cm = importlib.util.module_from_spec(_spec)
sys.modules["crossmodal_decodability"] = cm
_spec.loader.exec_module(cm)


# ---------------------------------------------------------------- alignment


def test_valid_window_ends_start_after_full_context_and_stay_in_film():
    ends = cm.valid_window_ends(10.0, window_s=0.5, context_s=2.0)
    assert ends[0] == 2.0
    assert ends[-1] == 10.0
    assert np.allclose(np.diff(ends), 0.5)


def test_valid_window_ends_short_film_is_empty():
    assert cm.valid_window_ends(1.0).size == 0


def test_valid_window_ends_stride_subsamples_evenly():
    full = cm.valid_window_ends(60.0)
    sub = cm.valid_window_ends(60.0, stride=4)
    assert np.array_equal(sub, full[::4])


def test_clip_frame_indices_end_on_window_end_and_step_by_tenth_of_second():
    times = np.arange(10_000) / 25.0
    idx = cm.clip_frame_indices(np.array([4.0]), times)
    assert idx.shape == (1, 16)
    assert idx[0, -1] == 100  # frame at t = 4.0 s
    assert idx[0, 0] == 62  # 2.5 s
    steps = np.diff(idx[0])
    assert set(steps.tolist()) <= {2, 3}  # 2.5 frames per sample at 25 fps / 10 Hz


def test_clip_frame_indices_follow_real_timestamps_not_nominal_fps():
    # A variable-frame-rate file: 25 fps for the first 10 s, then 20 fps. The frame
    # shown at t = 14 s is frame 250 + 80 = 330, not frame 14 * 25 = 350.
    times = np.concatenate([np.arange(250) / 25.0, 10.0 + np.arange(400) / 20.0])
    idx = cm.clip_frame_indices(np.array([14.0]), times)
    assert idx[0, -1] == 330


def test_clip_frame_indices_clip_to_film():
    times = np.arange(100) / 25.0
    idx = cm.clip_frame_indices(np.array([1.0, 1000.0]), times)
    assert idx.min() >= 0 and idx.max() == 99


def test_audio_sample_span_is_trailing_context():
    lo, hi = cm.audio_sample_span(5.0)
    assert hi == 5 * 16000 and hi - lo == 2 * 16000
    lo, hi = cm.audio_sample_span(1.0)
    assert lo == 0 and hi == 16000


def test_shift_pairs_inside_film():
    v, a = cm.shift_pairs(10, 3)
    assert v.tolist() == list(range(0, 7)) and (a - v).tolist() == [3] * 7
    v, a = cm.shift_pairs(10, -3)
    assert v.min() == 3 and v.max() == 9 and ((a - v) == -3).all()
    v, a = cm.shift_pairs(10, 25)
    assert v.size == 0


def test_shuffles_are_permutations_within_segments():
    sizes = [400, 300]
    for mode in ("shuffle_window", "shuffle_block"):
        p = cm.build_pairs(sizes, mode, seed=1, block=20, scheme="block", n_blocks=4)
        for f, n in enumerate(sizes):
            m = p.film == f
            assert sorted(p.a[m].tolist()) == list(range(n))
            for lo, hi in cm.segment_bounds(n, "block", 4):
                inside = (p.v[m] >= lo) & (p.v[m] < hi)
                assert ((p.a[m][inside] >= lo) & (p.a[m][inside] < hi)).all()
        assert (p.a != p.v).mean() > 0.7  # alignment actually destroyed


def test_block_shuffle_keeps_local_order_inside_blocks():
    p = cm.build_pairs([200], "shuffle_block", seed=3, block=20, scheme="film")
    d = np.diff(p.a)
    assert (d == 1).mean() > 0.9


# ------------------------------------------------------------- leakage-safe


def _lag_pairs(sizes, shift=0):
    return cm.build_pairs(sizes, "shift", shift=shift)


def test_film_folds_hold_out_whole_films_and_never_train_on_them():
    sizes = [50, 60, 70]
    pairs = _lag_pairs(sizes)
    folds = cm.make_folds(sizes, "film")
    assert len(folds) == 3
    for i, fold in enumerate(folds):
        test = cm.fold_test_mask(pairs, fold)
        train = cm.purged_train_mask(test, pairs, sizes, gap=5)
        assert (pairs.film[test] == i).all() and test.sum() == sizes[i]
        assert not (train & (pairs.film == i)).any()
        assert train.sum() == sum(sizes) - sizes[i]


def test_block_folds_are_contiguous_and_cover_everything_once():
    sizes = [100, 80]
    folds = cm.make_folds(sizes, "block", n_blocks=4)
    pairs = _lag_pairs(sizes)
    total = np.zeros(len(pairs), dtype=int)
    for fold in folds:
        test = cm.fold_test_mask(pairs, fold)
        total += test
        for f in np.unique(pairs.film[test]):
            v = pairs.v[test & (pairs.film == f)]
            assert (np.diff(v) == 1).all()  # contiguous
    assert (total == 1).all()


def test_purge_removes_a_gap_either_side_of_the_test_block():
    sizes = [100]
    pairs = _lag_pairs(sizes)
    test = np.zeros(len(pairs), dtype=bool)
    test[40:60] = True
    train = cm.purged_train_mask(test, pairs, sizes, gap=5)
    kept = np.flatnonzero(train)
    assert kept[kept < 40].max() == 34
    assert kept[kept > 59].min() == 65
    assert not train[35:65].any()


def test_purge_covers_shifted_audio_footprints():
    # With a +30 window shift, a test pair (v, v+30) touches audio window v+30. A
    # training pair that uses that audio window (or its neighbourhood) is purged.
    sizes = [200]
    pairs = _lag_pairs(sizes, shift=30)
    test = (pairs.v >= 20) & (pairs.v < 40)
    train = cm.purged_train_mask(test, pairs, sizes, gap=3)
    touched = set(range(20, 40)) | set(range(50, 70))
    dil = {w + d for w in touched for d in range(-3, 4)}
    for v, a, t in zip(pairs.v, pairs.a, train):
        if t:
            assert v not in dil and a not in dil
    assert train.sum() > 0


def test_no_train_test_window_overlap_for_any_scheme_and_pairing():
    sizes = [120, 90, 60]
    gap = 4
    for scheme in ("film", "block"):
        folds = cm.make_folds(sizes, scheme, n_blocks=4)
        for pairs in (
            _lag_pairs(sizes, 0),
            _lag_pairs(sizes, 12),
            _lag_pairs(sizes, -12),
            cm.build_pairs(sizes, "shuffle_window", seed=2, scheme=scheme, n_blocks=4),
            cm.build_pairs(sizes, "shuffle_block", seed=2, block=10, scheme=scheme, n_blocks=4),
        ):
            for fold in folds:
                test = cm.fold_test_mask(pairs, fold)
                train = cm.purged_train_mask(test, pairs, sizes, gap=gap)
                assert not (train & test).any()
                for f in range(len(sizes)):
                    te = np.zeros(sizes[f], dtype=bool)
                    sel = test & (pairs.film == f)
                    te[pairs.v[sel]] = True
                    te[pairs.a[sel]] = True
                    tr = train & (pairs.film == f)
                    if not tr.any():
                        continue
                    for w in np.concatenate([pairs.v[tr], pairs.a[tr]]):
                        lo, hi = max(0, w - gap), min(sizes[f], w + gap + 1)
                        assert not te[lo:hi].any(), (scheme, f, w)


def test_inner_blocks_partition_rows():
    ms = cm.inner_blocks(103, 4)
    assert (np.sum(ms, axis=0) == 1).all()


# --------------------------------------------------------------- statistics


def _planted_films(coupled=True, seed=0, sizes=(400, 300, 350), dv=12, da=6):
    rng = np.random.default_rng(seed)
    films = []
    w = rng.normal(size=(dv, da))
    for i, n in enumerate(sizes):
        z = np.cumsum(rng.normal(size=(n, dv)), axis=0)
        z = (z - z.mean(0)) / (z.std(0) + 1e-9)
        v = z + 0.3 * rng.normal(size=z.shape)
        a = z @ w + 0.5 * rng.normal(size=(n, da)) if coupled else rng.normal(size=(n, da))
        films.append(
            cm.FilmEmbeddings(
                f"f{i}", np.arange(n) * 0.5 + 2.0, v.astype(np.float32), a.astype(np.float32)
            )
        )
    return films


def _run(films, cfg, scheme="film", gap=5, n_blocks=4):
    sizes = [len(f.t_end) for f in films]
    folds = cm.make_folds(sizes, scheme, n_blocks)
    units = cm.run_config(
        films, cfg, folds, gap=gap, unit_len=20, block_windows=20, n_blocks=n_blocks
    )
    uni = cm.universe_keys(sizes, folds, 20)
    counts = cm.stratified_counts(uni, 60, np.random.default_rng(0))
    return cm.aggregate(cfg.method, units, cm.counts_for(units, uni, counts))


def test_planted_coupling_is_recovered_and_shift_and_shuffle_controls_fail():
    films = _planted_films(coupled=True)
    lag0 = _run(films, cm.Config("film", "v2a", "ridge", "lag"))
    assert lag0["r2"][0] > 0.3 and lag0["corr"][0] > 0.5
    shifted = _run(films, cm.Config("film", "v2a", "ridge", "lag", shift=120, shift_s=60))
    assert shifted["r2"][0] < 0.1
    shuf = _run(films, cm.Config("film", "v2a", "ridge", "shuffle_window"))
    assert shuf["r2"][0] < 0.05
    blk = _run(films, cm.Config("film", "v2a", "ridge", "shuffle_block"))
    assert blk["r2"][0] < 0.1


def test_reverse_direction_and_block_scheme_work():
    films = _planted_films(coupled=True)
    a2v = _run(films, cm.Config("block", "a2v", "ridge", "lag"), scheme="block")
    assert a2v["r2"][0] > 0.1


def test_uncoupled_streams_have_no_held_out_signal():
    films = _planted_films(coupled=False, seed=3)
    r = _run(films, cm.Config("film", "v2a", "ridge", "lag"))
    assert r["r2"][0] < 0.03
    c = _run(films, cm.Config("film", "v2a", "cca", "lag"))
    assert c["corr1"][0] < 0.25


def test_cca_recovers_planted_coupling_out_of_sample():
    films = _planted_films(coupled=True)
    c = _run(films, cm.Config("film", "v2a", "cca", "lag"))
    assert c["corr1"][0] > 0.6


def test_bootstrap_interval_contains_point_and_per_film_restricts_units():
    films = _planted_films(coupled=True)
    sizes = [len(f.t_end) for f in films]
    folds = cm.make_folds(sizes, "film")
    cfg = cm.Config("film", "v2a", "ridge", "lag")
    units = cm.run_config(films, cfg, folds, gap=5, unit_len=20, block_windows=20)
    uni = cm.universe_keys(sizes, folds, 20)
    counts = cm.stratified_counts(uni, 100, np.random.default_rng(1))
    cnt = cm.counts_for(units, uni, counts)
    agg = cm.aggregate("ridge", units, cnt)
    s = cm.summarise(agg["r2"])
    assert s["lo"] <= s["est"] <= s["hi"]
    pf = cm.aggregate("ridge", units, cnt, films=[0])
    assert pf["r2"].shape == agg["r2"].shape
    assert pf["r2"][0] != agg["r2"][0]


def test_stratified_counts_keep_group_sizes():
    keys = [(0, i, 0) for i in range(7)] + [(1, i, 0) for i in range(5)]
    c = cm.stratified_counts(keys, 20, np.random.default_rng(0))
    assert (c[0] == 1).all()
    assert np.allclose(c[1:, :7].sum(axis=1), 7) and np.allclose(c[1:, 7:].sum(axis=1), 5)


def test_pearson_from_sums_matches_numpy():
    rng = np.random.default_rng(0)
    a, b = rng.normal(size=(50, 3)), rng.normal(size=(50, 3))
    r = cm._pearson_from_sums(
        np.array([[50.0]]), a.sum(0), b.sum(0), (a * a).sum(0), (b * b).sum(0), (a * b).sum(0)
    )
    ref = [np.corrcoef(a[:, i], b[:, i])[0, 1] for i in range(3)]
    assert np.allclose(r, ref)


def test_accumulate_units_sums_per_unit():
    keys = [(0, 0, 0)] * 3 + [(0, 1, 0)] * 2
    ch = [np.arange(10, dtype=float).reshape(5, 2)]
    u = cm.accumulate_units(keys, ch)
    assert u.n.tolist() == [3, 2]
    assert np.allclose(u.stats[0, 0], [0 + 2 + 4, 1 + 3 + 5])
    assert np.allclose(u.stats[1, 0], [6 + 8, 7 + 9])


def test_select_alpha_gram_shortcut_matches_brute_force_inner_cv():
    films = _planted_films(coupled=True, seed=5, sizes=(300, 260), dv=10, da=4)
    sizes = [len(f.t_end) for f in films]
    pairs = cm.build_pairs(sizes, "shift", shift=0)
    x, y = cm._gather(films, pairs, "v2a")
    chosen = cm.select_alpha(x, y, pairs, sizes, gap=4)

    # brute force, z-scoring with the outer-train statistics as the shortcut does
    xmu, xsd = cm._zstats(x)
    ymu, ysd = cm._zstats(y)
    xz, yz = (x - xmu) / xsd, (y - ymu) / ysd
    order = np.lexsort((pairs.v, pairs.film))
    err = np.zeros(len(cm.ALPHAS))
    for tm in cm.inner_blocks(len(order), 4):
        tmask = np.zeros(len(pairs), dtype=bool)
        tmask[order[tm]] = True
        keep = cm.purged_train_mask(tmask, pairs, sizes, 4)
        g = xz[keep].T @ xz[keep] / keep.sum()
        b = xz[keep].T @ yz[keep] / keep.sum()
        for i, a in enumerate(cm.ALPHAS):
            w = np.linalg.solve(g + a * np.trace(g) / g.shape[0] * np.eye(g.shape[0]), b)
            err[i] += ((yz[tmask] - xz[tmask] @ w) ** 2).sum()
    assert chosen == cm.ALPHAS[int(np.argmin(err))]
