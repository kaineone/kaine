# nexus-dashboard Specification

## Purpose
Nexus is the operator's local web dashboard for a running KAINE: service and
dependency health, live metrics, and the supported operator controls, presented in one
consistent visual design. It stays on loopback behind the operator token, never shows
cognitive content past the privacy boundary, explains an incomplete setup instead of
crashing, and only ever sends the operator to consoles that are mounted.

## Requirements

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

### Requirement: Nexus reports incomplete setup without a traceback
When the event bus cannot be configured, for example because no Redis password
exists yet, `python -m kaine.nexus` SHALL exit with status 1. It SHALL log a
single message that names the setup step that fixes the problem, and SHALL NOT
print a traceback.

#### Scenario: Fresh clone before Redis setup
- **WHEN** Nexus is started before `scripts/redis-bootstrap.sh` has run
- **THEN** it exits 1
- **AND** it logs a message naming `bash scripts/redis-bootstrap.sh`
- **AND** no traceback is printed

### Requirement: Login lands on a mounted console
After a successful sign-in, Nexus SHALL redirect the operator to a console
that is mounted:

- `/` when the conversation console is enabled;
- otherwise `/diagnostics/`.

Page navigation SHALL link only consoles that are mounted. Nexus SHALL refuse
to start when neither console is enabled, since sign-in would lead nowhere.

#### Scenario: Default configuration
- **WHEN** conversation is disabled and diagnostics is enabled
- **AND** the operator signs in
- **THEN** the login response redirects to `/diagnostics/`

#### Scenario: Conversation enabled
- **WHEN** conversation is enabled
- **AND** the operator signs in
- **THEN** the login response redirects to `/`

#### Scenario: Navigation links only mounted consoles
- **WHEN** conversation is disabled
- **THEN** the diagnostics and evaluation pages show no link to the conversation console
- **AND** their brand link points to `/diagnostics/`

#### Scenario: Nothing to serve
- **WHEN** both the conversation console and diagnostics are disabled
- **THEN** Nexus exits 1 with a message saying that no console is enabled

### Requirement: Nexus access mode
Nexus SHALL support `[nexus].access` with values `"open"` and `"token"`, overridable by `KAINE_NEXUS_ACCESS`. The committed configuration SHALL ship `"open"`. An invalid value SHALL fail startup with an error naming the allowed values.

**Open mode:**
- Every surface, read and state-changing, SHALL work without a token or sign-in.
- `/login` SHALL redirect to the landing console.
- At startup, Nexus SHALL log once, at INFO, that it is open to anyone who can reach it, and list the accepted hosts.

**Token mode** SHALL behave exactly as before: bearer token or session, with the session key required for state-changing requests.

**In both modes:**
- The Host allowlist and the Origin/CSRF validation SHALL apply to every request.
- A non-loopback bind SHALL still require `non_loopback_allowed`.

#### Scenario: Open mode needs no sign-in
- **WHEN** `access = "open"` and a browser on the same machine opens `/diagnostics/`
- **THEN** the page and its privileged reads succeed with no token or session

#### Scenario: Open mode still refuses foreign hosts
- **WHEN** `access = "open"` and a request arrives with a Host header that is not in the allowlist
- **THEN** it is rejected

#### Scenario: Open mode still refuses cross-origin writes
- **WHEN** `access = "open"` and a state-changing request carries an Origin that is not allowed
- **THEN** it is rejected

#### Scenario: Token mode is unchanged
- **WHEN** `access = "token"` and a request has no token or session
- **THEN** privileged surfaces are refused exactly as before

### Requirement: Tailnet hosts can reach Nexus
`KAINE_NEXUS_EXTRA_HOSTS`, a comma-separated list of host names or addresses, SHALL be added to the Host allowlist. For each entry, its `http://` and `https://` origins, with and without the configured and published ports, SHALL be added to the allowed origins. Entries SHALL be validated as host names or IP literals; an invalid entry SHALL fail startup naming it.

#### Scenario: Served over the tailnet
- **WHEN** `KAINE_NEXUS_EXTRA_HOSTS` names the machine's tailnet host and a tailnet browser opens `https://<that host>/diagnostics/` through `tailscale serve`
- **THEN** the Host and Origin checks accept it

### Requirement: The root address leads to a console
When the conversation console is not mounted, a request for `/` SHALL redirect to the landing console instead of returning 404.

#### Scenario: Observed study
- **WHEN** conversation is disabled and an operator opens `http://127.0.0.1:8088/`
- **THEN** the response redirects to `/diagnostics/`

### Requirement: Read-only mode refuses every control
Nexus SHALL support `[nexus].read_only` (default false), overridable by `KAINE_NEXUS_READ_ONLY`. When it is true, Nexus SHALL refuse every request whose method is not GET, HEAD or OPTIONS with HTTP 403, before routing and in every access mode. Pages SHALL show a banner saying controls are off. A study viewer SHALL run Nexus in read-only mode, because some controls (the cycle rate) reach a running entity through its bus.

#### Scenario: A rate change against a watched study is refused
- **WHEN** `read_only` is true and a client POSTs to `/diagnostics/cycle/rates`
- **THEN** the response is 403 and nothing is published to `cycle.control`

#### Scenario: Viewing still works
- **WHEN** `read_only` is true and a browser opens `/diagnostics/`
- **THEN** the page renders with the read-only banner

### Requirement: The merge form offers the world-model choice and shows refusal reasons
The dashboard's snapshot-merge form SHALL offer a labelled choice of which parent's Phantasia world model continues: none, A, or B. It SHALL send `world_model_from` as `"a"` or `"b"` when A or B is chosen and leave the field out otherwise. When the merge API answers with an error, the form SHALL show the status code and the server's `detail` text. The form SHALL NOT offer `allow_unmerged_adapters`.

#### Scenario: Choosing parent B's world model
- **WHEN** the operator enters two snapshot ids, chooses B under "world model from" and confirms the merge
- **THEN** the request body to `POST /diagnostics/merges` contains `"world_model_from": "b"`

#### Scenario: No choice leaves the field out
- **WHEN** the operator leaves "world model from" at none and confirms the merge
- **THEN** the request body contains no `world_model_from` key

#### Scenario: A refusal shows its reason
- **WHEN** the merge API answers `409` with detail "both parents carry a Phantasia world model; ..."
- **THEN** the form's status shows `409` and that detail text

### Requirement: Resume releases only the operator's own freeze
The Nexus resume control SHALL remove only freeze entries whose source is `operator`. When other holders remain, the cycle SHALL stay frozen and the response and the freeze panel SHALL name the remaining holders.

#### Scenario: Resume over a welfare pause
- **WHEN** the operator resumes while `operator` and `welfare` freezes are active
- **THEN** the `operator` entry is removed, the `welfare` entry stays, the cycle stays frozen, and Nexus shows that a welfare freeze is holding it

### Requirement: Protective freezes are lifted only by a named override
Nexus SHALL lift a `welfare`, `gestation` or `programme_end` freeze only through a separate override that names each holder it lifts and is confirmed by repeating those names. It SHALL refuse to override `spot` or `preserve` freezes, which release themselves, and any unknown source. Each override SHALL append a content-free record (time, sources lifted, holders remaining) to an audit log and SHALL be refused in read-only mode.

#### Scenario: A confirmed override lifts the named welfare freeze
- **WHEN** a welfare freeze is active and the operator overrides `welfare` with the confirmation `welfare`
- **THEN** the welfare entry is removed, one audit record is written, and the cycle resumes if no other holder remains

#### Scenario: An unconfirmed override is refused
- **WHEN** the operator overrides `welfare` with a confirmation that does not name it
- **THEN** the request is refused and the welfare freeze stays

### Requirement: Detail pages scroll vertically and keep each board whole
The diagnostics and evaluation pages SHALL lay their boards out so that a board's title stays with its cards and every board is reachable by scrolling down: the page takes its content's height and the main area scrolls vertically. They SHALL never place boards in columns beyond the visible width. The console keeps its fixed, non-scrolling screen. Key/value lists SHALL give their labels at most half the row, so values stay readable. The right sidebar SHALL not be rendered on pages that do not fill it.

#### Scenario: A tall board stays whole on the diagnostics page
- **WHEN** the health board is taller than the viewport on the diagnostics page
- **THEN** its title is directly above its cards, and the boards after it are reachable by scrolling down, none positioned past the right edge of the page

#### Scenario: No empty sidebar strip
- **WHEN** a page renders nothing into the right sidebar
- **THEN** no right sidebar element is rendered

### Requirement: The EventSource wrapper installs in browsers
The Nexus auth script SHALL replace `window.EventSource` with its wrapper without error when the browser's `EventSource` defines `CONNECTING`, `OPEN` and `CLOSED` as read-only, and the wrapper SHALL expose the same constant values.

#### Scenario: Read-only constants
- **WHEN** `nexus_auth.js` loads in a page whose `EventSource` constants are non-writable
- **THEN** no error is thrown, `window.EventSource` is the wrapper, and `window.EventSource.OPEN` equals the original value

### Requirement: Perception availability survives missing system libraries
The perception status endpoint SHALL report a live sense as unavailable, and still answer successfully, when importing that sense's extra fails because a system library it loads is missing (an `OSError` at import), exactly as when the extra is not installed.

#### Scenario: PortAudio is missing
- **WHEN** importing `sounddevice` raises `OSError("PortAudio library not found")`
- **THEN** `GET /diagnostics/perception.json` answers 200 with `audio_available` false

### Requirement: Diagnostics renders without a running cycle
The diagnostics page SHALL render successfully when no cycle is running, whether or not operator controls are enabled, treating every cycle metric the stopped-cycle snapshot omits as absent.

#### Scenario: Controls on, cycle stopped
- **WHEN** controls are enabled and the metrics snapshot holds only `cycle_status` and a hint
- **THEN** `GET /diagnostics/` answers 200 and shows the rate form without an effective-rate line

### Requirement: Operator controls require authentication and CSRF protection
All operator controls exposed by the Nexus dashboard (cycle freeze/unfreeze, cycle rate adjustment, fork/merge actions, perception toggle, and perception locus selection) SHALL be gated by both the operator token and CSRF/Origin validation. The controls SHALL NOT be reachable by unauthenticated or cross-origin requests.

#### Scenario: Unauthenticated freeze request is rejected
- **WHEN** a POST request arrives at the cycle freeze endpoint without a valid operator token
- **THEN** the server responds with HTTP 401 and the entity's freeze state is unchanged

#### Scenario: Cross-origin fork request is rejected
- **WHEN** a cross-origin POST arrives at a fork/merge endpoint with a valid token but failing Origin validation
- **THEN** the server responds with HTTP 403 and no fork or merge is performed

### Requirement: Privileged content surfaces require authentication
The conversation surface and any dashboard panel that renders raw message text, beliefs, memory bodies, internal speech, or affect reasons SHALL require the operator token before serving content.

#### Scenario: Conversation page without token is rejected
- **WHEN** `conversation_enabled` is true and a client requests the conversation page without a token
- **THEN** the server responds with HTTP 401 and renders no privileged content

#### Scenario: Dev-content diagnostics without token is rejected
- **WHEN** `dev_content_override` is true and a client requests the diagnostics stream without a token
- **THEN** the server responds with HTTP 401 and does not stream raw content
