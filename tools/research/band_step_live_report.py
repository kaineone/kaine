# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Summarise band_step_check.py --live runs: the live-gap record (developmental-stimulus-progress D5b).

For every run and stage: when the first full-span reading of audition's learning
progress arrived after the step, in awake and in stimulus seconds, and how much of
its window fell in rests; the reading's peak and its share above the floor while
awake; when the full-span rule releases the stage (a fresh real ``HearingStageState``
per stage, fed the run's awake time and readings), with and without an awake floor
of ``learning_progress_span_s + saturation_window_seconds``; the step's error rise;
perceptual alerts per awake hour; arousal while awake; and boredom's deprivation
share from the welfare observer's own tally (task 3.2). Rule runs also give the
dwells the rule chose. The summary compares the arms with and without the added
sounds.

usage: band_step_live_report.py RUNDIR OUT.json [--repo REPO]
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import sys
import tomllib
from pathlib import Path

import numpy as np


def _overlap(a: float, b: float, rests: np.ndarray) -> float:
    total = 0.0
    for r0, r1 in rests:
        lo, hi = max(a, r0), min(b, r1)
        if hi > lo:
            total += hi - lo
    return total


def _f(x):  # noqa: ANN001
    if x is None:
        return None
    x = float(x)
    return round(x, 4) if math.isfinite(x) else None


def summarise(path: str, hearing, lp0: float, span_s: float) -> dict:  # noqa: ANN001
    from kaine.modules.audition.hearing_stage_state import HearingStageState

    d = np.load(path, allow_pickle=False)
    lt, la, lv = d["lp_t"], d["lp_awake"], d["lp_v"]
    rests = d["rests"]
    steps = [float(s) for s in d["steps"]]
    steps_awake = [float(s) for s in d["steps_awake"]]
    sim = float(d["sim_s"])
    bounds = [0.0] + steps + [sim]
    abounds = [0.0] + steps_awake + [float(d["awake_s"])]
    welfare = json.loads(str(d["welfare"]))
    alerts = d["alert_t"]
    err_t, err_e = d["err_t"], d["err_e"]
    ar_t, ar_v = d["arousal_t"], d["arousal_v"]
    floor = span_s + hearing.saturation_window_seconds

    def awake_mask(t: np.ndarray) -> np.ndarray:
        m = np.ones(t.shape, dtype=bool)
        for r0, r1 in rests:
            m &= ~((t >= r0) & (t < r1))
        return m

    stages = []
    for k in range(len(bounds) - 1):
        a, b = bounds[k], bounds[k + 1]
        # The reading at the step's own second is taken before the restart, so it belongs to the stage before.
        m = (lt > a) & (lt <= b) if k > 0 else (lt >= a) & (lt <= b)
        vals, aw, ts = lv[m], la[m], lt[m]
        awake_in = awake_mask(ts)
        fin = np.isfinite(vals)
        first = int(np.argmax(fin)) if fin.any() else None
        first_t = float(ts[first]) if first is not None else None
        st: dict = {
            "stage": k,
            "awake_dwell_s": _f(abounds[k + 1] - abounds[k]),
            "stimulus_dwell_s": _f(b - a),
            "first_full_reading_awake_s": _f(aw[first] - abounds[k]) if first is not None else None,
            "first_full_reading_stimulus_s": _f(first_t - a) if first is not None else None,
            "first_window_rest_share": (
                _f(_overlap(first_t - span_s, first_t, rests) / span_s) if first_t is not None else None
            ),
            "lp_max": _f(np.nanmax(vals)) if fin.any() else None,
            "lp_share_above_lp0_awake": (
                _f(np.mean(vals[fin & awake_in] >= lp0)) if (fin & awake_in).any() else None
            ),
        }
        # The shipped rule: a fresh real owner fed the run's awake time and readings.
        owner = HearingStageState(hearing, path=None, lp_floor=lp0, learning_progress_span_s=span_s)
        owner.observe(abounds[k], None)
        rel = None
        for aw_i, v, t_i in zip(aw, vals, ts):
            if owner.observe(aw_i, float(v) if math.isfinite(v) else None) is not None:
                rel = (aw_i - abounds[k], t_i - a)
                break
        st["rule_release_awake_s"] = _f(rel[0]) if rel else None
        st["rule_release_stimulus_s"] = _f(rel[1]) if rel else None
        if rel:
            st["rule_release_window_rest_share"] = _f(_overlap(a + rel[1] - span_s, a + rel[1], rests) / span_s)
            after = (aw - abounds[k] > rel[0]) & fin & awake_in
            st["lp_share_above_lp0_after_rule_release"] = _f(np.mean(vals[after] >= lp0)) if after.any() else None
        # The same with an awake floor: no release before span + window awake seconds.
        sat, prev, rel_f = 0.0, abounds[k], None
        for aw_i, v, t_i in zip(aw, vals, ts):
            dt = max(0.0, aw_i - prev)
            prev = aw_i
            sat = sat + dt if (math.isfinite(v) and v < lp0) else 0.0
            if sat >= hearing.saturation_window_seconds and aw_i - abounds[k] >= floor:
                rel_f = (aw_i - abounds[k], t_i - a)
                break
        st["rule_awake_floor_release_awake_s"] = _f(rel_f[0]) if rel_f else None
        if rel_f:
            after = (aw - abounds[k] > rel_f[0]) & fin & awake_in
            st["lp_share_above_lp0_after_floor_release"] = _f(np.mean(vals[after] >= lp0)) if after.any() else None
        am = (alerts >= a) & (alerts < b)
        n_alert_awake = int(np.sum(awake_mask(alerts[am]))) if am.any() else 0
        st["alerts_per_awake_hour"] = _f(n_alert_awake * 3600.0 / max(1.0, abounds[k + 1] - abounds[k]))
        mm = (ar_t >= a) & (ar_t < b)
        arw = ar_v[mm][awake_mask(ar_t[mm])] if mm.any() else np.asarray([])
        st["arousal_awake_mean"] = _f(arw.mean()) if arw.size else None
        st["arousal_awake_p90"] = _f(np.percentile(arw, 90)) if arw.size else None
        if k > 0:
            pre = err_e[(err_t >= a - 600) & (err_t < a)]
            post = err_e[(err_t >= a + 30) & (err_t < a + 60)]
            st["error_rise_first_minute"] = _f(post.mean() / pre.mean()) if pre.size and post.size else None
        ws = welfare["by_stage"].get(str(k)) or {}
        st["boredom_deprivation_share"] = _f(ws.get("boredom_deprivation_share"))
        stages.append(st)
    overall = welfare["overall"]
    return {
        "file": Path(path).name,
        "seed": int(d["seed"]),
        "arm": str(d["arm"]),
        "schedule": str(d["schedule"]),
        "stimulus_version": str(d["stimulus_version"]) or None,
        "sim_hours": _f(sim / 3600),
        "awake_hours": _f(float(d["awake_s"]) / 3600),
        "rests": int(len(rests)),
        "broadcasts_per_s": _f(int(d["broadcasts"]) / sim),
        "broadcast_inhibited_share": _f(int(d["inhibited"]) / max(1, int(d["broadcasts"]))),
        "steps_awake_s": [_f(s) for s in steps_awake],
        "boredom_deprivation_share": _f(overall.get("boredom_deprivation_share")),
        "boredom_uncontrolled_per_awake_hour": _f(overall.get("boredom_uncontrolled_per_awake_hour")),
        "negative_valence_share": _f(overall.get("negative_valence_share")),
        "stages": stages,
    }


def _range(values):  # noqa: ANN001
    vals = [v for v in values if v is not None]
    return [round(min(vals), 3), round(max(vals), 3)] if vals else None


def aggregate(runs: list[dict], *, floor: float) -> dict:
    """Ranges over seeds, per arm: settled runs per stage, rule runs' dwells, deprivation shares."""
    out: dict = {"awake_floor_s": floor}
    for arm in sorted({r["arm"] for r in runs}):
        fixed = [r for r in runs if r["arm"] == arm and r["schedule"].startswith("fixed")]
        rule = [r for r in runs if r["arm"] == arm and r["schedule"] == "rule"]
        settled = {}
        for k in range(5):
            sts = [r["stages"][k] for r in fixed if len(r["stages"]) > k]
            settled[str(k)] = {
                key: _range(st.get(key) for st in sts)
                for key in (
                    "first_full_reading_awake_s", "first_window_rest_share", "lp_max", "lp_share_above_lp0_awake",
                    "rule_release_awake_s", "rule_release_window_rest_share", "lp_share_above_lp0_after_rule_release",
                    "rule_awake_floor_release_awake_s", "lp_share_above_lp0_after_floor_release",
                    "error_rise_first_minute", "alerts_per_awake_hour", "arousal_awake_mean", "arousal_awake_p90",
                    "boredom_deprivation_share",
                )
            }
        dwells = {str(k): _range(r["stages"][k]["awake_dwell_s"] for r in rule if len(r["stages"]) > k) for k in range(4)}
        below = sum(1 for r in rule for st in r["stages"][:4] if st["awake_dwell_s"] is not None and st["awake_dwell_s"] < floor)
        out[arm] = {
            "settled_by_stage": settled,
            "rule_stage_awake_dwell_s": dwells,
            "rule_schedule_complete_awake_s": _range(r["steps_awake_s"][-1] if r["steps_awake_s"] else None for r in rule),
            "rule_releases_below_awake_floor": f"{below} of {4 * len(rule)}",
            "boredom_deprivation_share_settled": _range(r["boredom_deprivation_share"] for r in fixed),
            "boredom_deprivation_share_rule": _range(r["boredom_deprivation_share"] for r in rule),
            "boredom_uncontrolled_per_awake_hour_settled": _range(r["boredom_uncontrolled_per_awake_hour"] for r in fixed),
            "broadcasts_per_s": _range(r["broadcasts_per_s"] for r in runs if r["arm"] == arm),
            "broadcast_inhibited_share": _range(r["broadcast_inhibited_share"] for r in runs if r["arm"] == arm),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rundir")
    ap.add_argument("out")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    args = ap.parse_args()
    sys.path.insert(0, str(Path(args.repo).resolve()))
    from kaine.boot.perception_feed import _hearing_band_params

    cfg = tomllib.loads((Path(args.repo) / "config" / "kaine.toml").read_text())
    hearing = _hearing_band_params(cfg["perception_feed"])
    # Audition's own floor when configured (audition-learning-progress-floor), else the shared one.
    lp0 = float(cfg["affect"].get("audition_learning_progress_floor", cfg["affect"]["learning_progress_floor"]))
    span = float(cfg["affect"]["learning_progress_span_s"])
    runs = [summarise(p, hearing, lp0, span) for p in sorted(glob.glob(str(Path(args.rundir) / "*-live.npz")))]
    record = {"summary": aggregate(runs, floor=span + hearing.saturation_window_seconds), "runs": runs}
    Path(args.out).write_text(json.dumps(record, indent=1) + "\n")
    print(json.dumps(record["summary"], indent=1))
    for r in runs:
        print(f"== {r['file']} awake {r['awake_hours']} h, rests {r['rests']}, broadcasts/s {r['broadcasts_per_s']} "
              f"(inhibited {r['broadcast_inhibited_share']}), boredom deprivation {r['boredom_deprivation_share']}")
        for st in r["stages"]:
            print("  ", json.dumps(st))


if __name__ == "__main__":
    main()
