## 1. Implementation

- [ ] 1.1 Valence relaxes toward `pl + <w>_f - <w>_s` under `valence_rule = "error_dynamics"` (default), with wellness means that carry through sleep and persist; `"wellness_level"` keeps the previous rule bit for bit
- [ ] 1.2 Config key `[affect] valence_rule` in the factory and `config/kaine.toml`
- [ ] 1.3 Welfare observer writes the content-free `affect_welfare` record (negative-valence share of awake time, per-drive uncontrolled-end share and rate), with `[evaluation.welfare]` keys for the bar and the interval
- [ ] 1.4 Tests: falling error raises valence and rising error lowers it; bounded; old rule identical to origin/main over a multi-seed trace; welfare metrics from a synthetic run; records content-free; mutation checks
- [ ] 1.5 Docs: `docs/09-modules/affect.md`, welfare-records docs, configuration appendix
