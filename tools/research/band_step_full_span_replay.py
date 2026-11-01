# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Replay band-step traces through the full-span release rule (developmental-stimulus-progress task 2.3).

For each settled run (``fixed:SECONDS``) of ``band_step_check.py``, the recorded
audition prediction errors go, in their order, to the real ``Affect`` module,
with a ``development.hearing_stage`` event at each recorded step, so the affect
module's own bins restart there. Once a simulated second the replay reads
``Affect.audition_learning_progress(stage)``, the gated accessor the hearing-stage
watch reads, and feeds it to a fresh ``HearingStageState`` per stage with the
shipped parameters. The record is when that owner would have released each stage,
measured from the step, or null when it would not have within the run's hold.

The stimulus within a stage of a settled run is the same as under the rule until
the release, but the forward model has had the settled run's longer exposure to
the stages before, so the dwells are those of a settled history.

usage: band_step_full_span_replay.py RUNDIR OUT.json [--repo REPO]
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import json
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


async def replay_run(path: str, cfg: dict) -> dict:
    from kaine.bus.schema import Event
    from kaine.modules.affect.module import Affect
    from kaine.modules.audition.hearing_band import HearingBandParams
    from kaine.modules.audition.hearing_stage_state import HearingStageState

    class _Bus:
        async def publish(self, event) -> str:  # noqa: ANN001
            return "0-0"

    d = np.load(path, allow_pickle=False)
    acfg = cfg["affect"]
    hearing = HearingBandParams.from_section(cfg["perception_feed"]["stimulus_source"].get("hearing"))
    lp0 = float(acfg["learning_progress_floor"])
    span = float(acfg["learning_progress_span_s"])
    now = [0.0]
    affect = Affect(
        _Bus(), clock=lambda: now[0],
        fast_time_constant_s=float(acfg["fast_time_constant_s"]), slow_time_constant_s=float(acfg["slow_time_constant_s"]),
        learning_progress_floor=lp0, learning_progress_span_s=span,
        learning_progress_bin_s=float(acfg["learning_progress_bin_s"]),
    )

    def stage_event(stage: int) -> Event:
        return Event(source="development", type="development.hearing_stage", payload={"stage": stage},
                     salience=0.05, timestamp=datetime.now(timezone.utc))

    def audition_event(err: float) -> Event:
        return Event(source="audition", type="audition.perception", payload={"prediction_error": err},
                     salience=0.4, timestamp=datetime.now(timezone.utc))

    steps = [float(s) for s in d["steps"]]
    sim = float(d["sim_s"])
    bounds = [0.0] + steps + [sim]
    stage = 0
    await affect._handle_peer_event(affect._development_stream, stage_event(0))

    def owner() -> HearingStageState:
        return HearingStageState(hearing, path=None, lp_floor=lp0, learning_progress_span_s=span)

    state = owner()
    state.observe(0.0, None)
    released: list[float | None] = [None] * len(bounds[:-1])
    first_full: list[float | None] = [None] * len(bounds[:-1])
    tick = 1.0
    for t, e in zip(d["err_t"], d["err_e"]):
        now[0] = float(t)
        await affect._handle_peer_event("audition.out", audition_event(float(e)))
        while tick <= now[0]:
            lp = affect.audition_learning_progress(stage)
            if lp is not None and first_full[stage] is None:
                first_full[stage] = tick - bounds[stage]
            if released[stage] is None and state.observe(tick, lp) is not None:
                released[stage] = tick - bounds[stage]
            if stage < len(steps) and tick >= steps[stage]:
                stage += 1
                await affect._handle_peer_event(affect._development_stream, stage_event(stage))
                state = owner()
                state.observe(tick, None)
            tick += 1.0
    return {
        "file": Path(path).name,
        "seed": int(d["seed"]),
        "arm": str(d["arm"]),
        "schedule": str(d["schedule"]),
        "hold_s": [b - a for a, b in zip(bounds[:-1], bounds[1:])],
        "first_full_span_reading_s": first_full,
        "released_after_s": released,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rundir")
    ap.add_argument("out")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    args = ap.parse_args()
    sys.path.insert(0, str(Path(args.repo).resolve()))
    cfg = tomllib.loads((Path(args.repo) / "config" / "kaine.toml").read_text())
    runs = []
    for path in sorted(glob.glob(str(Path(args.rundir) / "*-fixed_*.npz"))):
        run = asyncio.run(replay_run(path, cfg))
        print(run["file"], [None if r is None else round(r / 3600, 2) for r in run["released_after_s"]], flush=True)
        runs.append(run)
    by_stage: dict[int, list[float]] = {}
    censored: dict[int, int] = {}
    for run in runs:
        for k, r in enumerate(run["released_after_s"]):
            if k == len(run["released_after_s"]) - 1:
                continue  # stage 4 is final: nothing to release
            if r is None:
                censored[k] = censored.get(k, 0) + 1
            else:
                by_stage.setdefault(k, []).append(r)
    summary = {
        str(k): {
            "released_h_min": round(min(v) / 3600, 2) if v else None,
            "released_h_max": round(max(v) / 3600, 2) if v else None,
            "runs_released": len(v),
            "runs_not_released_within_hold": censored.get(k, 0),
        }
        for k, v in sorted({**{k: [] for k in censored}, **by_stage}.items())
    }
    record = {
        "method": "replay of the 2026-10-31 settled runs' audition errors through the real Affect module "
                  "(gated hearing-stage accessor) and a fresh HearingStageState per stage (full-span rule, "
                  "no minimum dwell)",
        "config": {
            "learning_progress_floor": cfg["affect"]["learning_progress_floor"],
            "learning_progress_span_s": cfg["affect"]["learning_progress_span_s"],
            "learning_progress_bin_s": cfg["affect"]["learning_progress_bin_s"],
            "saturation_window_seconds": cfg["perception_feed"]["stimulus_source"]["hearing"]["saturation_window_seconds"],
            "max_dwell_seconds": cfg["perception_feed"]["stimulus_source"]["hearing"]["max_dwell_seconds"],
        },
        "summary_by_stage": summary,
        "runs": runs,
    }
    Path(args.out).write_text(json.dumps(record, indent=1) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
