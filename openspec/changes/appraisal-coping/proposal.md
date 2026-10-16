## Why

The paper (Appendix A.4, predictive-workspace-paper #46) now defines coping potential. The code uses a proxy, `clip(valence + (0.5 - arousal), -1, 1)`, that has no basis in the literature: in the component process model arousal follows appraisal, and coping is checked only for relevant content (Scherer 2009; Marsella and Gratch 2009). The proxy sits near 0.3 at rest, so fear, anger and sadness can fire from resting affect state rather than from any estimate of the entity's ability to change an outcome.

## What Changes

- Coping is computed only when the goal score is above 0. Otherwise it is undefined: the scores carry `coping_available = False`, the numeric value is 0.0, and `classify()` does not return fear, anger or sadness.
- Each drive counts how its crossings end: re-armed by relief (`relieve`, `relieve_rate`) or by decay alone (`tick`). A sleep reset counts as neither. The counts persist across preservation.
- The goal ledger reports how many goals were completed and how many abandoned.
- Power is the Laplace-smoothed success ratio `p = (s + 1) / (s + f + 2)`: the dominant drive's relief and decay counts when the drive term sets the goal score (also on a tie), the ledger's completed and abandoned counts when the ledger term sets it. Coping is `2p - 1`, so 0.0 before any history.
- Arousal and valence no longer enter coping.
- `affect.emotion` carries `coping_available`.

## Capabilities

### Modified Capabilities

- `affect`: coping potential is gated by relevance and estimated as a success ratio.

## Impact

- `kaine/modules/affect/drives.py`, `kaine/modules/affect/goals.py`, `kaine/modules/affect/appraisal.py`, `kaine/modules/affect/module.py`, `docs/09-modules/affect.md`, new `tests/test_affect_coping.py`.
- Behaviour: with no relevant content no emotion that needs coping can fire; before any drive or goal history coping is 0.0, so fear and anger need a learned record of low or high power.
