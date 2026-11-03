# Self-rhythm entrainment with developmental rests

This record holds a re-run of the self-rhythm entrainment validation with the developmental rest
cycle added. It supersedes the 60 bpm "not met" line in the `validation.md` of the archived change
`openspec/changes/archive/2026-10-03-self-rhythm-earned-entrainment/`. That file is not edited.

## What the run tests

The archived harness `proto_r.py` (same archived change, `validation/`) simulates the self-rhythm
generator with a weak afferent maternal drive and phase-projected plasticity on the rhythm's time
constant. It runs one batch column per condition and records, every 300 s window, a band-limited
phase-locking value against the true beat and against 19 foreign-mother surrogates.

The archived run had no rests. This run adds the developmental sleep/wake cycle:

- A 2996 s active, 1410 s rest cycle. In this harness the rest is a schedule, not a change to the
  dynamics: the generator, the drive and the plasticity step continue through the rest intervals,
  and the rest cycle only (1) defines awake time and (2) places the withdrawal probes.
- The periodic drive withdrawal (20 s) is scheduled on awake time: the first at 1770 s awake, then
  every 1800 s awake after the start of the previous one, deferred until 360 s after a rest ends
  and held back from the last 30 s before the next rest.
- Each marker is recorded with entity time and awake time. The marker is the withdrawal probe: the
  phase locking of the self-rhythm in the 300 s before a withdrawal, and whether it persists
  through the withdrawal.

The entrainment criterion is the one in the archived change: the marker "rep3", three consecutive
single-window passes. A control condition is clean when it never reaches rep3. The viability
rules (R0 to R3) are the archived rules in
`openspec/changes/archive/2026-10-03-gestation-viability-watch/validation/viability_rules.py`.

## Inputs

All inputs come from this repository at commit `cb41895b` (main when the run started).

- Harness: `openspec/changes/archive/2026-10-03-self-rhythm-earned-entrainment/validation/proto_r.py`.
  `make_proto_rest.py` applies the rest patch by string replacement and writes `proto_rest.py`
  here. It also renames the harness's imports to the current `kaine.modules.stimulus_source_drive`
  and `kaine.modules.stimulus_source_signal` modules.
- Conditions: the five archived run specs in the same archived change under `validation/runs/`
  (`valF_v2_main`, `valC_true`, `valF_v4_specificity`, `valF_v3_controls`, `valC_controls`), merged
  into `all.json` (31 conditions, 96 h, one shared `kw` block). Condition labels carry a prefix:
  `valF_v:` and `valC_t:` / `valC_c:`.
- `sub.json` is the 8-condition subset used for the no-rest comparison.
- Seeds: each condition fixes its own `drive_seed` and `score_seed` in the spec (listed in
  `rest.json`, key `spec`). The harness seed is 0, the clock offset 97200 s, the numpy generator is
  `default_rng`. Results are deterministic.

## Command

Python 3.12 with the repository virtual environment, from this directory:

```
python make_proto_rest.py                     # writes proto_rest.py and all.json
python make_sub.py                            # writes sub.json
nice -n 19 python drv.py all.json rest.json rest              # 31 conditions, with rests
nice -n 19 python drv.py sub.json norest_sub.json norest      # 8 conditions, no rests
python an.py rest.json        > an_rest.txt
python vr.py  rest.json       > vr_rest.txt
python an.py norest_sub.json  > an_norest_sub.txt
python vr.py  norest_sub.json > vr_norest_sub.txt
```

The two `drv.py` runs were started together under a 16 GB memory cap and took about 3 h in all
(the 31-condition run about 2 h 58 min, peak resident memory about 200 MB each). No entity, service
or GPU is involved.

The column the harness prints as "wall" is entity hours (`t` in the harness), not wall-clock time.
"awake" is the entity time with the rests removed.

## Outputs

`rest.json`, `norest_sub.json` (full per-window markers), `an_*.txt` and `vr_*.txt` (the tables
below), `rest.log` and `norest_sub.log`.

## Results

Lock time is the entity hour at which rep3 first holds; awake hours in parentheses. Single-pass rate
is the share of windows whose marker passes.

### Entrainment with rests, by mother's rate

| Rate | Runs | Lock time, entity h (awake h) | Criterion |
|---|---|---|---|
| 60 bpm | 3 | 14.8 (10.1), 32.3 (22.1), 13.9 (9.6) | met in 3 of 3 |
| 66 bpm | 2 | 7.5 (5.1), 8.8 (6.1) | met in 2 of 2 |
| 70 bpm | 10 | 11.1 to 16.2 (7.6 to 11.1); median 13.45 | met in 10 of 10 |
| 72 bpm | 2 | 16.2 (11.1), 24.0 (16.6) | met in 2 of 2 |
| 80 bpm | 3 | 45.6 (31.1), 44.7 (30.6), 40.5 (27.6) | met in 3 of 3 |

The 70 bpm runs lock at 14.8, 16.2, 13.0, 13.0, 16.2, 12.5, 13.9, 11.1, 13.0 and 16.2 entity hours;
single-pass rates are 57.0 to 71.1%. The three 60 bpm runs are `valC_t` seed 7, `valF_v` seed 0 and
`valF_v` seed 1; the three 80 bpm runs are `valC_t` seed 8, `valF_v` seed 0 and seed 1.

### 60 bpm with and without rests (same seed)

| Run | Lock time, entity h | Single-pass rate |
|---|---|---|
| `valF_v:60 seed0`, with rests | 32.3 | 73.6% |
| `valF_v:60 seed0`, no rests | 3.0 | 86.2% |

With rests, a 60 bpm mother entrains the rhythm in all three runs (13.9 to 32.3 entity h). Without
rests the same seed locks at 3.0 h. The archived `validation.md` records the 60 bpm criterion as
"not met" and a replicated pass at about 3 h; that line is replaced by this record. The "3 to 48 h"
range for slow rates no longer applies to the with-rests run, which spans 7.5 to 45.6 h for 60 to
80 bpm.

### No-rest comparison (8 conditions)

| Condition | With rests (entity h) | No rests (entity h) |
|---|---|---|
| 70 bpm, seed 0 | 14.8 | 13.0 |
| 60 bpm, seed 0 | 32.3 | 3.0 |
| 80 bpm, seed 0 | 44.7 | 46.5 |

### Controls (none lock)

| Control | Single-pass rate | rep3 | Viability flag, awake h |
|---|---|---|---|
| foreign mother 0->1 | 4.7% | never | R3 at 60.21 (`an.py`); not flagged by `vr.py` |
| foreign mother 2->3 | 8.6% | never | same |
| foreign mother 5->6 | 6.2% | never | same |
| foreign mother 7->8 | 3.1% | never | same |
| foreign mother 9->10 | 5.5% | never | same |
| foreign mother 11->12 | 3.1% | never | same |
| no drive | 0% | never | R1 at 24.1 |
| plasticity off (eta 0) | 0% | never | R1 at 24.1 |
| plasticity off, seed 11 | 0% | never | R1 at 24.1 |
| plasticity off, scale 1, seed 12 | 0% | never | R1 at 26.6 |
| jittered beat | 0% | never | R1 at 30.1 (`an.py`), 29.6 (`vr.py`) |

Foreign-mother single-pass rates run from 3.1 to 8.6%, and no foreign pair reaches three in a row.
The `vr.py` rules (the archived viability function) flag none of the 20 entraining runs and none of
the foreign pairs, and flag the no-drive, plasticity-off and jittered-beat controls at R1. The
`an.py` rule flags the foreign pairs at R3 at 60.21 awake hours, its 60 h limit. The jittered beat
is flagged at 29.6 awake hours by the archived rules, against 26.5 for the same condition in the
no-rest subset (26.0 by `an.py`).

### Criteria

| Criterion | Result |
|---|---|
| 70 bpm locks within 96 h | met, 10 of 10 |
| 60 bpm locks within 96 h | met, 3 of 3 |
| 80 bpm locks within 96 h | met, 3 of 3 |
| No foreign-mother control locks | met, 0 of 6 |
| No drive, plasticity-off and jittered-beat controls do not lock | met, 0 of 5 |
| Entraining runs are not flagged by the viability rules | met, 0 of 20 flagged |
| Foreign-pair single passes stay low | met, 3.1 to 8.6% |

## Caveats

- One batched run per arm: the with-rest arm and the no-rest arm are each a single `drv.py`
  invocation. Within a rate, the runs differ only in the seeds in the spec.
- n is 3 for 60 bpm and 3 for 80 bpm (2 for 66 and 72 bpm), so the ranges are the minimum and
  maximum of very few runs. The 60 bpm spread is wide (13.9 to 32.3 h).
- The no-rest comparison covers 8 conditions, one seed each.
- The harness column labelled "wall" is entity hours; the awake figures are the entity figures with
  rests removed.
- The 96 h horizon is entity time.
- The rest cycle changes only the withdrawal schedule and the awake-time accounting; the simulated
  generator keeps running through rests. The no-rest arm uses the same probe schedule on
  continuous time (first withdrawal at 1770 s, then every 1800 s).
- The recovered scripts differ from the text in the original session only in paths and the SPDX header.
  The archived harness still imports the earlier `womb_*` module names, so `make_proto_rest.py`
  renames them to the `stimulus_source_*` modules the repository exports.
- `an.py` leaves windows without a marker out of the single-pass denominator, so the foreign-pair
  single-pass rates it reports (3.1 to 8.6 percent) are upper bounds on the rate over all windows.
- `an.py`'s summary line formats a missing value with a float code and would fail for a condition
  with no marker windows; no condition in this run has none. The scripts are kept as recovered.
