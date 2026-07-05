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

