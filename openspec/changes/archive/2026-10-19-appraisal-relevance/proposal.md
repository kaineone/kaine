## Why

The paper (Appendix A.4) now scores goal relevance as `v* × frac`, and the ledger term as `r_led`, both in `[0, 1]`. Content that serves neither the dominant drive nor a goal is irrelevant, because the component process model checks relevance before conduciveness (Scherer 2009). The code still uses the old `v × (2f − 1)` and `2 × relevance − 1`, which score unrelated content as an obstructed goal. Coping rests near 0.3 (`valence + 0.5 − arousal` at baseline), so an idle entity with a mild unmet drive classifies as anger. A short first-configuration run on main showed it: curiosity 0.32, goal significance −0.32, coping 0.30, emotion anger. An emotion change is published at the alert intensity, so the label tops the coalition and reaches the language organ.

## What Changes

- The drive score becomes `v × f`, with `f` the intensity-weighted share of coalition members whose source relieves the dominant drive; `0.0` for an empty coalition or no drive above zero.
- The ledger score becomes `relevance` (in `[0, 1]`), not `2 × relevance − 1`.
- The goal score is never negative. `classify()` is unchanged; its anger branch needs a goal score at or below −0.3, so anger stays unreachable until an obstruction check exists, the way disgust waits on norm signals. The docstring and docs say so.

## Capabilities

### Modified Capabilities

- `affect`: goal significance scores relevance in `[0, 1]`; unrelated content is irrelevant, not obstructive.

## Impact

- `kaine/modules/affect/module.py`, `kaine/modules/affect/appraisal.py` (docstring), `docs/09-modules/affect.md`, `tests/test_affect_goal_check.py` and any test that relied on a negative goal score.
- Behaviour: an idle or unrelated coalition classifies as neutral instead of anger.
