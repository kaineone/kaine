# Positive-control run id audit

Date: 2026-11-16. Report only; no code/config/policy changes.

## Run id lifecycle

- Run ids are minted as `uuid.uuid4().hex` in
  `kaine/experiment/run_context.py::mint_run_context` and stored in the run manifest
  at `data/evaluation/runs/<run_id>/manifest.json` (field `run_id`), then stamped on
  records via the process-global `RunContext`.
- Evaluation records are keyed by that `run_id` (see
  `kaine/experiment/run_records.py`). Offline tools consume caller-supplied ids;
  they do not invent or persist ids themselves:
  - `kaine/experiment/positive_control.py`: CLI takes one or more run ids and loads
    `load_run_records(run_id, root=...)`; verification is pooled/derived from records.
  - `kaine/experiment/calibrate.py`: plan names `preliminary_run` plus pilot run
    ids; loads manifests from `root/runs/<run_id>/manifest.json` and principal
    components from `root/positive_control/<preliminary_run>/<processor>.json`.
  - `kaine/experiment/log_schema.py`: CLI takes one run id and sweeps its logs.

## References found

- Code/tests: no hard-coded positive-control run id. The code paths above take ids
  as arguments or plan fields. Tests use synthetic temporary run ids only.
- Config: `config/studies/workspace_mediation_pilot_competitive.toml` has
  `principal_components_run = ""` (must be set to the preliminary run id). The
  positive-control study uses `settings_record = "config/studies/workspace_mediation_settings.json"`.
- Docs: `docs/15-experiments/README.md` documents the preliminary output path
  `data/evaluation/positive_control/<run_id>/` and the positive-control check command.
- Records/data: no preliminary positive-control artifacts are present:
  `data/evaluation/positive_control/` does not exist. Existing `data/evaluation/runs/`
  manifests have `study = null` and no `positive_control`/settings-record linkage.

## Preliminary artifacts now

None. No `positive_control/<run_id>/principal_component_<processor>.json` files and
no settings record at `config/studies/workspace_mediation_settings.json`.

## Likely next action

Run the preliminary study (`KAINE_STUDY=workspace_mediation_preliminary`) to mint
the first run id and write its principal components, then set that id as
`principal_components_run` in the pilot competitive config before the pilot runs.