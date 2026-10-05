## Why

Thymos is the precision core of the workspace competition: its arousal sets the gain on prediction errors. The paper describes its appraisal "following the account in which affect arises from prediction over the body's internal state" (Seth 2013; Seth and Friston 2016; Tschantz et al. 2022). The implementation is a hand-written cascade over salience statistics (`thymos/appraisal.py`), and Thymos publishes no prediction error of its own (alternatives review 2026-10-05, §2.3 item 3, §5.2). Its goal check was fixed separately (`thymos-goal-check`). The rest stays an engineering stand-in.

**Design document only.** Nothing here is built until the workspace-mediation ablation has run on the current Thymos. Changing the precision term changes what every experiment tests.

## What Changes

A design for computing valence and arousal from the entity's own inference, introduced in two steps:

1. **Shadow readouts.** Thymos computes the Pattisapu et al. (arXiv 2407.02474, CC BY 4.0) readouts beside the current appraisal and logs them as content-free shadow signals. They drive nothing.
   - **Valence:** `V = U − EU`, where `U = log P(o_t | C)` is the log-preference of the current observation and `EU` is its expectation under the predicted observation distribution.
   - **Arousal:** `A = H[Q(s | o)]`, the posterior entropy.

   Offline analysis compares the shadow readouts with the current appraisal on recorded runs.
2. **The switch.** Only through a later OpenSpec change, with a paper revision note and a re-baselined study, may the readouts replace the cascade.

**Open items recorded here, not decided:**
- **Social drive from isolation since spawn.** Today `time_since_last_interaction_s` is `inf` until the first operator speech, and Thymos ignores `inf`, so the social drive never builds in a run with no operator speech. Whether isolation since spawn should raise it is a new affect rule with welfare weight, because studies never have operator speech. It belongs to this design, not to a code fix. It was deferred from `chronos-forward-model-on`, where D3 kept the behaviour unchanged.
- **The generative model.** The readouts need a generative model with preferences `C`, which naturally means Nous. Nous is off in base-thesis. Either Thymos keeps a minimal interoceptive generative model of its own, or the readouts exist only when Nous is on.

## Impact

- Code: none in this change.
- Research: the design defines the shadow-readout instrument for after the ablation.
- Paper: none until the switch.
