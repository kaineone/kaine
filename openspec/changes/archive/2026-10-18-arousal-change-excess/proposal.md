## Why

The paper (Appendix A.5 item 1, predictive-workspace-paper #47) now raises arousal on a perceptual alert by the excess of the larger of the report's error ratio and change ratio over 1: `a <- a + gamma_a * min(nu_cap, max(0, max(nu_tilde, c_tilde) - 1))`, and Appendix A.2 says each report carries `nu_t`, `nu_tilde_t` and `c_tilde_t`. The code reads only the error ratio. The locus coeruleus responds phasically to salient abrupt change in the environment as well as to unexpected outcomes (Bouret and Richmond 2009), and a live run showed that vision alerts are almost all change alerts with an error ratio near 0.99, so arousal never moved from its baseline.

## What Changes

- `vision.report` and `audition.perception` carry `normalised_change`, the change ratio the change alert already computes (the change score over the running mean of change scores, 0.0 when that mean is 0), on every published report, with forward prediction on or off.
- On an alert from vision or acoustic audition, the affect module raises arousal by `0.15 * min(4, max(0, max(r_err, r_chg) - 1))`, with `r_err` the report's `normalised_error` and `r_chg` its `normalised_change`. A missing, non-numeric or non-finite ratio counts as 0.0, so a report without `normalised_change` behaves as before.
- Non-alert reports still never raise arousal. `gamma_a = 0.15` and `nu_cap = 4.0` are unchanged.

## Capabilities

### Modified Capabilities

- `affect`: the perception-to-arousal coupling reads the change ratio as well as the error ratio.
- `vision`: `vision.report` carries `normalised_change`.
- `audition`: `audition.perception` carries `normalised_change`.

## Impact

- `kaine/modules/vision/module.py`, `kaine/modules/audition/module.py`, `kaine/modules/affect/module.py`, `docs/09-modules/affect.md`, `docs/09-modules/vision.md`, `docs/09-modules/audition.md`, tests for the three modules.
- Behaviour: change alerts now raise arousal in proportion to how far the change exceeds its running mean. Error alerts raise it exactly as before. The research event log allowlist (`kaine/evaluation/observers/research_event_observer.py`) is not changed here; `normalised_change` should be allowlisted for both report types in a coordinated change.
