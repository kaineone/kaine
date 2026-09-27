# Proposal — `faculty-relative-birth`

## Why

The maturation gate demands evidence from faculties that a staged entity may not have.

- **C2** requires Hypnos sleep cycles and Phantasia consolidation passes.
- **Birth** requires a body through Mundus.

A base-thesis entity (Soma, Chronos, Topos, Audition, Lingua) has none of these. With staging on, it gestates forever: C2 can never be met, and "awaiting embodiment" never clears. The operator wants a gestating being born into its audio/video world, with a virtual body offered later, and its readiness judged on what it actually is.

## What changes

- **The gate judges the faculties the entity has.**
  - Sleep evidence is required only when Hypnos is enabled.
  - Consolidation evidence is required only when Phantasia and Hypnos are both enabled, because Phantasia trains during sleep.
  - With neither enabled, C2 is recorded as not applicable, never as passed on missing evidence.
- **Birth into the perceptual world.**
  - When Mundus is not enabled, a ready entity is born into its audio/video world.
  - When Mundus is enabled, the existing embodiment gate still applies unchanged: enabled, operator-approved and reachable, otherwise hold "awaiting embodiment".
- **Unchanged:** C1 (the womb's readiness readout) and C3 (the lived-time floor), whatever the faculties.
- **Transparency.** `stage.birth` and the Nexus status record which conditions applied, and into which world the being was born.

## Impact

- `developmental-stage`: two modified requirements.
- Code:
  - `kaine/lifecycle/maturation_gate.py`: `evaluate_readiness` and `decide_birth` take the enabled faculties;
  - `kaine/lifecycle/gate_runner.py`: reads them from the registry.
