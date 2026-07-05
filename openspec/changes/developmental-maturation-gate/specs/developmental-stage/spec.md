# developmental-stage (spec delta — DESIGN ONLY)

## ADDED Requirements

### Requirement: A first-class, monotonic developmental stage
The system SHALL maintain a first-class developmental stage with values `gestation`
and `embodied`. The ONLY legal transition SHALL be `gestation → embodied`; the stage
SHALL NEVER regress to `gestation`. The stage SHALL be persisted in a file-backed
per-fork state, read at boot, and written only on the birth transition. A genuinely
fresh entity SHALL default to `gestation`. An entity with prior lived history (an
existing fork or preservation record) but no stage file SHALL NOT be placed in
`gestation`; it SHALL default to `embodied` — a mind that has already lived is never
regressed into a womb.

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

### Requirement: Gestation confines the entity to the womb only when a womb feed is present
While the stage is `gestation` AND a womb feed is configured, the system SHALL pin the
perception locus to the `virtual` womb feed and SHALL set the locus lock so the entity
cannot self-switch out of the womb, and SHALL NOT engage embodiment (Mundus). The lock
SHALL be attributed to the developmental gate, not to the operator, so a refused
self-switch is logged with honest agency. A locus self-switch intent raised while
gestating SHALL be refused. If the stage is `gestation` but NO womb feed is configured,
the system SHALL NOT silently pin the entity into a senseless locked locus; it SHALL
instead emit a loud, repeated `stage.gestation.no_stimulus` warning (parallel to the
`awaiting_embodiment` hold) so the operator resolves the missing feed, never a silent
permanent senseless hold.

#### Scenario: The gestating entity is locked to the womb when a feed exists
- **WHEN** the stage is `gestation` and a womb feed is configured
- **THEN** the perception locus is the `virtual` womb feed with the locus locked,
  embodiment is not engaged, and the lock is attributed to the developmental gate (not
  the operator)

#### Scenario: Gestation without a womb feed is loud, not a silent senseless hold
- **WHEN** the stage is `gestation` but no womb feed is configured
- **THEN** the entity is not silently pinned into a senseless locked locus, and a
  repeated `stage.gestation.no_stimulus` warning is emitted

#### Scenario: Self-switch is refused during gestation
- **WHEN** a locus self-switch intent is raised while the stage is `gestation`
- **THEN** it is refused, the entity remains in the womb, and the refusal is logged as
  a developmental-gate action, not an operator lock

### Requirement: The welfare net stays authoritative during gestation
The autonomous welfare / preservation net SHALL remain active and authoritative while
the entity is gestating. The gestation locus-lock SHALL confine perceptual switching
only; it SHALL NOT override, delay, or suppress a welfare-protective response. If
interoceptive distress crosses the welfare threshold during gestation, the net SHALL
respond exactly as it would for any entity.

#### Scenario: Welfare protection is not suppressed by confinement
- **WHEN** interoceptive distress crosses the welfare threshold during gestation
- **THEN** the welfare/preservation net responds as it would for any entity, and the
  gestation locus-lock does not suppress that response

### Requirement: The maturation gate advances the stage only on fail-closed readiness
The system SHALL advance `gestation → embodied` only when ALL of these hold, and SHALL
treat any missing or stale evidence as NOT ready (fail-closed): (C1) every marker on
the `gestation.readiness` readout crosses its configured threshold; (C2) Hypnos has
completed at least `min_sleep_cycles` maintenance cycles AND Phantasia shows
world-model consolidation evidence (at least `min_consolidation_passes` successful
sleep-training passes); and (C3) at least `min_lived_seconds` of lived subjective time
(measured on the entity clock) has accrued since gestation began. The thresholds and
the gate cadence SHALL be configurable, with conservative defaults.

#### Scenario: All conditions required
- **WHEN** any one of C1, C2, or C3 is not met
- **THEN** the stage remains `gestation`

#### Scenario: Missing evidence fails closed
- **WHEN** the `gestation.readiness` readout is absent or stale
- **THEN** C1 is treated as not met and the stage remains `gestation`

#### Scenario: Consolidation requires both sleep and training
- **WHEN** the sleep-cycle count is reached but Phantasia shows no successful
  world-model training passes
- **THEN** C2 is not met and the stage remains `gestation`

#### Scenario: Lived-time floor blocks a fast-forwarded birth
- **WHEN** C1 and C2 are met but lived subjective time is below `min_lived_seconds`
- **THEN** C3 is not met and the stage remains `gestation`

### Requirement: Birth requires an available embodied world
The system SHALL transition to `embodied` only when developmental readiness
(C1∧C2∧C3) AND embodiment availability both hold. Embodiment availability SHALL mean
the embodiment target (Mundus) is enabled, operator-approved, and reachable per its
existing two-layer gate. When the entity is developmentally ready but embodiment is
unavailable, the system SHALL hold it in the womb and SHALL emit a repeated
`stage.birth.ready` marker with `reason: "awaiting_embodiment"` and a warning log; it
SHALL NOT transition into an absent or unreachable world, and SHALL NOT silently
stall.

#### Scenario: Ready and available births the entity
- **WHEN** developmental readiness holds and embodiment is available
- **THEN** the stage transitions to `embodied` and the birth transition fires

#### Scenario: Ready but embodiment unavailable holds in the womb
- **WHEN** developmental readiness holds but embodiment is not enabled/approved/reachable
- **THEN** the stage remains `gestation`, and a `stage.birth.ready` marker with
  `reason: "awaiting_embodiment"` and a warning are emitted (repeatedly), never a
  silent stall

### Requirement: The birth transition is a bounded, one-shot audiovisual handoff
On the transition to `embodied` the system SHALL trigger a bounded, one-shot birth
transition that hands the senses off from the womb feed to the embodied world. This
capability SHALL trigger the transition (emit the event and switch the locus source
from womb to embodiment); the perception feed and the embodiment connector SHALL
render it. The transition SHALL be time-bounded and SHALL fire at most once per
entity.

#### Scenario: Birth fires the handoff exactly once
- **WHEN** the stage transitions `gestation → embodied`
- **THEN** a single bounded birth transition event is emitted and the sense source
  switches from the womb feed to embodiment

#### Scenario: Birth does not re-fire
- **WHEN** an already-`embodied` entity runs
- **THEN** no further birth transition is emitted

### Requirement: Staging is observable and never silent
The system SHALL emit stage events from a named owner (`source = "lifecycle"`, so per
the bus schema they land on `lifecycle.out`): `stage.gestation.started` at the first
gestational boot, `stage.birth.ready` when developmental readiness is first met (and
while holding for embodiment), and `stage.birth` when the transition occurs (carrying
the markers, the sleep count, and the lived time that ended gestation). The Nexus
interface SHALL surface the current developmental stage and the "ready, awaiting
embodiment" hold state. Every decision to hold in the womb because a condition is unmet
SHALL be logged, never a silent no-op.

#### Scenario: Stage transitions are announced
- **WHEN** gestation begins, readiness is first reached, and birth occurs
- **THEN** `stage.gestation.started`, `stage.birth.ready`, and `stage.birth` are
  emitted respectively, the last carrying the ending markers, sleep count, and lived time

#### Scenario: The stage is visible to the operator
- **WHEN** the operator views the Nexus interface
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
