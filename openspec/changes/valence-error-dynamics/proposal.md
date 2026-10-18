## Why

The paper (§3.5 and Appendix A.4, predictive-workspace-paper #47) grounds valence in error dynamics: valence is the negative rate of change of free energy (Joffily and Coricelli 2013), positive while prediction errors fall and negative while they rise, with a steady state neutral (Van de Cruys 2017; Kiverstein, Miller and Rietveld 2019). The pleasantness check already follows the signed fall of the perceptual errors, but valence also relaxed toward the wellness level, `pl + (w - 0.5)`. A level is not a rate. In the fourth test boot the host stayed healthy (w near 0.88), so valence sat near +0.38 for the whole run, never went below zero, and the error-dynamics term (about plus or minus 0.05) was swamped. The welfare records also had no measure of how much awake time the entity spends in negative valence, or of how often its drives end without its own response, the response-independent outcomes that define helplessness (Maier and Seligman 2016).

## What Changes

- Valence relaxes toward `v_inf = clip(pl + <w>_f - <w>_s, -1, 1)`, where `<w>_f` and `<w>_s` are the fast and slow time-decayed means (tau_f, tau_s, the error-mean time constants) of the reported wellness. Wellness enters as its change, the dynamics of the homeostatic error, so a steady host is neutral. The difference is 0 before any wellness report. The relaxation constant tau_v is unchanged.
- The wellness means carry through the sleep reset with the error means (A.4 item 4) and persist with the module state.
- A new `[affect] valence_rule` key selects the rule: `"error_dynamics"` (default) or `"wellness_level"`, the previous rule, which then behaves bit for bit as before.
- The welfare observer writes a content-free `affect_welfare` record to its JSONL log every `[evaluation.welfare].affect_summary_interval_s` (default 300 s of unfrozen time) and when it stops: the share of awake time with valence below `-negative_valence_bar` (default 0.5, the regulation set point theta_E), and per drive the share of goal ends credited "other" (`without_response`) against those credited "own" (`own_response`) by the A.4 credit rule, with the rate of "other" ends per awake hour. Rates and shares only.

## Capabilities

### Modified Capabilities

- `affect`: valence follows error dynamics, including the change in wellness.
- `evaluation-observers`: the welfare log gives a negative-valence share and per-drive uncontrolled-end shares.

## Impact

- `kaine/modules/affect/module.py`, `kaine/boot/factories/affect.py`, `config/kaine.toml`, `kaine/evaluation/config.py`, `kaine/evaluation/observers/welfare_observer.py`, `docs/09-modules/affect.md`, `docs/17-research-data/README.md`, `docs/appendix-a-configuration/lifecycle-and-research.md`, new tests.
- Behaviour: with a steady healthy host, valence now rests near 0 instead of near +0.4 and moves with the entity's own error dynamics. Selecting `wellness_level` restores the previous valence exactly.
