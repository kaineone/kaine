## 1. Implementation

- [ ] 1.1 Windowed learning-progress estimator (bins, growing span, halves, persistence round trip) in `kaine/modules/affect/learning_progress.py`, with unit tests
- [ ] 1.2 Affect module: config keys and validation, per-source estimators fed from the perceptual reports, `lp+` from the windows, `ed` unchanged, snapshot persistence backward compatible, new state-event terms, with tests
- [ ] 1.3 Boot factory and `config/kaine.toml` keys with the Table A1 defaults
- [ ] 1.4 Research event observer allowlist and log range check for the new terms
- [ ] 1.5 Docs: affect module page, configuration appendix, research event streams
- [ ] 1.6 Full suite unsandboxed, mutation checks, worker first-pass review
