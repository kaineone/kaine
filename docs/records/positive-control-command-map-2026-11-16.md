# Positive-control command map

Date: 2026-11-16. Report only; no code, config or task changes.

## Is calibration one command or multi-step?

Calibration itself is **one command** once its inputs exist:

```bash
python -m kaine.experiment.calibrate PLAN.json \
  --out config/studies/workspace_mediation_settings.json \
  [--root data/evaluation]
```

It is not the whole positive-control flow. The command only reads already-produced run records and manifests, plus principal-component files from the preliminary run. Reaching it requires the preliminary run, 30 counted pilots (each as three arm runs), and a hand-authored plan JSON. The full path is therefore multi-stage; only the calibration step is a single command.

## End-to-end positive-control path

1. Preliminary run (principal components):

```bash
KAINE_STUDY=workspace_mediation_preliminary python -m kaine.cycle
```

- Writes `data/evaluation/positive_control/<run_id>/principal_component_{vision,audition,interoception}.json`.
- Mints `run_id` in `data/evaluation/runs/<run_id>/manifest.json`.
- Seed must be one never used again.

2. Set preliminary run id in pilot competitive config:

```toml
# config/studies/workspace_mediation_pilot_competitive.toml
principal_components_run = "<preliminary run id>"
```

3. Pilot runs, three on one seed each, repeatedly until at least 30 counted pilots:

```bash
KAINE_STUDY=workspace_mediation_pilot_competitive python -m kaine.cycle
KAINE_STUDY=workspace_mediation_pilot_matched python -m kaine.cycle
KAINE_STUDY=workspace_mediation_pilot_pooled python -m kaine.cycle
```

- Competitive pilot also runs the SNR ladder positive control.
- Every NOT EXERCISED pilot is replaced; distinct seeds only.

4. Plan file (`PLAN.json`), in attempted order:

```json
{"preliminary_run": "<run id>",
 "pilots": [{"competitive": "<run id>", "matched": "<run id>", "pooled": "<run id>", "tone": "<run id>"}]}
```

5. Calibrate:

```bash
python -m kaine.experiment.calibrate PLAN.json \
  --out config/studies/workspace_mediation_settings.json
```

- Exit 0: complete record.
- Exit 1: incomplete record (values null / blocked).
- Exit 2: bad input; nothing written.
- Prints `record_sha256` for preregistration.

6. Positive-control runs (mode control):

```bash
KAINE_STUDY=workspace_mediation_positive_control python -m kaine.cycle
```

7. Verify complete control runs:

```bash
python -m kaine.experiment.positive_control <run_id> [<run_id> ...] \
  [--root data/evaluation] [--json]
```

- Exit 0 only when all three processors pass and no record parse error.

8. Live runs only after step 7 passes:

```bash
KAINE_STUDY=workspace_mediation_competitive python -m kaine.cycle
KAINE_STUDY=workspace_mediation_matched python -m kaine.cycle
KAINE_STUDY=workspace_mediation_pooled python -m kaine.cycle
```

## Required inputs and artifacts

- Plan: JSON object with `preliminary_run` (non-empty string) and non-empty `pilots` list.
- Each pilot must contain exactly `competitive`, `matched`, `pooled`, plus `tone` in every pilot or in none.
- Run manifests: `data/evaluation/runs/<run_id>/manifest.json`; fields `study`, `seed`, and consistent `perception_feed` across all runs.
- Run records loaded under `data/evaluation/runs/<run_id>/` via `load_records_for_runs`.
- Principal-component files: `data/evaluation/positive_control/<preliminary_run>/principal_component_<processor>.json` for vision, audition, interoception.
- Settings record output: `config/studies/workspace_mediation_settings.json` plus its digest.
- Positive-control checks use `positive_control.result` records in mode `control`.

## Unstarted prerequisites (as of 2026-11-16)

- No preliminary positive-control artifacts exist: `data/evaluation/positive_control/` is absent.
- No settings record exists at `config/studies/workspace_mediation_settings.json`.
- `config/studies/workspace_mediation_pilot_competitive.toml` still has `principal_components_run = ""`.
- No calibration has been run; no `record_sha256` available for preregistration.
- Seed discipline, 30 counted pilots, and plan file all remain to be produced.
- `tools/maintainer/*` contains no positive-control/calibration wrapper; calibration is invoked directly through `python -m kaine.experiment.calibrate`, and positive-control verification through `python -m kaine.experiment.positive_control`.
