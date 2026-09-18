# faithful-renderer Specification

## Purpose
TBD - created by archiving change faithful-renderer. Update Purpose after archive.

## Requirements

### Requirement: Renderer is deterministic and side-effect free
The `FaithfulRenderer` SHALL be a pure function: identical input
SHALL produce identical output bytes, the renderer SHALL NOT mutate
its inputs, and rendering SHALL NOT call out to LLMs, networks, or
other non-deterministic sources.

#### Scenario: Same input twice yields identical output
- **WHEN** `FaithfulRenderer.render_event(event)` is called twice
  with the same event
- **THEN** the two return values are byte-identical strings

### Requirement: Templates per (source, type) with unknown fallback
The renderer SHALL look up a template by `(event.source, event.type)`
and apply it to `event.payload`. When no exact-match template is
registered, the renderer SHALL fall back to a structured summary
template that lists the source, type, and key=value pairs of the
payload's top-level entries.

#### Scenario: Known template used when matching
- **WHEN** rendering an event with `source="soma"`, `type="soma.report"`,
  payload `{"wellness": 0.85, "alerts": []}`
- **THEN** the output is a plain-text sentence beginning with the
  soma-specific template (not the fallback) and including the
  wellness value

#### Scenario: Unknown source/type falls back gracefully
- **WHEN** rendering an event whose `(source, type)` has no template
  registered
- **THEN** the output is non-empty plain text that names the source,
  the type, and at least one payload key

### Requirement: Snapshot rendering composes per-event lines
`FaithfulRenderer.render_snapshot(snapshot)` SHALL render every
event in `snapshot.selected_events` on a separate line, in the
snapshot's order, prefixed with a stable per-position marker (e.g.
`- `) so the output is line-oriented and easy to diff.

#### Scenario: Empty snapshot yields fixed empty marker
- **WHEN** rendering a snapshot whose `selected_events` is empty
- **THEN** the output is the configured empty-snapshot string (default
  `"(no events selected)"`)

#### Scenario: Multiple events render in input order
- **WHEN** rendering a snapshot with three selected events
- **THEN** the output contains three lines, each prefixed identically,
  preserving the input order

### Requirement: No LLM-style hedging or filler
The shipped templates SHALL NOT contain LLM-style hedging
("I think", "perhaps", "maybe", "it seems"), self-references
("As an AI"), or filler ("In summary,"). The renderer's purpose is
ground-truth rendering — anything the templates would soften must
be removed at the template level, not at use time.

#### Scenario: No banned phrases in any template's output
- **WHEN** every registered template is rendered with a representative
  payload
- **THEN** none of the outputs contain the strings "I think", "as an AI",
  "maybe", "perhaps", "in summary", "it seems"

### Requirement: Templates for remaining v4 event types
The FaithfulRenderer SHALL provide named, human-readable templates for the v4
event types that currently fall back to raw-dict rendering: `nous.timeout`,
`audition.prosody`, `vox.synthesized`, `mnemos.replay`, `hypnos.sleep.started`,
`hypnos.sleep.completed`, `hypnos.association`, and `eidolon.self_model`. Each
SHALL render readable text, never a raw dict.

#### Scenario: New event types render via named templates
- **WHEN** any of the listed v4 event types is passed to the renderer
- **THEN** the output is produced by that event's named template, not the fallback

#### Scenario: Replay and self-model render no raw content
- **WHEN** a `mnemos.replay` or `eidolon.self_model` event is rendered
- **THEN** the output contains memory IDs / trait labels and numeric attributes
  only, and no raw transcript or sense-data text

### Requirement: Report templates include v4 predictive fields
The `soma.report` template SHALL render `prediction_error` and `fatigue_value`,
and the `chronos.report` template SHALL render `temporal_prediction_error`, so the
forward-model signals are visible in the conscious-coalition view rather than
silently dropped.

#### Scenario: Soma report shows predictive fields
- **WHEN** a `soma.report` carrying `prediction_error` and `fatigue_value` is rendered
- **THEN** the rendered line includes both values

#### Scenario: Chronos report shows temporal prediction error
- **WHEN** a `chronos.report` carrying `temporal_prediction_error` is rendered
- **THEN** the rendered line includes that value

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
