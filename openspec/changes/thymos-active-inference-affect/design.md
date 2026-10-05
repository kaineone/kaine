## Context

- Hesp, Smith, Parr, Allen, Friston and Ramstead, "Deeply Felt Affect" (Neural Comput 33(2):398–446, 2021): valence is inferred from affective charge, the update in expected policy precision. The reference code is MATLAB from SPM with no LICENSE, so it is for reference only.
- Pattisapu et al. (VERSES, arXiv 2407.02474, CC BY 4.0): the cheaper V = U − EU and A = H[Q(s|o)] readouts. The authors note the model is non-hierarchical and does not directly invoke policy selection.
- Grimbly et al. (SAB 2026, arXiv 2608.04232, MIT code in JAX and pymdp ≥ 1.0.2): routing a fixed precision budget by homeostatic deficit. It supports precision-as-allocation, not specifically the paper's arousal-sets-precision commitment.

## Shadow readouts

- **Where.** In Thymos, from the same broadcast the appraisal reads. When Nous is enabled, `U` and `EU` come from Nous's preference vector `C` and its predicted observations (an injected read-only provider). When Nous is off, a minimal interoceptive model is used: categorical Soma bands with preferences at the homeostatic set points. Which of the two becomes primary is an open item.
- **Output.** `thymos.shadow_affect` on `thymos.out` carries `{valence_shadow, arousal_shadow, model}`. It is content-free and excluded from salience and from every consumer except the research log.
- **Offline comparison.** On recorded runs, the correlation and lag between the shadow readouts and today's valence and arousal; the shadow readouts' response to marked surprises; and the stability of their range.

## Gate

The ablation runs on the current Thymos first. Then shadow readouts can ship off by default. A switch needs its own change, the paper note and a re-baselined study.
