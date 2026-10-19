## 1. Implementation

- [x] 1.1 `DriveSet` gives each drive's above-threshold flag and crossing-end counts; the affect module adds them to every `affect.state` event as `drive_above` and `drive_ends`
- [x] 1.2 `AffectWelfareTally` scores crossing ends from `drive_ends` increases and accumulates each drive's awake time at or above threshold; the observer stops feeding it `affect.goal` events
- [x] 1.3 Tests: state fields on the periodic and reset events; a stall leaves the crossing open; sleep counts as neither; counter decreases re-baseline; frozen control ranks worst and the deprivation share is independent of the sleep cadence
- [x] 1.4 Docs: affect state event fields and the research-data description of the `affect_welfare` record
- [x] 1.5 Harness check: the developmental simulation through the real tally, learning and frozen, with and without a 25 min sleep cadence
