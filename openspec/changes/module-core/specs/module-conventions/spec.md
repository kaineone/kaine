## ADDED Requirements

### Requirement: A ratchet keeps convention breaks from growing
`tests/test_conventions.py` SHALL count, per file, direct clock calls, raw bus publishes, hand-written file writes and directly started tasks under `kaine/modules/`, and event-type and module-name string literals compared in `kaine/workspace/` and `kaine/cycle/`. It SHALL resolve import aliases. It SHALL fail when a count rises above its recorded baseline and when a count falls below it, so the baseline only tightens.

#### Scenario: A new direct clock call fails
- **WHEN** a module file gains a `time.monotonic()` call, including through `import time as t`
- **THEN** the test fails and names the file, the kind, and `EntityClock` as the service to use

#### Scenario: A fixed call site tightens the baseline
- **WHEN** a migration removes a counted call
- **THEN** the test fails until the baseline is lowered to the new count

### Requirement: Module names and event types have one source
Module names SHALL be defined once in `kaine/module_names.py` and cross-module event types once in `kaine/bus/event_types.py`. Workspace and cycle code SHALL import them rather than writing the strings.

#### Scenario: Every registered module's name is defined
- **WHEN** the module registry is built with every module enabled
- **THEN** each module's `name` is a constant in `kaine/module_names.py` and matches `kaine/legacy_names.py`
