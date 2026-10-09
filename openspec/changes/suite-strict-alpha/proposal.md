## Why

The offline suite's workspace-mediation verdict calls a result significant when the sign-test p-value satisfies `p <= alpha` (`kaine/evaluation/benchmarks/suite.py:233`), while the Holm correction the suite reports beside every verdict rejects only when the adjusted value satisfies `p < alpha` (`kaine/experiment/multiple_comparisons.py`), and the active-inference verdict already uses `<`. Two rules for one decision in one report invite a verdict and its adjusted value to disagree at the boundary. The mathematics review of 2026-10-08 flagged the mismatch.

## What Changes

- The suite's mediation WIN requires `pvalue < alpha`, the same strict inequality Holm and the active-inference verdict use. The verdict detail text says `<`.

## Capabilities

### Modified Capabilities

- `workspace-mediation-ablation`: the suite-level significance rule.

## Impact

- **Code:** `kaine/evaluation/benchmarks/suite.py`.
- **Behaviour:** none in practice today, because a sign-test p-value is `k/2^n` and never equals 0.05. The rule is now consistent for any future test or alpha.
- **Paper:** none; Appendix A.8 already states Holm's rule.
