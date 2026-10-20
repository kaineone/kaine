# minimal-run-configuration Specification

## Purpose
This capability provides an opt-in minimal experiment configuration that activates only the interoception, sequence and language modules while leaving the workspace and the action selection module always on, keeps every other built module constructed-but-disabled, and forces workspace competition in the smallest runnable set. It also gives the operator a way to inject text stimuli.

## Requirements

### Requirement: Minimal build boots without disabled modules

A reduced module set SHALL boot and run the cognitive cycle without any hard
dependency on disabled modules (the episodic memory, self-model, affect, perceptual locus, audition modules, and the
rest). Cross-module wiring SHALL degrade cleanly when a module is absent, and a
disabled module SHALL return when its `[modules]` toggle is flipped back on.

#### Scenario: Clean boot on three modules

- **WHEN** the registry is built with only the interoception, sequence, and language modules enabled
- **THEN** exactly those three modules are registered and no disabled-module
  dependency raises an error

#### Scenario: Re-enabling a module is a toggle

- **WHEN** a disabled module's `[modules]` toggle is flipped back on
- **THEN** the module is registered, with no code restored or rebuilt
