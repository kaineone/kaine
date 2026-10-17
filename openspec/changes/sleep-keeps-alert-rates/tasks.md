## 1. Implementation

- [ ] 1.1 Stop clearing the alert rates, the error means, the intent rate and the intent count in `affective_reset()`
- [ ] 1.2 Tests: the reset keeps them, a habituated stream stays habituated after sleep, the next report re-weights the error means by the elapsed time, boredom is not relieved by the reset, everything else still resets; update tests that assumed the old reset
- [ ] 1.3 Update `docs/09-modules/affect.md`; run the affect, sleep and resume tests and the full suite
