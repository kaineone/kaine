## 1. Estimator

- [x] 1.1 `kaine/experiment/rd_robust.py`: local-polynomial fits, conventional and bias-corrected estimates as linear weights, nearest-neighbor, plug-in and clustered variances, robust interval
- [x] 1.2 MSE-optimal bandwidth selector of CCT Supplement S.2.6
- [x] 1.3 Tests against black-box reference values, the paper's population bandwidths and Monte Carlo averages, and exact cases

## 2. Contrast at threshold

- [x] 2.1 `kaine/experiment/threshold_contrast.py`: observations from the logs, per-run and per-bin estimates, run contrast, pooled clustered interval, verdict
- [x] 2.2 Tests on synthetic logs with a known jump

## 3. Calibration

- [x] 3.1 theta_band, b_band, age bins and the contrast's minimum effect; nothing always blocked
- [x] 3.2 Loader requires the four values
- [x] 3.3 Tests: a complete record on synthetic pilot data

## 4. Docs

- [x] 4.1 Experiments and researchers pages
