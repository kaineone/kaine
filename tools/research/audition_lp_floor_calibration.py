# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Calibrate audition's learning-progress floor on its own noise (audition-learning-progress-floor).

Inputs are ``band_step_check.py --live`` runs on the settled schedule (5 awake hours a
stage), under live conditions: the affect module's arousal, the developmental rests
and broadcast context, with the hearing-stage reading on awake bins.

- The null: a learning audition forward model in the stages with nothing left to learn,
  stages 3 and 4 (the band-step record: the new band carries 0.2 to 7% of the power and
  the error does not rise). Its full-span readings there are the measure's noise for a
  model that keeps re-adapting to the stimulus' episodes. The floor is the 95th
  percentile, rounded up to 0.01, of the awake readings of the null stage with the
  larger one: a stage with nothing to learn then reads at or above the floor in about
  5% of awake readings.
- The frozen control, ``--frozen-audition`` (a model that never adapts), is reported
  as a lower bound: without re-adaptation its readings are far smaller, so a floor set
  on it would leave stages with nothing to learn above it most of the time.

The record also gives, for stages 0 to 2 (steps that register), the share of awake
readings at or above the calibrated floor and at the shared floor.

usage: audition_lp_floor_calibration.py LEARNING_RUNDIR FROZEN_RUNDIR OUT.json
"""
from __future__ import annotations

import argparse
import glob
import json
import math
from pathlib import Path

import numpy as np

QUANTILE = 0.95
NULL_STAGES = (3, 4)


def _stage_readings(path: str) -> tuple[dict, dict[int, np.ndarray]]:
    d = np.load(path, allow_pickle=False)
    assert bool(d["live"]), path
    lt, lv = d["lp_t"], d["lp_v"]
    steps = [float(s) for s in d["steps"]]
    awake = np.ones(lt.shape, dtype=bool)
    for r0, r1 in d["rests"]:
        awake &= ~((lt >= r0) & (lt < r1))
    out = {}
    for k in range(5):
        a = 0.0 if k == 0 else steps[k - 1]
        b = steps[k] if k < len(steps) else float(d["sim_s"])
        m = (lt > a) & (lt <= b) & awake & np.isfinite(lv)
        out[k] = lv[m]
    meta = {"file": Path(path).name, "seed": int(d["seed"]), "arm": str(d["arm"]),
            "frozen_audition": bool(d["frozen_audition"]), "stimulus_version": str(d["stimulus_version"]) or None}
    return meta, out


def _q(v: np.ndarray, q: float) -> float:
    return round(float(np.quantile(v, q)), 4)


def _describe(v: np.ndarray) -> dict:
    return {"readings": int(v.size), "p50": _q(v, 0.5), "p90": _q(v, 0.9), "p95": _q(v, 0.95), "p99": _q(v, 0.99)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("learning_rundir")
    ap.add_argument("frozen_rundir")
    ap.add_argument("out")
    ap.add_argument("--shared-floor", type=float, default=0.20)
    args = ap.parse_args()

    learning = [_stage_readings(p) for p in sorted(glob.glob(str(Path(args.learning_rundir) / "*-fixed_18000-live.npz")))]
    frozen = [_stage_readings(p) for p in sorted(glob.glob(str(Path(args.frozen_rundir) / "*-frozen.npz")))]
    pooled = {k: np.concatenate([r[k] for _, r in learning]) for k in range(5)}
    frozen_pooled = {k: np.concatenate([r[k] for _, r in frozen]) for k in range(5)}
    null_q = max(float(np.quantile(pooled[k], QUANTILE)) for k in NULL_STAGES)
    floor = math.ceil(null_q * 100.0 - 1e-9) / 100.0
    frozen_q = max(float(np.quantile(frozen_pooled[k], QUANTILE)) for k in range(5))
    frozen_floor = math.ceil(frozen_q * 100.0 - 1e-9) / 100.0
    learn = np.concatenate([pooled[k] for k in (0, 1, 2)])
    nulls = np.concatenate([pooled[k] for k in NULL_STAGES])
    record = {
        "method": "95th percentile, rounded up to 0.01, of the awake full-span readings of a learning audition model "
                  "in the null stage (3 or 4, nothing left to learn) with the larger one; settled live runs "
                  "(arousal, developmental rests, broadcast context, awake bins), seeds 1-3, with and without the "
                  "added sounds. A frozen model (never adapts) is the lower bound.",
        "quantile": QUANTILE,
        "audition_learning_progress_floor": floor,
        "frozen_lower_bound": frozen_floor,
        "by_stage_learning": {str(k): _describe(pooled[k]) for k in range(5)},
        "by_stage_frozen": {str(k): _describe(frozen_pooled[k]) for k in range(5)},
        "share_at_or_above_floor": {
            "stages_0_2": round(float(np.mean(learn >= floor)), 4),
            "stages_3_4": round(float(np.mean(nulls >= floor)), 4),
        },
        "share_at_or_above_shared_floor": {
            "stages_0_2": round(float(np.mean(learn >= args.shared_floor)), 4),
            "stages_3_4": round(float(np.mean(nulls >= args.shared_floor)), 4),
        },
        "share_at_or_above_frozen_floor": {
            "stages_0_2": round(float(np.mean(learn >= frozen_floor)), 4),
            "stages_3_4": round(float(np.mean(nulls >= frozen_floor)), 4),
        },
        "runs": [m for m, _ in learning] + [m for m, _ in frozen],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(record, indent=1) + "\n")
    print(json.dumps({k: v for k, v in record.items() if k != "runs"}, indent=1))


if __name__ == "__main__":
    main()
