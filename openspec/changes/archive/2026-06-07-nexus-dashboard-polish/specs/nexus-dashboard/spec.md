## ADDED Requirements

### Requirement: Service and dependency health board

The diagnostics surface SHALL present a health board that shows, at a glance,
the live status of every external dependency and every configured module. For
each dependency it SHALL show a status of `up`, `down`, `degraded`, or
`not_configured`, with a short human-readable detail and a last-checked time.
Dependencies covered SHALL include: Redis (bus), Qdrant (Mnemos), the chat LLM
endpoint (Lingua/Hypnos), Speaches/STT (Audio In), Chatterbox/TTS (Audio Out),
and the ONA `NAR` binary (Nous). For each module the board SHALL show whether it
is enabled, initialized, and — where applicable — actively capturing or
erroring.

A dependency whose owning module is disabled SHALL render as `not_configured`
(neutral), not `down`. Health checks SHALL run server-side with a bounded
per-probe timeout and SHALL be cached briefly so that rendering or polling the
page never blocks on a hung dependency and never floods a service with probes.

#### Scenario: A stopped service shows as down

- **WHEN** a required dependency for an enabled module is unreachable (e.g. STT
  is enabled but Speaches is not listening)
- **THEN** the health board shows that dependency as `down` with a detail
  identifying it
- **AND** the rest of the board still renders without blocking

#### Scenario: A disabled module's dependency is neutral, not an error

- **WHEN** a module is disabled in `[modules]` (e.g. `audio_out = false`)
- **THEN** its dependency (Chatterbox) renders as `not_configured`, not `down`

#### Scenario: A hung dependency does not block the page

- **WHEN** a dependency probe exceeds its timeout
- **THEN** that dependency renders as `down`/`degraded` after the timeout
- **AND** the page and other probes are unaffected

### Requirement: Professional visual design system

The Nexus surfaces (conversation, diagnostics, evaluation) SHALL share a
cohesive, professional visual design: a responsive multi-panel layout, a refined
dark theme with a defined type scale and status color palette, and clear
grouping of related information into cards/panels. The redesign SHALL NOT remove
any information currently shown, and SHALL keep working without any client-side
build step (server-rendered templates plus vanilla JS and vendored assets).

#### Scenario: Surfaces render with the shared design on a normal viewport

- **WHEN** an operator opens the conversation, diagnostics, and evaluation pages
- **THEN** each renders with the shared layout, theme, and panel grouping
- **AND** all data previously shown on each page is still present

### Requirement: Live metric visualizations

The diagnostics surface SHALL render live numeric metrics as visualizations
rather than only as raw text: at minimum a time-series of cycle processing and
experiential rate, a time-series of Thymos affect (valence/arousal/dominance),
and module-attribution as a chart. Visualizations SHALL be driven by data
already exposed (the metrics snapshot, the diagnostics SSE stream, and the
evaluation summary), buffering recent points client-side. All charting assets
SHALL be served locally with no runtime network fetch.

#### Scenario: Cycle-rate graph updates live from the stream

- **WHEN** the cycle is running and the diagnostics page is open
- **THEN** a time-series visualization of processing/experiential rate updates
  as new metric events arrive
- **AND** no chart asset is fetched from a remote network at runtime

#### Scenario: Charts degrade gracefully without data

- **WHEN** a metric source has no data yet (e.g. evaluation disabled)
- **THEN** its panel shows an empty/placeholder state rather than erroring

### Requirement: Operator controls for supported backend actions

The diagnostics surface SHALL expose UI controls for backend actions that
already have endpoints or bus support: perception toggles (audio/video), cycle
processing/experiential rate control (via the `cycle.control` stream), and fork
creation and snapshot merge (via the existing fork/merge endpoints). Any control
that turns on a sensor, changes the entity's pacing, or is otherwise hard to
reverse SHALL require an explicit confirmation before acting.

#### Scenario: Cycle rate can be changed from the UI

- **WHEN** an operator sets a new processing rate in the diagnostics control
- **THEN** a `cycle.set_rates` event is published to the `cycle.control` stream
- **AND** the live rate visualization reflects the change

#### Scenario: Sensor-on and pacing controls confirm first

- **WHEN** an operator activates live audio/video or changes the cycle rate
- **THEN** the UI requires an explicit confirmation before the action is sent

### Requirement: Privacy boundary and loopback preserved

The redesign SHALL preserve the existing privacy boundary and binding: content
fields SHALL remain stripped on the diagnostics surface unless
`dev_content_override` is set (with the dev-mode banner shown when it is), the
conversation surface SHALL continue to show full content, the evaluation surface
SHALL remain scrubbed, and Nexus SHALL continue to bind loopback-only. Health
and metric data (statuses, counts, rates) are non-content and MAY be shown
without `dev_content_override`.

#### Scenario: Diagnostics still strips content by default

- **WHEN** `dev_content_override` is false and the diagnostics page renders
  module events
- **THEN** content fields (text, body, internal speech, transcription, memory
  bodies) remain stripped, exactly as before the redesign

#### Scenario: Health/metric data shows without dev mode

- **WHEN** `dev_content_override` is false
- **THEN** the health board and metric visualizations still render (statuses,
  counts, and rates are not private content)
