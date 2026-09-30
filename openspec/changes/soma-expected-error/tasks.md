## 1. Expected error
- [x] 1.1 `kaine/modules/soma/forward.py`: `SubstrateForwardModel` records `last_residuals` (signed `feature - last_prediction` per slot) on each step that computes an error. It is `None` before the first prediction and after a skipped non-finite tick. The scalar `step()` return is unchanged.
- [x] 1.2 New `kaine/modules/soma/expected_error.py` with an `ExpectedErrorModel`:
  - per-channel expected absolute error and spread (EWMA over `tau_s` of subjective time, `alpha = 1 - exp(-dt / tau_s)`);
  - `unexpected(residuals, dt, *, learn: bool) -> float`, using the band from before the update;
  - `state_dict` / `load_state_dict` holding scalars only, where a width mismatch or a bad value restores fresh estimates with a warning;
  - validation: `tau_s > 0`, `band >= 0`.
- [x] 1.3 `kaine/modules/soma/module.py`: build the model from `expected_error_tau_s` and `expected_error_band`. Each tick:
  - read `last_residuals`, falling back to `(prediction_error,)`;
  - compute `unexpected_error`, learning only when the forward model is not suspended;
  - set `action_error = prediction_error if hard_breach else unexpected_error`;
  - the fatigue input starts from `action_error`, and the warm-up dampening applies to it exactly as today;
  - regulation is updated with `action_error`;
  - `soma.report` gains `unexpected_error`.
  - Salience stays on the raw error. `serialize` / `deserialize` carry the estimates, and an absent key keeps fresh estimates.
- [x] 1.4 `config/kaine.toml` `[soma]`: `expected_error_tau_s = 600.0` and `expected_error_band = 2.0`, with comments. Add them to the allowed Soma keys in `kaine/boot.py`.

## 2. Research record
- [x] 2.1 `kaine/experiment/log_schema.py`: `soma.report.fatigue_value` is `NONNEG`, and `unexpected_error` is `NONNEG`.

## 3. Tests
- [x] 3.1 Unit tests for `ExpectedErrorModel`:
  - steady noise converges to near-zero unexpected error;
  - a spike far above the band counts;
  - band-before-update semantics;
  - no learning when `learn=False`;
  - round trip of `state_dict`;
  - fresh estimates on a bad state;
  - validation.
- [x] 3.2 Soma tests (fake forward models):
  - the report carries the raw `prediction_error` unchanged and `unexpected_error`;
  - steady residual variability stops accruing fatigue after the expectation is learned, while the raw error stays high;
  - a sustained spike accrues and crosses;
  - a hard breach integrates the raw error;
  - regulation uses the action error;
  - a forward model without `last_residuals` works as one channel;
  - serialize and deserialize round trip, with an old snapshot without the key restoring fresh estimates.
- [x] 3.3 An integration test with the real `SubstrateForwardModel` and a synthetic noisy periodic channel shows no fatigue crossing over a long simulated run. The same run on the raw error crosses repeatedly.
- [x] 3.4 Log schema: `fatigue_value = 57.3` passes, and a negative `unexpected_error` is a violation.
- [x] 3.5 The existing Soma, warm-up, regulation, Hypnos-trigger, self-rhythm and observer suites pass unchanged, or with changes justified in the PR.

## 4. Docs
- [x] 4.1 The Soma module doc and `docs/processes/sleep-maintenance.md` describe unexpected error and the two new settings. `docs/configuration.md` lists the settings.
