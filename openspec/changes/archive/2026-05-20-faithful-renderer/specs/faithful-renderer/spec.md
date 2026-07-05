## ADDED Requirements

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
