## Why

The divergence monitor preserves the live entity when the shared verdict gains an arm it had not seen before, but it records every such preservation with the reason `individuation`, whatever arm fired. In the 2026-10-16 integration boot the voice arm fired on `measurement_missing` and the consolidation arm fired after the first sleep, and both bundles, both `preservation.preserved` records and the log line said "individuation". A reader of the incident log or the research log cannot tell which evidence led to a preservation, and a bundle labelled "individuation" suggests a significant permutation test that never ran.

## What Changes

- The reason passed to `preserve_live`, written into the `preservation.preserved` record and named in the log line is the set of new arms that fired, sorted and joined with `+` (for example `voice`, `consolidation`, `consolidation+voice`; `diverged` when the verdict is diverged with no named arm).
- The bundle label is `divergence:<incident_id>` in place of `individuation:<incident_id>`.
- The `preservation.failed` record carries the same `reason`.
- No change to when the monitor fires. The paper sets no minimum amount of evidence for any divergence arm, so none is added here (see the PR for the consolidation arm firing on one usable pair).

## Capabilities

### Modified Capabilities

- `entity-preservation`: a divergence-triggered preservation records the arm that triggered it.

## Impact

- `kaine/cycle/preservation_monitor.py`, `tests/test_preservation_monitors.py`, `docs/11-preservation.md`.
- Records and bundles written before this change keep the reason `individuation`.
