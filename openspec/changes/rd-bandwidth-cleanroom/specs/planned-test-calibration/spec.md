## ADDED Requirements

### Requirement: Robust bias-corrected regression discontinuity, written from the paper
`kaine/experiment/rd_robust.py` SHALL implement, from Calonico, Cattaneo and Titiunik (2014) and its Supplemental Material only, the local-linear estimate of the jump at the cutoff with the triangular kernel, its local-quadratic bias correction, the conventional and robust standard errors with nearest-neighbor or plug-in-residual variance, a run-clustered variance, the robust confidence interval, and the MSE-optimal bandwidths of Supplement S.2.6. It SHALL take no dependency on the authors' software.

#### Scenario: A linear outcome with a jump
- **WHEN** the outcome is a linear function of the running variable plus a jump of 0.5 at the cutoff
- **THEN** the conventional and bias-corrected estimates equal 0.5 for any bandwidths

### Requirement: The contrast at threshold and its settings
The calibration tool SHALL compute theta_band and b_band on the pooled on-arm pilot broadcasts that have a following included report (one observation each, the mean gain of those reports), the age bins as quintiles of the context age over the included reports that follow broadcasts within theta_band of the threshold, and the contrast's minimum effect as c_eff times the sample SD of the run contrast over the counted pilots, leaving out undefined ones. A side of a bin SHALL count as fittable only when it holds at least 10 distinct scores within theta_band and within b_band and each weighted least-squares problem, with the score scaled by its bandwidth, has a condition number of at most 10^8. The run contrast SHALL be the mean, over the age bins whose two sides can be fitted, of the bias-corrected jump of the per-broadcast mean gain at S*_k = theta, with bandwidths theta_band and b_band. The analysis SHALL report, for each bin, the robust interval of the estimate pooled over runs with standard errors clustered by run (the joint Liang-Zeger sandwich with the CR1 factor G/(G-1)(N-1)/(N-K), K = 6 for the robust variance), and the verdict of the decision rule's sign tests on the run contrasts.

#### Scenario: Complete pilot data
- **WHEN** the plan has counted pilots with tone runs and on-arm logs that record the preceding broadcast of each report
- **THEN** the settings record has no blocked value and is complete
