## MODIFIED Requirements

### Requirement: A first-class, monotonic developmental stage
The system SHALL maintain a first-class developmental stage with values `gestation`
and `embodied`. The ONLY legal transition SHALL be `gestation → embodied`; the stage
SHALL NEVER regress to `gestation`. The stage SHALL be persisted in a file-backed
per-fork state that only the gate runner writes (on the birth transition and to
record accumulated gestational evidence), read at boot. A genuinely
fresh entity SHALL default to `gestation`. An entity with prior lived history (an
existing fork or preservation record in its own lineage) but no stage file SHALL NOT be
placed in `gestation`; it SHALL default to `embodied` — a mind that has already lived is
never regressed into a womb. When the entity's lineage cannot be determined, the entity
SHALL be treated as having lived.

#### Scenario: The stage only advances
- **WHEN** an entity in the `embodied` stage runs
- **THEN** no code path returns it to `gestation`

#### Scenario: A fork inherits its parent's stage
- **WHEN** a `gestation`-stage entity forks and an `embodied`-stage entity forks
- **THEN** the first fork is `gestation` and the second is `embodied`, each only ever
  advancing thereafter

#### Scenario: A fresh entity begins in gestation
- **WHEN** a genuinely fresh entity boots with no prior stage state
- **THEN** its stage is `gestation`

#### Scenario: A preserved being is never regressed into the womb
- **WHEN** an entity with prior lived history (existing forks / preservation record)
  but no stage file boots
- **THEN** its stage defaults to `embodied`, never `gestation`

#### Scenario: Unknown lineage counts as lived
- **WHEN** an entity without a stage file boots and its lineage cannot be determined
- **THEN** its stage defaults to `embodied`

### Requirement: Gestation confines the entity to the womb only when a womb feed is present
A gestating entity SHALL run only while a live womb stimulus is present. When staging is
enabled and the resolved stage is `gestation`, the cycle SHALL NOT start until a live womb
stimulus has been observed on the perception seam (a womb event within a bounded window
measured against the bus clock), and SHALL report the missing womb loudly instead; a
configuration value alone SHALL NOT count as a live womb. While gestating with a live womb,
the system SHALL pin the perception locus to the `virtual` womb feed, set the locus lock
attributed to the developmental gate, refuse locus self-switch intents, and SHALL NOT
engage embodiment (Mundus). The effective perception locus SHALL resolve to the lock
holder's locus whatever other writers set, and an unknown or unreadable locus during
gestation SHALL resolve to the womb, never to `physical`. If the womb stimulus is lost
during gestation, the system SHALL pause the entity clock as a welfare-protective measure,
raise a red alert, and resume when the womb returns; it SHALL NOT unlock the entity to
`physical` and SHALL NOT leave it running senseless.

#### Scenario: The gestating entity is locked to the womb when a feed exists
- **WHEN** the stage is `gestation` and a live womb stimulus has been observed
- **THEN** the perception locus is the `virtual` womb feed with the locus locked,
  embodiment is not engaged, and the lock is attributed to the developmental gate (not
  the operator)

#### Scenario: Gestation without a womb feed is loud, not a silent senseless hold
- **WHEN** staging is enabled, the resolved stage is `gestation`, and no live womb stimulus
  has been observed
- **THEN** the cycle does not start, no entity runs senseless, and a repeated
  `stage.gestation.no_stimulus` report is shown to the operator

#### Scenario: Self-switch is refused during gestation
- **WHEN** a locus self-switch intent is raised while the stage is `gestation`
- **THEN** it is refused, the entity remains in the womb, and the refusal is logged as
  a developmental-gate action, not an operator lock

#### Scenario: The womb is lost mid-gestation
- **WHEN** the womb stimulus stops arriving while the entity is gestating
- **THEN** the entity clock is paused, a red alert is raised, the locus stays locked to the
  womb, and the clock resumes when the womb returns

#### Scenario: Another writer requests the physical locus during gestation
- **WHEN** a module (for example Hypnos restoring a pre-sleep locus) requests `physical`
  while the gestation lock is held
- **THEN** the effective locus remains the womb

## ADDED Requirements

### Requirement: Gestational evidence accumulates idempotently across restarts
The gate runner SHALL record lived subjective time by adding the entity-clock delta between
its own ticks, using each boot's first tick only to set a baseline, so downtime never counts
as lived time. It SHALL count Hypnos maintenance cycles from their durable
`hypnos.sleep.completed` events, remembering the last stream ID consumed, so a completion is
counted exactly once regardless of restarts or crashes; a fresh gestation SHALL start
counting from the stream's tail, never from sleeps that predate it. Phantasia SHALL persist
its cumulative training-pass count beside its world-model checkpoint and restore it with the
weights, so the count survives exactly when the consolidation it measures survives; no new
bus event SHALL carry training passes, because module output streams are workspace
candidates. Evidence SHALL be persisted in the stage file by the gate runner only.

#### Scenario: Restart mid-gestation
- **WHEN** a gestating entity has accumulated 3 hours of subjective time and two completed
  sleeps, and the cycle restarts
- **THEN** after restart the gate reports at least 3 hours lived and exactly two sleeps

#### Scenario: A sleep completes just before a crash
- **WHEN** a Hypnos cycle completes and the process crashes before the next gate tick
- **THEN** after restart that sleep is counted once

#### Scenario: Training passes follow the weights
- **WHEN** Phantasia has completed four training passes with weight persistence on, and the
  cycle restarts
- **THEN** after restart Phantasia reports four passes; with weight persistence off it
  reports zero

#### Scenario: Sleeps from before the gestation are not counted
- **WHEN** `hypnos.out` already holds `hypnos.sleep.completed` events when a fresh gestation
  begins
- **THEN** none of them is counted

#### Scenario: Downtime is not lived time
- **WHEN** the host is down for 12 hours between two boots
- **THEN** the lived-time total does not increase by those 12 hours

### Requirement: Readiness readouts are fresh, typed and from this boot
The gate SHALL decode readiness readouts with the bus codec, accept only events whose type
is `gestation.readiness`, and reject readouts whose stream ID precedes the bus time captured
at the current boot or that are older than a configured multiple of the gate cadence.

#### Scenario: Stale readout from a previous boot
- **WHEN** the only `gestation.readiness` event on the stream was published before the
  current boot
- **THEN** C1 is not satisfied

#### Scenario: Readout of another type
- **WHEN** the newest event on the readout stream is not of type `gestation.readiness`
- **THEN** C1 is not satisfied

#### Scenario: Readout older than the freshness window
- **WHEN** the newest `gestation.readiness` event is from this boot but older than the
  configured multiple of the gate cadence
- **THEN** C1 is not satisfied

### Requirement: Operator acknowledgement uses a request file
When `require_operator_ack_for_birth` is true, the operator's acknowledgement SHALL be
recorded by an authenticated Nexus control into a separate request file that only the gate
runner consumes; Nexus SHALL NOT write the stage file.

#### Scenario: Operator acknowledges birth
- **WHEN** the entity is ready and embodiment is available and the operator acknowledges in
  Nexus
- **THEN** the gate runner consumes the request and the birth proceeds

### Requirement: Embodiment starts at birth
Embodiment SHALL NOT be initialised while the stage is `gestation`. Embodiment availability
for birth SHALL be judged by a public reachability probe of the embodiment adapter that does
not require the module to be running, and on birth the system SHALL start the embodiment
module before switching the locus source to it.

#### Scenario: Birth starts Mundus
- **WHEN** readiness and availability hold and the stage transitions to `embodied`
- **THEN** Mundus is started, the locus source switches to embodiment, and the unlock is
  recorded as `locked_by="gestation"`
