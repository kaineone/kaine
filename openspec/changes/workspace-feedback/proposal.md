## Why

The paper (§3.2 "Workspace feedback (held extension)", §6.4, Table A1; predictive-workspace-paper #47) adds a held extension in which the workspace sends two signals back to the context-conditioned processors, after the predictive global neuronal workspace (Whyte and Smith 2021; Whyte, Hohwy and Smith 2022) and the neuronal workspace model (Dehaene, Kerszberg and Changeux 1998): a top-down prediction of each processor's next input, and a per-processor gain on its standardized error that conflict resolution shifts. In the first configuration the workspace sends no error signal or directive back to any module. The extension ships off, so the first configuration and the test of §6.3 are unchanged, and §6.4 plans a five-arm ablation of it on the §6.3 harness.

## What Changes

- New `[workspace.feedback]` table with one switch, `enabled = false`, and the ablation arm selector `arm`: `off` (the current build), `head_only`, `head_gain`, `full`, `matched_random`. Disabled, or with `arm = "off"`, no feedback object is built and every module and the workspace run the current code path, bit for bit.
- Top-down head (arms `head_only`, `head_gain`, `full`, `matched_random`). Vision, audition (the acoustic path) and interoception each get a linear head predicting the processor's next input from the context `b` (A.1) and the sequence module's predicted next broadcast featurization, plus a constant, as the interoceptive readout of A.5 stacks its regressor. It starts at zero and learns by one stochastic-gradient step on the mean squared error per input, rate `eta_fm`, skipped during sleep, like the forward model. The processor predicts with the blend of its own and the top-down prediction, each weighted by the inverse square of its running mean error over `W_P`; its reported error, error ratio, intensity and interoceptive residuals are the blend's. The null-context evaluation of A.8 forms the blend with `b0` in place of `b` in both predictions and the same weights.
- The sequence module, when feedback is on, publishes its predicted next broadcast featurization on its report; the workspace carries the latest one, with the gains, on each accessed broadcast, and the processors adopt both only from accessed broadcasts, as they adopt the context.
- Gain (arms `head_gain`, `full`, `matched_random`). Each processor's graded intensity uses `pi_j` times its error ratio, `pi_j` in `[pi_min, pi_max] = [0.8, 1.25]` (Table A1), the mean over the three processors held at one. Gains relax toward one with time constant `gain_relax_s` in entity time, which keeps the mean at one.
- Conflict (arms `full`, `matched_random`). A processor is in conflict when its accessed report has a disagreement `||z_top - z_own|| / mean error` of at least `disagreement_threshold` and an error ratio of at least `conflict_error_ratio`. Resolution moves `gain_step` of gain toward the accessed processor with the lowest precision-weighted error `pi_l * ratio_l` and away from the conflicting one, clipped so both stay in bounds. One episode per processor is in flight, followed by a refractory interval `refractory_s`. `matched_random` detects the same episodes and moves the same step between two processors drawn at random from a generator seeded by the run seed.
- `head_gain` moves gain without the conflict test: on each accessed broadcast with at least two accessed processors, `gain_step` moves toward the one with the lowest precision-weighted error and away from the one with the highest, under the same bounds and refractory interval.
- Feedback never acts on an inhibited broadcast: the workspace attaches nothing to it and moves no gain, and the processors adopt nothing from it.
- Five study files `config/studies/workspace_feedback_<arm>.toml` select the arms through the existing `KAINE_STUDY` overlay. The §6.3 study files are unchanged.

## Design values the paper does not fix (proposed for Table A1)

| Key | Meaning | Default |
| --- | --- | --- |
| `disagreement_threshold` | own and top-down disagreement over the mean error that counts as large | 2.0 |
| `conflict_error_ratio` | error ratio that counts as high (the ratio at which intensity reaches the alert level, `beta_Gamma`) | 2.0 |
| `gain_step` | gain moved per episode | 0.1 |
| `gain_relax_s` | gain relaxation time constant, entity seconds (`tau_f`) | 10.0 |
| `refractory_s` | interval before a processor can start another episode, entity seconds | 10.0 |
| `head_learning_rate` | top-down head learning rate (`eta_fm`) | 0.001 |

## Capabilities

### New Capabilities

- `workspace-feedback`: the held top-down feedback extension of the workspace and its ablation arms.

## Impact

- New `kaine/workspace/feedback.py` (settings and the workspace-side controller) and `kaine/modules/feedback.py` (top-down head, blend and the processors' feedback channel).
- `kaine/workspace/core.py`, `kaine/boot/wiring.py`, `kaine/boot/registry.py`, `kaine/cycle/__main__.py`, the vision, audition, interoception and sequence modules and their factories.
- `config/kaine.toml`, five new study files, docs for the global workspace and the four modules, new tests.
- Behaviour: none with the shipped configuration. Feedback refuses to run with the coherence layer, a non-competitive workspace arm, or the positive control of A.8 on. The top-down heads and gains are not preserved across boots.
