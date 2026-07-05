## ADDED Requirements

### Requirement: Praxis acts only on provenance-verified act intents

Praxis SHALL realize an `act` intent only when the intent's provenance from the
cycle's action-selection step (Volition) is verified. Provenance SHALL be enforced
by either a datastore-level restriction on who may publish to `volition.out`, or a
cryptographic signature over the canonical intent payload verified by Praxis before
any effector runs. An `act` intent that fails provenance verification SHALL NOT
execute any effector, SHALL be dropped, and SHALL be recorded in the audit log
under a distinct provenance-rejected category.

This boundary is in addition to, not a replacement for, the effector whitelist and
filesystem sandbox, which remain the primary enforced gate.

#### Scenario: Forged act intent from a non-Volition writer is blocked

- **WHEN** a module other than Volition publishes an `act` intent onto `volition.out`
- **THEN** Praxis does not run the effector
- **AND** the attempt is recorded in the audit log as provenance-rejected

#### Scenario: Legitimate Volition intent still executes

- **WHEN** Volition emits an `act` intent for an enabled effector from a
  non-inhibited snapshot
- **THEN** Praxis verifies provenance and realizes the action normally

#### Scenario: A captured signed intent cannot be replayed

- **WHEN** a previously-realized signed act intent is re-published
- **THEN** Praxis rejects it as already realized and runs no effector
