## Why

The planned test has a tone analysis (paper §6.3 "Speech sound and tone of voice", Appendix A.8 "Speech sound and tone"). Audition reports a non-neutral tone at its alert intensity (A.2), which builds a preference for emotional tone into the competition. "In a variant of the on arm the tone rule of A.2 is replaced by I(e) = Gamma_Aud(nu~utt_t) for every tone event. The analysis compares the fraction of emotional tone events that are accessed content with the fraction of neutral ones, and across runs it uses a sign test of the same form." Its bins and minimum effect are fixed from the pilot runs, and the pilot runs include the tone variant: "n_cal = 30 paired pilot runs of the three arms and of the tone variant".

None of it was built. The variant did not exist, `audition.emotion` did not carry nu~utt_t, the research log could not tell which tone events were accessed content, and the calibration tool recorded the tone settings as blocked.

## What Changes

- Audition computes the tone path's running error ratio nu~utt_t as A.2 defines it (0 when the error is not defined) and sets each tone event's intensity by `[audition].tone_rule`: `categorical` (default, A.2) gives a non-neutral tone the alert level and a neutral one Gamma_Aud(nu~utt_t); `error_ratio` (the tone variant, A.8) gives every tone event Gamma_Aud(nu~utt_t) and marks none as an alert, so no tone event drives the phasic access rate by category either. `audition.emotion` carries `normalised_error` (nu~utt_t), `tone_rule` and `classified` (false for a failed or degraded classification, which is not a classified tone).
- Studies may set `[audition].tone_rule` and no other `[audition]` key. New studies `workspace_mediation_pilot_tone` (role pilot) and `workspace_mediation_tone` (role test) run the on arm with `tone_rule = "error_ratio"`; the boot gate refuses a workspace-mediation study whose tone rule is not its own.
- The research log keeps the bus entry id of each `audition.emotion` record and of each broadcast member, and copies `normalised_error`, `tone_rule`, `classified` and `alert` from `audition.emotion`. A tone event is accessed content when it is a member of an accessed broadcast whose score reaches the access threshold (A.1). The range sweep bounds `normalised_error` below by 0.
- New `kaine/experiment/tone_analysis.py`: the tone events of a run, the accessed fractions, the run-level statistic (the fraction of emotional tone events that are accessed content minus the fraction of neutral ones) and the verdict across runs by the sign tests of the decision rule (A.8). The exact sign test and its verdict live in `calibration_rules.py`, so the threshold contrast can share them.
- The calibration tool accepts a tone-variant run in each pilot, checks its study, seed, film program and tone rule, records it with the other runs, and sets the tone analysis's minimum effect: c_eff times the standard deviation of the run-level statistic over the counted pilots, leaving out runs in which it is undefined. The loader accepts the tone runs and, for a complete record, requires them and the tone settings.

## Not changed, open for the operator

- **Tone bins.** A.8: "the tone bins are the quintiles of nu~utt_t over the tone events of the pilot runs". The pilot runs are the three arms and the tone variant. The text does not say whether the quintiles pool the tone events of every pilot run or only those of the tone-variant pilots, whose events the analysis bins. Recommendation: the tone-variant pilots only. Subclassification (Cochran 1968) sets the subclass boundaries from the distribution of the covariate in the groups being compared, and only the tone variant's events are compared. `tone_bins` stays blocked until this is decided.
- **The within-bin comparison.** "The same comparison within bins of nu~utt_t checks that the ratio accounts for it." The paper does not say how the bins enter across runs. One reading runs the run-level statistic and its sign test separately in each bin; the other averages the within-bin differences of each run into one adjusted statistic, as the contrast at threshold averages its per-bin estimates, which is also how Cochran (1968) combines subclasses. The paper names one minimum effect for the tone analysis, which fits the second reading better. Recommendation: the second reading, with an unweighted mean over the bins in which both emotional and neutral events occur, mirroring the contrast at threshold. It is not implemented until decided.
- **Live run count of the tone variant.** A.8 sets n_run for the arms; it does not say how many live runs of the tone variant enter its sign test. Recommendation: the same planned count, run in pairs with the arms.

## Capabilities

### New Capabilities

- `planned-test-calibration`: the tone variant's pilot runs, the tone analysis's minimum effect and the tone analysis.

### Modified Capabilities

- `audition-predictive`: the tone rule and the tone error ratio on `audition.emotion`.
- `research-event-log`: entry ids of tone events and broadcast members; the tone fields.
- `configuration-loading`: studies may set `[audition].tone_rule`; the tone studies.

## Impact

- New: `kaine/experiment/tone_analysis.py`, two study files, tests.
- Changed: `kaine/modules/audition/module.py`, `kaine/boot/factories/audition.py`, `kaine/config.py`, `config/kaine.toml`, `kaine/evaluation/observers/research_event_observer.py`, `kaine/experiment/{log_schema,calibration_rules,calibrate,planned_test_settings}.py`, docs.
- Ordinary boots keep the categorical rule. A neutral tone's intensity now follows Gamma_Aud exactly: a report whose error is not defined gets the baseline level, where the old code scaled the raw error.
