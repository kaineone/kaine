# Positive-control pre-execution checklist

Date: 2026-11-16. Docs only. No source, config, task, run, or experiment
changes were made while producing this file, and no commands were executed.

This record expands `positive-control-preliminary-2026-11-16.md` and
`positive-control-command-map-2026-11-16.md` into the pre-execution checklist,
required inputs, estimated artifact sizes, and completion criteria for operator
task `4.1` in `openspec/changes/ablation-positive-control/tasks.md`:

> Fix `min_effect` and `snr` with the preregistration and run the control on
> the live tier until every processor passes.

Sources:
- `openspec/changes/ablation-positive-control/tasks.md`
- `openspec/changes/ablation-positive-control/proposal.md`
- `docs/records/positive-control-preliminary-2026-11-16.md`
- `docs/records/positive-control-command-map-2026-11-16.md`
- `kaine/experiment/calibrate.py`
- `kaine/experiment/calibration_rules.py`
- `kaine/experiment/principal_component.py`
- `kaine/experiment/positive_control.py`

## 1. Ground rules

- Work remains documentation-only until the operator explicitly runs a stage.
- No `KAINE_STUDY=... python -m kaine.cycle` command has been run for the
  positive-control sequence.
- Do not change protected operator configuration to force the preliminary arm;
  the study configs are the non-protected surface (see `2.3`).
- Distinct seeds only. No seed may be reused across the preliminary run, any
  pilot, or any control run; the boot rejects a reused seed for the control run.
- Do not append new work to this file's sources after a stage completes; instead
  append a dated run record under `docs/records/`.

## 2. Pre-execution checklist

### 2.1 Repository and safety baseline

- [ ] Operator confirms the desired branch and a clean-enough tree; record the
  starting commit SHA in a follow-up run record.
- [ ] Run disk baseline before any run:
  `df -h /var/home/erik` and `du -sh data/evaluation`.
- [ ] Confirm no pinned local model is loaded that would collide with KAINE's
  GPU use (`ollama ps`); unload models before runs.
- [ ] Confirm the baseline size record (current `data/evaluation`: about 39 MB)
  is available for before/after comparison.

### 2.2 Code/configuration inputs present

- [ ] Confirm `[positive_control]` defaults in `config/kaine.toml` are
  disabled with `min_effect`, `min_reports` and `snr` unset.
- [ ] Confirm `config/studies/workspace_mediation_preliminary.toml` uses
  `mode = "estimate_pc"` and role `preliminary`.
- [ ] Confirm `config/studies/workspace_mediation_pilot_competitive.toml`
  currently has `principal_components_run = ""` (will be the first required edit).
- [ ] Confirm `config/studies/workspace_mediation_positive_control.toml`
  points `settings_record` at
  `config/studies/workspace_mediation_settings.json`.
- [ ] Confirm `python -m kaine.experiment.calibrate` and
  `python -m kaine.experiment.positive_control` are importable:
  `python -c "import kaine.experiment.calibrate, kaine.experiment.positive_control"`.

### 2.3 Preliminary run unblock check

The preliminary live run is blocked while the operator overlay enables
`[stimulus_control]`; the workspace-mediation preliminary arm refuses that state.
Operator-only verification:

- [ ] Read the merged effective configuration with
  `KAINE_STUDY=workspace_mediation_preliminary` applied.
- [ ] Confirm this does not leave stimulus control enabled.
- [ ] Do not edit protected operator configuration to bypass the refusal.
  If it is enabled, stop and resolve through the operator-config surface rather
  than forcing the study.

### 2.4 Stage checklist (documentation-only order)

1. Preliminary run:
   - Command (not executed here):
     `KAINE_STUDY=workspace_mediation_preliminary python -m kaine.cycle`
   - Uses a seed never used again.
   - Writes `data/evaluation/positive_control/<run_id>/principal_component_{vision,audition,interoception}.json`.
   - Mints `run_id` in `data/evaluation/runs/<run_id>/manifest.json`.
2. Record the preliminary `run_id`.
3. Set `principal_components_run = "<run_id>"` in
   `config/studies/workspace_mediation_pilot_competitive.toml`.
4. Run pilots in triples on distinct seeds until at least 30 counted pilots:
   - `KAINE_STUDY=workspace_mediation_pilot_competitive python -m kaine.cycle`
   - `KAINE_STUDY=workspace_mediation_pilot_matched python -m kaine.cycle`
   - `KAINE_STUDY=workspace_mediation_pilot_pooled python -m kaine.cycle`
   - The competitive pilot also runs the SNR ladder positive control.
   - Any pilot classified NOT EXERCISED is replaced; do not reuse its seed.
5. Tone pilots (optional but consistent): if used, every pilot tuple includes
   `tone`; if not used, none does.
6. Author `PLAN.json` in attempted order:
   ```json
   {"preliminary_run": "<run id>",
    "pilots": [{"competitive": "<run id>", "matched": "<run id>", "pooled": "<run id>", "tone": "<run id>"}]}
   ```
7. Calibration:
   - Command (not executed here):
     `python -m kaine.experiment.calibrate PLAN.json --out config/studies/workspace_mediation_settings.json`
   - Exit 0: complete record; nonzero leaves the run blocked.
8. Control run(s):
   - `KAINE_STUDY=workspace_mediation_positive_control python -m kaine.cycle`
9. Verify:
   - `python -m kaine.experiment.positive_control <run_id> [<run_id> ...]`
   - Exit 0 only when all three processors pass and no record parse error.
10. Live runs only after step 9 passes:
    - `KAINE_STUDY=workspace_mediation_competitive python -m kaine.cycle`
    - `KAINE_STUDY=workspace_mediation_matched python -m kaine.cycle`
    - `KAINE_STUDY=workspace_mediation_pooled python -m kaine.cycle`

## 3. Required inputs

### 3.1 Calibration plan

- `PLAN.json` with non-empty `preliminary_run` and a non-empty `pilots` list.
- Each pilot contains exactly `competitive`, `matched`, `pooled`.
- `tone` appears in every pilot or in none.
- Run IDs are attempted-order `workspace_mediation_*` run IDs.

### 3.2 Preliminary artifacts

- `data/evaluation/runs/<preliminary_run_id>/manifest.json`.
- `data/evaluation/positive_control/<preliminary_run_id>/principal_component_{vision,audition,interoception}.json`.
- Manifest fields `study` must be `workspace_mediation_preliminary`, with a
  finite `seed`, and all runs must share a consistent `perception_feed`.

### 3.3 Pilot artifacts

- `data/evaluation/runs/<run_id>/manifest.json` for every arm run.
- Run records under `data/evaluation/runs/<run_id>/` loaded through
  `load_records_for_runs`.
- Manifest fields `study`, `seed`, and consistent `perception_feed` across all runs.
- At least 30 counted (non-excluded) pilot triples.
- SNR ladder outputs from the competitive pilot for control min reports.

### 3.4 Positive-control settings record

- Output path: `config/studies/workspace_mediation_settings.json`.
- Contains the calibrated `min_effect`, `snr`, `min_reports`, learning period,
  tone bins, age bins, and contrasts.
- `complete` must be true before a live run is admissible; a `False` record is
  treated as blocked by boot.
- `record_sha256` from the calibration output is the value intended for
  preregistration.

### 3.5 Live control run artifacts

- Run manifests with the study `workspace_mediation_positive_control`.
- Terminal `positive_control.result` records in mode `control`.
- Verification artifact from `python -m kaine.experiment.positive_control`
  showing all processors pass and no parse errors.

## 4. Estimated artifact sizes

Measured local baselines:
- Existing run manifest: about 2.7 KB; planning budget 8 KB after settings
  digest fields.
- Existing `data/evaluation` root: about 39 MB, dominated by
  `research_events` (about 35 MB / 48,054 records, roughly 730 bytes/record).
- Existing run directories: about 4 KB each (minimal manifests only).

Planning estimates for the full sequence:

| Artifact | Per item | Count | Budget |
|---|---:|---:|---:|
| Preliminary run manifest | ~3-8 KB | 1 | ~8 KB |
| Principal-component JSON | ~5-50 KB each (depends on processor input dimension) | 3 | ~150 KB total |
| Pilot run manifest | ~3-8 KB | 90 minimum (3 arms * 30) | ~720 KB |
| Tone pilot manifests | ~3-8 KB | 0 or 30 additional | up to ~240 KB |
| `PLAN.json` | <10 KB | 1 | negligible |
| Settings record | ~10-50 KB | 1 | negligible |
| Run-scoped logs and records | 1-5 MB | 90+ | ~500 MB worst case |
| Control run artifacts | ~1-5 MB | 1+ | ~5 MB each |

Operational estimate: the full prelim + 30 counted pilots + control sequence
needs on the order of 0.5-1 GB of free space, not counting model caches.
Run `df -h` before and every 15 minutes during pilot batches, following the
resource guardrails in the user directives. Clean build artifacts and stopped
containers before starting.

## 5. What would complete 4.1

Task 4.1 is complete only when all of the following are true:

1. The preliminary run has completed and its artifacts exist at the paths named
   in `3.2`, with a unique seed.
2. `principal_components_run` in
   `config/studies/workspace_mediation_pilot_competitive.toml` is set to the
   preliminary `run_id`.
3. At least 30 counted (non-excluded) pilots have completed, with distinct seeds
   and no NOT EXERCISED replacement left unresolved.
4. `PLAN.json` exists and passes calibration input validation.
5. `python -m kaine.experiment.calibrate PLAN.json --out ...` exits 0, writes
   `config/studies/workspace_mediation_settings.json`, and the record has
   `complete == true`, no `blocked` reason, and no null calibrated value
   required for the control.
6. `record_sha256` is captured for preregistration.
7. `config/kaine.toml` `[positive_control]` remains disabled by default; any
   settings-derived `min_effect`, `snr`, and `min_reports` are supplied only
   through the settings record referenced by the control study.
8. At least one `workspace_mediation_positive_control` run completes and
   `python -m kaine.experiment.positive_control <run_id>` exits 0, with
   all three processors passing and no record parse error.
9. The operator then updates `openspec/changes/ablation-positive-control/tasks.md`
   to mark `4.1` complete.

## 6. Current blockers (as of 2026-11-16)

- `data/evaluation/positive_control/` does not exist.
- `config/studies/workspace_mediation_settings.json` does not exist.
- `config/studies/workspace_mediation_pilot_competitive.toml` still has
  `principal_components_run = ""`.
- No calibration has run; no `record_sha256` exists.
- Seed discipline, 30 counted pilots, the `PLAN.json` file, and the control
  verification all remain to be produced.
- The preliminary live run remains configuration-blocked by the operator overlay
  noted in `2.3`.