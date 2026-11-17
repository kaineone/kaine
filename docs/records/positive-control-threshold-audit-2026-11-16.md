# Positive-control threshold audit and run plan

Date: 2026-11-16. Documentation only. No source, config, task, run, or
experiment changes were made while producing this record; no study command was
executed.

This record is the threshold-audit view of operator task `4.1` in
`openspec/changes/ablation-positive-control/tasks.md`:

> Fix `min_effect` and `snr` with the preregistration and run the control on
> the live tier until every processor passes.

It combines the command map, preliminary note, and pre-execution checklist into
one staged execution order for the preliminary run, the 30 counted finals, the
calibration digest, and the 4.1 live verdicts. It supplements rather than
replaces those records.

Companion records:

- `docs/records/positive-control-command-map-2026-11-16.md`
- `docs/records/positive-control-preliminary-2026-11-16.md`
- `docs/records/positive-control-pre-execution-checklist-2026-11-16.md`
- `docs/records/positive-control-run-id-audit-2026-11-16.md`

---

## 1. Audit conclusion

No 4.1 threshold or live verdict exists yet. Specifically:

- `data/evaluation/positive_control/` is absent, so no principal-component
  thresholds have been minted.
- `config/studies/workspace_mediation_pilot_competitive.toml` still has
  `principal_components_run = ""`.
- `config/studies/workspace_mediation_settings.json` does not exist, so no
  `min_effect`, `snr`, `min_reports`, learning period, bins, or contrasts have
  been calibrated, and no `record_sha256` digest exists for preregistration.
- No `workspace_mediation_positive_control` run has been executed or verified.

An offline oscillatory-ablation preliminary did complete and wrote
`docs/records/oscillatory-ablation-positive-control-2026-11-16.jsonl`
(verdict: WIN). That is supporting evidence only. It does not mint the
per-processor principal components, plan, settings record, or run IDs required
by `4.1`. Therefore `4.1` is correctly left open even though the offline
control passes.

---

## 2. Global invariant

- `config/kaine.toml` `[positive_control]` remains disabled by default, with
  `min_effect` and `snr` unset.
- Calibrated values reach live runs only through the settings record referenced
  by `config/studies/workspace_mediation_positive_control.toml`
  (`settings_record = config/studies/workspace_mediation_settings.json`).
- `N_CAL = 30`: at least 30 counted (non-excluded) pilot triples are required.
- Distinct seeds only. No seed may be reused across the preliminary run, any
  pilot, any replacement pilot, or any control run.
- A calibration rule that cannot be applied fails closed: the affected value is
  null, `blocked` gives the reason, `complete` is `False`, and boot refuses
  the live run.
- A control verdict passes only when all three processors pass and there are no
  record parse errors.

---

## 3. Exact sequence

### Stage A - Preliminary run (principal components)

Purpose: mint the preliminary run ID and the vision/audition/interoception
principal-component axes used to score every later pilot and control run.

Command (target, not executed by this record):

```bash
KAINE_STUDY=workspace_mediation_preliminary python -m kaine.cycle
```

Required result on success:

- `data/evaluation/runs/<preliminary_run_id>/manifest.json`
- `data/evaluation/positive_control/<preliminary_run_id>/principal_component_vision.json`
- `data/evaluation/positive_control/<preliminary_run_id>/principal_component_audition.json`
- `data/evaluation/positive_control/<preliminary_run_id>/principal_component_interoception.json`

Manifest invariants:

- `study == "workspace_mediation_preliminary"`
- finite `seed`
- `perception_feed` consistent with all later runs.

Prerequisite: the operator overlay must not leave `[stimulus_control]` enabled,
because the workspace-mediation preliminary arm refuses that state. Resolve
through the operator-config surface only; do not edit protected operator
configuration to bypass the refusal.

### Stage B - Bind the preliminary run to the competitive pilot

Edit recorded as a run-recorded configuration change before any pilot runs:

```toml
# config/studies/workspace_mediation_pilot_competitive.toml
principal_components_run = "<preliminary run id>"
```

### Stage C - Thirty counted finals (pilot triplets)

Run triplets on distinct seeds until at least 30 counted (non-excluded) pilots:

```bash
KAINE_STUDY=workspace_mediation_pilot_competitive python -m kaine.cycle
KAINE_STUDY=workspace_mediation_pilot_matched python -m kaine.cycle
KAINE_STUDY=workspace_mediation_pilot_pooled python -m kaine.cycle
```

Notes:

- The competitive pilot also runs the SNR ladder positive control.
- Any pilot classified NOT EXERCISED is replaced; do not reuse its seed.
- Tone pilots are optional but must be applied consistently: every pilot
  tuple includes `tone`, or none does. If used, add:

```bash
KAINE_STUDY=workspace_mediation_pilot_tone python -m kaine.cycle
```

### Stage D - Plan file

Author `PLAN.json` in attempted order:

```json
{
  "preliminary_run": "<preliminary run id>",
  "pilots": [
    {
      "competitive": "<competitive run id>",
      "matched": "<matched run id>",
      "pooled": "<pooled run id>",
      "tone": "<tone run id>"
    }
  ]
}
```

Input invariants:

- `preliminary_run` is a non-empty string.
- `pilots` is non-empty.
- Every pilot contains exactly `competitive`, `matched`, `pooled`.
- `tone` appears in every pilot or in none.
- Run IDs are the attempted-order `workspace_mediation_*` run IDs.

### Stage E - Calibration digest

Command:

```bash
python -m kaine.experiment.calibrate PLAN.json \
  --out config/studies/workspace_mediation_settings.json
```

Calibration writes the settings record and prints `record_sha256`. Exit codes:

- `0`: complete record, admissible for the live control run.
- `1`: incomplete record (null/blocked values); the sequence is blocked.
- `2`: bad input; nothing written.

Required digest properties before proceeding:

- record path: `config/studies/workspace_mediation_settings.json`
- `complete == true`
- no `blocked` reason
- no null calibrated value required for the control (`min_effect`, `snr`,
  `min_reports`, learning period, bins, contrasts)
- `record_sha256` captured for preregistration.

### Stage F - Positive-control live runs

Run the control study:

```bash
KAINE_STUDY=workspace_mediation_positive_control python -m kaine.cycle
```

Consecutive complete control runs may be required; capture each run ID.

### Stage G - 4.1 live verdict

Verify every processor:

```bash
python -m kaine.experiment.positive_control <run_id> [<run_id> ...] \
  [--root data/evaluation] [--json]
```

Pass condition (exit 0):

- all three processors pass (vision, audition, interoception)
- no record parse error
- no run parse or manifest inconsistency.

### Stage H - Live studies after pass (still part of completing 4.1)

Only after Stage G exits 0:

```bash
KAINE_STUDY=workspace_mediation_competitive python -m kaine.cycle
KAINE_STUDY=workspace_mediation_matched python -m kaine.cycle
KAINE_STUDY=workspace_mediation_pooled python -m kaine.cycle
```

These are verification/follow-on live runs, not substitutes for the control
verdict itself.

### Stage I - Task state update

Mark `4.1` complete in
`openspec/changes/ablation-positive-control/tasks.md` only after Stage G exits
0 and the settings record verifies as complete.

---

## 4. Required artifacts

| Stage | Artifact | Path / form |
|---|---|---|
| A | Preliminary manifest | `data/evaluation/runs/<preliminary_run_id>/manifest.json` |
| A | Principal components | `data/evaluation/positive_control/<preliminary_run_id>/principal_component_{vision,audition,interoception}.json` |
| B | Config binding | `config/studies/workspace_mediation_pilot_competitive.toml` with `principal_components_run = "<preliminary run id>"` |
| C | Pilot manifests | `data/evaluation/runs/<run_id>/manifest.json`, 90 minimum (3 arms x 30) |
| C | Tone manifests | 0 or 30 additional, applied consistently |
| C | SNR ladder outputs | from the competitive pilot, for control minimum reports |
| D | Plan | `PLAN.json`, valid against `calibrate` input rules |
| E | Settings record | `config/studies/workspace_mediation_settings.json` |
| E | Digest | `record_sha256` from calibration output |
| F | Control runs | manifests with study `workspace_mediation_positive_control` |
| G | Verdict | output of `python -m kaine.experiment.positive_control` showing all processors pass and no parse errors |
| G | Terminal records | `positive_control.result` records in mode `control` |

Manifest invariants across runs: fields `study`, `seed`, and consistent
`perception_feed`.

---

## 5. Prerequisites checklist

- [ ] Starting branch and clean-enough tree confirmed; base commit SHA recorded in
      a follow-up run record.
- [ ] Disk baseline recorded before any run:
      `df -h /var/home/erik` and `du -sh data/evaluation`.
- [ ] Free space at least 20 GB before starting; plan 0.5-1 GB minimum for the
      full preliminary + 30 pilots + control sequence.
- [ ] No pinned local model collisions: `ollama ps`; unload models before runs.
- [ ] `[positive_control]` defaults in `config/kaine.toml` disabled with
      `min_effect`, `min_reports`, and `snr` unset.
- [ ] Preliminary study uses `mode = "estimate_pc"` and role `preliminary`.
- [ ] Control study references
      `config/studies/workspace_mediation_settings.json`.
- [ ] CLI modules importable:
      `python -c "import kaine.experiment.calibrate, kaine.experiment.positive_control"`.
- [ ] Preliminary run is not blocked by an enabled `[stimulus_control]`
      overlay (Stage A prerequisite).
- [ ] Offline support record retained:
      `docs/records/oscillatory-ablation-positive-control-2026-11-16.jsonl`.

---

## 6. Why 4.1 stays open (as of 2026-11-16)

1. The preliminary live run has not produced
   `data/evaluation/positive_control/<run_id>/principal_component_{vision,audition,interoception}.json`.
2. `principal_components_run` in
   `config/studies/workspace_mediation_pilot_competitive.toml` is still empty.
3. zero counted finals and no pilot manifests exist, so the `N_CAL = 30`
   requirement is unmet.
4. `PLAN.json` has not been authored, so calibration input validation has not
   passed.
5. `python -m kaine.experiment.calibrate` has not exited 0; no settings record
   and no `record_sha256` digest exist.
6. `min_effect` and `snr` have not been fixed by preregistration; the global
   config remains disabled and unset by design.
7. No control run has completed and
   `python -m kaine.experiment.positive_control` has not exited 0, so the "live
   tier until every processor passes" criterion is unmet.
8. The offline ablation verdict does not satisfy the live, per-processor
   principal-component and settings requirements. It is evidence, not a
   replacement.

Until Stage G exits 0 with all processors passing and no parse error, `4.1`
must stay open and the live studies in Stage H must not be treated as
completion.