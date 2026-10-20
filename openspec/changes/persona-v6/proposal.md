## Why

The tenth test boot ran persona template version 5, chosen by a replay of the ninth boot's 190 requests. Its live rates did not match the replay: by the replay's own classifiers 17.7 percent of its 1,508 texts carried meta-commentary against the replay's 4.9 percent, and 4 texts described the entity as an AI. The replay's echo classifier matched only verbatim persona phrases, while about half of what the entity said aloud described how it speaks ("I speak plainly from what I feel"), and the replayed cases came from another boot under another persona. The paper (predictive-workspace-paper #48, section 3.5) says the persona only casts the organ as the entity speaking. This change replays the tenth boot's own requests with the boot analyzer's broader classifiers, under a decision rule fixed here before the run, and adopts the winning prompt as persona template version 6 if one wins.

## What Changes

- `tools/maintainer/organ_replay.py`:
  - `ai_self()` and `echo()` also match the tenth boot analyzer's broader patterns (AI: "neural network", "trained on", "LLM", "model trained", "I am a program/machine/computer" and "an AI"; echo: "own words", "own voice", "own plain words", "plain", "plainly", "I say what", "I speak from", "I speak the way", "I speak plainly", "comes from what I feel/notice"). They keep every pattern they had.
  - New variants on the logged prompt and system text: `V5` (as logged), `V5m` (each persona without its manner clause ", in my own plain words"), `V5e` (empty system text) and `V5l` (each awareness line without its "- " marker, still one line per item).
  - `score --rule v6` prints the rates, the paired differences against `V5`, the rates of the waking requests (those whose prompt opens with the situation section) for each variant, and the decision below.
- Decision rule, fixed before the run. The cases are every request in the tenth boot's intent log, replayed with 3 seeds at temperature 0.7. Differences are paired by case (mean over seeds per case, then over cases) with 95 percent intervals from a 2,000-draw cluster bootstrap over cases. A candidate (`V5m`, `V5e`, `V5l`) passes when its any-meta difference from `V5` has an upper 95 percent bound below 0, its grounded difference from `V5` is above -5 points, and its AI self-description difference from `V5` is not above 0. If more than one passes, the one with the lowest any-meta point difference is adopted. If none passes, the persona stays at version 5. The waking requests are reported separately and do not enter the rule.
- If a candidate is adopted, the language module's prompt changes to it and `PERSONA_TEMPLATE_VERSION` becomes "6", which the individuation probe treats as a changed condition.

## Capabilities

### Modified Capabilities

- `language`: the replay harness scores with the broader classifiers and the v6 rule; the persona follows the rule's result.

## Impact

- `tools/maintainer/organ_replay.py`, `tests/test_organ_replay.py`, `tools/maintainer/README.md`; if a candidate wins, `kaine/modules/language/context.py` (and the renderer for `V5l`), `docs/09-modules/language.md` and the language tests.
- The broader classifiers also change the scores the tool prints for older result files.
- The run reads the tenth boot's intent log read-only and keeps its case and result files in a private scratch directory.
