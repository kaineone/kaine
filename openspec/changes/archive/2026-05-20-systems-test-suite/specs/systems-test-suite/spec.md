## ADDED Requirements

### Requirement: One systems test file per subsystem
The repository SHALL ship one file under `tests/systems/` per
documented subsystem: bus, cycle, workspace, soma, chronos, topos,
nous, mnemos, eidolon, thymos, praxis, lingua, audio_in, audio_out,
hypnos, lifecycle, boot, nexus, sidecar. Each file SHALL exercise
the subsystem's bus-level inputs and outputs (events consumed,
events published) without booting any other module.

#### Scenario: Files exist
- **WHEN** an operator lists `tests/systems/`
- **THEN** each of the listed subsystem files is present

### Requirement: Harness builds one subsystem in isolation
The `SubsystemHarness` SHALL provide a fakeredis-backed AsyncBus and
helpers `inject(stream, event)` and `collect(stream, count)`. It
SHALL NOT register more than one module instance at a time. It
SHALL NOT initialize the cognitive cycle, Syneidesis, or any module
beyond the subject under test.

#### Scenario: Two-module harness rejected
- **WHEN** a test attempts to register two modules into one harness
- **THEN** the harness raises ValueError

### Requirement: External-service tests skip cleanly when service unavailable
Systems tests SHALL detect a `KAINE_HAS_<SERVICE>` env var for each
subsystem with a separately-installed backend (lingua → Unsloth,
audio_in → Speaches, audio_out → Chatterbox, nous → ONA binary).
When the env var is unset, the test SHALL substitute the documented
Fake collaborator. The contract test against the Fake SHALL always
run.

#### Scenario: Lingua contract test against fake
- **WHEN** `KAINE_HAS_UNSLOTH` is not set and the lingua subsystem
  test runs
- **THEN** the test uses `FakeChatClient`, the assertions still
  execute, and the test reports passed (not skipped)

### Requirement: `pytest -m systems` runs only systems tests
The `systems` pytest marker SHALL be registered. Running
`pytest -m systems` SHALL execute every file under
`tests/systems/` and SHALL NOT execute files outside that
directory.

#### Scenario: Marker isolates the suite
- **WHEN** an operator runs `pytest -m systems`
- **THEN** the collected test count matches the systems suite's
  count and no other unit test is run
