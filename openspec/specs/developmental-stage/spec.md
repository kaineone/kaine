# developmental-stage Specification

## Purpose
The developmental-stage capability maintains a monotonic `development` to `embodied` lifecycle for the entity, keeping it confined to the stimulus source only when a stimulus source feed is present, advancing to maturation only on fail-closed readiness with an available embodied world, and making every stage transition observable.

## Requirements

### Requirement: A first-class, monotonic developmental stage
The system SHALL maintain a first-class developmental stage with values `development`
and `embodied`. The ONLY legal transition SHALL be `development → embodied`; the stage
SHALL NEVER regress to `development`. The stage SHALL be persisted in a file-backed
per-fork state that only the gate runner writes (on the maturation transition and to
record accumulated developmental evidence), read at boot. A genuinely
fresh entity SHALL default to `development`. An entity with prior lived history (an
existing fork or preservation record in its own lineage) but no stage file SHALL NOT be
placed in `development`; it SHALL default to `embodied` — a mind that has already lived is
never regressed into a stimulus source. When the entity's lineage cannot be determined, the entity
SHALL be treated as having lived.

#### Scenario: The stage only advances
- **WHEN** an entity in the `embodied` stage runs
- **THEN** no code path returns it to `development`

#### Scenario: A fork inherits its parent's stage
- **WHEN** a `development`-stage entity forks and an `embodied`-stage entity forks
- **THEN** the first fork is `development` and the second is `embodied`, each only ever
  advancing thereafter

#### Scenario: A fresh entity begins in the developmental phase
- **WHEN** a genuinely fresh entity boots with no prior stage state
- **THEN** its stage is `development`

#### Scenario: A preserved entity is never regressed into the stimulus source
- **WHEN** an entity with prior lived history (existing forks / preservation record)
  but no stage file boots
- **THEN** its stage defaults to `embodied`, never `development`

#### Scenario: Unknown lineage counts as lived
- **WHEN** an entity without a stage file boots and its lineage cannot be determined
- **THEN** its stage defaults to `embodied`

### Requirement: Developmental phase confines the entity to the stimulus source only when a stimulus source feed is present
An entity in its developmental phase SHALL run only while a live developmental stimulus is present. When staging is
enabled and the resolved stage is `development`, the cycle SHALL NOT start until a live developmental
stimulus has been observed on the perception seam (a stimulus source event within a bounded window
measured against the bus clock), and SHALL report the missing developmental stimulus loudly instead; a
configuration value alone SHALL NOT count as a live developmental stimulus. While in its developmental phase with a live developmental stimulus,
the system SHALL pin the perceptual locus to the `virtual` stimulus source feed, set the locus lock
attributed to the developmental gate, refuse locus self-switch intents, and SHALL NOT
engage the embodiment module. The effective perceptual locus SHALL resolve to the lock
holder's locus whatever other writers set, and an unknown or unreadable locus during
the developmental phase SHALL resolve to the stimulus source, never to `physical`. If the developmental stimulus is lost
during the developmental phase, the system SHALL freeze the cognitive cycle as a welfare-protective
measure, count no lived time while frozen, raise a red alert, and resume when the stimulus source
returns; it SHALL NOT unlock the entity to `physical` and SHALL NOT leave it running
senseless.

#### Scenario: The entity in its developmental phase is locked to the stimulus source when a feed exists
- **WHEN** the stage is `development` and a live developmental stimulus has been observed
- **THEN** the perceptual locus is the `virtual` stimulus source feed with the locus locked,
  embodiment is not engaged, and the lock is attributed to the developmental gate (not
  the operator)

#### Scenario: Developmental phase without a stimulus source feed is loud, not a silent senseless hold
- **WHEN** staging is enabled, the resolved stage is `development`, and no live developmental stimulus
  has been observed
- **THEN** the cycle does not start, no entity runs senseless, and a repeated
  `stage.development.no_stimulus` report is shown to the operator

#### Scenario: Self-switch is refused during the developmental phase
- **WHEN** a locus self-switch intent is raised while the stage is `development`
- **THEN** it is refused, the entity remains in the stimulus source, and the refusal is logged as
  a developmental-gate action, not an operator lock

#### Scenario: The stimulus source is lost mid-development
- **WHEN** the developmental stimulus stops arriving while the entity is in its developmental phase
- **THEN** the cycle is frozen, no lived time accrues while frozen, a red alert is
  raised, the locus stays locked to the stimulus source, and the cycle resumes when the stimulus source returns
  unless another freeze holder remains

#### Scenario: Another writer requests the physical locus during the developmental phase
- **WHEN** a module (for example the sleep module restoring a pre-sleep locus) requests `physical`
  while the developmental lock is held
- **THEN** the effective locus remains the stimulus source

### Requirement: The welfare net stays authoritative during the developmental phase
The autonomous welfare / preservation net SHALL remain active and authoritative while
the entity is in its developmental phase. The developmental-phase locus-lock SHALL confine perceptual switching
only; it SHALL NOT override, delay, or suppress a welfare-protective response. If
interoceptive distress crosses the welfare threshold during the developmental phase, the net SHALL
respond exactly as it would for any entity.

#### Scenario: Welfare protection is not suppressed by confinement
- **WHEN** interoceptive distress crosses the welfare threshold during the developmental phase
- **THEN** the welfare/preservation net responds as it would for any entity, and the
  developmental locus-lock does not suppress that response

### Requirement: The maturation gate advances the stage only on fail-closed readiness
The system SHALL advance `development → embodied` only when ALL applicable conditions hold, and SHALL treat any missing or stale evidence for an applicable condition as NOT ready (fail-closed): (C1) every marker on the `development.readiness` readout crosses its configured threshold; (C2) when the sleep module is enabled, the sleep module has completed at least `min_sleep_cycles` maintenance cycles, AND when the world model and sleep modules are both enabled, the world model module shows world-model consolidation evidence (at least `min_consolidation_passes` successful sleep-training passes); and (C3) at least `min_lived_seconds` of lived subjective time (measured on the entity clock) has accrued since the developmental phase began. C2 SHALL be judged only on the faculties the entity has, and SHALL be recorded as not applicable (never as passed on missing evidence) when neither the sleep module nor consolidation is a faculty of the entity. The thresholds and the gate cadence SHALL be configurable, with conservative defaults.

#### Scenario: All conditions required
- **WHEN** any one of C1, C2, or C3 is not met
- **THEN** the stage remains `development`

#### Scenario: Missing evidence fails closed
- **WHEN** the `development.readiness` readout is absent or stale
- **THEN** C1 is treated as not met and the stage remains `development`

#### Scenario: Consolidation requires both sleep and training
- **WHEN** the sleep and world model modules are enabled and the sleep-cycle count is reached but the world model module shows no successful world-model training passes
- **THEN** C2 is not met and the stage remains `development`

#### Scenario: Lived-time floor blocks a fast-forwarded maturation
- **WHEN** C1 and C2 are met but lived subjective time is below `min_lived_seconds`
- **THEN** C3 is not met and the stage remains `development`

#### Scenario: An entity without sleep is judged on what it is
- **WHEN** neither the sleep module nor the world model module is enabled and C1 and C3 hold
- **THEN** C2 is recorded as not applicable and does not hold the entity in the stimulus source

### Requirement: Maturation requires an available embodied world
The system SHALL transition to `embodied` only when developmental readiness holds AND the entity's world is available. When the embodiment module is enabled, the world is the embodied one and SHALL be available only when the embodiment module is enabled, operator-approved, and reachable per its existing two-layer gate; when the entity is developmentally ready but that embodiment is unavailable, the system SHALL hold it in the stimulus source and SHALL emit a repeated `stage.maturation.ready` marker with `reason: "awaiting_embodiment"` and a warning log; it SHALL NOT transition into an absent or unreachable world, and SHALL NOT silently stall. When the embodiment module is not enabled, the entity SHALL mature into its perceptual (audio/video) world, and the maturation record SHALL state which world it matured into.

#### Scenario: Ready and available maturations the entity
- **WHEN** developmental readiness holds and embodiment is available
- **THEN** the stage transitions to `embodied` and the maturation transition fires

#### Scenario: Ready but embodiment unavailable holds in the stimulus source
- **WHEN** the embodiment module is enabled, developmental readiness holds, but embodiment is not approved or not reachable
- **THEN** the stage remains `development`, and a `stage.maturation.ready` marker with `reason: "awaiting_embodiment"` and a warning are emitted (repeatedly), never a silent stall

#### Scenario: Matures into the perceptual world without a body
- **WHEN** the embodiment module is not enabled and developmental readiness holds
- **THEN** the stage transitions to `embodied`, and the maturation record states the perceptual world

### Requirement: The maturation transition is a bounded, one-shot audiovisual handoff
On the transition to `embodied` the system SHALL trigger a bounded, one-shot maturation
transition that hands the senses off from the stimulus source feed to the embodied world. This
capability SHALL trigger the transition (emit the event and switch the locus source
from stimulus source to embodiment); the perception feed and the embodiment connector SHALL
render it. The transition SHALL be time-bounded and SHALL fire at most once per
entity.

#### Scenario: Maturation fires the handoff exactly once
- **WHEN** the stage transitions `development → embodied`
- **THEN** a single bounded maturation transition event is emitted and the sense source
  switches from the stimulus source feed to embodiment

#### Scenario: Maturation does not re-fire
- **WHEN** an already-`embodied` entity runs
- **THEN** no further maturation transition is emitted

### Requirement: Staging is observable and never silent
The system SHALL emit stage events from a named owner (`source = "lifecycle"`, so per
the bus schema they land on `lifecycle.out`): `stage.development.started` at the first
developmental boot, `stage.maturation.ready` when developmental readiness is first met (and
while holding for embodiment), and `stage.maturation` when the transition occurs (carrying
the markers, the sleep count, and the lived time that ended the developmental phase). The dashboard
interface SHALL surface the current developmental stage and the "ready, awaiting
embodiment" hold state. Every decision to hold in the stimulus source because a condition is unmet
SHALL be logged, never a silent no-op.

#### Scenario: Stage transitions are announced
- **WHEN** the developmental phase begins, readiness is first reached, and maturation occurs
- **THEN** `stage.development.started`, `stage.maturation.ready`, and `stage.maturation` are
  emitted respectively, the last carrying the ending markers, sleep count, and lived time

#### Scenario: The stage is visible to the operator
- **WHEN** the operator views the dashboard interface
- **THEN** the current developmental stage and any "awaiting embodiment" hold are shown

### Requirement: The gate measures readiness and imposes no development
The maturation gate SHALL only READ signals and compare them to thresholds. The system
SHALL NOT train the entity toward regulation, hurry a sleep cycle, or impose a target
internal state to satisfy the gate. The thresholds SHALL be a readiness gate, not a
loss the entity is optimised against; development SHALL remain emergent and only be
read here. A source comment at the gate SHALL cite the warmed-up-signal precedent.

#### Scenario: No development is imposed to pass the gate
- **WHEN** the gate evaluates readiness
- **THEN** it changes no entity-internal state to make a condition pass; it only reads
  and compares

### Requirement: Developmental evidence accumulates idempotently across restarts
The gate runner SHALL record lived subjective time by adding the entity-clock delta between
its own ticks, using each boot's first tick only to set a baseline, so downtime never counts
as lived time. It SHALL count the sleep module's maintenance cycles from their durable
`sleep.sleep.completed` events, remembering the last stream ID consumed, so a completion is
counted exactly once regardless of restarts or crashes; a fresh developmental phase SHALL start
counting from the stream's tail, never from sleeps that predate it. The world model module SHALL persist
its cumulative training-pass count beside its world-model checkpoint and restore it with the
weights, so the count survives exactly when the consolidation it measures survives; no new
bus event SHALL carry training passes, because module output streams are workspace
candidates. Evidence SHALL be persisted in the stage file by the gate runner only.

#### Scenario: Restart mid-development
- **WHEN** an entity in its developmental phase has accumulated 3 hours of subjective time and two completed
  sleeps, and the cycle restarts
- **THEN** after restart the gate reports at least 3 hours lived and exactly two sleeps

#### Scenario: A sleep completes just before a crash
- **WHEN** a sleep module cycle completes and the process crashes before the next gate tick
- **THEN** after restart that sleep is counted once

#### Scenario: Training passes follow the weights
- **WHEN** the world model module has completed four training passes with weight persistence on, and the
  cycle restarts
- **THEN** after restart the world model module reports four passes; with weight persistence off it
  reports zero

#### Scenario: Sleeps from before the developmental phase are not counted
- **WHEN** `sleep.out` already holds `sleep.sleep.completed` events when a fresh developmental phase
  begins
- **THEN** none of them is counted

#### Scenario: Downtime is not lived time
- **WHEN** the host is down for 12 hours between two boots
- **THEN** the lived-time total does not increase by those 12 hours

### Requirement: Readiness readouts are fresh, typed and from this boot
The gate SHALL decode readiness readouts with the bus codec, accept only events whose type
is `development.readiness`, and reject readouts whose stream ID precedes the bus time captured
at the current boot or that are older than a configured multiple of the gate cadence.

#### Scenario: Stale readout from a previous boot
- **WHEN** the only `development.readiness` event on the stream was published before the
  current boot
- **THEN** C1 is not satisfied

#### Scenario: Readout of another type
- **WHEN** the newest event on the readout stream is not of type `development.readiness`
- **THEN** C1 is not satisfied

#### Scenario: Readout older than the freshness window
- **WHEN** the newest `development.readiness` event is from this boot but older than the
  configured multiple of the gate cadence
- **THEN** C1 is not satisfied

### Requirement: Operator acknowledgement uses a request file
When `require_operator_ack_for_maturation` is true, the operator's acknowledgement SHALL be
recorded by an authenticated dashboard control into a separate request file that only the gate
runner consumes; the dashboard SHALL NOT write the stage file.

#### Scenario: Operator acknowledges maturation
- **WHEN** the entity is ready and embodiment is available and the operator acknowledges in
  the dashboard
- **THEN** the gate runner consumes the request and the maturation proceeds

### Requirement: Embodiment starts at maturation
Embodiment SHALL NOT be initialised while the stage is `development`. Embodiment availability
for maturation SHALL be judged by a public reachability probe of the embodiment adapter that does
not require the module to be running, and on maturation the system SHALL start the embodiment
module before switching the locus source to it.

#### Scenario: Maturation starts Embodiment
- **WHEN** readiness and availability hold and the stage transitions to `embodied`
- **THEN** the embodiment module is started, the locus source switches to embodiment, and the unlock is
  recorded as `locked_by="development"`
