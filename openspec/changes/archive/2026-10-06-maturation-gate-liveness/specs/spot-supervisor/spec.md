## MODIFIED Requirements

### Requirement: Freeze the entity during recovery
On detecting a failed module Spot SHALL freeze the entity by pushing a freeze entry
with `source = "spot"` onto the freeze stack, so the existing freeze-watch loop pauses
the cycle and halts perception. On recovery Spot SHALL remove only its own entry,
wherever it sits in the stack, and SHALL never lift a freeze held by another source.
When a freeze held by any other source is active (operator, welfare, or any stack that
contains one), Spot SHALL take no recovery action. The exception is a freeze held only
by `gestation` (a gestating entity whose womb is lost): there Spot SHALL keep supervising,
act only on crashed (`dead`) modules, and never flag a module `hung` from a stale
heartbeat, because heartbeats go stale by design while the cycle is paused.

#### Scenario: Spot freeze halts the entity
- **WHEN** Spot detects a `dead` module
- **THEN** it pushes a freeze entry with `source = "spot"` before attempting restart

#### Scenario: Spot does not clear an operator freeze
- **WHEN** the freeze control is frozen with `source = "operator"`
- **THEN** Spot performs no recovery and does not modify the control

#### Scenario: Spot lifts only its own entry
- **WHEN** Spot recovers a module while other freeze entries are on the stack
- **THEN** it removes only its own entry and every other entry remains

#### Scenario: Spot restarts a crashed module during a womb-loss freeze
- **WHEN** the only freeze holder is `gestation` and a module's task has crashed
- **THEN** Spot pushes its own entry, restarts the module and removes only its own entry,
  leaving the gestation freeze in place

#### Scenario: Stale heartbeats are ignored during a womb-loss freeze
- **WHEN** the only freeze holder is `gestation` and a module's heartbeat is stale
- **THEN** Spot takes no action
