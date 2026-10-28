## Why

Forty-six changes on main had every task ticked, or had only "archive after merge" left after their pull requests merged, and none had been archived. The roadmap's active table listed them as in flight, the capability specs lagged the merged code, and the roadmap carried two totals lines from a merge that kept both sides. Four capability specs still had the placeholder Purpose that `openspec archive` writes for a new capability, so `openspec validate --specs --strict` failed on main.

## What Changes

- Archive every change whose tasks are all done with `openspec archive`, so the specs carry their deltas. This includes `ci-torch-within-pin`, `js-sleep-duration-clock`, `study-overlay-individuation` and `language-shutdown-failure-quiet`, whose last task was to archive after their merge, and `rest-resume-process-restart` after `developmental-state-cycle`.
- `hearing-band-12h` set the colour ramp to the awake-time floor and the hearing band to twelve awake hours. `developmental-state-cycle` retired the colour ramp and `hearing-stage-saturation` made the stages advance by saturation, so its delta is dropped from the specs: its modified colour-ramp requirement is removed from the delta, and its twelve-hour requirement is taken back out of the developmental-stimulus spec, which states the saturation rule.
- Write a real Purpose for container-deployment, dashboard-health, planned-test-calibration and vision-foveation.
- Keep one totals line in the roadmap and regenerate it.

Changes with an open task stay active, among them the two documentation changes waiting on the operator's review.

## Capabilities

None. The archived changes carry their own deltas.

## Impact

Specs and the roadmap only. No code changes.
