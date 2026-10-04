## ADDED Requirements

### Requirement: The cycle boots through ordered phases
The cycle entrypoint SHALL boot by running an ordered list of phase functions over one shared boot context. Each phase SHALL return an exit code to stop the boot, or nothing to continue, and the entrypoint SHALL return the first exit code a phase returns without running the later phases, the run loop or shutdown. Once every phase has run, the entrypoint SHALL run the cycle until it is stopped and SHALL then run shutdown, even if the run loop raised. Every value a phase shares with a later phase SHALL be a declared field of the boot context.

#### Scenario: A phase refuses the boot
- **WHEN** a phase returns an exit code
- **THEN** the entrypoint returns that code
- **AND** no later phase, run loop or shutdown runs

#### Scenario: Shutdown follows a failed run loop
- **WHEN** every phase completes and the run loop raises
- **THEN** shutdown runs

#### Scenario: An undeclared context field
- **WHEN** a phase sets a boot-context attribute that is not a declared field
- **THEN** it raises
