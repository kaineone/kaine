## 1. Strict significance

- [x] 1.1 `suite.py`: the mediation WIN condition uses `pvalue < config.alpha`, and the detail text prints `<`.
- [x] 1.2 Test: a mediation result whose sign-test p-value equals alpha exactly is not a WIN (mutation-check by reverting to `<=`).
- [x] 1.3 `openspec validate suite-strict-alpha --strict`.
