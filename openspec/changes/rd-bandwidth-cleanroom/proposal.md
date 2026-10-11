## Why

The contrast at threshold of the planned test (paper §6.3, Appendix A.8) is a sharp regression discontinuity: the jump of the mean gain of the reports that follow a broadcast at S*_k = theta, estimated per run and age bin by a local-linear fit with a triangular kernel of half-width theta_band, corrected for its leading bias by a local-quadratic fit of half-width b_band (Calonico, Cattaneo and Titiunik 2014), with theta_band and b_band the MSE-optimal bandwidths computed on the pilot runs. The authors' software is GPL-3.0-only, which CAL 0.4 cannot take as a dependency, so the operator approved a clean-room implementation written only from the published paper and its supplement. Until it existed, theta_band, b_band, the age bins and the contrast's minimum effect were always blocked, so no settings record could be complete.

## What Changes

- New `kaine/experiment/rd_robust.py`, written from CCT (2014, Econometrica 82(6)) and its Supplemental Material only: local-polynomial fits on each side of the cutoff with the triangular kernel; the conventional and bias-corrected estimates (Section 2.1, Appendix A.2), both as linear weights on the outcome; their variances with nearest-neighbor (Section 5, Abadie and Imbens 2006, J = 3) or plug-in-residual (Supplement S.2.4) estimates, and a run-clustered (Liang and Zeger) variance with the same residuals; the robust confidence interval (Theorem 1); and the data-driven MSE-optimal bandwidths of Supplement S.2.6 (Steps 0 to 2).
- New `kaine/experiment/threshold_contrast.py`: from a run's research log, the broadcasts' running variable S*_k - theta, the included reports that follow each broadcast (by `prediction_broadcast_tick`), the per-broadcast observations for the bandwidths, the ages for the bins, the per-run and per-bin bias-corrected jumps, the run contrast (the mean over the bins that can be fitted), the run-clustered interval per bin pooled over runs, and the sign-test verdict.
- The calibration tool computes theta_band and b_band on the pooled on-arm pilot broadcasts, the age bins as quintiles of the context age over reports following near-threshold broadcasts, and the contrast's minimum effect as c_eff times the pilot SD of the run contrast. Nothing is always blocked any more: a complete record is possible. The loader requires the four values.

## Implementation choices the paper leaves open (operator to confirm)

- **Regularization scale in the bandwidth selector.** S.2.6 adds 3 V_hat to a squared coefficient difference, while V_hat carries the derivative factor (p+1)!^2. With V_hat as printed the selector's averages are half those CCT report in Table S.A.II; on the coefficient scale (V_hat / (p+1)!^2) they match (400 replications: Model 1 0.207 and 0.337 against the published 0.204 and 0.332; Model 2 0.097 and 0.224 against 0.097 and 0.223, all within 1.5 Monte Carlo standard errors). The coefficient scale is used.
- **Nearest neighbors.** J = 3, as in CCT's main simulations (Table S.A.II); ties at the J-th distance are all matched (Abadie and Imbens 2006); neighbors are taken over the whole side, as CCT define them.
- **Clustered interval.** CCT 2014 does not treat clustering. The interval uses the Liang-Zeger sandwich over runs with the residuals of the local-quadratic fit at b_band (with h = b these are the local-quadratic estimator's own residuals, CCT Remark 7) with the CR1 small-sample adjustment G/(G-1) (N-1)/(N-K) of Cameron and Miller (2015, Journal of Human Resources 50(2), doi:10.3368/jhr.50.2.317), N the units of positive weight, G their runs and K the parameters of the two side fits. The intervals are only reported and do not enter a test.
- **Fit identification.** A side "can be fitted" when its weighted least-squares fits are identified (at least p + 1 distinct scores within theta_band and q + 1 within b_band).

## Validation

- Point estimates and plug-in and nearest-neighbor standard errors match, to 1e-9 relative, reference values produced by running the authors' GPL package (rdrobust 2.1.1) as a black box in a separate virtual environment outside the repository, on four synthetic datasets regenerated deterministically by the tests. Only output numbers were kept; its source and documentation were not read or copied. Its nearest neighbors are taken inside the bandwidth window; the tests pass that window to match it exactly and check that the paper's whole-side definition differs by less than 0.1 percent.
- The bandwidth formula reproduces CCT's population MSE-optimal bandwidths (Tables S.A.I and S.A.II, Models 1 and 2), and the data-driven selector reproduces their Monte Carlo averages within Monte Carlo error.
- The threshold contrast recovers a known jump exactly on synthetic logs.

## Capabilities

### Modified Capabilities

- `planned-test-calibration`: the threshold band, bias bandwidth, age bins, minimum effect and the contrast at threshold itself.

## Impact

- New: `kaine/experiment/rd_robust.py`, `kaine/experiment/threshold_contrast.py`, `tests/data/rd_robust_reference.json`, tests.
- Changed: `kaine/experiment/calibrate.py`, `kaine/experiment/planned_test_settings.py`, `.github/slow-test-paths.txt`, docs.
