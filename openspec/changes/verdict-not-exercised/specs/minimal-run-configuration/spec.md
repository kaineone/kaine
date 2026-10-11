## REMOVED Requirements

### Requirement: Minimal experiment configuration
**Reason**: The profile served a retired design of the workspace-mediation ablation (Soma, Chronos and Lingua with an output-divergence measure). The planned test runs the base-thesis form in the three arms of paper §6.3, and the paper holds that a system limited to substrate telemetry and event timing offers too little diversity for competition to matter.
**Migration**: Use the base-thesis default (`thesis_test`) and the study configurations of the planned test; enable a reduced set of modules in `config/kaine.operator.toml` when one is needed.

### Requirement: Workspace capacity forces competition in the minimal set
**Reason**: It applied only to the retired minimal profile.
**Migration**: The offline development harness sets its own capacity below the per-tick candidate count.

### Requirement: Operator text-stimulus injection
**Reason**: The injection tool was deleted when the harness was rebuilt around the information-gain measure; the language organ's utterances are not a measure (paper §3.5, §6.3).
**Migration**: None.

## MODIFIED Requirements

### Requirement: Minimal build boots without disabled modules

A reduced module set SHALL boot and run the cognitive cycle without any hard
dependency on disabled modules (Mnemos, Eidolon, Thymos, Perception, Audition, and the
rest). Cross-module wiring SHALL degrade cleanly when a module is absent, and a
disabled module SHALL return when its `[modules]` toggle is flipped back on.

#### Scenario: Clean boot on three modules

- **WHEN** the registry is built with only Soma, Chronos, and Lingua enabled
- **THEN** exactly those three modules are registered and no disabled-module
  dependency raises an error

#### Scenario: Re-enabling a module is a toggle

- **WHEN** a disabled module's `[modules]` toggle is flipped back on
- **THEN** the module is registered, with no code restored or rebuilt
