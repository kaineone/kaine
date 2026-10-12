## Why

The planned test has a tone analysis (paper §6.3 "Speech sound and tone of voice", Appendix A.8 "Speech sound and tone"). Audition reports a non-neutral tone at its alert intensity (A.2), which builds a preference for emotional tone into the competition. "In a variant of the on arm the tone rule of A.2 is replaced by I(e) = Gamma_Aud(nu~utt_t) for every tone event. The analysis compares the fraction of emotional tone events that are accessed content with the fraction of neutral ones, and across runs it uses a sign test of the same form." Its bins and minimum effect are fixed from the pilot runs, and the pilot runs include the tone variant: "n_cal = 30 paired pilot runs of the three arms and of the tone variant".

None of it was built. The variant did not exist, `audition.emotion` did not carry nu~utt_t, the research log could not tell which tone events were accessed content, and the calibration tool recorded the tone settings as blocked.

## What Changes

- Audition computes the tone path's running error ratio nu~utt_t as A.2 defines it (0 when the error is not defined) and sets each tone event's intensity by `[audition].tone_rule`: `categorical` (default, A.2) gives a non-neutral tone the alert level and a neutral one Gamma_Aud(nu~utt_t); `error_ratio` (the tone variant, A.8) gives every tone event Gamma_Aud(nu~utt_t) and marks none as an alert, so no tone event drives the phasic access rate by category either. `audition.emotion` carries `tone_error_ratio` (nu~utt_t), `tone_rule` and `classified` (false for a failed or degraded classification, which is not a classified tone).
- Studies may set `[audition].tone_rule` and no other `[audition]` key. New studies `workspace_mediation_pilot_tone` (role pilot) and `workspace_mediation_tone` (role test) run the on arm with `tone_rule = "error_ratio"`; the boot gate refuses a workspace-mediation study whose tone rule is not its own.
- The research log keeps the bus entry id of each `audition.emotion` record and of each broadcast member, and copies `tone_error_ratio`, `tone_rule`, `classified` and `alert` from `audition.emotion`. A tone event is accessed content when it is a member of an accessed broadcast whose score reaches the access threshold (A.1). The range sweep bounds `tone_error_ratio` below by 0.
- New `kaine/experiment/tone_analysis.py`: the tone events of a run, the accessed fractions, the run's difference (the fraction of emotional tone events that are accessed content minus the fraction of neutral ones), the adjusted difference over the tone bins, and the verdict of each across runs by the sign tests of the decision rule (A.8). The exact sign test and its verdict live in `calibration_rules.py`, so the threshold contrast can share them.
- The calibration tool accepts a tone-variant run in each pilot, checks its study, seed, film program and tone rule, records it with the other runs, and sets the tone bins and the minimum effects of both tone tests. The loader accepts the tone runs and, for a complete record, requires them and the tone settings.

## Settled by paper PR #30

The first version left three questions open. Paper PR #30 settled them, and this change follows it:

- **Tone bins.** "The tone bins are the quintiles of nu~utt_t over all tone events, emotional and neutral together, in the pilot runs of the tone variant." The tool takes them over the classified tone events of the counted pilots' tone-variant runs. A ratio equal to an edge falls in the bin above it.
- **Two tests.** "The adjusted difference of run r is the mean, over the bins that hold both emotional and neutral tone events, of the difference of the two fractions within the bin, and it is undefined when there is none. It enters a second sign test of the same form, and the bins are not tested separately." Each test's minimum effect is c_eff times the pilot standard deviation of its own run-level statistic. Both tests are made at alpha_test without multiplicity adjustment, because the tone analysis, like the contrast at threshold, stays outside the verdict on the thesis.
- **Runs.** "Run r of the variant uses the seeds of run r of the arms." The first test has the WIN test's power function, so n_exact is 102 and the variant is planned with the arms' n_run; runs are added until at least 102 give a defined difference (`tone_runs_still_needed`).

## Second-review changes

- The tone ratio is published as `tone_error_ratio`. The affect module reads any member's `normalised_error` as appraisal novelty, so a tone event never carries that key, and the default build's affect module novelty is as on main.
- Under `error_ratio` a failed classification is graded by the ratio like every other tone event (A.8, "for every tone event"); under the default rule it keeps the alert level.
- The analysis refuses a broadcast whose members share an entry id, because the cycle keys scores by entry id alone. It adopts the stream-and-id key once the `salience-score-keys` change merges.
- The calibration tool refuses an arm pilot whose tone events carry the variant's rule.

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
