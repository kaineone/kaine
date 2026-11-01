# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Summarise band_step_check.py runs: per step, the stimulus's spectral change, the
embedding shift, the forward-model error before and after, the learning-progress
trace, and whether the estimator's window can see the transient.

usage: band_step_report.py RUNDIR OUT.json [--repo REPO]

The estimator replays use the real ``WindowedProgress`` on the published error
trace with the affect module's restart at each step; the 60 s replay must equal
the affect module's own reading (a fault check), and the shorter-bin replays are
the candidate fixes of design D4 H2.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import sys
from pathlib import Path

import numpy as np

NEW_REGION = {1: [1], 2: [0], 3: [3], 4: [4, 5]}  # region indices each step opens
REGION_NAMES = ["<158", "158-354", "354-707", "707-1732", "1732-3000", ">3000"]
AFTER_WINDOWS = [(0, 0.5), (0.5, 1), (1, 2), (2, 5), (5, 10), (10, 30), (30, 60), (60, 120)]  # minutes
ANCHORED_L = [20, 40, 60, 120, 240, 600, 1800, 5400]  # seconds


def _mean(x):
    return float(np.mean(x)) if len(x) else float("nan")


def replay(WindowedProgress, t, e, steps, bin_s, max_bins):
    """Replay the affect module's per-source estimator in the harness's event order.

    After each report the harness reads every whole second up to the report's
    time, then applies a step due at that second, which drops the window; the
    next report starts a fresh one (the affect module's restart).
    """
    w = None
    out_t, out_v = [], []
    tick, si = 1.0, 0
    for ti, ei in zip(t, e):
        if w is None:
            w = WindowedProgress(bin_s, max_bins)
        w.add(float(ti), float(ei))
        if not w.started:
            w = None
        while tick <= ti:
            v = None if w is None else w.value(tick)
            out_t.append(tick)
            out_v.append(np.nan if v is None else v)
            if si < len(steps) and tick >= steps[si]:
                w = None
                si += 1
            tick += 1.0
    return np.asarray(out_t), np.asarray(out_v)


def saturation_times(lt, lv, s, end, lp0, w_sat, d_min):
    """First time after step s at which lp stayed below lp0 for w_sat (missing = unsaturated), without and with d_min."""
    m = (lt > s) & (lt <= end)
    run = 0.0
    no_min = with_min = None
    prev = s
    for tt, v in zip(lt[m], lv[m]):
        dt = tt - prev
        prev = tt
        run = run + dt if (np.isfinite(v) and v < lp0) else 0.0
        if no_min is None and run >= w_sat:
            no_min = tt - s
        if with_min is None and run >= w_sat and tt - s >= d_min:
            with_min = tt - s
        if no_min is not None and with_min is not None:
            break
    return no_min, with_min


def analyse(path: str, WindowedProgress) -> dict:
    d = np.load(path)
    t, e = d["err_t"], d["err_e"]
    lt, lv, ls = d["lp_t"], d["lp_v"], d["lp_stage"]
    steps = list(d["steps"])
    lp0, w_sat, d_min, bin_s, span_s = (float(d[k]) for k in ("lp0", "w_sat", "d_min", "bin_s", "span_s"))
    sim = float(d["sim_s"])
    reg = d["reg"] / np.maximum(1, d["reg_n"])[:, None]
    emb_mu = d["emb"] / np.maximum(1, d["emb_n"])[:, None]
    run = {
        "file": Path(path).name, "seed": int(d["seed"]), "arm": str(d["arm"]), "schedule": str(d["schedule"]),
        "sim_hours": sim / 3600, "wall_s": float(d["wall_s"]), "steps_s": steps, "n_reports": int(len(e)),
        "voice_slot_share": len(d["voice_slots"]) / max(1, int(sim // 30)),
        "melody_slots": int(len(d["melody_slots"])), "outside_proxy_slots": int(len(d["outside_slots"])),
        # Runs of the shipped arm name the stimulus version they measured; the others measured none.
        "stimulus_version": (str(d["stimulus_version"]) or None) if "stimulus_version" in d else None,
        "d_min_s": d_min,
    }
    if run["arm"] == "shipped":
        run["outside_voice_slots"] = run.pop("outside_proxy_slots")
    # Fault check: the 60 s replay equals the affect module's own reading.
    rt, rv = replay(WindowedProgress, t, e, steps, bin_s, int(span_s / bin_s))
    n = min(len(rv), len(lv))
    both = np.isfinite(rv[:n]) & np.isfinite(lv[:n])
    run["replay_matches_affect"] = bool(
        np.array_equal(np.isfinite(rv[:n]), np.isfinite(lv[:n])) and np.allclose(rv[:n][both], lv[:n][both], atol=1e-9)
    )
    alt = {
        "bins10s_2min": replay(WindowedProgress, t, e, steps, 10.0, 12),
        "bins10s_span": replay(WindowedProgress, t, e, steps, 10.0, int(span_s / 10.0)),
    }
    bounds = [0.0] + steps + [sim]
    stages = []
    for k in range(len(bounds) - 1):
        a, b = bounds[k], bounds[k + 1]
        st: dict = {"stage": k, "start_s": a, "end_s": b}
        m = ls == k
        vals = lv[m]
        fin = vals[np.isfinite(vals)]
        st["lp_first_reading_s"] = float(lt[m][np.isfinite(vals)][0] - a) if fin.size else None
        st["lp_max"] = float(fin.max()) if fin.size else None
        st["lp_share_above_lp0"] = float(np.mean(fin > lp0)) if fin.size else None
        above = lt[m][np.isfinite(vals) & (vals > lp0)] - a
        st["lp_above_lp0_first_last_s"] = [float(above[0]), float(above[-1])] if above.size else None
        st["lp_trace_10min"] = [None if not np.isfinite(v) else round(float(v), 4) for v in vals[::600]]
        no_min, with_min = saturation_times(lt, lv, a, b, lp0, w_sat, d_min)
        st["saturation_no_min_dwell_s"] = no_min
        st["saturation_shipped_rule_s"] = with_min
        for name, (at, av) in alt.items():
            mm = (at > a) & (at <= b)
            f2 = av[mm][np.isfinite(av[mm])]
            st[f"{name}_max"] = float(f2.max()) if f2.size else None
            ab = at[mm][np.isfinite(av[mm]) & (av[mm] > lp0)] - a
            st[f"{name}_above_lp0_s"] = [float(ab[0]), float(ab[-1]), int(ab.size)] if ab.size else None
        st["err_mean_last10min"] = _mean(e[(t > b - 600) & (t <= b)])
        st["err_mean_first10min"] = _mean(e[(t > a) & (t <= a + 600)])
        mi0, mi1 = int(a // 60), int(b // 60)
        st["region_power_db"] = [float(10 * np.log10(np.mean(reg[mi0:mi1, j]) + 1e-30)) for j in range(6)]
        stages.append(st)
    run["stages"] = stages
    step_rows = []
    for i, s in enumerate(steps, start=1):
        row: dict = {"step": i, "t_s": s}
        pre = e[(t > s - 600) & (t <= s)]
        pre_m = _mean(pre)
        row["err_pre10min"] = pre_m
        row["err_pre10min_sd_of_1min_means"] = float(np.std([_mean(e[(t > s - 600 + 60 * j) & (t <= s - 540 + 60 * j)]) for j in range(10)]))
        for lo, hi in AFTER_WINDOWS:
            v = _mean(e[(t > s + 60 * lo) & (t <= s + 60 * hi)])
            row[f"err_{lo}-{hi}min_rel"] = v / pre_m - 1.0 if pre_m > 0 else None
        # Recovery: 60 s rolling mean of the excess back under half its first-minute value.
        first = _mean(e[(t > s) & (t <= s + 60)]) - pre_m
        row["excess_first_min"] = first
        rec = None
        if first > 0:
            for j in range(1, 240):
                v = _mean(e[(t > s + 30 * j) & (t <= s + 30 * j + 60)]) - pre_m
                if v <= first / 2:
                    rec = 30 * j
                    break
        row["excess_half_recovery_s"] = rec
        # Anchored windows from the step: relative fall from first to second half.
        anch = {}
        for L in ANCHORED_L:
            o = _mean(e[(t > s) & (t <= s + L / 2)])
            nn = _mean(e[(t > s + L / 2) & (t <= s + L)])
            anch[str(L)] = 1 - nn / o if o > 0 else None
        row["anchored_relative_fall"] = anch
        # Stimulus spectral change, 10 min either side.
        mi = int(s // 60)
        before, after = reg[max(0, mi - 10):mi].mean(axis=0), reg[mi:mi + 10].mean(axis=0)
        row["total_power_change_db"] = float(10 * np.log10(after.sum() / before.sum()))
        newr = NEW_REGION[i]
        row["new_region"] = [REGION_NAMES[j] for j in newr]
        row["new_region_power_change_db"] = float(10 * np.log10(after[newr].sum() / max(1e-30, before[newr].sum())))
        row["new_region_share_after"] = float(after[newr].sum() / after.sum())
        mb, ma = emb_mu[max(0, mi - 10):mi].mean(axis=0), emb_mu[mi:mi + 10].mean(axis=0)
        spread = math.sqrt(max(0.0, 1.0 - float(mb @ mb)))
        row["embedding_shift"] = float(np.linalg.norm(ma - mb))
        row["embedding_within_spread"] = spread
        step_rows.append(row)
    run["steps"] = step_rows
    al = d["alert_t"]
    run["alerts_per_hour_by_stage"] = [len(al[(al > a) & (al <= b)]) / max(1e-9, (b - a) / 3600) for a, b in zip(bounds[:-1], bounds[1:])]
    return run


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("rundir")
    ap.add_argument("out")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    args = ap.parse_args()
    sys.path.insert(0, args.repo)
    from kaine.modules.affect.learning_progress import WindowedProgress

    runs = [analyse(p, WindowedProgress) for p in sorted(glob.glob(f"{args.rundir}/*.npz"))]
    Path(args.out).write_text(json.dumps(runs, indent=1, default=lambda o: None if isinstance(o, float) and not math.isfinite(o) else float(o)))
    for r in runs:
        print(f"== {r['file']} steps={[round(s / 3600, 2) for s in r['steps_s']]} replay_ok={r['replay_matches_affect']} alerts/h={[round(x) for x in r['alerts_per_hour_by_stage']]}")
        for st in r["stages"]:
            print(f"  stage {st['stage']}: lp max {st['lp_max']} share>lp0 {st['lp_share_above_lp0']} first {st['lp_first_reading_s']} sat(no min) {st['saturation_no_min_dwell_s']} sat(rule) {st['saturation_shipped_rule_s']} | 10s/2min max {st['bins10s_2min_max']} {st['bins10s_2min_above_lp0_s']} | err first10 {st['err_mean_first10min']:.4f} last10 {st['err_mean_last10min']:.4f}")
        for row in r["steps"]:
            rel = {k[4:-8]: round(v, 4) for k, v in row.items() if k.startswith("err_") and k.endswith("_rel") and v is not None}
            print(f"  step {row['step']}: dP_new {row['new_region_power_change_db']:.1f} dB share {row['new_region_share_after']:.3f} dP_tot {row['total_power_change_db']:.2f} dB | emb shift {row['embedding_shift']:.4f} spread {row['embedding_within_spread']:.4f} | pre {row['err_pre10min']:.4f} +- {row['err_pre10min_sd_of_1min_means']:.4f} rel {rel} half-rec {row['excess_half_recovery_s']} | anchored {({k: round(v, 3) for k, v in row['anchored_relative_fall'].items() if v is not None})}")


if __name__ == "__main__":
    main()
