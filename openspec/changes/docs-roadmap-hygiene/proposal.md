## Why

The roadmap listed 123 active changes, and most of them had every task ticked
but had never been archived, so the capability specs under `openspec/specs/`
lagged the merged code by weeks. Four of the completed changes carried deltas
that no longer matched the current specs, one design-only change had no
`skip_specs` marker, and `openspec validate --all` failed on main. The
k1-jev-decision-model row and the records index gave an out-of-date status
instead of naming the real blocker, and the module pages had no text for the
organ replay harness or for the planned action path.

## What Changes

- Archive every change whose tasks are all ticked with `openspec archive`, so
  the specs carry their deltas. Changes with an open task stay active.
- Refresh the deltas that would drop or contradict current scenarios:
  `mnemos-trace-strength` keeps the replay window and the
  replay-before-downscale scenario, `affect-goals-obstruction` keeps the coping
  crossing rules and their scenarios, and `appraisal-relevance` and
  `sequence-finite-payload` replace their requirement through REMOVED plus
  ADDED because a scenario changes meaning.
- Mark `seed-entity-distribution` as design only (`skip_specs: true`).
- State the k1-jev-decision-model blocker plainly in its roadmap row and in the
  records index line for the K1-Jev smoke run.
- Add the organ replay harness to the language module page and the planned
  action path to the effectors page.
- Regenerate the roadmap.

## Capabilities

### Modified Capabilities

None. The archive applies the deltas the merged changes already carry; this
change adds no requirement of its own.

### New Capabilities

None.

## Impact

`openspec/changes/`, `openspec/specs/`, `docs/appendix-d-roadmap.md`,
`docs/records/README.md`, `docs/09-modules/language.md`,
`docs/09-modules/effectors.md`. No code changes.
