## Why

Paper PR #26 fixed every setting of the planned test by a rule stated in advance (§6.3, §9, Appendix A.8 "Settings from the pilot runs", Table A1), and §5.4 lists "the tool that derives the test's settings from the pilot runs" as work to finish before the live runs. The code did not follow those rules yet:

- the positive control projected the input on a random direction, used one signal-to-noise ratio for all processors, counted every awake report from the start of the run, and took `snr`, `min_effect` and `min_reports` as typed-in configuration keys;
- nothing derived the minimum effects, the learning period, the control's settings or the run count from pilot runs;
- the research log could not support those rules, because reports carried neither the entity time nor whether the entity was awake, and broadcasts did not carry the coalition capacity that decides whether a run is NOT EXERCISED;
- a live arm study booted with no record of its settings.

## What Changes

- New `kaine/experiment/calibration_rules.py`: the paper's fixed constants and pure rules, each citing its source. The exact binomial power of the sign test and the stable run count (102 at q = 0.65, power 0.9, alpha 0.05; Chernick and Liu 2002), the planned run count under attrition and the add-until-102 rule, the sample standard deviation and c_eff = 0.5 (Norman, Sloan and Wyrwich 2003; Lakens 2017), MSER-5 (White 1997; Hoad, Robinson and Davies 2010), Browne's (1995) upper confidence factor, Currie's (1968) detection term of n_PC, the log-linear SNR interpolation that fails closed when the ladder does not reach theta_PC, and quintile edges (Cochran 1968).
- New `kaine/experiment/principal_component.py`: a streaming estimator of the first principal component and mean of a processor's inputs (Jolliffe 2002), and the versioned file that records them with its sha256. No input is stored.
- New `kaine/experiment/calibrate.py` (`python -m kaine.experiment.calibrate PLAN --out PATH`): reads the preliminary run and the attempted pilot runs, checks their studies, seeds and film program, classifies NOT EXERCISED pilots, and writes one versioned settings record (`kaine/experiment/planned_test_settings.py`) with its inputs (run ids, seeds, manifest and record hashes), the tool version, the constants and every derived value: r_NE and n_run, T_learn, s_cal and theta_eff per control, theta_PC, min_effect = theta_PC / 2, SNR_j per processor, n_PC, and the principal-component files. A rule that cannot be applied fails closed: its value is null, `blocked` names the reason, and the record is incomplete.
- `kaine/experiment/planned_test_settings.py`: the record's schema, digest, loader and the boot check. A study named `workspace_mediation_*` must declare `[planned_test].role`. Roles `test` and `positive_control` refuse to boot (exit 12) without a complete record whose digest and principal-component files verify, or with a seed the preliminary or pilot runs used. Ordinary boots and other studies are untouched.
- The positive control has three modes. `estimate_pc` (the preliminary run) accumulates each processor's inputs and writes the principal-component file at shutdown. `ladder` (pilot runs of the on arm) runs informative and uninformative components at every SNR in {4^-2, ..., 4^4} and publishes one `positive_control.ladder` record per report. `control` reads SNR_j, min_effect, min_reports, T_learn and the principal components from the settings record and counts only reports after T_learn. The component is v_j^T (x - mu_j) plus noise. `snr`, `min_effect` and `min_reports` are no longer configuration keys.
- `python -m kaine.experiment.positive_control RUN_ID [RUN_ID ...]` pools consecutive complete control runs until each processor reaches min_reports, as the paper requires.
- Topos, Audition and Soma reports carry `entity_time_s` and `awake`; competitive and matched broadcasts carry `coalition_capacity`; the research log and the range sweep know the new fields.
- Studies may set `[planned_test]` and `[positive_control]`. New studies: `workspace_mediation_preliminary`, `workspace_mediation_pilot_competitive`, `_pilot_matched`, `_pilot_pooled` and `workspace_mediation_positive_control`; the three live arm studies declare role `test` and the record path.

## Review changes (independent second review, 2026-10-11)

- The boot gate keys on `[planned_test].role` whatever the study is called, maps each shipped workspace-mediation study to its role, refuses unknown `workspace_mediation_*` studies, and refuses a live test run that carries the positive control in a mode other than `control`.
- The loader checks the record's constants against the paper's (n_cal, c_eff, q_pow, power, alpha, the MSER settings, bins, ladder), n_counted == n_cal and n_exact == 102; the record's digest goes into the run manifest as `settings_record_sha256`, and the tool prints it for the preregistration.
- The positive control runs after the report is published, off the report path, one queued step per report in order. The tool records every pilot run's report rate and compares the on arm's mean rate with each control arm's, for inspection only: the paper has no rule on report rates, so nothing is blocked on them. The paper does not say where the ladder runs; it says only "Every pilot run of the on arm carries the two components of each processor at SNR in {4^-2, ..., 4^4}".
- A malformed or unfinished ladder blocks the SNR and the report count instead of stopping the tool. s2_j over the two bracketing rungs is documented as an approximation.
- The MSER-5 rule follows paper PR #27: the search runs over 0 <= d <= b - 5, and the pilots are too short when b < 10 or d* > b/2 for any arm and processor (`MSER_IGNORE_END = 5`, `MSER_MIN_BATCHES = 10`).

## Open questions (operator)

1. **theta_band and b_band** need the rdrobust package of Calonico, Cattaneo and Titiunik (2014), which is not in the environment, and the reports do not yet record which broadcast preceded each prediction. They, the age bins and the threshold contrast's minimum effect are recorded as blocked.
2. **The tone variant** of the on arm is not built and `audition.emotion` does not carry the tone model's error ratio, so the tone bins and the tone analysis's minimum effect are recorded as blocked.

Every record is therefore incomplete today, and the boot check refuses live runs, as the paper requires until every setting is recorded.

## Capabilities

### New Capabilities

- `planned-test-calibration`: the calibration tool, its rules, the settings record, and the boot check of the live planned-test studies.

### Modified Capabilities

- `information-gain-positive-control`: principal-component direction, the three modes, per-processor SNR, T_learn, settings from the record, pooled verdict.
- `research-event-log`: entity time and wakefulness on reports, ladder records, coalition capacity on broadcasts.
- `configuration-loading`: studies may set `[planned_test]` and `[positive_control]`; the repository ships the preliminary, pilot and positive-control studies.

## Impact

- New: `kaine/experiment/{calibration_rules,principal_component,planned_test_settings,calibrate}.py`, five study files, tests.
- Changed: `kaine/modules/positive_control.py`, `kaine/modules/{topos,audition,soma}/module.py`, `kaine/experiment/{positive_control,run_records,log_schema}.py`, `kaine/workspace/syneidesis.py`, `kaine/evaluation/observers/research_event_observer.py`, `kaine/config.py`, `kaine/cycle/__main__.py`, `config/kaine.toml`, the three arm studies, docs.
- Ordinary boots: reports gain two fields and broadcasts one; nothing else changes.
