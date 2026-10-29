## Why

Three changes merged on 2026-10-28 with every task ticked: `welfare-response-rearms` (#611), `docs-update-2026-10-28` (#614) and `maturation-reference-before-seed` (#610). Until they are archived the roadmap lists them as in flight and the capability specs lag the merged code.

## What Changes

- Archive the three changes with `openspec archive`, so their deltas land in the specs.
- Remove the scenario "A capture reference does not count" from the module-ignition-study spec. It said the runner keeps waiting on a complete `capture` reference, while the requirement and the scenario "A sleep downgrades the capture" fail the step at once, which is what the runner does since the #610 review.
- Regenerate the roadmap.

## Capabilities

None. The archived changes carry their own deltas.

## Impact

Specs and the roadmap only. The scenario removal brings the spec in line with the code. No code changes.
