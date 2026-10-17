## 1. Implementation

- [ ] 1.1 Add `drive_arousal_gain` (gamma_D, default 0.2, validated in [0, 1]) to `Affect` and relax arousal toward `a_0 + gamma_D (1 - a_0) v*`, `v*` the largest drive value at the start of the update; dominance keeps relaxing toward its baseline
- [ ] 1.2 Wire `[affect].drive_arousal_gain` through the factory and `config/kaine.toml`
- [ ] 1.3 Tests: target values, deprived and satisfied rest, phasic steps unchanged, sleep reset, gain 0 identical to the old rule, validation, config wiring; mutation checks
- [ ] 1.4 Update `docs/09-modules/affect.md` and `docs/appendix-a-configuration/modules.md`; run the affect tests, `tests/test_resume_checkpoint*.py` and the full suite
