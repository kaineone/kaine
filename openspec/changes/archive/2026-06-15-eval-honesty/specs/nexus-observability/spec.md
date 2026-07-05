## ADDED Requirements

### Requirement: Nous health probe verifies the generative model builds

The Nous health probe SHALL confirm that the active-inference generative
model can be constructed, not merely that `pymdp` and `jax` are importable.
A broken dependency (e.g. numpy ABI mismatch) that only surfaces at
construction time would pass an import-only probe and give a false UP result.

The probe SHALL attempt `build_generative_model()` with default parameters
after confirming imports succeed.  The build attempt SHALL be guarded so
that any exception is caught within the probe and never propagates to the
caller.

#### Scenario: Imports and build succeed

- **WHEN** `pymdp` and `jax` are importable
- **AND** `build_generative_model()` completes without raising
- **THEN** the probe SHALL return `UP`
- **AND** the detail message SHALL include `"generative model built"`

#### Scenario: Imports succeed but build fails

- **WHEN** `pymdp` and `jax` are importable
- **AND** `build_generative_model()` raises any exception
- **THEN** the probe SHALL return `DEGRADED`
- **AND** the detail message SHALL include `"build failed"` and the exception message

#### Scenario: Import fails

- **WHEN** `pymdp` or `jax` cannot be imported
- **THEN** the probe SHALL return `DOWN` (unchanged from prior behaviour)
