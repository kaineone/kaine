## ADDED Requirements

### Requirement: Spot recovery re-wiring is tested
The `rewire_module` helper in `kaine/boot.py` SHALL have automated tests verifying that after Spot rebuilds a module, the self-hearing gate (Vox↔Audition `SpeakingGate`), Eidolon capability whitelist, and oscillator wiring are restored on the replaced instance.

#### Scenario: Self-hearing gate is restored after rebuild
- **WHEN** `build_registry` is run with Vox and Audition and then `rewire_module(registry, "vox", cfg)` is called
- **THEN** the replaced Vox module shares the same `SpeakingGate` as Audition

#### Scenario: Eidolon whitelist is re-seeded after rebuild
- **WHEN** `build_registry` is run with Praxis and Eidolon and then `rewire_module(registry, "eidolon", cfg)` is called
- **THEN** the replaced Eidolon's capability map matches the Praxis whitelist

#### Scenario: Oscillator wiring is restored after rebuild
- **WHEN** oscillators are enabled and `rewire_module(registry, "soma", cfg)` is called
- **THEN** the replaced Soma module is wired to the same oscillator phase reference as before
