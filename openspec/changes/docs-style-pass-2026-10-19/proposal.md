## Why

Prose added today in `docs-roadmap-hygiene` (#562) and in the six action-path
proposals (#561) carries patterns from the field guide to AI writing telltales
that the project's writing rules exclude: bold-first list items, long sentences
of near-equal length strung with semicolons, a signposting colon ("blocked on two
things:") and a few crafted antitheses ("informative instead of decorative").

## What Changes

- `docs/09-modules/language.md`, "Replaying logged requests": split the single
  paragraph into one paragraph per command of `organ_replay.py` and break the
  longest sentences. Every fact, variant, threshold and safeguard is kept.
- `docs/09-modules/effectors.md`: split the action-path paragraph into shorter
  sentences, the first step named on its own.
- `docs/appendix-d-roadmap.md`: reword the `k1-jev-decision-model` row's blocker
  sentence without the signposting colon.
- The proposals of `act-intent-derivation`, `planning-act-proposals`,
  `embodiment-motor-contingency`, `active-vision`,
  `world-model-action-outcomes` and `goal-directed-grasping`: drop the bold from
  the stems of list items and rewrite three phrases. Their requirements, gates,
  dependencies and recommendations are unchanged.
- The `docs/records/README.md` index line #562 changed was checked and is left
  as it is.

## Capabilities

### Modified Capabilities

None. Wording only.

### New Capabilities

None.

## Impact

The files above. No code, configuration or spec changes.
