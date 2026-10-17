## 1. Regulation policy

- [x] 1.1 `ThreeTierRegulation`: episode, window and tier rule of A.5 on intensity and a negative appraisal; per-source intensity mass of negatively appraised coalitions; tests
- [x] 1.2 Keep `PassiveDecay` as the off arm

## 2. Affect module

- [x] 2.1 Run the monitor on each update and fire tier 1 (publish the target, bias and decay), tier 2 (one reappraisal per episode, replacing the categorical emotion with the re-run result) and tier 3 (a maintenance request), each published as `affect.regulation` with its size
- [x] 2.2 Off during the developmental phase through an injected probe; wiring helper re-run on a supervisor rebuild
- [x] 2.3 `[affect.regulation]` keys in the factory and `config/kaine.toml`; `policy = "passive"` bit-for-bit as before

## 3. Selection and sleep

- [x] 3.1 `RegulationBias` in the workspace: read tier-1 events from the candidates, multiply the target source's scores by `1 - b_E exp(-(t - t1) / tau_E)`, record it in the broadcast metadata
- [x] 3.2 `[workspace].regulation_bias` gate; every workspace-mediation study config sets it false; the ranking invariant holds in the study arms
- [x] 3.3 The sleep module's maintenance consumer accepts the affect module's `request_maintenance`

## 4. Tests and docs

- [x] 4.1 Tests: no-op below the set point or with a non-negative appraisal; each tier; the bias bounded and decaying; neutral in the study arms; off before maturation; passive identical to today
- [x] 4.2 Docs: affect, workspace and sleep pages and the configuration reference
