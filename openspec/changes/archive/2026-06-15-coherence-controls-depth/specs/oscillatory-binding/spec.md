## ADDED Requirements

### Requirement: Disabled coherence layer is bit-for-bit identical across many cycles

The disabled coherence layer SHALL be bit-for-bit identical to the layer absent
across MANY consecutive cycles given the same seed and the same per-cycle events
and phases — not merely for a single tick. On every cycle the selected events,
their order, the salience scores, and the inhibition flag SHALL match the
layer-absent baseline exactly, and the applied coherence multiplier SHALL be a
literal no-op: the disabled path SHALL write no `metadata['coherence']` key and
SHALL leave the salience scores equal to the raw strategy scores (an effective
multiplier of exactly 1.0). The bounded gain map SHALL satisfy
`factor_from_plv(1.0) == coherence_ceiling` and SHALL be monotone non-decreasing
in PLV, so a unit-PLV coalition is mapped to the configured ceiling and never
attenuated.

#### Scenario: Disabled equals absent over many cycles

- **WHEN** a disabled-layer Syneidesis and a layer-absent baseline Syneidesis are
  driven through many consecutive cycles with the same seed and the same per-cycle
  events and phases
- **THEN** on every cycle the selected events, their order, the salience scores,
  and the inhibition flag are identical between the two
- **AND** neither snapshot carries a `metadata['coherence']` key on any cycle

#### Scenario: Disabled multiplier is a literal no-op

- **WHEN** the disabled-layer Syneidesis selects from a set of events
- **THEN** the resulting salience scores equal the raw strategy scores (effective
  multiplier exactly 1.0)
- **AND** no `metadata['coherence']` key is written

#### Scenario: Unit PLV maps to the ceiling

- **WHEN** a `CoherenceScorer` evaluates `factor_from_plv` at PLV 1.0
- **THEN** the returned factor equals `coherence_ceiling`
- **AND** the map is monotone non-decreasing across PLV in `[0, 1]`

### Requirement: Extreme precision gain demonstrably changes selection

An extreme precision gain SHALL demonstrably change selection. With the coherence
layer enabled and the precision gain cranked to an EXTREME ceiling (with a low
floor), Syneidesis selection SHALL FLIP relative to the salience-only baseline: a desynchronized event with higher raw salience
SHALL be overtaken by a phase-locked event with lower raw salience once the
extreme coherence gain is applied. This is a strong proof that the enable toggle
is firmly connected to the selection mechanism, complementing the moderate-gain
control.

#### Scenario: Extreme gain flips the top selection

- **WHEN** the layer is enabled with an extreme `coherence_ceiling` and a low
  `coherence_floor`, a phase-locked source carries a lower raw salience than a
  desynchronized source, and the same inputs are scored with the layer absent
- **THEN** with the layer absent the higher-raw-salience desynchronized event
  ranks first
- **AND** with the extreme-gain layer enabled the phase-locked event overtakes it
  and ranks first, demonstrating the toggle drives selection
