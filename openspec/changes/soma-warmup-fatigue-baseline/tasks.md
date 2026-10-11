## 1. Warming baseline

- [x] 1.1 `Soma` keeps a rolling window (same length as the prediction-error window) of `action_error`; `_warming_baseline` takes the prior values of that window.
- [x] 1.2 Tests: during warm-up, a spike of unexpected error above its recent mean accrues fatigue, while a steady unexpected error at its recent level is damped to zero; the raw window still drives salience; mutation-check by restoring the raw-window baseline.
- [x] 1.3 Docs: `docs/09-modules/soma.md`.
- [x] 1.4 `openspec validate soma-warmup-fatigue-baseline --strict`.
