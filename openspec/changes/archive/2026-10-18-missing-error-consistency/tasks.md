## 1. Wetware Interoception backend

- [x] 1.1 `WetwareInteroceptiveModel` exposes `last_reading_skipped` and `last_error_defined`, clears its prediction and hidden state on a non-finite reading, and marks that reading and the next one as having no defined error; `reset()` clears the flags
- [x] 1.2 The interoception module reports an unexpected error of 0 and does not learn for a reading without a defined error from a model without per-channel residuals
- [x] 1.3 Tests: the plugin's wetware tests cover the skip, the reading after it, the first reading and `reset()`; the interoception module's expected-error tests cover the scalar model
- [x] 1.4 Plugin spec delta and docs (`docs/19-plugins-and-cl1.md`, `docs/09-modules/interoception.md`)

## 2. Social cognition merge

- [x] 2.1 `SocialCognitionMergeStrategy` treats a missing or null `behavioral_summary` entry as absent and averages only the defined ones
- [x] 2.2 Tests: one side missing, one side null (both orders), both missing, both defined, and a defined side with no interactions
- [x] 2.3 Docs (`docs/12-forks-and-merges.md`, `docs/09-modules/social-cognition.md`)
