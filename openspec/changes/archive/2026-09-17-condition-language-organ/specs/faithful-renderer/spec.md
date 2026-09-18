## ADDED Requirements

### Requirement: Snapshot rendering is a prompt input with bounded selection

The faithful renderer's snapshot rendering SHALL be usable as a prompt input to
Lingua, not only as an evaluation-log artifact. For that use the renderer SHALL
provide a salience-bounded, stably-ordered selection: render at most a caller-
supplied maximum number of events, chosen by highest salience, ordered stably
(e.g. by event timestamp) for readability. The existing unbounded
`render_snapshot` behavior SHALL remain available unchanged for current callers;
the bounded selection is additive.

Rendering SHALL remain faithful: plain declarative lines, no hedging, no filler,
no invented content beyond the event payloads.

#### Scenario: Bounded rendering caps and orders events

- **WHEN** a snapshot with more selected events than the supplied maximum is
  rendered with the bounded selection
- **THEN** only the highest-salience events up to the maximum are included
- **AND** the rendered lines are in a stable order
- **AND** the output contains no content not present in the event payloads

#### Scenario: Existing unbounded rendering is unchanged

- **WHEN** an existing caller invokes `render_snapshot` as before
- **THEN** its output is identical to prior behavior
