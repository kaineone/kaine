## ADDED Requirements

### Requirement: Familiarity-modulated affect coupling
Thymos SHALL shift its dimensional (valence/arousal/dominance) state toward a
detected speaker emotion on each `audition.emotion` event, by a coupling
coefficient `coupling_base + coupling_familiarity_gain × familiarity` clamped to
`coupling_ceiling`, where `familiarity` is taken from the latest
`empatheia.agent_model`. The shift SHALL be applied directly to the dimensional
state (not routed through the Scherer appraisal), preserving existing drift and
hysteresis.

#### Scenario: Detected emotion shifts affect
- **WHEN** an `audition.emotion` event reports a strongly positive-valence emotion
- **THEN** Thymos's valence moves toward that emotion's target

#### Scenario: Higher familiarity couples more strongly
- **WHEN** the same detected emotion is processed at familiarity 0.2 versus 0.9
- **THEN** the dimensional shift at 0.9 is strictly larger than at 0.2

#### Scenario: Coupling is bounded per step
- **WHEN** an extreme detected emotion is processed at maximum familiarity
- **THEN** the single-step shift does not exceed `coupling_ceiling`

### Requirement: Cumulative-drift safeguard
Thymos SHALL enforce a `coupling_max_rate_per_s` rolling-window cap (or an
equivalent cooldown after N consecutive nudges) so that sustained emotion events
at high frequency toward an extreme cannot leave the dimensional state pinned at
the boundary. After input stops, the dimensional state SHALL recover from any
boundary position within a bounded time determined by the existing drift dynamics.

#### Scenario: Sustained high-frequency extreme emotion does not pin state at boundary
- **WHEN** emotion events fire at 3.33 Hz toward an extreme value for 10 seconds
- **THEN** the dimensional state is NOT pinned at the boundary after input stops
  and the drift mechanism returns it toward the neutral range

### Requirement: Graceful degradation and opt-out
Thymos SHALL fall back to `coupling_base` when no familiarity is known for the
speaker, and SHALL apply no coupling shift when `[thymos.coupling].enabled` is
false.

#### Scenario: No Empatheia model uses base coupling
- **WHEN** an `audition.emotion` arrives with no prior `empatheia.agent_model`
- **THEN** the shift uses `coupling_base`

#### Scenario: Disabled coupling does nothing
- **WHEN** coupling is disabled and an `audition.emotion` arrives
- **THEN** the dimensional state is not shifted by coupling

### Requirement: Familiarity cache persistence
Thymos SHALL serialize the per-agent familiarity cache so that coupling strength
is not cold-reset after a fork restore.

#### Scenario: Cache survives a serialize/deserialize round-trip
- **WHEN** the familiarity cache holds a non-empty entry and Thymos is serialized
  then deserialized
- **THEN** the same familiarity values are present and coupling uses them on the
  next event
