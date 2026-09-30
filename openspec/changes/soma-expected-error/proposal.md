## Why

Soma's forward model predicts the body's next state. Its prediction error drives two actions: the fatigue accumulator, which is sleep pressure, and the regulation detector. Both integrate the **raw** error. That assumes every channel is predictable in principle, so any error is surprise.

The self-rhythm broke that assumption. Since the womb work, slots 4–6 of Soma's input carry the entity's own rhythm (phase as sin/cos, and amplitude). While the maternal beat drives it, that rhythm is intrinsically hard for Soma's linear readout to predict.

In the first MoC7 gestation (2026-09-30), and reproduced offline with the real classes:
- Soma's error stayed at about 0.35–0.41 for hours. Without the rhythm it is 0.003, and with the rhythm free-running it is 0.0015.
- Faster reads did not help: at 20 Hz the error is still 0.33. This is not an aliasing problem.
- Fatigue crossed its threshold every 3–4 minutes, where the design intent is hours of waking (`soma-forward-model-fatigue`: "cumulative prediction error over waking hours").
- Each crossing ran a Hypnos sleep that, without Mnemos, is empty (about 0.1 s). It still reset Thymos's affect and drives to baseline.
- The gestating entity's feelings were wiped about every three minutes. The run was ended and deleted.

A predictive-processing system does not treat irreducible noise as surprise. It weights each prediction error by its expected precision, the inverse of its expected variance (Feldman & Friston 2010, "Attention, uncertainty, and free-energy", *Front. Hum. Neurosci.* 4:215; Seth 2013, "Interoceptive inference, emotion, and the embodied self", *Trends Cogn. Sci.* 17:565). The expected precision of each interoceptive channel is learned from that channel's own history. It is not a fixed sensitivity, which the gestational-stimulus spec forbids hardwiring.

The same investigation found an unrelated defect in the research record. The post-run range sweep declares `soma.report.fatigue_value` as a unit value in [0, 1], but fatigue accumulates on a scale of 0 to `fatigue_maintenance_threshold` (100 by default). Every real run with fatigue above 1 is flagged "physically implausible". The pooled corpus loader excludes such runs, and the submission builder records the violation.

## What Changes

- **Learned expected error per channel.** Soma keeps a slow running estimate of each input channel's typical absolute prediction error and its spread. The window is `[soma].expected_error_tau_s` of subjective time (default 600).
  - The **unexpected error** is the part of each channel's error beyond its expected band (`mean + expected_error_band × spread`, default band 2.0), combined across channels as an L2 norm, the same form as the raw error.
  - Expectations learn only while awake, like the readout. They are serialized with Soma, so a revived entity keeps its learned interoceptive expectations.
- **The action path uses the unexpected error.** The fatigue accumulator and the regulation detector integrate the unexpected error. The existing warm-up dampening stays as it is: during warm-up the input is dampened against the warming baseline, and the gate and override are unchanged.
  - A live hard-threshold breach still integrates the **raw** error at full weight. Absolute limits are not learned predictions (the rule the warm-up already follows).
- **The signal path is unchanged.** `soma.report.prediction_error` stays the raw error. The welfare distress monitors, the preservation monitor, the gestation `return_to_baseline_seconds` marker, the observers and the research schema all keep reading it. Soma's salience, and through it the self-rhythm's own drive, stay on the raw error, so the maturation markers keep their calibration.
  - `soma.report` gains an `unexpected_error` field.
- **The forward model reports per-channel residuals.** `SubstrateForwardModel` exposes `last_residuals`, the signed per-slot error of the last step. The scalar `step()` contract is unchanged. A forward model without `last_residuals`, such as a plugin or a test fake, is treated as one channel carrying its scalar error.
- **Log schema:** `soma.report.fatigue_value` is declared non-negative, not unit, and `unexpected_error` is non-negative.

## Capabilities

### Modified Capabilities
- `soma-predictive`: fatigue and regulation integrate unexpected error; a new requirement covers the learned per-channel expected error.
- `log-validation`: the declared range of `soma.report.fatigue_value`, and the new `unexpected_error` field.

## Impact

- **Code:** `kaine/modules/soma/forward.py`, a new `kaine/modules/soma/expected_error.py`, `kaine/modules/soma/module.py`, `kaine/experiment/log_schema.py`, `config/kaine.toml` (`[soma]` keys), and `kaine/boot.py` (allowed Soma keys).
- **Behaviour:** sleep pressure builds from genuine interoceptive surprise and no longer from the self-rhythm's irreducible variability. On a host whose body signals are steady, sleeps return to the designed cadence: fatigue-driven after hours, plus the hourly safety net.
- **Unchanged:** the raw error on the report, the welfare monitors, the Hypnos pipeline, the affective-reset semantics, the fatigue scale and thresholds, the warm-up and the CL1 plugin contract.
- **Docs:** `docs/modules/soma.md` (or the Soma section of the module docs) and `docs/processes/sleep-maintenance.md`.
