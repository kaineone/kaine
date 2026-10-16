## Why

The paper (§3.5, predictive-workspace-paper #47) now maps the appraisal checks to a categorical emotion by rules modeled on the predicted appraisal profiles of Sander, Grandjean and Scherer (2005, Table 3). Their disgust profile needs very low intrinsic pleasantness, low familiarity and low goal relevance, and leaves the standards check open. The code instead requires a norm violation (`norm <= -0.4`) for disgust. Norm compatibility is fixed at 0 because KAINE has no standards until an operator writes a list, so disgust can never fire. The comments in `appraisal.py` and `module.py` say disgust waits on norm signals and that anger is unreachable, which no longer describes the design.

## What Changes

- `classify()` returns disgust when pleasantness is very low (`<= -0.5`), novelty is above 0.3 and the goal score is low in magnitude (`|goal| < 0.3`), with no norm requirement. Fear and anger, which need coping, are checked first, so relevant content with low coping still classifies as fear.
- KAINE has a single novelty check, `1 - prod(1 - s)` over the coalition's error ratios, which covers suddenness, familiarity and predictability together. Low familiarity in Table 3 maps to high novelty here: a report the processor did not expect is unfamiliar to it.
- `classify()`'s docstring cites Table 3 and states each rule's profile and its mapping onto KAINE's checks, including that anger matches at best the irritation profile, since KAINE attributes no obstruction to another agent and has no standards check.
- The stale comments go: disgust no longer waits on norm signals, and anger is described as reachable once the obstruction term of A.4 makes the goal score negative.
- Norm compatibility stays unavailable: the numeric value stays 0.0 and `affect.emotion` keeps `norm_compatibility_available: false`. No standards are invented.

## Capabilities

### Modified Capabilities

- `affect`: disgust follows the Table 3 profile and no longer needs a norm violation.

## Impact

- `kaine/modules/affect/appraisal.py`, `kaine/modules/affect/module.py` (comments only), `docs/09-modules/affect.md`, `tests/test_affect_appraisal.py`.
- Behaviour: disgust becomes reachable on very unpleasant, novel, irrelevant content. Every other category classifies as before.
