# dashboard-observability Specification

## Purpose
The dashboard's live diagnostics: one server-sent-event feed of every active module stream and the workspace broadcast, and the status indicators an operator needs to watch a run, from coherence, fatigue and welfare to encryption, supervision, the safety net and run admissibility.

## Requirements

### Requirement: Live streams for all active modules
The dashboard diagnostics SSE bridge SHALL relay the output streams of every active
module, including `social_cognition.out`, `world_model.out`, and the `workspace.broadcast`
stream (which carries `metadata['coherence']`), so no enabled module is invisible
in the live event feed.

#### Scenario: New module streams reach the feed
- **WHEN** the social cognition module or the world model module publishes an event while enabled
- **THEN** that event appears in the dashboard diagnostics SSE feed

#### Scenario: Disabled-module stream is a no-op
- **WHEN** a module is disabled and produces no events
- **THEN** its stream contributes nothing and the dashboard renders without error

### Requirement: Coherence (PLV) chart
The dashboard SHALL render a phase-locking-value (coherence) time series from
`WorkspaceSnapshot.metadata['coherence']`. When the oscillatory layer is disabled
and the key is absent, the chart SHALL render empty without error rather than
breaking the page.

#### Scenario: Coherence updates when present
- **WHEN** a `workspace.broadcast` carries `metadata['coherence']`
- **THEN** the coherence chart's series advances with that value

#### Scenario: Coherence absent degrades gracefully
- **WHEN** the oscillator is disabled and no coherence key is present
- **THEN** the coherence chart shows an empty series and the page still loads

### Requirement: Fatigue-accumulator trend
The dashboard SHALL render an interoception fatigue-accumulator trend from `interoception.report`
`fatigue_value`, with the maintenance threshold shown as a reference, so the
operator can see how close the substrate is to triggering the sleep module's maintenance.

#### Scenario: Fatigue trend advances
- **WHEN** `interoception.report` events carrying `fatigue_value` are observed
- **THEN** the fatigue trend series advances and the threshold reference is shown

### Requirement: Welfare and prediction-error counts on the evaluation tab
The dashboard SHALL surface, on the evaluation tab, the `welfare_observer` Gray-Zone
counts (unmaintained fatigue, sustained extreme VAD, replay overload), the
`prediction_error_observer` sliding-window statistics per source, and a coherence
summary — read from the live sidecar registry when available and otherwise from
the observer JSONL rollups. Each section SHALL render a "no data" state, never an
error, when its source is absent.

#### Scenario: Welfare counts are visible
- **WHEN** the welfare observer has recorded one or more Gray-Zone events
- **THEN** the evaluation tab shows the per-type counts

#### Scenario: Prediction-error stats are visible
- **WHEN** the prediction-error observer has accumulated samples
- **THEN** the evaluation tab shows per-source mean/p95/p99

#### Scenario: No observer data degrades gracefully
- **WHEN** neither a live registry nor observer JSONL is available
- **THEN** the welfare, prediction-error, and coherence sections render "no data"
  without error

### Requirement: State-encryption status probe
The dashboard health board SHALL report the `[security.state_encryption]` posture —
encrypted-at-rest, plaintext (disabled), or enabled-but-no-key (fail-closed) —
without ever reading or logging the encryption key.

#### Scenario: Encryption enabled with a key
- **WHEN** state encryption is enabled and a key is resolvable
- **THEN** the health board reports an encrypted-at-rest status and never logs the key

#### Scenario: Encryption enabled without a key
- **WHEN** state encryption is enabled but no key is resolvable
- **THEN** the health board reports a fail-closed (no-key) status

### Requirement: Fork merge-warning surfaced
The dashboard forks panel SHALL surface the `planning.merge_warning` flag when a fork
merge recorded a planning module policy divergence, so the operator is alerted to a posterior
clash across branches.

#### Scenario: Merge warning is shown
- **WHEN** a merge snapshot carries `planning.merge_warning`
- **THEN** the forks panel shows a warning marker for that fork

#### Scenario: No warning when absent
- **WHEN** a merge snapshot has no merge-warning flag
- **THEN** no warning marker is shown for that fork

### Requirement: Supervisor incident status on the health surface
The dashboard health snapshot SHALL include a `supervisor` block reporting the supervisor
incident state — `ok`, `recovery`, or `critical` — derived from the freeze control
(`frozen` and `source == "supervisor"` ⇒ `recovery`) and the escalation record
(`escalated` ⇒ `critical`), together with the affected `module`, `attempts`,
`max_attempts`, an operator `message`, and the saved `snapshot_id` when present.
The block SHALL contain only operational data (no sensory content) and SHALL be
served on `/diagnostics/health.json` so a freshly loaded or reconnected page paints
the correct state.

#### Scenario: Recovery state surfaced
- **WHEN** the freeze control is frozen with `source == "supervisor"` and no escalation
  is recorded
- **THEN** the health snapshot's `supervisor.state` is `"recovery"`

#### Scenario: Critical state surfaced
- **WHEN** an escalation record exists
- **THEN** the health snapshot's `supervisor.state` is `"critical"` and carries the
  operator message and `snapshot_id`

#### Scenario: Default ok state
- **WHEN** there is no supervisor freeze and no escalation
- **THEN** the health snapshot's `supervisor.state` is `"ok"`

### Requirement: Operator alert UI for supervisor incidents
The diagnostics UI SHALL render a full-window alert border that turns yellow during
a `recovery` state and red during a `critical` state, a status banner carrying the
human message, and a live incident console fed by the `supervisor.out` bus stream
(`supervisor.status` flips the border/banner; `supervisor.log` lines append to the console).
`supervisor.out` SHALL be included in the diagnostics SSE streams. Any pulse animation on
the alert border SHALL be disabled under `prefers-reduced-motion`.

#### Scenario: Border reflects incident state
- **WHEN** the health snapshot reports `supervisor.state == "critical"`
- **THEN** the page renders the alert border in its red (critical) state

#### Scenario: Live console receives incident lines
- **WHEN** the supervisor publishes `supervisor.log` events during an incident
- **THEN** the diagnostics page appends those lines to the incident console via the
  SSE stream

#### Scenario: Reduced motion disables the pulse
- **WHEN** the operator's environment requests reduced motion
- **THEN** the alert border is shown without a pulsing animation

### Requirement: Entity-care status on the health surface
The dashboard health snapshot SHALL include a read-only `entity_care` block reporting the entity's
divergence/individuation summary and the CAL care-obligation checklist that applies before
decommission. The block SHALL be non-content (statuses and static obligation text only) and SHALL
NOT expose any destructive control — decommission remains a gated CLI action. The block SHALL be
guarded so a missing or unreadable signal yields a safe default rather than an error.

#### Scenario: Care block present and read-only
- **WHEN** the diagnostics health snapshot is produced
- **THEN** it includes an `entity_care` block with the divergence summary and the care-obligation
  checklist, and the diagnostics page exposes no delete/decommission control

#### Scenario: Safe default when signals are absent
- **WHEN** no divergence signals are available
- **THEN** the `entity_care` block renders a safe default summary without raising

### Requirement: GPU pre-flight status is surfaced read-only

The dashboard health snapshot SHALL include a read-only `gpu_preflight` block derived
from the last pre-flight verdict, reporting only non-content operational data:
per-device VRAM, evicted/loaded model ids, GPU process names, the KAINE services
detected, and an operator state. The block SHALL never raise; a missing or corrupt
pre-flight record SHALL yield state `unknown`. The dashboard SHALL NOT expose any control
that terminates a process from this block.

#### Scenario: Blocked pre-flight surfaces as critical

- **WHEN** the last pre-flight recorded a `blocked` verdict
- **THEN** the `gpu_preflight` block reports state `critical` with the per-device
  shortfall

#### Scenario: No pre-flight record is unknown, not an error

- **WHEN** no pre-flight record exists
- **THEN** the `gpu_preflight` block reports state `unknown`
- **AND** the snapshot is produced without error

### Requirement: Planning health probe verifies the generative model builds

The planning module health probe SHALL confirm that the active-inference generative
model can be constructed, not merely that `pymdp` and `jax` are importable.
A broken dependency (e.g. numpy ABI mismatch) that only surfaces at
construction time would pass an import-only probe and give a false UP result.

The probe SHALL attempt `build_generative_model()` with default parameters
after confirming imports succeed.  The build attempt SHALL be guarded so
that any exception is caught within the probe and never propagates to the
caller.

#### Scenario: Imports and build succeed

- **WHEN** `pymdp` and `jax` are importable
- **AND** `build_generative_model()` completes without raising
- **THEN** the probe SHALL return `UP`
- **AND** the detail message SHALL include `"generative model built"`

#### Scenario: Imports succeed but build fails

- **WHEN** `pymdp` and `jax` are importable
- **AND** `build_generative_model()` raises any exception
- **THEN** the probe SHALL return `DEGRADED`
- **AND** the detail message SHALL include `"build failed"` and the exception message

#### Scenario: Import fails

- **WHEN** `pymdp` or `jax` cannot be imported
- **THEN** the probe SHALL return `DOWN` (unchanged from prior behaviour)

### Requirement: Run identity surfaced on diagnostics
The dashboard SHALL surface the live run's identity — `run_id`, `seed`,
`git_sha`, `kaine_version`, and the `deterministic` flag — read from the active
`RunContext` and persisted by the cycle into `state/cycle/runtime.json`. The
diagnostics page SHALL render a "run identity" block from these fields, and
`metrics_snapshot` SHALL include them. All of these fields are non-content
run metadata; the surface SHALL carry no entity-interior content.

#### Scenario: Run identity renders when a run is live
- **WHEN** the cycle has minted a `RunContext` and written runtime.json
- **THEN** the diagnostics "run identity" block shows the run id, seed, git sha, and version
- **AND** `metrics_snapshot` includes `run_id`, `seed`, `git_sha`, `kaine_version`, and `deterministic`

#### Scenario: Run identity absent before a run starts
- **WHEN** no run context has been set (no runtime.json or no identity fields)
- **THEN** the run-identity block degrades gracefully and the page still loads

### Requirement: Supervision mode and safety-net gate badge
The dashboard SHALL surface the active supervision mode — `operator` or
`research` — and, in research mode, the four-condition safety-net gate `checks`
dict (`preservation_enabled`, `welfare_response_wired`, `logging_active`,
`self_check_passed` / `dry_self_check_passed`). The cycle SHALL write
`supervision_mode` (and, in research mode, the gate checks) into runtime.json.
The diagnostics page SHALL render a badge at the top, visually distinct from the
research-participation telemetry panel, and a research-mode badge SHALL be
visually prominent. These are non-content operational flags.

#### Scenario: Research-mode badge is prominent and shows gate checks
- **WHEN** the cycle booted in research mode with the safety-net gate satisfied
- **THEN** the diagnostics page shows a prominent research-mode badge with the gate checks

#### Scenario: Operator-mode badge is shown
- **WHEN** the cycle booted operator-present
- **THEN** the diagnostics page shows an operator-supervised badge and no gate-checks list

### Requirement: Preservation and welfare-protective events surfaced
The dashboard SHALL surface preservation and welfare-protective events —
`preservation.preserved`, `preservation.failed`, `preservation.skipped`, and
`welfare.protective_action` (source `preservation`, stream `preservation.out`) —
in a persistent panel analogous to the supervisor console. The panel SHALL display
only an allowlist of non-content fields (e.g. `preservation_id`, `snapshot_id`,
`reason`, `action`/`action_taken`, `transition`, `monitor`), render a
`preservation.failed` event in the down/critical colour, and persist the last N
events in `sessionStorage` so a reload does not lose context. A
`HealthProber._preservation_block()` SHALL backfill the panel by reading the
incident-log directory (`state/cycle/preservation/`). No entity-interior content
SHALL be surfaced.

#### Scenario: A preservation event is shown and persisted
- **WHEN** a `preservation.preserved` event arrives on the diagnostics SSE stream
- **THEN** a line appears in the preservation panel with the preservation id, snapshot id, and reason
- **AND** the line is persisted so it survives a page reload

#### Scenario: A failed preservation is visually distinct
- **WHEN** a `preservation.failed` event arrives
- **THEN** its line renders in the down/critical colour

#### Scenario: Backfill reads the incident log without content
- **WHEN** the diagnostics page loads and the incident-log directory holds prior records
- **THEN** `_preservation_block()` returns the recent records using only allowlisted non-content fields

### Requirement: Live welfare status on the entity-care panel
The dashboard SHALL surface a compact numeric welfare-counter row —
unmaintained-fatigue crossings, sustained-VAD episodes, replay overload, and
sustained interoceptive distress — on the diagnostics entity-care panel, sourced
from the same aggregation as the evaluation tab. The row SHALL be numeric only
and carry no entity-interior content. Below it, the panel SHALL show the number of
blind-sensor and silent-sensor advisories raised since the welfare observer last
started and the labels of the processors that are blind or silent now. Each
processor's state SHALL come from its latest advisory or clear after the latest
reset line in the welfare rollup, read without a line window, decrypting encrypted
lines; only known processor labels SHALL be shown, and the panel SHALL state that
a sensor advisory is a sensor fault on which no protective action follows.

#### Scenario: Welfare counters render on the entity-care panel
- **WHEN** welfare counters are available (live registry or JSONL rollup)
- **THEN** the entity-care panel shows the four numeric counters

#### Scenario: Welfare counters absent degrade gracefully
- **WHEN** no welfare data is available
- **THEN** the row renders an empty/none state and the page still loads

#### Scenario: A blind processor is listed until it clears
- **WHEN** the rollup holds advisories for `vision` and `interoception` and a clear for `vision`
- **THEN** the panel lists `interoception` as blind now and shows two advisories raised

#### Scenario: A restart clears a stale state
- **WHEN** the rollup holds a blind advisory for `vision`, then a reset line, then a blind advisory for `audition_acoustic`
- **THEN** the panel lists only `audition_acoustic` as blind now

#### Scenario: A long rollup keeps a still-blind processor
- **WHEN** a blind advisory for `interoception` is followed by thousands of other rollup lines and no clear for `interoception`
- **THEN** the panel still lists `interoception` as blind now

### Requirement: Live admissibility indicator
The dashboard SHALL surface a lightweight live admissibility indicator that,
without scanning all run history, reports whether the current run's manifest is
present (`data/evaluation/runs/<run_id>/manifest.json`), the last tick index from
runtime.json, and a recording / gap-detected / unknown pill. A `HealthProber`
probe SHALL produce this block. The full completeness scan SHALL remain a
command-line operation.

#### Scenario: Recording when the manifest is present and ticks advance
- **WHEN** the current run's manifest exists and runtime.json reports a tick index
- **THEN** the admissibility indicator shows the manifest present, the last tick index, and a "recording" pill

#### Scenario: Unknown when no run is identifiable
- **WHEN** no run id is available from runtime.json
- **THEN** the admissibility indicator shows an "unknown" pill without error

### Requirement: Deterministic-mode indicator
The dashboard SHALL render a deterministic-mode indicator near the
cycle-rate charts, shown ONLY when the run's `deterministic` flag (from
runtime.json) is true, stating that timestamps are logical rather than wall-clock.
The indicator SHALL use the degraded colour and SHALL NOT appear in production
(non-deterministic) runs.

#### Scenario: Indicator shown in deterministic mode
- **WHEN** runtime.json reports `deterministic` true
- **THEN** a deterministic-mode badge appears near the cycle-rate charts

#### Scenario: Indicator hidden otherwise
- **WHEN** `deterministic` is false or absent
- **THEN** no deterministic-mode badge is shown

### Requirement: The diagnostics surface streams over a single multiplexed connection

The dashboard console SHALL open at most one Server-Sent-Events connection to the
diagnostics stream, and client features SHALL receive events through a client-side
dispatcher rather than each opening its own `EventSource`. The server SHALL
privacy-filter and encode each bus event once per event, then fan the filtered event
to connected clients, rather than filtering once per client.

The UI SHALL pause its streams and pollers when the document is hidden, and SHALL
surface a visible connection status (live / reconnecting) so a dropped link does not
silently present stale values as current. Health polling SHALL NOT poll faster than
the health cache's time-to-live.

The render-layer privacy boundary (diagnostics templates render only metadata, never
cognitive content) SHALL remain unchanged.

#### Scenario: Console uses one stream

- **WHEN** the console page is open
- **THEN** exactly one diagnostics `EventSource` connection is established
- **AND** each bus event is privacy-filtered once before fan-out

#### Scenario: Hidden tab stops streaming

- **WHEN** the operator backgrounds the tab
- **THEN** the SSE and pollers pause until the tab is visible again

#### Scenario: Dropped connection is visible

- **WHEN** the stream disconnects
- **THEN** the UI shows a reconnecting state rather than continuing to display stale
  values as live

### Requirement: The status chip reflects real cycle state

The left-rail status chip SHALL reflect the real cognitive-cycle state, not a hardwired
awake/sleeping binary. It SHALL be a four-state chip — OFFLINE, FROZEN, SLEEPING,
AWAKE — computed live from the single diagnostics stream (the pushed cycle-status and
operator-freeze flag, plus the sleep module's sleep/wake events), with priority
OFFLINE > FROZEN > SLEEPING > AWAKE. Its page-load default (before any live data
arrives) SHALL be OFFLINE, since with no live data the console cannot know a cycle is
running. The chip inputs SHALL be metadata-only (cycle running-state, freeze flag,
sleep/wake) and carry no cognitive content.

#### Scenario: No cycle running reads OFFLINE

- **WHEN** no cognitive cycle is running (including at page load, before live data)
- **THEN** the status chip reads OFFLINE (not AWAKE)

#### Scenario: Frozen cycle reads FROZEN

- **WHEN** the cycle is running but the experiential loop is frozen (operator freeze)
- **THEN** the status chip reads FROZEN

#### Scenario: Running cycle reflects sleep/wake

- **WHEN** the cycle is running, not frozen, and the sleep module is asleep
- **THEN** the status chip reads SLEEPING
- **AND WHEN** the sleep module wakes, the chip reads AWAKE

### Requirement: The diagnostics streams are streams that something writes
Every stream returned by `diagnostics_streams()` SHALL be one the system writes: `workspace.broadcast` or `module_stream(name)` for a canonical module name. It SHALL include `cycle.out`, so `cycle.tick`, `cycle.rates` and `cycle.time_scale` events reach the dashboard. It SHALL NOT list an event type as if it were a stream.

#### Scenario: No phantom stream
- **WHEN** the diagnostics stream list is built
- **THEN** every entry is `workspace.broadcast` or the output stream of a canonical module, and `cycle.tick` is not in the list

#### Scenario: Ticks reach the feed
- **WHEN** the cycle publishes a `cycle.tick` event
- **THEN** the dashboard bridge relays it to diagnostics clients

### Requirement: Charts read the events that carry their data
The coherence chart SHALL plot `metadata.coherence` from `workspace.broadcast` events when it is a number. The salience chart SHALL plot only module events, not events from source `cycle` or `workspace`.

#### Scenario: Coherence from a broadcast
- **WHEN** a `workspace.broadcast` event carries `metadata.coherence = 0.42`
- **THEN** the coherence chart receives the sample 0.42

#### Scenario: Operational events stay off the salience chart
- **WHEN** a `cycle.tick` event with salience 0.05 arrives
- **THEN** the salience chart receives no sample from it

### Requirement: The bridge relays every event published after it starts
The dashboard bus bridge SHALL resolve each stream's starting cursor to that stream's last entry id at the time of its first successful read (`0-0` when the stream is empty) and SHALL relay, after the privacy filter, every decodable event published to its streams after that point. A failed resolution SHALL be retried on the next poll. A non-blocking read SHALL never be issued with the `$` cursor.

#### Scenario: Events after start reach a client
- **WHEN** the bridge has started and a module publishes an event to a diagnostics stream
- **THEN** a connected diagnostics client receives that event, filtered, within a poll interval

#### Scenario: History before start is not replayed
- **WHEN** a stream already holds entries when the bridge starts
- **THEN** those entries are not relayed, and the next new entry is

### Requirement: Diagnostics SSE requires authentication when privileged content is enabled
When `[dashboard].dev_content_override` is true or `[dashboard].conversation_enabled` is true, the unified diagnostics SSE stream SHALL require the operator token. When both are false, the stream may remain unauthenticated but SHALL still carry only privacy-filtered content.

#### Scenario: Privileged SSE without token is rejected
- **WHEN** `dev_content_override` is true and a client connects to the diagnostics SSE stream without a token
- **THEN** the server responds with HTTP 401 and does not start the stream

#### Scenario: Filtered SSE remains privacy-safe
- **WHEN** `dev_content_override` is false and a client connects to the diagnostics SSE stream
- **THEN** the stream carries only content that has passed the `PrivacyFilter`

### Requirement: Metrics endpoints that expose privileged content require authentication
Any metrics or health endpoint that can expose module-internal details (e.g. raw error messages containing paths or model identifiers) SHALL require the operator token when `dev_content_override` is enabled.

#### Scenario: Metrics endpoint without token is rejected in dev mode
- **WHEN** `dev_content_override` is true and a client requests a metrics endpoint without a token
- **THEN** the server responds with HTTP 401

### Requirement: The entity name is always shown and kept current
Every dashboard page SHALL show the entity's name in its shared header, whether or not the conversation surface is enabled. The dashboard SHALL re-read the name from the self-model document and the identity file when either changes, so a name assigned after the dashboard started is shown without a restart. Before a name exists the header SHALL show the placeholder.

#### Scenario: The first configuration
- **WHEN** the dashboard runs with `conversation_enabled = false` and the identity holds "Kaine Whipple"
- **THEN** the diagnostics page header shows "Kaine Whipple"

#### Scenario: A name minted after startup
- **WHEN** the dashboard starts before the identity file exists and the cycle then writes a named identity
- **THEN** the header shows the name without a dashboard restart

### Requirement: Dashboard welfare counts honour restart resets
The dashboard SHALL compute welfare counts with the reset-aware reader, so a count after a restart reset is not raised by records from before it. The evaluation tab SHALL read only the rollups the cycle writes, and SHALL NOT report counters from a sidecar registry the dashboard process never starts.

#### Scenario: Dashboard welfare counts honour restart resets
- **WHEN** the welfare JSONL holds a count of 5, then a restart reset, then a count of 0
- **THEN** the dashboard shows 0

#### Scenario: No registry stands in for the cycle
- **WHEN** the dashboard builds the evaluation tab
- **THEN** it builds no sidecar registry and no panel reports a source of live

### Requirement: Backend load failures come from the cycle
The cycle SHALL write the content-free records of its runtime-backend load failures (`module`, `backend`, `reason`, `fallback`, `ts`) into `state/cycle/runtime.json` as `backend_failures`, an empty list when every selected backend loaded. The dashboard's `backends` block SHALL report those records together with any recorded in the dashboard's own process, and SHALL carry `source`: `cycle` when the runtime file holds the list, `cycle_not_running` when there is no runtime file, `not_reported` when the file lacks the key. `ok` SHALL be false when any failure is reported, true when the cycle reported an empty list and the dashboard recorded none, and null otherwise. The health board SHALL show the block.

#### Scenario: The cycle fell back
- **WHEN** the cycle recorded that the language module's `llama_cpp` backend failed and `ollama` was used instead
- **THEN** the backends block has `ok` false and that record, and the health board shows it with its fallback

#### Scenario: No cycle running
- **WHEN** there is no runtime file and the dashboard recorded no failure
- **THEN** the block has `ok` null and `source` "cycle_not_running", and the board says the cycle is not running

#### Scenario: Every backend loaded
- **WHEN** the runtime file holds an empty `backend_failures` list
- **THEN** the block has `ok` true and `source` "cycle"

### Requirement: The console shows the entity's name
The dashboard SHALL show the entity's name in the console's page title and left rail. At start it SHALL read the name from the self-model file at `[self_model].persistence_path` through the self-model document loader, and when that file holds no name, from an optional `name` field of the identity file. While running it SHALL take the name from the `name` field of each `self_model.document` event on `self_model.out`, read by a bridge observer whether or not a browser is connected, and when the app starts it SHALL read the newest such event already on the stream. When no source gives a non-empty name the console SHALL show "KAINE". A missing, unreadable or undecryptable file and a bus error SHALL leave the name as it was and SHALL NOT stop the dashboard. The observer SHALL read no other field of the event.

#### Scenario: The persisted launch name is shown
- **WHEN** the self-model file holds the name "Kaine Voxel" and the dashboard starts
- **THEN** the console's title and left rail show "Kaine Voxel"

#### Scenario: A rename arrives on the bus
- **WHEN** a `self_model.document` event with the name "Lyra" is read from `self_model.out` and no browser is connected
- **THEN** the next console page shows "Lyra"

#### Scenario: No name anywhere
- **WHEN** the self-model file and the identity file are absent and the bus holds no `self_model.document` event
- **THEN** the console shows "KAINE"

### Requirement: The status chip starts from the server's sleep state
The dashboard SHALL follow `sleep.sleep.started` and `sleep.sleep.completed` on `sleep.out` through a bridge observer and, when the app starts, SHALL read the newest of the two among the stream's last 500 entries. The console SHALL render that state on the status chip as a `data-sleeping` attribute, and the chip script SHALL start from it, so a page opened during a sleep shows "sleeping" once the cycle reports running.

#### Scenario: A page opened during a sleep
- **WHEN** the newest sleep lifecycle event is `sleep.sleep.started` and the console is loaded
- **THEN** the chip carries `data-sleeping="true"` and reads "sleeping" after the first metrics snapshot reports the cycle running

#### Scenario: An observer error does not stop the bridge
- **WHEN** an observer raises on an event
- **THEN** the error is logged and the bridge still delivers that event and later ones

### Requirement: The welfare board shows the affect welfare record
The health snapshot's `welfare` block SHALL carry `affect_welfare`: the newest `affect_welfare` record in the welfare rollup, holding only its timestamp and these numeric measures (each a finite number or null): `awake_seconds`, `negative_valence_bar`, `negative_valence_share`, and for each of `boredom`, `social_drive` and `restlessness` the `_uncontrolled_share`, `_uncontrolled_per_awake_hour`, `_deprivation_share`, `_sleep_reset_ends` and `_open_crossings` measures, and `curiosity_interest_share`, together with `current_run`, true when no observer start follows the record in the rollup. Any other field SHALL be dropped. With no record the value SHALL be null. The welfare board SHALL show the measures per drive, the record's time, and a note when the record predates the observer's latest start.

#### Scenario: A record since the latest start
- **WHEN** the rollup's newest affect welfare record follows its latest reset advisory
- **THEN** the panel shows its measures per drive and `current_run` is true

#### Scenario: Only an older record
- **WHEN** a reset advisory follows the newest affect welfare record
- **THEN** the panel shows that record with a note that it predates the observer's latest start

### Requirement: The welfare board shows the sleep trigger, the rest and rest requests
The dashboard SHALL follow `sleep.sleep.started`, `sleep.sleep.completed` and `affect.rest_request` through a bridge observer and, when the app starts, SHALL read the newest of them from the last 2000 entries of `sleep.out` and `affect.out`. `GET /diagnostics/sleep.json` SHALL return whether the entity sleeps, the current or last sleep's trigger, start time, duration, developmental rest length and abort flag, and the last rest request's reason, drive, stall length and time. The trigger SHALL be the one the sleep module states (`developmental_rest` on the completion, or `developmental_rest` or `requested` on the start). For a sleep whose start the dashboard saw without a trigger, it SHALL be `backstop` when the completion carries `fatigue_triggered` false and `fatigue_or_backstop` when it carries true, since that flag stays true after the first fatigue sleep. Otherwise it SHALL be null. Labels read from the bus SHALL be kept only when they are lower-case identifiers of at most 40 characters.

#### Scenario: A developmental rest
- **WHEN** `sleep.sleep.started` carries `trigger` "developmental_rest" and the completion carries `rest_seconds` 1260
- **THEN** sleep.json reports the trigger "developmental_rest" and the rest length 1260 s

#### Scenario: An interval sleep
- **WHEN** a sleep starts without a trigger and completes with `fatigue_triggered` false
- **THEN** sleep.json reports the trigger "backstop"

#### Scenario: A sleep after an earlier fatigue sleep
- **WHEN** a sleep starts without a trigger and completes with `fatigue_triggered` true
- **THEN** sleep.json reports the trigger "fatigue_or_backstop"

#### Scenario: A spent stimulus
- **WHEN** `affect.rest_request` arrives with reason "stimulus_spent", drive "boredom" and `stall_s` 612
- **THEN** sleep.json reports that request with its time

### Requirement: The development panel shows the hearing stage's dwell
`/diagnostics/maturation.json` SHALL carry, in `hearing`, `dwell_seconds` read from `state/lifecycle/hearing_stage.json` (null when the file is missing, unusable, or names a different stage than the runtime reading) and the configured `min_dwell_seconds` and `max_dwell_seconds`. The development panel SHALL show the dwell in hours against the bounds, for example "1.2 h of 1.5 to 7 h", after the band, and SHALL show no dwell when the dwell or a bound is missing or the stage is 4.

#### Scenario: Stage 3 with 4320 s of dwell
- **WHEN** the owner file holds stage 3 and dwell 4320 s, and the bounds are 5400 s and 25200 s
- **THEN** the panel shows "stage 3 of 4, below 1732.1 Hz, 1.2 h of 1.5 to 7 h"

#### Scenario: The owner file is missing
- **WHEN** `hearing_stage.json` cannot be read
- **THEN** `dwell_seconds` is null and the panel shows the stage and band without a dwell

### Requirement: The development panel shows the hearing stage and the gate's conditions
`/diagnostics/maturation.json` SHALL return the runtime file's `hearing_stage` as `hearing` (or null), and its `development` object SHALL keep the gate status's `world` and `conditions` beside the existing keys. The development panel SHALL show the hearing stage as "stage N of 4" with its band (both edges, "below" the upper edge, or "open"), the world, each readiness marker the gate reports as not applicable, and the consolidation passes only when `conditions.c2_consolidation_required` is true; when it is false the panel SHALL say that consolidation is not required.

#### Scenario: A perceptual world without a world model
- **WHEN** the gate reports `world` "perceptual", `c2_sleep_required` and `c2_consolidation_required` false and the marker `C2_reality_model_consolidated` as not applicable
- **THEN** the panel shows the world, marks C2 not applicable and says consolidation is not required, with no pass count

#### Scenario: The hearing band in its second step
- **WHEN** runtime.json holds `hearing_stage` with stage 1 and the band 158.1 to 707.1 Hz
- **THEN** the panel shows "stage 1 of 4" and "158.1 to 707.1 Hz"

### Requirement: The perception-feed panel describes the developmental feed
In stimulus-source mode the perception-feed block SHALL carry a `stimulus_source` summary with the base heartbeat rate and drift, the colour ramp's time constant and hue gain, whether the maternal voice is on (null when its parameters cannot be read), and the hearing band's span and whether it is on, all read from the feed configuration. The panel SHALL show them and the current hearing stage. The summary SHALL hold only numbers and booleans.

#### Scenario: The shipped stimulus source
- **WHEN** the feed is `stimulus_source` with the shipped parameters
- **THEN** the panel shows a 70 bpm heartbeat, a 3600 s colour ramp, the maternal voice on and a 43200 s hearing span

### Requirement: The module grid shows the perception modules on a deterministic feed as capturing
The module grid SHALL mark the vision and audition modules capturing when the running cycle has them and the feed mode is `seeded`, `playlist`, `screen` or `stimulus_source`, or when their live sensor is active, and SHALL name the feed (the mode, or "live").

#### Scenario: The stimulus-source feed
- **WHEN** the cycle runs with the vision module and the feed mode is `stimulus_source`
- **THEN** the vision row reads capturing with the feed "stimulus_source"

#### Scenario: Feed off and no live sensor
- **WHEN** the feed mode is `off` and the camera is not live
- **THEN** the vision row is not capturing

### Requirement: The sleep panel names the state-cycle rest
The dashboard's sleep panel SHALL label a sleep with trigger `state_cycle` as a state-cycle rest and SHALL show its rest length.

#### Scenario: A state-cycle rest
- **WHEN** the latest sleep has trigger `state_cycle` and `rest_seconds` 1410
- **THEN** the sleep panel shows a state-cycle rest of 1410 s

### Requirement: Earlier records stay readable and the rest-request line is gone
The sleep panel SHALL label a sleep with trigger `developmental_rest`, recorded under the earlier rule, as a developmental rest of the earlier rule, and SHALL show no rest-request line, because the affect module no longer publishes `affect.rest_request`.

#### Scenario: An earlier developmental rest
- **WHEN** the latest sleep has trigger `developmental_rest`
- **THEN** the sleep panel labels it as a developmental rest (earlier rule)
