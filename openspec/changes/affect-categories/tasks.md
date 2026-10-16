## 1. Implementation

- [ ] 1.1 Replace the norm requirement in `classify()`'s disgust rule with the Table 3 profile (very low pleasantness, novelty above 0.3, low goal relevance), checked after fear and anger, and cite Table 3 in the docstring
- [ ] 1.2 Remove the stale comments in `appraisal.py` and `module.py` that say disgust waits on norm signals and anger is unreachable; keep `norm_compatibility_available` false
- [ ] 1.3 Tests: disgust reachable from the Table 3 profile with norm 0; disgust not returned for relevant or merely unpleasant content; every other category unchanged
- [ ] 1.4 Docs: the novelty-to-familiarity mapping and the disgust and anger rules in `docs/09-modules/affect.md`
