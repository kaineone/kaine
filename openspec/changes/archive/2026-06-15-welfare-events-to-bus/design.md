# Design: gray-zone welfare events to the bus

## Principle

The architecture's welfare safeguards must *act* under unsupervised research, not
merely log. A detector that fires into a JSONL file alone cannot reach the
cycle-layer protective monitor, which by design imports nothing from
`kaine.evaluation` (the sidecar boundary). The bus is the only sanctioned coupling
between the sidecar detector and the core monitor — so the detector must publish.

## The signal

- **Type:** `welfare.gray_zone`
- **Source:** `welfare`
- **Stream:** `welfare.out`
- **Payload:** the `gray_zone_event` enum label (one of `replay_overload`,
  `unmaintained_fatigue`, `sustained_extreme_vad`,
  `sustained_interoceptive_distress`) plus the numeric scalars/counters the
  observer computed for that category. NEVER a field copied from a source event
  payload.

## Content-free enforcement (two layers)

1. **At the emitter.** `WelfareObserver._emit_gray_zone` builds the published
   payload from the record by copying ONLY the `gray_zone_event` label and values
   that are `int`/`float` (excluding `bool`). The record itself is constructed
   from observer-computed scalars, never from a source payload — guarded by a
   comment-contract at each of the four detection sites.
2. **At the curated research log.** `research_event_observer` records
   `welfare.gray_zone` through an EXACT numeric-field allowlist
   (`_WELFARE_NUMERIC_FIELDS`), replacing the previous suffix-matching. A future
   payload field cannot reach the export-eligible log unless deliberately added to
   that allowlist.

## Protective-response coupling

`WelfareProtectiveMonitor` keeps its sustained-distress arm (reads `soma.out`
`soma.report` `prediction_error` via the shared `SustainedThresholdTracker`) and
adds a gray-zone arm: a separate `welfare.out` cursor drains `welfare.gray_zone`
events and feeds each into the existing `WindowedEventCounter`
(`repeat_window_s` / `repeat_threshold`). A windowed crossing classifies as
`repeated_gray_zone` and triggers the same preserve-then-act response. The repeat
counter is now shared across both arms, so sustained distress and gray-zone events
accumulate toward the same windowed threshold — the intended "repeated welfare
distress within a window" semantics.

## Why bus-only coupling preserves the boundary

The monitor reads `welfare.out` off the bus exactly as it already reads
`soma.out`. It imports no `kaine.evaluation` symbol; the welfare observer (which
lives in `kaine.evaluation`) gains a publish path but the boundary test only
forbids CORE modules from importing `kaine.evaluation`, which remains true.
