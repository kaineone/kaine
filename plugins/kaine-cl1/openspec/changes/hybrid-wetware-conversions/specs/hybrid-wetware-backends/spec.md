## ADDED Requirements

### Requirement: Hybrid conversions are partial and default-off

Each hybrid backend SHALL convert only its named sub-signal (Audition front end,
Phantasia surprise, Volition action-selection, or Thymos affect), leave the rest
of the module on silicon, keep the module's `<name>.out` event shapes unchanged,
and ship disabled by default. Each SHALL have an explicit acceptance gate that
keeps it disabled until passed. A hybrid split MAY remain permanent when its
silicon half is not a wetware task.

#### Scenario: Default configuration converts nothing in the hybrid tier

- **WHEN** the overlay boots with no hybrid backend explicitly enabled
- **THEN** Audition, Phantasia, Volition, and Thymos all run fully on silicon

#### Scenario: A failed gate keeps a backend disabled

- **WHEN** a hybrid backend does not meet its acceptance gate on the simulator
- **THEN** it remains disabled and the module stays fully on silicon

### Requirement: Decoded actions and affect never bypass safety or welfare gates

A decoded action from the Volition backend SHALL pass through KAINE's unchanged
two-layer safety gate before becoming an outward act. The Thymos affect read-out
SHALL require an explicit review flag even in the simulator and SHALL NOT drive
outward action.

#### Scenario: Action selection respects the safety boundary

- **WHEN** the Volition backend decodes an action
- **THEN** that action is subject to KAINE's two-layer action gate exactly as a
  silicon-selected action would be

#### Scenario: Affect read-out is review-gated

- **WHEN** the Thymos affect backend is enabled without the required review flag
- **THEN** it does not activate

### Requirement: The array ceiling bounds simultaneous conversions

The broker SHALL refuse to bring online more converted modules than the 64
electrodes allow, logging the refusal rather than silently dropping a module.

#### Scenario: Oversubscription is reported

- **WHEN** enabling a hybrid backend would exceed the 64-channel budget
- **THEN** the broker refuses it and logs the reason
