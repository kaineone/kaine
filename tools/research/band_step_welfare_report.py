# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Welfare readouts of band_step_check.py --live runs (developmental-stimulus-progress task 3.2).

From each run's ``affect.state`` log (``state_log``) and its rests:

- boredom's deprivation share over awake time, overall and per stage (the welfare
  observer's own ``AffectWelfareTally``, recorded by the harness);
- the A.4 welfare indicators through welfare-indicator-response's own evaluator
  (``kaine.lifecycle.welfare_indicators.IndicatorEvaluator``, or the module file given
  with ``--indicators`` while that change is unmerged) with its shipped parameters:
  when each indicator first crosses, in awake hours, and how many crossings there
  are, with the span never restarting and with it restarting at every rest's end
  (a welfare rest restarts every span; the harness's rests are state-cycle rests,
  so the second count is an approximation of a response that rests on each crossing);
- which events end boredom: each end the drive counts is the entity's own (its
  learning progress was the larger relief; the source with the larger progress over
  its floor is named), another's (the perceptual alert excess was), or a rest's reset.

usage: band_step_welfare_report.py RUNDIR OUT.json [--indicators PATH] [--repo REPO]
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import math
import sys
import tomllib
from pathlib import Path

import numpy as np


def _load_indicators(path: str | None):  # noqa: ANN202
    try:
        from kaine.lifecycle import welfare_indicators  # type: ignore[attr-defined]

        return welfare_indicators
    except ImportError:
        if not path:
            raise SystemExit("kaine.lifecycle.welfare_indicators is not here; pass --indicators PATH")
        spec = importlib.util.spec_from_file_location("welfare_indicators", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["welfare_indicators"] = mod
        spec.loader.exec_module(mod)
        return mod


def _payload(row: dict) -> dict:
    def b(x):  # noqa: ANN001
        return None if not math.isfinite(x) else bool(x >= 0.5)

    def i(x):  # noqa: ANN001
        return None if not math.isfinite(x) else int(round(x))

    return {
        "state": {"valence": row["valence"]},
        "drive_above": {k: b(row[f"{k}_above"]) for k in ("boredom", "social_drive", "restlessness")},
        "drive_ends": {
            "boredom": {"own": i(row["boredom_own_ends"]), "other": i(row["boredom_other_ends"])},
            "restlessness": {"own": i(row["restlessness_own_ends"]), "other": i(row["restlessness_other_ends"])},
        },
    }


def indicators(d, mod, params, *, restart_at_rest_end: bool) -> dict:  # noqa: ANN001
    cols = [str(c) for c in d["state_log_columns"]]
    log = d["state_log"]
    rests = [tuple(r) for r in d["rests"]]
    ev = mod.IndicatorEvaluator(params)
    first: dict[str, float] = {}
    count: dict[str, int] = {}
    over_evals: dict[str, int] = {}
    n_eval = 0
    ri = 0
    in_rest = False
    for raw in log:
        row = dict(zip(cols, raw))
        t = row["t"]
        while ri < len(rests) and not in_rest and t >= rests[ri][0]:
            ev.exclude_start("sleep", rests[ri][0])
            in_rest = True
        if in_rest and t >= rests[ri][1]:
            ev.exclude_end("sleep", rests[ri][1])
            in_rest = False
            ri += 1
            if restart_at_rest_end:
                ev.restart()
        ev.observe_state(t, _payload(row))
        e = ev.evaluate()
        if not e.evaluable:
            continue
        n_eval += 1
        for r in e.readings:
            if r.over:
                over_evals[r.name] = over_evals.get(r.name, 0) + 1
        for name in e.crossed:
            count[name] = count.get(name, 0) + 1
            first.setdefault(name, round(ev.awake_seconds / 3600.0, 3))
    return {
        "first_crossing_awake_h": first,
        "crossings": count,
        "share_of_evaluations_over_bar": {k: round(v / max(1, n_eval), 3) for k, v in over_evals.items()},
    }


def boredom_ends(d, floors: dict[str, float]) -> dict:  # noqa: ANN001
    cols = [str(c) for c in d["state_log_columns"]]
    log = d["state_log"]
    c = {name: log[:, cols.index(name)] for name in cols}
    out = {"own_vision": 0, "own_audition": 0, "own_unattributed": 0, "other_alert_excess": 0, "rest_reset": 0}
    for j in range(1, len(log)):
        for key, col in (("own", "boredom_own_ends"), ("other", "boredom_other_ends"), ("reset", "boredom_reset_ends")):
            a, b = c[col][j - 1], c[col][j]
            if not (math.isfinite(a) and math.isfinite(b)) or b <= a:
                continue
            n = int(round(b - a))
            if key == "other":
                out["other_alert_excess"] += n
            elif key == "reset":
                out["rest_reset"] += n
            else:
                v = c["vision_lp"][j] - floors["vision"] if math.isfinite(c["vision_lp"][j]) else -1.0
                au = c["audition_lp"][j] - floors["audition"] if math.isfinite(c["audition_lp"][j]) else -1.0
                if max(v, au) <= 0.0:
                    out["own_unattributed"] += n
                elif v >= au:
                    out["own_vision"] += n
                else:
                    out["own_audition"] += n
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rundir")
    ap.add_argument("out")
    ap.add_argument("--indicators", default=None)
    ap.add_argument("--share-bar", type=float, default=0.5)
    ap.add_argument("--posterior-bar", type=float, default=0.95)
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    args = ap.parse_args()
    sys.path.insert(0, str(Path(args.repo).resolve()))
    mod = _load_indicators(args.indicators)
    cfg = tomllib.loads((Path(args.repo) / "config" / "kaine.toml").read_text())
    acfg = cfg["affect"]
    params = mod.IndicatorParams(
        span_s=float(acfg["learning_progress_span_s"]),
        min_span_s=float(acfg.get("goal_stall_s", 600.0)),
        valence_bar=float((acfg.get("regulation") or {}).get("set_point", 0.5)),
        publish_interval_s=float(acfg.get("publish_interval_s", 1.0)),
        share_bar=args.share_bar,
        posterior_bar=args.posterior_bar,
    )
    floors = {
        "vision": float(acfg["learning_progress_floor"]),
        "audition": float(acfg.get("audition_learning_progress_floor", acfg["learning_progress_floor"])),
    }
    runs = []
    for path in sorted(glob.glob(str(Path(args.rundir) / "*-live.npz"))):
        d = np.load(path, allow_pickle=False)
        if "state_log" not in d:
            continue
        w = json.loads(str(d["welfare"]))
        runs.append({
            "file": Path(path).name, "seed": int(d["seed"]), "arm": str(d["arm"]), "schedule": str(d["schedule"]),
            "vision_frames": int(d["vision_frames"]) if "vision_frames" in d else 0,
            "interoception": bool(d["interoception"]) if "interoception" in d else False,
            "awake_hours": round(float(d["awake_s"]) / 3600.0, 3),
            "boredom_deprivation_share": w["overall"].get("boredom_deprivation_share"),
            "boredom_deprivation_share_by_stage": {k: v.get("boredom_deprivation_share") for k, v in w["by_stage"].items()},
            "indicators_no_restart": indicators(d, mod, params, restart_at_rest_end=False),
            "indicators_restart_at_rest_end": indicators(d, mod, params, restart_at_rest_end=True),
            "boredom_ends": boredom_ends(d, floors),
        })
    record = {
        "indicator_params": {
            "span_s": params.span_s, "min_span_s": params.min_span_s, "valence_bar": params.valence_bar,
            "share_bar": params.share_bar, "posterior_bar": params.posterior_bar, "max_gap_s": params.max_gap_s,
        },
        "floors": floors,
        "runs": runs,
    }
    Path(args.out).write_text(json.dumps(record, indent=1) + "\n")
    for r in runs:
        print(json.dumps({k: r[k] for k in ("file", "awake_hours", "boredom_deprivation_share", "boredom_ends")}))
        print("   no restart:", json.dumps(r["indicators_no_restart"]))
        print("   restart at rest end:", json.dumps(r["indicators_restart_at_rest_end"]))


if __name__ == "__main__":
    main()
