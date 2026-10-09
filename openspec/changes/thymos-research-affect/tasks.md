## 1. Drives

- [x] 1.1 `Drive.tick` uses the exact exponential solution; `Drive.relieve(c)`; `relief_gain` field; `DriveSet.relieve(name, c)`.
- [x] 1.2 The Thymos factory builds `DriveSet` from `[thymos.drives.*]`.

## 2. Signals, valence, appraisal

- [x] 2.1 Pooled perceptual learning progress (fast and slow averages of each perceptual module's raw prediction error); alert rate; intent rate from `volition.out`.
- [x] 2.2 Drive signals and relief as in the proposal; the social overwrite from Chronos is replaced by relief on a new interaction.
- [x] 2.3 Valence relaxes toward `tanh(gain * g + (W - 0.5) + coupling)`; the pleasantness and wellness nudges are removed.
- [x] 2.4 Novelty from coalition surprise ratios; pleasantness from progress; the appraisal arousal nudge removed.
- [x] 2.5 With no per-broadcast nudges left, `appraisal_reference_interval_s` is removed from the constructor, factory, `config/kaine.toml` and docs.

## 3. Tests, docs

- [x] 3.1 Tests: exact drive solution and boundedness; relief; curiosity falls with learning progress; boredom falls on alerts; social relieved by a new interaction and inert before any; restlessness relieved by intents; valence rises when errors fall and falls when they rise; surprise reachable at ratio 3; mutation-check.
- [x] 3.2 Docs: `docs/09-modules/thymos.md`.
- [x] 3.3 `openspec validate thymos-research-affect --strict`.
