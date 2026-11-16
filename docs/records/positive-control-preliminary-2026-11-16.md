# Positive-control preliminary run

Date: 2026-11-16. Report only; no source or config edits, no commit.

## Vendor-supported path used

The live entity cycle preliminary (`KAINE_STUDY=workspace_mediation_preliminary python -m kaine.cycle`) requires a configuration state that this repository's operator overlay disables for the requested study (operator config enables `[stimulus_control]`, which the workspace-mediation preliminary arm refuses) and would require changing protected operator configuration; that was not done. The vendor machinery that runs without touching protected refs is the offline positive-control ablation module:

```bash
python -m kaine.evaluation.benchmarks.oscillatory_ablation \
  --stimulus engineered \
  --out docs/records/oscillatory-ablation-positive-control-2026-11-16.jsonl
```

## Result

Exit code 0.

```
Oscillatory ablation: coherence layer ENABLED vs DISABLED
============================================================
seed=1234 ticks=16 gain=[0.05, 8.0] plv_window=12
selection_divergence_fraction = 0.3750
mean_ranking_divergence      = 0.5938
coherence_alignment_delta    = 0.3750
stimulus: engineered_phase_locked
VERDICT: WIN — coherence layer meaningfully changes selection toward the coherent coalition
```

## Named artifacts

- JSONL record: `docs/records/oscillatory-ablation-positive-control-2026-11-16.jsonl`
- No run ID was minted by this offline path (`run_id` is specific to the entity cycle's preliminary run, which was not executed).

## Next pilot steps (documented, not executed)

- Run the preliminary cycle once the operator configuration no longer blocks the study arm; mint the run ID under `data/evaluation/runs/<run_id>/manifest.json` and write `data/evaluation/positive_control/<run_id>/principal_component_{vision,audition,interoception}.json`.
- Set that run ID as `principal_components_run` in `config/studies/workspace_mediation_pilot_competitive.toml`.
- Run the three pilot studies on distinct seeds until at least 30 counted pilots, then author `PLAN.json` and run `python -m kaine.experiment.calibrate`.
