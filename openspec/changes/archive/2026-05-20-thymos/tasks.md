## 1. Package skeleton

- [ ] 1.1 Add `kaine.modules.thymos` to setuptools packages
- [ ] 1.2 Add `[thymos]` block to `config/kaine.toml` (full keys per spec); add `thymos = false` under `[modules]`

## 2. Dimensional state

- [ ] 2.1 Implement `kaine/modules/thymos/state.py` with `DimensionalState` dataclass + drift helper + clamping
- [ ] 2.2 Tests covering clamping, drift convergence, baseline reset

## 3. Goals

- [ ] 3.1 Implement `kaine/modules/thymos/goals.py` with `Goal` dataclass + `GoalLedger` (add/complete/abandon + `relevance(event)` via token overlap weighted by priority)
- [ ] 3.2 Tests covering lifecycle, relevance scoring, completed goals excluded from relevance

## 4. Appraisal

- [ ] 4.1 Implement `kaine/modules/thymos/appraisal.py` with `CategoricalEmotion` enum, five `Check` callables (novelty, intrinsic_pleasantness, goal_significance, coping_potential, norm_compatibility), and `classify(scores) -> CategoricalEmotion` pure function
- [ ] 4.2 Tests covering each emotion's region of the score space and the neutral fallback

## 5. Drives

- [ ] 5.1 Implement `kaine/modules/thymos/drives.py` with `Drive` dataclass + `DriveSet` (four drives, tick, hysteresis-respecting threshold crossing report)
- [ ] 5.2 Tests covering build rate, decay, threshold crossing, hysteresis

## 6. Regulation + modulator

- [ ] 6.1 Implement `kaine/modules/thymos/regulation.py` with `RegulationPolicy` protocol + `PassiveDecay` default
- [ ] 6.2 Implement `kaine/modules/thymos/modulator.py` with `StateModulator` implementing Syneidesis's `ThymosModulator` protocol; higher-arousal-strictly-larger requirement
- [ ] 6.3 Tests for both

## 7. Module

- [ ] 7.1 Implement `kaine/modules/thymos/module.py` with `Thymos(BaseModule)` — subscribes to soma.out (wellness → state nudge), chronos.out (TSLI → social_drive), mnemos.out (recall affect → state nudge); runs Scherer CPM on each workspace broadcast and publishes thymos.emotion / thymos.state / thymos.drive / thymos.goal events; affective_reset entry point
- [ ] 7.2 Update `kaine/modules/__init__.py` to export `Thymos` plus the public `CategoricalEmotion`, `Goal`, `GoalLedger`, `DimensionalState`

## 8. Module tests

- [ ] 8.1 `tests/test_thymos_module.py` (fakeredis): workspace broadcast → appraisal runs, emotion published if changed; soma.out wellness nudges state; chronos.out TSLI grows social_drive; mnemos.recall raises arousal; goal add/complete publishes thymos.goal; affective_reset zeroes state

## 9. Verification + tag

- [ ] 9.1 Full unit suite passes
- [ ] 9.2 `openspec validate thymos --strict` clean
- [ ] 9.3 Commit, merge, archive change, drop branch
- [ ] 9.4 Tag `v0.4-motivation` (closes Phase 4)
