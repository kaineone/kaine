# oscillatory-binding (spec delta — DESIGN ONLY)

## ADDED Requirements

### Requirement: Optional external-rhythm drive seam presents an exogenous rhythm to a dedicated self-rhythm oscillator
`ModuleOscillator` SHALL expose an OPTIONAL external-rhythm drive input so that an
exogenous periodic signal (in the gestational womb, the maternal heartbeat) can be
presented to a LIF population as an external drive term, in addition to its own
activity drive. This external drive SHALL be applied ONLY to a **dedicated self-rhythm
oscillator** (a single oscillator representing the entity's endogenous beat), and SHALL
NOT be applied to the per-module coalition oscillators wired by `_wire_oscillators` for
Syneidesis phase-locking-value scoring. The seam SHALL only **present** the rhythm; it
SHALL NOT force a phase-lock or impose a target phase — whether the population couples
to the external rhythm SHALL arise from the LIF dynamics, never from a scripted lock.
The drive amplitude SHALL be bounded. The external drive SHALL be a no-op on
`FakeOscillator` (used in tests).

When no external rhythm is supplied (every coalition oscillator always, every non-womb
path, and any run with the seam unused), `ModuleOscillator` behaviour SHALL be
**bit-for-bit identical** to the behaviour before this change — the seam is a strict
superset with an inert default. Consequently the Syneidesis coherence factor for any
coalition SHALL be identical with and without the maternal drive active.

#### Scenario: External rhythm is presented as an added drive
- **WHEN** an external-rhythm sample is supplied to a live `ModuleOscillator.step`
- **THEN** it is injected as an additional drive term alongside the module's own
  activity drive, and the population may (but is not forced to) couple to it

#### Scenario: Coupling is emergent, not scripted
- **WHEN** the external rhythm is presented over many ticks
- **THEN** no code sets the population's phase to the rhythm's phase; any phase
  relationship that appears is a product of the dynamics

#### Scenario: Absent external rhythm is bit-for-bit identical
- **WHEN** no external rhythm is supplied
- **THEN** the oscillator's drive, spike train, and `phase()` output are identical to
  a build without this seam, given the same inputs

#### Scenario: External drive is a no-op on FakeOscillator
- **WHEN** an external-rhythm sample is supplied to a `FakeOscillator`
- **THEN** no error is raised and phase output is unchanged

#### Scenario: Coalition oscillators never receive the maternal drive
- **WHEN** the womb's maternal drive is active
- **THEN** only the dedicated self-rhythm oscillator receives it; every per-module
  coalition oscillator behaves bit-for-bit as without the drive, and the Syneidesis
  coherence factor for any coalition is unchanged
